#!/usr/bin/env python3
"""
Engineering Efficiency Dashboard
轻量级FastAPI server，提供API + 单页面Dashboard
"""

import os
import sys
import json
import re
import sqlite3
import glob as globmod
from datetime import datetime, timedelta
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(__file__))
from prompt_advisor import analyze_sessions, get_session_advice

DB_PATH = os.path.expanduser("~/.claude/efficiency.db")
DAILY_LOG_DIR = os.path.expanduser("~/.claude/daily-logs")
DASHBOARD_HTML = os.path.join(os.path.dirname(__file__), "dashboard.html")


def get_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def api_summary(date_str):
    """当日KPI汇总"""
    db = get_db()
    next_day = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    # 会话统计
    row = db.execute(
        "SELECT COUNT(*) as cnt, COALESCE(SUM(total_tools),0) as tools FROM sessions WHERE start_time >= ? AND start_time < ?",
        (f"{date_str}T00:00:00", f"{next_day}T00:00:00")
    ).fetchone()

    # 日报贡献度
    report_row = db.execute(
        "SELECT total_commits, total_files_changed, contribution_scores FROM daily_reports WHERE date = ?",
        (date_str,)
    ).fetchone()

    contribution_scores = {}
    total_commits = 0
    total_files = 0
    productivity_pct = 0

    if report_row:
        total_commits = report_row["total_commits"] or 0
        total_files = report_row["total_files_changed"] or 0
        try:
            contribution_scores = json.loads(report_row["contribution_scores"] or "{}")
            productive = sum(v["score"] for k, v in contribution_scores.items() if k in ["产品开发", "Bug修复", "内容生产"])
            total = sum(v["score"] for v in contribution_scores.values())
            if total > 0:
                productivity_pct = round(productive / total * 100)
        except Exception:
            pass

    db.close()
    return {
        "date": date_str,
        "sessions": row["cnt"],
        "tool_uses": row["tools"],
        "commits": total_commits,
        "files_changed": total_files,
        "productivity_pct": productivity_pct,
        "contribution_scores": contribution_scores
    }


def api_tools(date_str):
    """工具使用分布"""
    db = get_db()
    next_day = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    rows = db.execute(
        "SELECT tool_name, COUNT(*) as cnt FROM tool_uses WHERE timestamp >= ? AND timestamp < ? GROUP BY tool_name ORDER BY cnt DESC",
        (f"{date_str}T00:00:00", f"{next_day}T00:00:00")
    ).fetchall()
    db.close()
    return [{"tool": r["tool_name"], "count": r["cnt"]} for r in rows]


def api_timeline(date_str):
    """今日时间线"""
    db = get_db()
    next_day = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    rows = db.execute(
        "SELECT tool_name, timestamp, session_id FROM tool_uses WHERE timestamp >= ? AND timestamp < ? ORDER BY timestamp",
        (f"{date_str}T00:00:00", f"{next_day}T00:00:00")
    ).fetchall()
    db.close()
    return [{"tool": r["tool_name"], "time": r["timestamp"], "session": r["session_id"][:8]} for r in rows]


def api_trend(days):
    """最近N天活跃度趋势"""
    db = get_db()
    results = []
    for i in range(days - 1, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        nd = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

        row = db.execute(
            "SELECT COUNT(*) as sessions, COALESCE(SUM(total_tools),0) as tools FROM sessions WHERE start_time >= ? AND start_time < ?",
            (f"{d}T00:00:00", f"{nd}T00:00:00")
        ).fetchone()

        report = db.execute(
            "SELECT total_commits FROM daily_reports WHERE date = ?", (d,)
        ).fetchone()

        results.append({
            "date": d,
            "sessions": row["sessions"],
            "tool_uses": row["tools"],
            "commits": report["total_commits"] if report else 0
        })
    db.close()
    return results


def api_projects(date_str):
    """项目分布"""
    db = get_db()
    next_day = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    rows = db.execute(
        "SELECT project, COUNT(*) as cnt, SUM(total_tools) as tools FROM sessions WHERE start_time >= ? AND start_time < ? GROUP BY project ORDER BY tools DESC",
        (f"{date_str}T00:00:00", f"{next_day}T00:00:00")
    ).fetchall()
    db.close()
    return [{"project": _clean_project_name(r["project"]), "sessions": r["cnt"], "tools": r["tools"] or 0} for r in rows]


def api_report(date_str):
    """日报内容"""
    report_path = os.path.join(DAILY_LOG_DIR, f"{date_str}.md")
    if os.path.exists(report_path):
        with open(report_path, 'r', encoding='utf-8') as f:
            return {"date": date_str, "content": f.read()}
    return {"date": date_str, "content": ""}


def api_weekly_compare():
    """本周vs上周对比"""
    db = get_db()
    today = datetime.now()
    # 本周（周一开始）
    this_monday = today - timedelta(days=today.weekday())
    last_monday = this_monday - timedelta(days=7)

    def week_stats(start):
        end = start + timedelta(days=7)
        s = start.strftime("%Y-%m-%d")
        e = end.strftime("%Y-%m-%d")
        row = db.execute(
            "SELECT COUNT(*) as sessions, COALESCE(SUM(total_tools),0) as tools FROM sessions WHERE start_time >= ? AND start_time < ?",
            (f"{s}T00:00:00", f"{e}T00:00:00")
        ).fetchone()
        commits = db.execute(
            "SELECT COALESCE(SUM(total_commits),0) as c FROM daily_reports WHERE date >= ? AND date < ?",
            (s, e)
        ).fetchone()
        return {
            "sessions": row["sessions"],
            "tool_uses": row["tools"],
            "commits": commits["c"]
        }

    this_week = week_stats(this_monday)
    last_week = week_stats(last_monday)
    db.close()

    return {"this_week": this_week, "last_week": last_week}


def api_tokens(date_str):
    """当日token用量"""
    db = get_db()
    row = db.execute(
        "SELECT * FROM token_daily WHERE date = ?", (date_str,)
    ).fetchone()
    db.close()
    if row:
        return dict(row)
    return {"date": date_str, "total_input": 0, "total_output": 0, "total_cache_write": 0, "total_cache_read": 0, "total_cost_usd": 0, "message_count": 0}


def api_token_trend(days):
    """最近N天token成本趋势"""
    db = get_db()
    results = []
    for i in range(days - 1, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        row = db.execute("SELECT * FROM token_daily WHERE date = ?", (d,)).fetchone()
        if row:
            results.append(dict(row))
        else:
            results.append({"date": d, "total_input": 0, "total_output": 0, "total_cache_write": 0, "total_cache_read": 0, "total_cost_usd": 0, "message_count": 0})
    db.close()
    return results


def api_model_breakdown(date_str):
    """按模型分解"""
    db = get_db()
    rows = db.execute(
        "SELECT model, SUM(input_tokens) as input_t, SUM(output_tokens) as output_t, SUM(cache_write_tokens) as cache_w, SUM(cache_read_tokens) as cache_r, ROUND(SUM(cost_usd),2) as cost, COUNT(*) as msgs FROM token_usage WHERE date = ? GROUP BY model ORDER BY cost DESC",
        (date_str,)
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def api_top_sessions(limit=10):
    """成本最高的会话"""
    db = get_db()
    rows = db.execute(
        "SELECT session_id, project, MIN(date) as date, ROUND(SUM(cost_usd),2) as cost, SUM(input_tokens+output_tokens) as total_tokens, COUNT(*) as msgs FROM token_usage GROUP BY session_id ORDER BY cost DESC LIMIT ?",
        (limit,)
    ).fetchall()
    db.close()
    result = [dict(r) for r in rows]
    for r in result:
        r["project"] = _clean_project_name(r.get("project", ""))
    return result


def api_benchmark(days=30):
    """Usage efficiency benchmark vs top user patterns"""
    db = get_db()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    # Tool counts
    tool_rows = db.execute(
        "SELECT tool_name, COUNT(*) as cnt FROM tool_uses WHERE timestamp >= ? GROUP BY tool_name",
        (f"{cutoff}T00:00:00",)
    ).fetchall()
    tool_counts = {r["tool_name"]: r["cnt"] for r in tool_rows}
    total_tools = sum(tool_counts.values()) or 1

    # Session stats (prefer session_summaries which has full history)
    sess = db.execute(
        "SELECT COUNT(*) as cnt, COALESCE(SUM(tool_calls),0) as tools, COALESCE(SUM(total_cost_usd),0) as cost "
        "FROM session_summaries WHERE date >= ?",
        (cutoff,)
    ).fetchone()
    session_count = max(sess["cnt"], 1)
    total_session_tools = sess["tools"]
    session_cost = sess["cost"]

    # Token/cost stats
    tok = db.execute(
        "SELECT COALESCE(SUM(total_input),0) as inp, COALESCE(SUM(total_output),0) as outp, "
        "COALESCE(SUM(total_cache_write),0) as cw, COALESCE(SUM(total_cache_read),0) as cr, "
        "COALESCE(SUM(total_cost_usd),0) as cost FROM token_daily WHERE date >= ?",
        (cutoff,)
    ).fetchone()
    db.close()

    # --- Dimension 1: Dedicated Tool Usage ---
    dedicated = sum(tool_counts.get(t, 0) for t in ['Read', 'Grep', 'Glob'])
    bash_count = tool_counts.get('Bash', 0)
    file_ops = dedicated + bash_count
    d1_ratio = dedicated / max(file_ops, 1)
    d1_score = min(100, round(d1_ratio / 0.65 * 100))
    d1_detail = f"Read+Grep+Glob占{round(d1_ratio*100)}%（基准65%+）"
    d1_tip = "用Read代替cat/head，用Grep代替grep/rg，用Glob代替find/ls。专用工具有更好的安全性和体验。"

    # --- Dimension 2: Read-Before-Edit ---
    reads = tool_counts.get('Read', 0)
    edits = tool_counts.get('Edit', 0) + tool_counts.get('Write', 0)
    re_ratio = reads / max(edits, 1)
    d2_score = min(100, round(re_ratio / 3.0 * 100))
    d2_detail = f"Read:Edit比 {re_ratio:.1f}:1（基准3:1）"
    d2_tip = "编辑前先充分阅读文件，理解上下文。3:1的Read:Edit比表明修改前有足够的理解。"

    # --- Dimension 3: Cache Utilization ---
    total_input_all = tok["inp"] + tok["cw"] + tok["cr"]
    cache_rate = tok["cr"] / max(total_input_all, 1)
    d3_score = min(100, round(cache_rate / 0.90 * 100))
    d3_detail = f"缓存命中率{round(cache_rate*100)}%（基准90%+）"
    d3_tip = "保持会话聚焦于相关任务，避免频繁切换上下文。用CLAUDE.md预加载项目背景。"

    # --- Dimension 4: Agent Parallel Usage ---
    agent_uses = tool_counts.get('Agent', 0)
    agent_ratio = agent_uses / total_tools
    d4_score = min(100, round(agent_ratio / 0.05 * 100))
    d4_detail = f"Agent占比{round(agent_ratio*100, 1)}%（基准5%+）"
    d4_tip = "用Agent并行处理独立子任务（代码搜索、测试运行、文件探索），大幅提升效率。"

    # --- Dimension 5: Cost Efficiency ---
    total_cost = max(session_cost or tok["cost"], 0.01)
    tools_per_dollar = total_session_tools / total_cost
    d5_score = min(100, round(tools_per_dollar / 8.0 * 100))
    d5_detail = f"{tools_per_dollar:.1f}次工具/$1（基准8次/$1）"
    d5_tip = "精简prompt，避免开放式问题产生长回复。提前用CLAUDE.md给出项目背景减少重复解释。"

    # --- Dimension 6: Session Focus ---
    avg_tools = total_session_tools / session_count
    d6_score = min(100, round(avg_tools / 50.0 * 100))
    d6_detail = f"平均{avg_tools:.0f}次/会话（基准50次/会话）"
    d6_tip = "每个会话聚焦单一任务或功能。高聚焦会话产出更多、成本更低。"

    dimensions = [
        {"name": "Dedicated Tools", "name_zh": "专用工具使用", "score": d1_score, "benchmark": 80, "detail": d1_detail, "tip": d1_tip, "weight": 0.20},
        {"name": "Read Before Edit", "name_zh": "先读后改习惯", "score": d2_score, "benchmark": 85, "detail": d2_detail, "tip": d2_tip, "weight": 0.20},
        {"name": "Cache Utilization", "name_zh": "缓存利用率", "score": d3_score, "benchmark": 90, "detail": d3_detail, "tip": d3_tip, "weight": 0.15},
        {"name": "Agent Parallel", "name_zh": "Agent并行", "score": d4_score, "benchmark": 75, "detail": d4_detail, "tip": d4_tip, "weight": 0.15},
        {"name": "Cost Efficiency", "name_zh": "成本效率", "score": d5_score, "benchmark": 70, "detail": d5_detail, "tip": d5_tip, "weight": 0.15},
        {"name": "Session Focus", "name_zh": "会话聚焦度", "score": d6_score, "benchmark": 75, "detail": d6_detail, "tip": d6_tip, "weight": 0.15},
    ]

    overall = round(sum(d["score"] * d["weight"] for d in dimensions))

    # Top 3 improvement tips sorted by largest gap
    sorted_dims = sorted(dimensions, key=lambda d: d["benchmark"] - d["score"], reverse=True)
    top_tips = []
    for d in sorted_dims[:3]:
        gap = d["benchmark"] - d["score"]
        if gap > 0:
            top_tips.append(f"【{d['name_zh']}】差距{gap}分 — {d['tip']}")

    return {
        "overall_score": overall,
        "period_days": days,
        "total_tools": total_tools,
        "total_cost": round(tok["cost"], 2),
        "session_count": session_count,
        "dimensions": dimensions,
        "top_tips": top_tips
    }


def api_cost_summary():
    """总体成本概览"""
    db = get_db()
    total = db.execute("SELECT COALESCE(SUM(total_cost_usd),0) as cost, COALESCE(SUM(message_count),0) as msgs, COUNT(*) as days FROM token_daily").fetchone()
    today_str = datetime.now().strftime("%Y-%m-%d")
    today = db.execute("SELECT COALESCE(total_cost_usd,0) as cost FROM token_daily WHERE date = ?", (today_str,)).fetchone()
    # 本周
    this_monday = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime("%Y-%m-%d")
    week = db.execute("SELECT COALESCE(SUM(total_cost_usd),0) as cost FROM token_daily WHERE date >= ?", (this_monday,)).fetchone()
    # 本月
    month_start = datetime.now().strftime("%Y-%m-01")
    month = db.execute("SELECT COALESCE(SUM(total_cost_usd),0) as cost FROM token_daily WHERE date >= ?", (month_start,)).fetchone()
    db.close()
    return {
        "total_cost": round(total["cost"], 2),
        "total_messages": total["msgs"],
        "total_days": total["days"],
        "today_cost": round(today["cost"], 2) if today else 0,
        "week_cost": round(week["cost"], 2),
        "month_cost": round(month["cost"], 2)
    }


# 项目别名映射（合并同项目的不同目录名）
# 可在这里添加: "旧目录名": "合并到的项目名"
PROJECT_ALIASES = {
    "tech-assessment": "CodeLens",
    "HireFlow-to-Candidate": "MockPro",
}


def _clean_project_name(raw):
    """清理项目名：-Users-xxx-Desktop-X → X, -Users-xxx → global, 合并别名"""
    if not raw or raw == "unknown":
        return raw or "unknown"
    if "-Desktop-" in raw:
        name = raw.split("-Desktop-", 1)[1]
    elif "-Projects-" in raw:
        name = raw.split("-Projects-", 1)[1]
    elif raw.startswith("-Users-") and "-" not in raw[7:]:
        name = "global"
    else:
        name = raw
    return PROJECT_ALIASES.get(name, name)


def api_project_costs(days=30):
    """各项目Claude成本排行"""
    db = get_db()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    rows = db.execute(
        "SELECT project, ROUND(SUM(cost_usd),2) as cost, SUM(input_tokens+output_tokens) as tokens, "
        "COUNT(DISTINCT session_id) as sessions, COUNT(*) as msgs, "
        "MIN(date) as first_date, MAX(date) as last_date "
        "FROM token_usage WHERE date >= ? AND project != '' "
        "GROUP BY project ORDER BY cost DESC",
        (cutoff,)
    ).fetchall()

    # 合并同名项目（清理后可能重名）
    merged = {}
    for r in rows:
        name = _clean_project_name(r["project"])
        if name in merged:
            m = merged[name]
            m["cost"] += r["cost"]
            m["tokens"] += r["tokens"]
            m["sessions"] += r["sessions"]
            m["msgs"] += r["msgs"]
            m["first_date"] = min(m["first_date"], r["first_date"]) if r["first_date"] else m["first_date"]
            m["last_date"] = max(m["last_date"], r["last_date"]) if r["last_date"] else m["last_date"]
        else:
            merged[name] = {
                "cost": r["cost"], "tokens": r["tokens"], "sessions": r["sessions"],
                "msgs": r["msgs"], "first_date": r["first_date"], "last_date": r["last_date"]
            }

    total_cost = sum(m["cost"] for m in merged.values()) or 1
    sorted_projects = sorted(merged.items(), key=lambda x: x[1]["cost"], reverse=True)

    result = []
    for name, m in sorted_projects:
        cost = m["cost"]
        result.append({
            "project": name,
            "cost": round(cost, 2),
            "percentage": round(cost / total_cost * 100, 1),
            "tokens": m["tokens"],
            "sessions": m["sessions"],
            "messages": m["msgs"],
            "first_date": m["first_date"],
            "last_date": m["last_date"],
            "cost_per_session": round(cost / max(m["sessions"], 1), 2),
        })

    db.close()
    return {"total_cost": round(total_cost, 2), "period_days": days, "projects": result}


def api_daily_history(days=14):
    """最近N天每日概览（每天有哪些会话，做了什么）"""
    db = get_db()
    results = []
    for i in range(days - 1, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        nd = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

        # 会话摘要
        sessions = db.execute(
            "SELECT session_id, project, topic, tool_calls, printf('%.2f', total_cost_usd) as cost, start_time FROM session_summaries WHERE date = ? ORDER BY start_time",
            (d,)
        ).fetchall()

        # 基础统计
        stats = db.execute(
            "SELECT COUNT(*) as sess, COALESCE(SUM(total_tools),0) as tools FROM sessions WHERE start_time >= ? AND start_time < ?",
            (f"{d}T00:00:00", f"{nd}T00:00:00")
        ).fetchone()

        # git提交
        report = db.execute(
            "SELECT total_commits, total_files_changed FROM daily_reports WHERE date = ?", (d,)
        ).fetchone()

        # token成本
        token = db.execute(
            "SELECT COALESCE(total_cost_usd,0) as cost FROM token_daily WHERE date = ?", (d,)
        ).fetchone()

        if not sessions and (stats["sess"] == 0):
            continue

        results.append({
            "date": d,
            "sessions": [{**dict(s), "project": _clean_project_name(s["project"])} for s in sessions],
            "session_count": stats["sess"],
            "tool_uses": stats["tools"],
            "commits": report["total_commits"] if report else 0,
            "files_changed": report["total_files_changed"] if report else 0,
            "cost": float(token["cost"]) if token else 0
        })

    db.close()
    return list(reversed(results))  # 最新日期在前


def api_session_detail(session_id):
    """单个会话详情"""
    db = get_db()
    summary = db.execute(
        "SELECT * FROM session_summaries WHERE session_id = ?", (session_id,)
    ).fetchone()
    tools = db.execute(
        "SELECT tool_name, COUNT(*) as cnt FROM tool_uses WHERE session_id = ? GROUP BY tool_name ORDER BY cnt DESC",
        (session_id,)
    ).fetchall()
    db.close()
    if summary:
        result = dict(summary)
        result["tool_breakdown"] = [dict(t) for t in tools]
        return result
    return {"error": "session not found"}


SESSIONS_DIR = os.path.expanduser("~/.claude/projects")


def _extract_text(content):
    """从消息content中提取纯文本"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
        return " ".join(parts)
    return ""


def api_search(query, max_results=50):
    """搜索所有JSONL会话文件中的对话记录"""
    if not query or len(query) < 2:
        return {"query": query, "results": [], "total": 0, "error": "关键词至少2个字符"}

    results = []
    try:
        pattern = re.compile(re.escape(query), re.IGNORECASE)
    except re.error:
        return {"query": query, "results": [], "total": 0, "error": "无效的搜索关键词"}

    # 遍历所有项目目录下的JSONL文件
    for proj_dir in globmod.glob(os.path.join(SESSIONS_DIR, "*")):
        if not os.path.isdir(proj_dir):
            continue
        project = _clean_project_name(os.path.basename(proj_dir))

        for jsonl_file in globmod.glob(os.path.join(proj_dir, "*.jsonl")):
            try:
                with open(jsonl_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
            except Exception:
                continue

            # 构建消息上下文列表
            messages = []
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = data.get("type")
                if msg_type not in ("human", "assistant"):
                    continue

                timestamp = data.get("timestamp", "")
                session_id = data.get("sessionId", "")

                if msg_type == "human":
                    msg = data.get("message", {})
                    content = _extract_text(msg.get("content", ""))
                    role = "user"
                elif msg_type == "assistant":
                    msg = data.get("message", {})
                    content = _extract_text(msg.get("content", ""))
                    role = "assistant"
                else:
                    continue

                if content:
                    messages.append({
                        "role": role,
                        "content": content,
                        "timestamp": timestamp,
                        "session_id": session_id,
                    })

            # 搜索匹配
            for i, m in enumerate(messages):
                if not pattern.search(m["content"]):
                    continue

                # 提取匹配片段（前后各100字符）
                text = m["content"]
                match = pattern.search(text)
                start = max(0, match.start() - 100)
                end = min(len(text), match.end() + 100)
                snippet = text[start:end]
                if start > 0:
                    snippet = "..." + snippet
                if end < len(text):
                    snippet = snippet + "..."

                # 获取前后各1条消息作为上下文
                context_before = ""
                context_after = ""
                if i > 0:
                    prev = messages[i - 1]
                    prev_text = prev["content"][:150]
                    context_before = f"[{prev['role']}] {prev_text}{'...' if len(prev['content']) > 150 else ''}"
                if i + 1 < len(messages):
                    nxt = messages[i + 1]
                    nxt_text = nxt["content"][:150]
                    context_after = f"[{nxt['role']}] {nxt_text}{'...' if len(nxt['content']) > 150 else ''}"

                results.append({
                    "role": m["role"],
                    "snippet": snippet,
                    "context_before": context_before,
                    "context_after": context_after,
                    "project": project,
                    "date": m["timestamp"][:10] if m["timestamp"] else "",
                    "time": m["timestamp"][11:16] if len(m["timestamp"]) > 16 else "",
                    "session_id": m["session_id"][:12] if m["session_id"] else "",
                })

                if len(results) >= max_results:
                    break
            if len(results) >= max_results:
                break
        if len(results) >= max_results:
            break

    # 按时间倒序
    results.sort(key=lambda r: r.get("date", "") + r.get("time", ""), reverse=True)

    return {"query": query, "results": results, "total": len(results)}


class DashboardHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        today = datetime.now().strftime("%Y-%m-%d")

        if parsed.path == "/" or parsed.path == "/dashboard":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            with open(DASHBOARD_HTML, 'r', encoding='utf-8') as f:
                self.wfile.write(f.read().encode())
            return

        # API 路由
        api_routes = {
            "/api/summary": lambda: api_summary(params.get("date", [today])[0]),
            "/api/tools": lambda: api_tools(params.get("date", [today])[0]),
            "/api/timeline": lambda: api_timeline(params.get("date", [today])[0]),
            "/api/trend": lambda: api_trend(int(params.get("days", ["7"])[0])),
            "/api/projects": lambda: api_projects(params.get("date", [today])[0]),
            "/api/report": lambda: api_report(params.get("date", [today])[0]),
            "/api/weekly": lambda: api_weekly_compare(),
            "/api/tokens": lambda: api_tokens(params.get("date", [today])[0]),
            "/api/token-trend": lambda: api_token_trend(int(params.get("days", ["7"])[0])),
            "/api/models": lambda: api_model_breakdown(params.get("date", [today])[0]),
            "/api/top-sessions": lambda: api_top_sessions(int(params.get("limit", ["10"])[0])),
            "/api/cost-summary": lambda: api_cost_summary(),
            "/api/benchmark": lambda: api_benchmark(int(params.get("days", ["30"])[0])),
            "/api/advice": lambda: analyze_sessions(int(params.get("days", ["30"])[0])),
            "/api/project-costs": lambda: api_project_costs(int(params.get("days", ["30"])[0])),
            "/api/daily-history": lambda: api_daily_history(int(params.get("days", ["14"])[0])),
            "/api/session-detail": lambda: api_session_detail(params.get("id", [""])[0]),
            "/api/search": lambda: api_search(params.get("q", [""])[0], int(params.get("limit", ["50"])[0])),
            "/api/session-advice": lambda: get_session_advice(params.get("id", [""])[0]),
        }

        if parsed.path in api_routes:
            try:
                data = api_routes[parsed.path]()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        # 静默日志
        pass


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8001
    server = HTTPServer(("127.0.0.1", port), DashboardHandler)
    print(f"Dashboard 启动: http://localhost:{port}")
    print(f"数据库: {DB_PATH}")
    print("Ctrl+C 退出")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        server.server_close()


if __name__ == "__main__":
    main()
