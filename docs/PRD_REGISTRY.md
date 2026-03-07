# PRD 总集（台账）

| 版本 | 标题 | 需求内容（详细摘要） | PRD链接 |
|------|------|---------------------|---------|
| PRD-001 | ArXiv 论文翻译管理系统 V1.0 | 将现有 chat_arxiv.py（关键词搜索+AI摘要）和 main.py（LaTeX全文翻译+PDF编译）整合为带前端的自动化流水线。用户在前端输入关键词触发搜索，系统自动串行完成：论文爬取入库→LLM中文摘要生成→LaTeX源码下载→LLM多线程翻译→编译双语对照PDF（comparison.pdf）。首页提供统计面板、论文列表（含摘要预览和状态过滤）、右下角悬浮任务进度面板。详情页全屏展示 comparison.pdf。支持失败重试。本地单用户使用，串行任务处理，依赖本地LaTeX环境。 | [docs/prd/PRD-001.md](prd/PRD-001.md) |
| PRD-002 | ArXiv 论文翻译管理系统 V2.0（论文库管理） | 补全论文生命周期管理能力。新增：单篇删除（鼠标悬浮显示🗑按钮，确认后联动清理磁盘缓存）、批量清空失败论文（过滤栏右侧）、状态重置 API（POST /reset 重新入队全流程）、服务启动时自动修复僵尸 RUNNING 任务（reset_stuck_tasks）。阻止删除处理中论文，支持 force=true 强制取消。新增3个API端点：DELETE /api/papers/<id>、POST /api/papers/<id>/reset、DELETE /api/papers?status=failed。 | [docs/prd/PRD-002.md](prd/PRD-002.md) |
