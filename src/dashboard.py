#!/usr/bin/env python3
"""
Engineering Efficiency Dashboard
轻量级FastAPI server，提供API + 单页面Dashboard
"""

import os
import sys
import json
import sqlite3
from datetime import datetime, timedelta
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

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
    return [{"project": r["project"], "sessions": r["cnt"], "tools": r["tools"] or 0} for r in rows]


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
    return [dict(r) for r in rows]


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
            "sessions": [dict(s) for s in sessions],
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
            "/api/daily-history": lambda: api_daily_history(int(params.get("days", ["14"])[0])),
            "/api/session-detail": lambda: api_session_detail(params.get("id", [""])[0]),
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
