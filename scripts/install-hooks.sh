#!/bin/bash
# 安装 Claude Code Hooks 到 ~/.claude/settings.json
# 添加 SessionStart / PostToolUse / SessionEnd 事件采集

set -e

SETTINGS="$HOME/.claude/settings.json"
HOOK_SCRIPT="$HOME/Projects/Engineering-Efficiency/hooks/session-tracker.sh"

# 确保 hook 脚本可执行
chmod +x "$HOOK_SCRIPT"

# 备份当前设置
if [ -f "$SETTINGS" ]; then
    cp "$SETTINGS" "${SETTINGS}.bak.$(date +%Y%m%d%H%M%S)"
    echo "已备份: ${SETTINGS}.bak.*"
fi

# 用 Python 安全地合并 hooks 配置到现有 settings.json
/usr/bin/python3 << 'PYEOF'
import json
import os

settings_path = os.path.expanduser("~/.claude/settings.json")
hook_script = os.path.expanduser("~/Projects/Engineering-Efficiency/hooks/session-tracker.sh")

# 读取现有配置
settings = {}
if os.path.exists(settings_path):
    with open(settings_path, 'r') as f:
        settings = json.load(f)

# 准备 hooks 配置
hooks = settings.get("hooks", {})

# SessionStart hook
hooks["SessionStart"] = [{
    "matcher": "",
    "hooks": [{
        "type": "command",
        "command": hook_script
    }]
}]

# PostToolUse hook (async=true 不阻塞)
hooks["PostToolUse"] = [{
    "matcher": "",
    "hooks": [{
        "type": "command",
        "command": hook_script,
        "timeout": 5
    }]
}]

# SessionEnd hook
hooks["SessionEnd"] = [{
    "matcher": "",
    "hooks": [{
        "type": "command",
        "command": hook_script
    }]
}]

settings["hooks"] = hooks

with open(settings_path, 'w') as f:
    json.dump(settings, f, indent=2)

print(f"Hooks 已安装到 {settings_path}")
print(f"  - SessionStart → {hook_script}")
print(f"  - PostToolUse  → {hook_script} (async)")
print(f"  - SessionEnd   → {hook_script}")
PYEOF

echo ""
echo "安装完成！重启 Claude Code 生效。"
echo "数据库位置: ~/.claude/efficiency.db"
echo "查看数据: sqlite3 ~/.claude/efficiency.db 'SELECT * FROM sessions;'"
