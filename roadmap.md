# Engineering Efficiency Roadmap

## Phase 1: 数据采集层（当前）

### 1.1 Claude Code Hooks → SQLite 实时采集
- [x] 创建 `hooks/session-tracker.sh` — 处理 SessionStart/PostToolUse/SessionEnd
- [x] SQLite schema 设计（sessions + tool_uses 表）
- [x] 安装脚本 `scripts/install-hooks.sh` 自动写入 `~/.claude/settings.json`
- [x] PostToolUse 设为 async:true 避免拖慢响应

### 1.2 日报系统迁移
- [x] 从 `~/.claude/daily-summary.py` 迁移到项目内 `scripts/daily-summary.py`
- [x] 日报数据同步写入 SQLite（daily_reports 表）
- [x] launchd 定时任务指向新路径
- [ ] 日报增加 Claude Code 会话统计（从 efficiency.db 读取当日数据）

### 1.3 数据验证
- [ ] 手动触发一次完整流程验证
- [ ] 确认 hooks 不影响 Claude Code 正常使用
- [ ] 确认日报能正确读取 SQLite 数据

---

## Phase 2: 可视化面板（已完成）

> UIUX专家评审后实施，弃用Datasette改为自研Dashboard

### 2.1 自研Dashboard（替代Datasette）
- [x] `src/dashboard.py` — Python HTTP server，7个API端点
- [x] `src/dashboard.html` — 单页面Dashboard，Chart.js + Tailwind CSS
- [x] 深色主题，WCAG AA对比度
- [x] 响应式布局（移动端适配）
- [x] 启动: `python3 src/dashboard.py [port]` → localhost:8001

### 2.2 Dashboard功能
- [x] 产品贡献度环形大卡（核心指标突出）
- [x] 4个辅助KPI卡片（会话/工具/提交/文件）
- [x] 本周vs上周对比条（带涨跌箭头）
- [x] 工具使用分布（水平条形图，按次数排序）
- [x] 近7天趋势折线图（工具调用+提交）
- [x] 今日时间线视图（按时间顺序展示工作流）
- [x] 项目分布条形图
- [x] 贡献度分类条形图
- [x] 日报Markdown渲染

### 2.3 待优化
- [ ] 工具使用热力图（什么时段用什么工具最多）
- [ ] launchd自动启动dashboard服务

---

## Phase 3: Token 用量分析（已完成）

### 3.1 JSONL 解析
- [x] `src/token_analyzer.py` — 解析所有 `~/.claude/projects/*/` 下的 JSONL 文件
- [x] 提取 token 用量（input_tokens, output_tokens, cache_creation, cache_read）
- [x] 按会话、按天聚合写入 SQLite（token_usage + token_daily 表）
- [x] 增量同步（通过 message_id 去重，不重复解析）
- [x] 日报生成时自动触发 token 同步

### 3.2 成本估算
- [x] 按模型定价计算（Opus/Sonnet/Haiku 各有独立定价）
- [x] 成本趋势柱状图（近7天）
- [x] 今日/本周/本月/总计 成本KPI卡片
- [x] Token分解可视化（Input/Output/Cache Write/Cache Read）
- [x] 按模型分解（哪个模型花钱最多）
- [x] 高成本会话 Top 5 排行（带项目名、会话ID、成本）
- [x] 日报中增加 Token 成本摘要section

---

## Phase 4: 智能分析

### 4.1 效率指标
- [ ] 定义"有效工作时间"指标（排除空闲、重复操作）
- [ ] 工具使用效率分析（哪些工具组合最高效）
- [ ] 项目切换频率分析

### 4.2 自动建议
- [ ] 基于历史数据推荐最优工作时段
- [ ] 检测重复模式（同一文件反复编辑→可能需要重构）
- [ ] 周报自动生成 + 下周计划建议

---

## Phase 5: 跨会话记忆（claude-mem 集成）

### 5.1 记忆持久化
- [ ] 评估 claude-mem MCP server 成熟度
- [ ] 集成跨会话上下文保留
- [ ] 记忆数据可视化

### 5.2 知识图谱
- [ ] 项目间关联分析
- [ ] 技术栈使用趋势
- [ ] 决策历史追溯

---

## 已完成事项

### 基础设施
- [x] 项目创建 (`~/Projects/Engineering-Efficiency`)
- [x] CLAUDE.md / README.md / roadmap.md
- [x] gen_horror_images.py API Key 硬编码修复 → 环境变量
- [x] SF_API_KEY 写入 ~/.zshrc

### 日报系统 v1（已上线）
- [x] `~/.claude/daily-summary.py` — git活动扫描 + 贡献度分析
- [x] launchd 每晚23:30自动执行
- [x] 支持手动指定日期生成
