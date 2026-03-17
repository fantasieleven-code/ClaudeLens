# Engineering Efficiency - Claude Code 工程效率追踪系统

## 项目定位
追踪和分析 Claude Code 的使用效率，整合日报系统、Hooks事件采集、token用量统计，提供可视化数据面板。

## 架构

```
Claude Code Session
  ↓ (Hooks: SessionStart/PostToolUse/SessionEnd)
hooks/session-tracker.sh → SQLite (efficiency.db)
  ↓
src/token_analyzer.py → JSONL解析 → token_usage/token_daily表
  ↓
scripts/daily-summary.py → 日报 Markdown（含token成本）
  ↓
src/dashboard.py + dashboard.html → 浏览器可视化Dashboard
```

## 核心组件

| 组件 | 路径 | 职责 |
|------|------|------|
| Hooks采集器 | `hooks/session-tracker.sh` | 实时采集Claude Code事件→SQLite |
| 日报生成器 | `scripts/daily-summary.py` | 每日23:30生成日报（从~/.claude迁移） |
| Token分析 | `src/token_analyzer.py` | 解析JSONL→token用量+成本计算 |
| Dashboard | `src/dashboard.py` + `dashboard.html` | API server + 单页面可视化 |

## 数据库

路径: `~/.claude/efficiency.db`

```sql
-- 会话表
sessions(session_id, start_time, end_time, cwd, project, total_tools, total_duration_seconds)

-- 工具使用表
tool_uses(id, session_id, tool_name, timestamp, success)

-- 日报表
daily_reports(date, report_md, total_commits, total_files_changed, contribution_scores)
```

## 技术栈
- Shell (hooks脚本)
- Python 3.9+ (日报、数据面板)
- SQLite (数据存储)
- Datasette (可视化，按需启用)
- launchd (macOS定时任务)

## 开发规范
1. 中文注释，PEP 8
2. Hooks脚本必须 `exit 0`（不阻塞Claude Code）
3. PostToolUse hook 必须设 `async: true`（不拖慢响应）
4. 敏感数据（API key、密码）不写入SQLite
5. 所有路径用 `$HOME` 或 `os.path.expanduser("~")`

## 相关路径
- Claude Code设置: `~/.claude/settings.json`
- 日报输出: `~/.claude/daily-logs/`
- 效率数据库: `~/.claude/efficiency.db`
- 当前日报脚本(旧): `~/.claude/daily-summary.py`
- launchd任务: `~/Library/LaunchAgents/com.claude.daily-summary.plist`
