#!/bin/bash
# Claude Code Hooks 事件采集器
# 处理 SessionStart / PostToolUse / SessionEnd 事件
# 数据写入 ~/.claude/efficiency.db

DB="$HOME/.claude/efficiency.db"
INPUT=$(cat)

# 用Python安全解析JSON并直接写入SQLite（避免shell SQL注入）
/usr/bin/python3 -c "
import sys, json, sqlite3, os
from datetime import datetime, timezone

db_path = os.path.expanduser('~/.claude/efficiency.db')
try:
    data = json.loads('''$( echo "$INPUT" | sed "s/'/'\\\\''/g" )''')
except:
    try:
        data = json.load(open('/dev/stdin'))
    except:
        sys.exit(0)

event = data.get('hook_event_name', '')
session_id = data.get('session_id', '')
ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

if not event or not session_id:
    sys.exit(0)

db = sqlite3.connect(db_path)
db.execute('''CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY, start_time TEXT, end_time TEXT,
    cwd TEXT, project TEXT, total_tools INTEGER DEFAULT 0)''')
db.execute('''CREATE TABLE IF NOT EXISTS tool_uses (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT,
    tool_name TEXT, timestamp TEXT, success INTEGER DEFAULT 1,
    FOREIGN KEY(session_id) REFERENCES sessions(session_id))''')

if event == 'SessionStart':
    cwd = data.get('cwd', '')
    project = os.path.basename(cwd) if cwd else 'unknown'
    db.execute('INSERT OR IGNORE INTO sessions (session_id, start_time, cwd, project) VALUES (?,?,?,?)',
               (session_id, ts, cwd, project))
elif event == 'PostToolUse':
    tool_name = data.get('tool_name', '')
    db.execute('INSERT INTO tool_uses (session_id, tool_name, timestamp) VALUES (?,?,?)',
               (session_id, tool_name, ts))
    db.execute('UPDATE sessions SET total_tools = total_tools + 1 WHERE session_id = ?',
               (session_id,))
elif event == 'SessionEnd':
    db.execute('UPDATE sessions SET end_time = ? WHERE session_id = ?',
               (ts, session_id))

db.commit()
db.close()
" <<< "$INPUT" 2>/dev/null

exit 0
