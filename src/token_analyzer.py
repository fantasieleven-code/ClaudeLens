#!/usr/bin/env python3
"""
Token用量分析器
解析 Claude Code JSONL session文件，提取token用量，写入SQLite
"""

import os
import json
import sqlite3
import glob
from datetime import datetime, timedelta

SESSIONS_DIR = os.path.expanduser("~/.claude/projects")
EFFICIENCY_DB = os.path.expanduser("~/.claude/efficiency.db")

# Claude 模型定价 (USD per million tokens)
MODEL_PRICING = {
    "claude-opus-4-6": {
        "input": 15.0,
        "output": 75.0,
        "cache_write": 18.75,  # 1.25x input
        "cache_read": 1.50,    # 0.1x input
    },
    "claude-sonnet-4-6": {
        "input": 3.0,
        "output": 15.0,
        "cache_write": 3.75,
        "cache_read": 0.30,
    },
    "claude-haiku-4-5-20251001": {
        "input": 0.80,
        "output": 4.0,
        "cache_write": 1.0,
        "cache_read": 0.08,
    },
}

# 默认定价（未知模型按Sonnet算）
DEFAULT_PRICING = MODEL_PRICING["claude-sonnet-4-6"]


def init_db():
    """初始化token_usage表"""
    db = sqlite3.connect(EFFICIENCY_DB)
    db.execute("""CREATE TABLE IF NOT EXISTS token_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        message_id TEXT UNIQUE,
        timestamp TEXT,
        date TEXT,
        model TEXT,
        input_tokens INTEGER DEFAULT 0,
        output_tokens INTEGER DEFAULT 0,
        cache_write_tokens INTEGER DEFAULT 0,
        cache_read_tokens INTEGER DEFAULT 0,
        cost_usd REAL DEFAULT 0,
        project TEXT
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS token_daily (
        date TEXT PRIMARY KEY,
        total_input INTEGER DEFAULT 0,
        total_output INTEGER DEFAULT 0,
        total_cache_write INTEGER DEFAULT 0,
        total_cache_read INTEGER DEFAULT 0,
        total_cost_usd REAL DEFAULT 0,
        message_count INTEGER DEFAULT 0
    )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_token_date ON token_usage(date)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_token_session ON token_usage(session_id)")
    db.commit()
    return db


def calc_cost(model, input_t, output_t, cache_write_t, cache_read_t):
    """计算单条消息成本"""
    pricing = DEFAULT_PRICING
    for key, p in MODEL_PRICING.items():
        if key in (model or ""):
            pricing = p
            break

    cost = (
        input_t * pricing["input"] / 1_000_000 +
        output_t * pricing["output"] / 1_000_000 +
        cache_write_t * pricing["cache_write"] / 1_000_000 +
        cache_read_t * pricing["cache_read"] / 1_000_000
    )
    return round(cost, 6)


def extract_project_from_path(filepath):
    """从JSONL路径提取项目名"""
    # ~/.claude/projects/-Users-stevezhu-Projects-XXX/session.jsonl
    parts = filepath.split("/")
    for i, p in enumerate(parts):
        if p == "projects" and i + 1 < len(parts):
            proj_dir = parts[i + 1]
            # 取最后一个有意义的段
            segments = proj_dir.split("-")
            # 找Projects后面的部分
            for j, s in enumerate(segments):
                if s == "Projects" and j + 1 < len(segments):
                    return "-".join(segments[j + 1:])
            return proj_dir
    return "unknown"


def parse_jsonl_file(filepath, db, existing_ids):
    """解析单个JSONL文件，提取token用量"""
    project = extract_project_from_path(filepath)
    new_records = []

    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            # 只处理assistant消息（包含usage）
            if data.get("type") != "assistant":
                continue

            msg = data.get("message", {})
            usage = msg.get("usage")
            if not usage:
                continue

            msg_id = msg.get("id", "")
            if not msg_id or msg_id in existing_ids:
                continue

            session_id = data.get("sessionId", "")
            timestamp = data.get("timestamp", "")
            date = timestamp[:10] if timestamp else ""
            model = msg.get("model", "")

            input_t = usage.get("input_tokens", 0)
            output_t = usage.get("output_tokens", 0)
            cache_write_t = usage.get("cache_creation_input_tokens", 0)
            cache_read_t = usage.get("cache_read_input_tokens", 0)

            cost = calc_cost(model, input_t, output_t, cache_write_t, cache_read_t)

            new_records.append((
                session_id, msg_id, timestamp, date, model,
                input_t, output_t, cache_write_t, cache_read_t,
                cost, project
            ))
            existing_ids.add(msg_id)

    if new_records:
        db.executemany(
            "INSERT OR IGNORE INTO token_usage (session_id, message_id, timestamp, date, model, input_tokens, output_tokens, cache_write_tokens, cache_read_tokens, cost_usd, project) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            new_records
        )
        db.commit()

    return len(new_records)


def aggregate_daily(db):
    """聚合每日token用量"""
    db.execute("DELETE FROM token_daily")
    db.execute("""INSERT INTO token_daily (date, total_input, total_output, total_cache_write, total_cache_read, total_cost_usd, message_count)
        SELECT date, SUM(input_tokens), SUM(output_tokens), SUM(cache_write_tokens), SUM(cache_read_tokens), SUM(cost_usd), COUNT(*)
        FROM token_usage
        WHERE date != ''
        GROUP BY date
        ORDER BY date
    """)
    db.commit()


def sync_all():
    """扫描所有JSONL文件，同步token数据"""
    db = init_db()

    # 获取已处理的message_id
    existing = set(r[0] for r in db.execute("SELECT message_id FROM token_usage").fetchall())

    total_new = 0
    total_files = 0

    # 遍历所有项目目录
    for proj_dir in glob.glob(os.path.join(SESSIONS_DIR, "*")):
        if not os.path.isdir(proj_dir):
            continue
        for jsonl_file in glob.glob(os.path.join(proj_dir, "*.jsonl")):
            total_files += 1
            new = parse_jsonl_file(jsonl_file, db, existing)
            total_new += new

    # 聚合每日数据
    aggregate_daily(db)

    # 统计
    total_records = db.execute("SELECT COUNT(*) FROM token_usage").fetchone()[0]
    total_cost = db.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM token_usage").fetchone()[0]
    days = db.execute("SELECT COUNT(*) FROM token_daily").fetchone()[0]

    db.close()

    print(f"扫描 {total_files} 个JSONL文件")
    print(f"新增 {total_new} 条记录（总计 {total_records} 条）")
    print(f"覆盖 {days} 天")
    print(f"总成本: ${total_cost:.2f}")

    return total_new


def get_daily_cost(date_str):
    """获取某天的成本数据"""
    db = sqlite3.connect(EFFICIENCY_DB)
    db.row_factory = sqlite3.Row
    row = db.execute("SELECT * FROM token_daily WHERE date = ?", (date_str,)).fetchone()
    db.close()
    if row:
        return dict(row)
    return None


def get_cost_trend(days=7):
    """获取最近N天成本趋势"""
    db = sqlite3.connect(EFFICIENCY_DB)
    db.row_factory = sqlite3.Row
    start = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    rows = db.execute(
        "SELECT * FROM token_daily WHERE date >= ? ORDER BY date", (start,)
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def get_model_breakdown(date_str=None):
    """按模型分解token用量"""
    db = sqlite3.connect(EFFICIENCY_DB)
    db.row_factory = sqlite3.Row
    if date_str:
        rows = db.execute(
            "SELECT model, SUM(input_tokens) as input_t, SUM(output_tokens) as output_t, SUM(cache_write_tokens) as cache_w, SUM(cache_read_tokens) as cache_r, SUM(cost_usd) as cost, COUNT(*) as msgs FROM token_usage WHERE date = ? GROUP BY model",
            (date_str,)
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT model, SUM(input_tokens) as input_t, SUM(output_tokens) as output_t, SUM(cache_write_tokens) as cache_w, SUM(cache_read_tokens) as cache_r, SUM(cost_usd) as cost, COUNT(*) as msgs FROM token_usage GROUP BY model"
        ).fetchall()
    db.close()
    return [dict(r) for r in rows]


def get_top_sessions(limit=10):
    """成本最高的会话"""
    db = sqlite3.connect(EFFICIENCY_DB)
    db.row_factory = sqlite3.Row
    rows = db.execute(
        "SELECT session_id, project, date, SUM(cost_usd) as cost, SUM(input_tokens+output_tokens+cache_write_tokens) as total_tokens, COUNT(*) as msgs FROM token_usage GROUP BY session_id ORDER BY cost DESC LIMIT ?",
        (limit,)
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "trend":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
        for d in get_cost_trend(days):
            print(f"{d['date']}: ${d['total_cost_usd']:.2f} ({d['message_count']} msgs, {d['total_input']+d['total_output']:,} tokens)")
    elif len(sys.argv) > 1 and sys.argv[1] == "top":
        for s in get_top_sessions(5):
            print(f"{s['session_id'][:12]} [{s['project']}] {s['date']}: ${s['cost']:.2f} ({s['msgs']} msgs)")
    else:
        sync_all()
