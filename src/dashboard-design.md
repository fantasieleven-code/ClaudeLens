# Engineering Efficiency Dashboard - 设计方案

## 技术选型
- **前端**: 单HTML文件，Chart.js图表，Tailwind CSS样式
- **后端**: Python FastAPI 轻量server，读取 efficiency.db
- **启动**: `python3 src/dashboard.py` → localhost:8001

## 页面布局（单页Dashboard）

### 顶部 Header
- 标题: "Engineering Efficiency"
- 日期选择器（默认今天）
- 刷新按钮

### 第一行: 4个KPI卡片
1. 今日会话数
2. 今日工具调用总数
3. 今日提交数
4. 产品贡献度（百分比）

### 第二行: 2列图表
- 左: 工具使用分布（饼图/环形图）
- 右: 每日活跃度趋势（折线图，最近7天）

### 第三行: 2列图表
- 左: 项目时间分布（横向柱状图）
- 右: 贡献度分类（堆叠柱状图）

### 第四行: 日报内容
- 当日日报 Markdown 渲染展示

## 配色方案
- 深色主题（开发者友好）
- 主色: #3B82F6 (蓝)
- 辅色: #10B981 (绿), #F59E0B (黄), #EF4444 (红)
- 背景: #0F172A
- 卡片背景: #1E293B

## API 端点
- GET /api/summary?date=YYYY-MM-DD — KPI汇总
- GET /api/tools?date=YYYY-MM-DD — 工具使用分布
- GET /api/trend?days=7 — 活跃度趋势
- GET /api/projects?date=YYYY-MM-DD — 项目分布
- GET /api/report?date=YYYY-MM-DD — 日报内容
