#!/bin/bash
# Claude Code Hooks 事件采集器
# 处理 SessionStart / PostToolUse / SessionEnd 事件
# 数据写入 ~/.claude/efficiency.db

set -e

DB="$HOME/.claude/efficiency.db"
INPUT=$(cat)
EVENT=$(echo "$INPUT" | /usr/bin/python3 -c "import sys,json; print(json.load(sys.stdin).get('hook_event_name',''))" 2>/dev/null || echo "")
SESSION_ID=$(echo "$INPUT" | /usr/bin/python3 -c "import sys,json; print(json.load(sys.stdin).get('session_id',''))" 2>/dev/null || echo "")
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# 确保数据库和表存在
sqlite3 "$DB" <<'SCHEMA'
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    start_time TEXT,
    end_time TEXT,
    cwd TEXT,
    project TEXT,
    total_tools INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tool_uses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    tool_name TEXT,
    timestamp TEXT,
    success INTEGER DEFAULT 1,
    FOREIGN KEY(session_id) REFERENCES sessions(session_id)
);
SCHEMA

case "$EVENT" in
    SessionStart)
        CWD=$(echo "$INPUT" | /usr/bin/python3 -c "import sys,json; print(json.load(sys.stdin).get('cwd',''))" 2>/dev/null || echo "")
        PROJECT=$(basename "$CWD" 2>/dev/null || echo "unknown")
        sqlite3 "$DB" "INSERT OR IGNORE INTO sessions (session_id, start_time, cwd, project) VALUES ('$SESSION_ID', '$TIMESTAMP', '$CWD', '$PROJECT');"
        ;;
    PostToolUse)
        TOOL_NAME=$(echo "$INPUT" | /usr/bin/python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_name',''))" 2>/dev/null || echo "")
        sqlite3 "$DB" "INSERT INTO tool_uses (session_id, tool_name, timestamp) VALUES ('$SESSION_ID', '$TOOL_NAME', '$TIMESTAMP');"
        sqlite3 "$DB" "UPDATE sessions SET total_tools = total_tools + 1 WHERE session_id = '$SESSION_ID';"
        ;;
    SessionEnd)
        sqlite3 "$DB" "UPDATE sessions SET end_time = '$TIMESTAMP' WHERE session_id = '$SESSION_ID';"
        ;;
esac

exit 0
