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

## Phase 2: 可视化面板

### 2.1 Datasette 基础面板
- [ ] 安装 datasette + datasette-vega（图表插件）
- [ ] 创建预定义查询：每日工具使用分布、会话时长趋势、项目活跃度
- [ ] 配置 `src/metadata.yml`（表描述、查询别名）
- [ ] launchd 自动启动 datasette 服务（localhost:8001）

### 2.2 自定义视图
- [ ] 周报聚合视图（按周汇总贡献度）
- [ ] 项目维度分析（哪个项目花时间最多）
- [ ] 工具使用热力图（什么时段用什么工具最多）

---

## Phase 3: Token 用量分析（ccusage 集成）

### 3.1 JSONL 解析
- [ ] 解析 `~/.claude/projects/*/` 下的 session JSONL 文件
- [ ] 提取 token 用量（input_tokens, output_tokens, cache_read/write）
- [ ] 按会话、按天聚合写入 SQLite（token_usage 表）

### 3.2 成本估算
- [ ] 按模型定价计算每日/每周/每月成本
- [ ] 成本趋势图表
- [ ] 高成本会话预警

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
