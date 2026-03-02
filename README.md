# ArXiv 论文翻译与管理系统

本项目是一个本地优先的 ArXiv 论文处理系统，覆盖以下完整流程：

1. 关键词检索最新论文
2. 入库并排队
3. LLM 生成中文摘要
4. LaTeX 全文翻译并编译 PDF
5. 前端查看状态、重试失败任务、阅读双语对照 `comparison.pdf`

## 重构说明（当前目录）
你这次重构后，核心代码已按职责拆分：

- `F:\claude\arxiv_translator\arxiv_translator`
  - `main.py` 所依赖的翻译能力包（LaTeX 处理、ArXiv 源码下载等）都在这里
- `F:\claude\arxiv_translator\arxiv_finder`
  - `chat_arxiv.py` 用到的检索、论文解析、摘要相关包都在这里

## 项目结构
```text
F:\claude\arxiv_translator
├─ server.py                 # Web 后端入口（推荐）
├─ main.py                   # 翻译 CLI 入口（单篇）
├─ chat_arxiv.py             # 检索+摘要 CLI 入口
├─ config.py                 # 翻译链路配置（API/缓存/输出等）
├─ arxiv_translator/         # 翻译任务依赖包（重构后）
│  ├─ arxiv_downloader/
│  └─ latex_processor/
├─ arxiv_finder/             # 检索与摘要依赖包（重构后）
│  ├─ crawler.py
│  ├─ paper.py
│  ├─ summarizer.py
│  ├─ translator.py
│  └─ llm_client.py
├─ api/                      # Flask API 路由
├─ worker/                   # 串行任务调度与执行
├─ db/                       # SQLite 模型与访问层
├─ frontend/                 # 前端静态页面（index.html + app.js + style.css）
├─ output/                   # 翻译输出目录
├─ pdf_files/                # 检索下载的原始 PDF
└─ arxiv_library.db          # 本地数据库
```

## 快速开始
### 1. 安装依赖
```bash
pip install -r requirements.txt
```

### 2. 安装 LaTeX（用于 PDF 编译）
- Windows: MiKTeX 或 TeX Live
- Linux: `sudo apt-get install texlive-full texlive-lang-chinese`
- macOS: `brew install --cask mactex`

### 3. 配置 API
翻译链路配置文件：`config.py`

关键项：
- `API_BASE`
- `API_KEY`
- `MODEL_NAME`
- `CACHE_DIR`
- `OUTPUT_DIR`

检索/摘要链路（`chat_arxiv.py` 侧）使用 `apikey.ini`（按 `arxiv_finder/config.py` 的读取逻辑放在项目运行目录）。

## 运行方式
### 方式 A：启动完整 Web 系统（推荐）
```bash
python server.py
```
然后访问：`http://localhost:5000`

系统会自动：
- 初始化 SQLite
- 启动后台 Worker（串行消费任务队列）
- 托管 `frontend/` 静态页面

### 方式 B：单篇翻译（CLI）
```bash
python main.py 2301.07041
python main.py https://arxiv.org/abs/2301.07041 --no-cache --workers 1
```

常用参数：
- `--api-base`
- `--api-key`
- `--model`
- `--cache-dir`
- `--output-dir`
- `--output-name`
- `--no-compile`
- `--no-cache`
- `--workers`
- `--proxy`
- `--requirement`

### 方式 C：检索并生成摘要（CLI）
```bash
python chat_arxiv.py --query "ti:transformer" --key_word "NLP" --days 30 --max_results 5
```

## 后端任务链路
### 状态流转
`discovered -> summarizing -> summarized -> translating -> translated`

失败分支：
- `summary_failed`
- `translation_failed`

### 队列机制
- 新论文入库后自动创建两个任务：`summarize`、`translate`
- Worker 串行执行任务（一次只处理一个）
- 某篇失败不阻塞其他论文
- 前端可对失败论文触发重试

## 关键 API（供前端调用）
- `GET /api/stats`
- `GET /api/papers`
- `GET /api/papers/<arxiv_id>`
- `POST /api/papers/<arxiv_id>/retry`
- `POST /api/search`
- `GET /api/searches`
- `GET /api/queue/status`
- `GET /api/queue/worker`
- `GET /api/files/by-arxiv/<id>/<type>`

## 主要输出文件
- 中文翻译 PDF：`output/<arxiv_id>/*.pdf`
- 双语对照 PDF：`output/<arxiv_id>/comparison.pdf`
- 原始下载 PDF：`pdf_files/...`
- 数据库：`arxiv_library.db`
- 日志：`arxiv_translator.log`

## 常见问题
### 1) PDF 编译失败
- 检查 LaTeX 是否正确安装并在 PATH 中
- 查看编译日志定位缺失宏包/语法错误

### 2) LLM 调用失败
- 检查 `config.py`（或 `apikey.ini`）中的 API 配置
- 检查本地模型服务或代理是否可达

### 3) 任务不动
- 检查 `GET /api/queue/worker` 是否 `running=true`
- 检查数据库 `task_queue` 中任务状态与错误信息
