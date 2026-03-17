# Engineering Efficiency

Claude Code 工程效率追踪系统 — 自动采集工作数据、生成日报、Token成本分析、可视化Dashboard。

## 功能

- **实时事件采集**: 通过 Claude Code Hooks 自动记录每次会话、工具调用
- **每日日报**: 23:30 自动扫描 git 活动，生成产品贡献度分析报告
- **Token成本分析**: 解析JSONL会话文件，按模型计算成本，高消耗预警
- **可视化Dashboard**: 深色主题单页面，KPI卡片+趋势图+时间线+成本分析

## 快速开始

```bash
# 1. 安装 hooks（自动修改 ~/.claude/settings.json）
./scripts/install-hooks.sh

# 2. 同步历史token数据
python3 src/token_analyzer.py

# 3. 查看今日日报
python3 scripts/daily-summary.py

# 4. 启动Dashboard
python3 src/dashboard.py
# 打开 http://localhost:8001
```

## 项目结构

```
hooks/
  session-tracker.sh      # Hooks事件→SQLite（参数化查询，防注入）
scripts/
  daily-summary.py        # 日报生成器（git+会话+token成本）
  install-hooks.sh        # 一键安装hooks
src/
  dashboard.py            # HTTP API server（12个端点）
  dashboard.html          # 单页面Dashboard（Chart.js+Tailwind）
  token_analyzer.py       # JSONL token用量解析+成本计算
```

## 路线图

详见 [roadmap.md](roadmap.md)
