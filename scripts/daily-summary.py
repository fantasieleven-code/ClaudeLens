#!/usr/bin/env python3
"""
Claude Code 日报自动生成器 v2
- 扫描当天的git活动、文件变更，生成结构化日报
- 从 efficiency.db 读取 Claude Code 会话统计
- 日报数据同步写入 SQLite
"""

import os
import subprocess
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

PROJECTS_DIR = os.path.expanduser("~/Projects")
DAILY_LOG_DIR = os.path.expanduser("~/.claude/daily-logs")
EFFICIENCY_DB = os.path.expanduser("~/.claude/efficiency.db")

os.makedirs(DAILY_LOG_DIR, exist_ok=True)


def run_cmd(cmd, cwd=None):
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=30)
        return result.stdout.strip()
    except Exception:
        return ""


def get_db():
    """获取SQLite连接，创建日报表如不存在"""
    db = sqlite3.connect(EFFICIENCY_DB)
    db.execute("""CREATE TABLE IF NOT EXISTS daily_reports (
        date TEXT PRIMARY KEY,
        report_md TEXT,
        total_commits INTEGER DEFAULT 0,
        total_files_changed INTEGER DEFAULT 0,
        contribution_scores TEXT,
        created_at TEXT
    )""")
    db.commit()
    return db


def get_session_stats(date_str):
    """从efficiency.db读取当日Claude Code会话统计"""
    if not os.path.exists(EFFICIENCY_DB):
        return None

    try:
        db = sqlite3.connect(EFFICIENCY_DB)
        next_day = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

        # 会话数
        sessions = db.execute(
            "SELECT COUNT(*), SUM(total_tools) FROM sessions WHERE start_time >= ? AND start_time < ?",
            (f"{date_str}T00:00:00", f"{next_day}T00:00:00")
        ).fetchone()

        # 工具使用分布
        tools = db.execute(
            "SELECT tool_name, COUNT(*) FROM tool_uses WHERE timestamp >= ? AND timestamp < ? GROUP BY tool_name ORDER BY COUNT(*) DESC",
            (f"{date_str}T00:00:00", f"{next_day}T00:00:00")
        ).fetchall()

        # 项目分布
        projects = db.execute(
            "SELECT project, COUNT(*) FROM sessions WHERE start_time >= ? AND start_time < ? GROUP BY project ORDER BY COUNT(*) DESC",
            (f"{date_str}T00:00:00", f"{next_day}T00:00:00")
        ).fetchall()

        db.close()

        if sessions[0] == 0:
            return None

        return {
            "session_count": sessions[0],
            "total_tool_uses": sessions[1] or 0,
            "tool_distribution": tools,
            "project_distribution": projects
        }
    except Exception:
        return None


def get_git_activity(project_path, date_str):
    """获取某天的git提交"""
    next_day = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    commits = run_cmd([
        "git", "log", "--oneline", "--all",
        f"--after={date_str}T00:00:00",
        f"--before={next_day}T00:00:00",
        "--format=%h|%s|%ai"
    ], cwd=project_path)

    diff_stat = run_cmd([
        "git", "log", "--all",
        f"--after={date_str}T00:00:00",
        f"--before={next_day}T00:00:00",
        "--stat", "--format="
    ], cwd=project_path)

    return commits, diff_stat


def get_file_changes(project_path, date_str):
    """获取某天修改的文件"""
    next_day = (datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

    files = run_cmd([
        "git", "log", "--all",
        f"--after={date_str}T00:00:00",
        f"--before={next_day}T00:00:00",
        "--name-only", "--format="
    ], cwd=project_path)

    return list(set(f for f in files.split('\n') if f.strip()))


def get_new_content_files(project_path, date_str):
    """检查新生成的内容文件"""
    content_dir = os.path.join(project_path, "data/output/content")
    if not os.path.isdir(content_dir):
        return []

    new_files = []
    target_date = datetime.strptime(date_str, "%Y-%m-%d")

    for root, dirs, files in os.walk(content_dir):
        for f in files:
            fp = os.path.join(root, f)
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(fp))
                if mtime.date() == target_date.date():
                    rel = os.path.relpath(fp, project_path)
                    new_files.append(rel)
            except Exception:
                pass

    return new_files


def categorize_work(commits, files_changed, new_content):
    """分类工作内容"""
    categories = {
        "产品开发": [],
        "内容生产": [],
        "Bug修复": [],
        "基础设施": [],
        "调研探索": [],
        "其他": []
    }

    for line in commits.split('\n'):
        if not line.strip():
            continue
        lower = line.lower()
        if any(w in lower for w in ['fix', 'bug', '修复', '修正']):
            categories["Bug修复"].append(line)
        elif any(w in lower for w in ['ghost', 'story', 'myth', '鬼故事', '神话', '内容']):
            categories["内容生产"].append(line)
        elif any(w in lower for w in ['script', 'config', 'ci', 'deploy', '脚本', '配置']):
            categories["基础设施"].append(line)
        elif any(w in lower for w in ['feat', 'add', 'update', '功能', '新增', '页面']):
            categories["产品开发"].append(line)
        else:
            categories["其他"].append(line)

    if new_content:
        for f in new_content:
            categories["内容生产"].append(f"新文件: {f}")

    return {k: v for k, v in categories.items() if v}


def calculate_contribution(categories):
    """计算产品贡献度"""
    weights = {
        "产品开发": 1.0,
        "Bug修复": 0.8,
        "内容生产": 0.6,
        "基础设施": 0.5,
        "调研探索": 0.3,
        "其他": 0.1
    }

    total_items = sum(len(v) for v in categories.values())
    if total_items == 0:
        return {}

    contributions = {}
    for cat, items in categories.items():
        weight = weights.get(cat, 0.1)
        raw_score = len(items) * weight
        contributions[cat] = {
            "items": len(items),
            "weight": weight,
            "score": round(raw_score, 1),
            "percentage": 0
        }

    total_score = sum(c["score"] for c in contributions.values())
    if total_score > 0:
        for cat in contributions:
            contributions[cat]["percentage"] = round(
                contributions[cat]["score"] / total_score * 100
            )

    return contributions


def generate_daily_report(date_str=None):
    """生成日报"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    report = f"# 日报 {date_str}\n\n"

    # Claude Code 会话统计
    stats = get_session_stats(date_str)
    if stats:
        report += "## Claude Code 使用统计\n\n"
        report += f"**会话数**: {stats['session_count']} | **工具调用**: {stats['total_tool_uses']}次\n\n"

        if stats['tool_distribution']:
            report += "| 工具 | 调用次数 |\n|------|--------|\n"
            for tool, count in stats['tool_distribution'][:10]:
                report += f"| {tool} | {count} |\n"
            report += "\n"

        if stats['project_distribution']:
            report += "**项目分布**: "
            report += " | ".join(f"{p}({c}次)" for p, c in stats['project_distribution'])
            report += "\n\n"

    all_categories = {}
    project_reports = []
    total_commits = 0
    total_files = 0

    # 扫描所有项目
    for proj_name in os.listdir(PROJECTS_DIR):
        proj_path = os.path.join(PROJECTS_DIR, proj_name)
        if not os.path.isdir(os.path.join(proj_path, ".git")):
            continue

        commits, diff_stat = get_git_activity(proj_path, date_str)
        new_content = get_new_content_files(proj_path, date_str)
        files_changed = get_file_changes(proj_path, date_str)

        if not commits and not new_content:
            continue

        categories = categorize_work(commits, files_changed, new_content)

        proj_report = f"## {proj_name}\n\n"

        if commits:
            commit_count = len([c for c in commits.split('\n') if c.strip()])
            total_commits += commit_count
            proj_report += f"**提交**: {commit_count}次\n"

        if files_changed:
            total_files += len(files_changed)
            proj_report += f"**变更文件**: {len(files_changed)}个\n"

        if new_content:
            proj_report += f"**新内容文件**: {len(new_content)}个\n"

        proj_report += "\n"

        for cat, items in categories.items():
            proj_report += f"### {cat}\n"
            for item in items[:10]:
                parts = item.split('|')
                if len(parts) >= 2:
                    proj_report += f"- `{parts[0]}` {parts[1]}\n"
                else:
                    proj_report += f"- {item}\n"
            if len(items) > 10:
                proj_report += f"- ...还有{len(items)-10}条\n"
            proj_report += "\n"

        project_reports.append(proj_report)

        for cat, items in categories.items():
            if cat not in all_categories:
                all_categories[cat] = []
            all_categories[cat].extend(items)

    if not project_reports and not stats:
        report += "> 今天没有检测到git活动或Claude Code会话。\n\n"
    else:
        # 产品贡献度分析
        contributions = calculate_contribution(all_categories)
        if contributions:
            report += "## 产品贡献度分析\n\n"
            report += "| 类别 | 事项数 | 权重 | 贡献度 |\n"
            report += "|------|--------|------|--------|\n"

            sorted_cats = sorted(contributions.items(),
                               key=lambda x: x[1]['percentage'], reverse=True)
            for cat, info in sorted_cats:
                bar = "█" * (info['percentage'] // 5) + "░" * (20 - info['percentage'] // 5)
                report += f"| {cat} | {info['items']} | {info['weight']} | {info['percentage']}% {bar} |\n"
            report += "\n"

            productive = sum(c['score'] for cat, c in contributions.items()
                           if cat in ['产品开发', 'Bug修复', '内容生产'])
            infra = sum(c['score'] for cat, c in contributions.items()
                       if cat == '基础设施')
            total = sum(c['score'] for c in contributions.values())

            if total > 0:
                prod_pct = round(productive / total * 100)
                report += f"**直接产出**: {prod_pct}% | **基础建设**: {round(infra/total*100)}% | **其他**: {100-prod_pct-round(infra/total*100)}%\n\n"

        for pr in project_reports:
            report += pr

    # 明日待办
    report += "## 明日待办\n\n"
    report += "_（根据今日进展自动推断，请手动调整）_\n\n"

    if '产品开发' in all_categories:
        report += "- [ ] 继续产品开发迭代\n"
    if '内容生产' in all_categories:
        report += "- [ ] 继续内容生产（检查质量、发布）\n"
    if 'Bug修复' in all_categories:
        report += "- [ ] 验证Bug修复效果\n"
    if not all_categories:
        report += "- [ ] 制定今日工作计划\n"
    report += "- [ ] 审核待发布内容\n"
    report += "- [ ] 检查产品指标\n"

    report += "\n---\n_自动生成于 " + datetime.now().strftime("%Y-%m-%d %H:%M") + "_\n"

    # 保存日报 Markdown
    report_path = os.path.join(DAILY_LOG_DIR, f"{date_str}.md")
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)

    # 同步写入 SQLite
    try:
        db = get_db()
        db.execute(
            "INSERT OR REPLACE INTO daily_reports (date, report_md, total_commits, total_files_changed, contribution_scores, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (date_str, report, total_commits, total_files,
             json.dumps(calculate_contribution(all_categories), ensure_ascii=False),
             datetime.now().isoformat())
        )
        db.commit()
        db.close()
    except Exception as e:
        print(f"SQLite写入失败（不影响日报）: {e}")

    print(f"日报已生成: {report_path}")
    print(report)

    return report_path


if __name__ == '__main__':
    import sys
    date = sys.argv[1] if len(sys.argv) > 1 else None
    generate_daily_report(date)
