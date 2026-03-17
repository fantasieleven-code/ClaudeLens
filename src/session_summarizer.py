#!/usr/bin/env python3
"""
会话摘要提取器
从JSONL文件提取每个会话的主题（第一条用户消息）和关键统计
写入SQLite session_summaries表
"""

import os
import json
import sqlite3
import glob
from datetime import datetime

SESSIONS_DIR = os.path.expanduser("~/.claude/projects")
EFFICIENCY_DB = os.path.expanduser("~/.claude/efficiency.db")


def init_db():
    db = sqlite3.connect(EFFICIENCY_DB)
    db.execute("""CREATE TABLE IF NOT EXISTS session_summaries (
        session_id TEXT PRIMARY KEY,
        project TEXT,
        date TEXT,
        start_time TEXT,
        topic TEXT,
        user_messages INTEGER DEFAULT 0,
        assistant_messages INTEGER DEFAULT 0,
        tool_calls INTEGER DEFAULT 0,
        tools_used TEXT,
        total_input_tokens INTEGER DEFAULT 0,
        total_output_tokens INTEGER DEFAULT 0,
        total_cost_usd REAL DEFAULT 0
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_summary_date ON session_summaries(date)")
    db.commit()
    return db


def extract_user_content(content):
    """从用户消息content提取文本"""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    texts.append(item.get("text", ""))
        return " ".join(texts).strip()
    return ""


def extract_project(filepath):
    """从路径提取项目名"""
    parts = filepath.split("/")
    for i, p in enumerate(parts):
        if p == "projects" and i + 1 < len(parts):
            proj_dir = parts[i + 1]
            if "-Projects-" in proj_dir:
                return proj_dir.split("-Projects-", 1)[1]
            if proj_dir.startswith("-Users-"):
                return "global"
            return proj_dir
    return "unknown"


def parse_session(filepath):
    """解析单个JSONL文件，提取会话摘要"""
    project = extract_project(filepath)
    session_id = os.path.basename(filepath).replace(".jsonl", "")

    topic = ""
    first_user_found = False
    start_time = ""
    user_msgs = 0
    assistant_msgs = 0
    tool_calls = 0
    tools_set = set()
    total_input = 0
    total_output = 0
    total_cost = 0

    # 模型定价
    pricing = {
        "claude-opus-4-6": {"input": 15.0, "output": 75.0, "cache_write": 18.75, "cache_read": 1.50},
        "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30},
    }
    default_p = pricing["claude-sonnet-4-6"]

    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type", "")
            timestamp = data.get("timestamp", "")

            if msg_type == "user":
                user_msgs += 1
                if not first_user_found:
                    content = extract_user_content(data.get("message", {}).get("content", ""))
                    if content and len(content) > 2:
                        # 跳过纯tool_result的消息
                        topic = content[:200]
                        first_user_found = True
                        if not start_time:
                            start_time = timestamp

            elif msg_type == "assistant":
                assistant_msgs += 1
                if not start_time and timestamp:
                    start_time = timestamp

                msg = data.get("message", {})
                usage = msg.get("usage", {})
                model = msg.get("model", "")

                inp = usage.get("input_tokens", 0)
                out = usage.get("output_tokens", 0)
                cw = usage.get("cache_creation_input_tokens", 0)
                cr = usage.get("cache_read_input_tokens", 0)

                total_input += inp + cw + cr
                total_output += out

                # 计算成本
                p = default_p
                for k, v in pricing.items():
                    if k in model:
                        p = v
                        break
                total_cost += (
                    inp * p["input"] / 1e6 +
                    out * p["output"] / 1e6 +
                    cw * p["cache_write"] / 1e6 +
                    cr * p["cache_read"] / 1e6
                )

                # 统计工具调用
                contents = msg.get("content", [])
                if isinstance(contents, list):
                    for block in contents:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            tool_calls += 1
                            tools_set.add(block.get("name", ""))

    if not topic and not first_user_found:
        topic = "(无用户消息)"

    date = start_time[:10] if start_time else ""

    return {
        "session_id": session_id,
        "project": project,
        "date": date,
        "start_time": start_time,
        "topic": topic,
        "user_messages": user_msgs,
        "assistant_messages": assistant_msgs,
        "tool_calls": tool_calls,
        "tools_used": ",".join(sorted(tools_set)[:10]),
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_cost_usd": round(total_cost, 4)
    }


def sync_all():
    """同步所有会话摘要"""
    db = init_db()
    existing = set(r[0] for r in db.execute("SELECT session_id FROM session_summaries").fetchall())

    total_new = 0
    for proj_dir in glob.glob(os.path.join(SESSIONS_DIR, "*")):
        if not os.path.isdir(proj_dir):
            continue
        for jsonl_file in glob.glob(os.path.join(proj_dir, "*.jsonl")):
            sid = os.path.basename(jsonl_file).replace(".jsonl", "")
            if sid in existing:
                continue

            summary = parse_session(jsonl_file)
            if not summary["date"]:
                continue

            db.execute(
                "INSERT OR REPLACE INTO session_summaries VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (summary["session_id"], summary["project"], summary["date"],
                 summary["start_time"], summary["topic"],
                 summary["user_messages"], summary["assistant_messages"],
                 summary["tool_calls"], summary["tools_used"],
                 summary["total_input_tokens"], summary["total_output_tokens"],
                 summary["total_cost_usd"])
            )
            total_new += 1

    db.commit()

    total = db.execute("SELECT COUNT(*) FROM session_summaries").fetchone()[0]
    db.close()

    print(f"新增 {total_new} 个会话摘要（总计 {total}）")
    return total_new


if __name__ == "__main__":
    sync_all()
