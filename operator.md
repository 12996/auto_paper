# Operator Manual

本文档用于日常运维与开发调试，基于当前重构后的目录结构。

## 1. 项目定位

系统流程：

1. 检索论文（ArXiv）
2. 入库与排队
3. 生成中文摘要
4. LaTeX 全文翻译并编译 PDF
5. 前端查看状态和双语对照 `comparison.pdf`

## 2. 目录职责

- `main.py`
  - 单篇翻译 CLI 入口
  - 使用 `arxiv_translator.*`
- `chat_arxiv.py`
  - 检索 + 摘要 CLI 入口
  - 使用 `arxiv_finder.*`
- `server.py`
  - Web 后端入口（Flask + API + Worker）
- `arxiv_translator/`
  - 翻译能力模块：`arxiv_downloader/`、`latex_processor/`
- `arxiv_finder/`
  - 检索/摘要能力模块：`crawler.py`、`paper.py`、`summarizer.py`
- `llm_client/`
  - 共享 LLM 客户端实现
  - `arxiv_finder/llm_client.py` 为适配层，复用此实现

## 3. 环境准备

```bash
pip install -r requirements.txt
```

需要本机安装 LaTeX（用于 PDF 编译）：

- Windows: MiKTeX 或 TeX Live
- Linux: `sudo apt-get install texlive-full texlive-lang-chinese`
- macOS: `brew install --cask mactex`

## 4. 配置说明

### 4.1 翻译链路（`main.py` / worker translate）

配置文件：`config.py`

关键项：

- `API_BASE`
- `API_KEY`
- `MODEL_NAME`
- `CACHE_DIR`
- `OUTPUT_DIR`
- `MAX_WORKERS`

### 4.2 检索/摘要链路（`chat_arxiv.py` / worker summarize）

配置来源：`arxiv_finder/config.py` 读取运行目录下 `apikey.ini`。

## 5. 启动方式

### 5.1 全流程 Web（推荐）

```bash
python server.py
```

访问：`http://localhost:5000`

### 5.2 单篇翻译 CLI

```bash
python main.py 2301.07041
python main.py https://arxiv.org/abs/2301.07041 --no-cache --workers 1
```

### 5.3 检索 + 摘要 CLI

```bash
python chat_arxiv.py --query "ti:transformer" --key_word "NLP" --days 30 --max_results 5
```

## 6. API 快速索引

- `GET /api/stats`
- `GET /api/papers`
- `GET /api/papers/<arxiv_id>`
- `POST /api/papers/<arxiv_id>/retry`
- `POST /api/search`
- `GET /api/searches`
- `GET /api/queue/status`
- `GET /api/queue/worker`
- `GET /api/files/by-arxiv/<id>/<type>`

## 7. 状态机与队列

论文状态：

- `discovered`
- `summarizing`
- `summarized`
- `translating`
- `translated`
- `summary_failed`
- `translation_failed`

队列策略：

- 串行执行（一次一个任务）
- 失败任务可重试
- 单篇失败不阻塞后续论文

## 8. 输出位置

- 翻译输出：`output/<arxiv_id>/`
- 双语对照：`output/<arxiv_id>/comparison.pdf`
- 原始下载：`pdf_files/`
- 数据库：`arxiv_library.db`
- 日志：`arxiv_translator.log`

## 9. 常见问题

### 9.1 `main.py` 导入报错

确认已使用重构后的导入路径（`arxiv_translator.*`），并在项目根目录执行命令。

### 9.2 LLM 调用失败

- 检查 `config.py` 或 `apikey.ini`
- 检查本地模型服务/API 地址
- 检查代理配置

### 9.3 PDF 编译失败

- 检查 LaTeX 是否安装并在 PATH
- 根据编译日志补装缺失宏包

### 9.4 队列不动

- 查看 `GET /api/queue/worker` 是否 `running=true`
- 检查 `task_queue` 状态和错误字段

## 10. 发布前检查

```bash
python -m py_compile main.py chat_arxiv.py server.py
python -m py_compile api\search.py worker\summarize_job.py worker\translate_job.py
```

如有改动，确认 README/本手册与代码一致后再提交。
