# Engineering Efficiency

Claude Code 工程效率追踪系统 — 自动采集工作数据、生成日报、可视化分析。

## 功能

- **实时事件采集**: 通过 Claude Code Hooks 自动记录每次会话、工具调用
- **每日日报**: 23:30 自动扫描 git 活动，生成产品贡献度分析报告
- **数据面板**: Datasette 零代码可视化，浏览器查看历史数据趋势

## 快速开始

```bash
# 1. 安装 hooks（自动修改 ~/.claude/settings.json）
./scripts/install-hooks.sh

# 2. 查看今日日报
python3 scripts/daily-summary.py

# 3. 启动数据面板（可选）
pip install datasette
datasette ~/.claude/efficiency.db
```

## 项目结构

```
hooks/                  # Claude Code Hooks 脚本
  session-tracker.sh    # 会话+工具使用采集→SQLite
scripts/
  daily-summary.py      # 日报生成器（含git扫描+贡献度分析）
  install-hooks.sh      # 一键安装hooks到Claude Code
src/
  dashboard.py          # Datasette 配置和自定义查询
```

## 路线图

详见 [roadmap.md](roadmap.md)
