# ArXiv Translator

本项目是一个本地优先的 ArXiv 论文处理系统，支持：搜索 -> 入库 -> 摘要 -> 全文翻译 -> 双语 PDF 阅读。

## 当前重构状态（已落地）

目录职责已经统一：

- `arxiv_translator/`
  - 翻译链路依赖（`arxiv_downloader`、`latex_processor`）
  - `main.py` 现在已通过 `arxiv_translator.*` 导入
- `arxiv_finder/`
  - 检索、论文解析、摘要链路（`crawler/paper/summarizer/...`）
  - `chat_arxiv.py`、`api/search.py` 已统一使用 `arxiv_finder.*`
- `llm_client/`
  - 全局共享 LLM 客户端实现
  - `arxiv_finder/llm_client.py` 已改为适配层，复用这里的实现，不再双份维护

## 项目结构

```text
F:\claude\arxiv_translator
├─ server.py
├─ main.py
├─ chat_arxiv.py
├─ config.py
├─ arxiv_translator/
│  ├─ arxiv_downloader/
│  └─ latex_processor/
├─ arxiv_finder/
│  ├─ config.py
│  ├─ crawler.py
│  ├─ paper.py
│  ├─ summarizer.py
│  ├─ translator.py
│  └─ llm_client.py   # adapter -> root llm_client/
├─ llm_client/
├─ api/
├─ worker/
├─ db/
├─ frontend/
└─ docs/
```

## 安装

```bash
pip install -r requirements.txt
```

需要本机 LaTeX（用于编译 PDF）：

- Windows: MiKTeX 或 TeX Live
- Linux: `sudo apt-get install texlive-full texlive-lang-chinese`
- macOS: `brew install --cask mactex`

## 配置

### 翻译链路

编辑 `config.py`：

- `API_BASE`
- `API_KEY`
- `MODEL_NAME`
- `CACHE_DIR`
- `OUTPUT_DIR`

### 检索/摘要链路

`arxiv_finder/config.py` 从运行目录读取 `apikey.ini`。

## 运行方式

### 1) Web 全流程（推荐）

```bash
python server.py
```

访问：`http://localhost:5000`

### 2) 单篇翻译 CLI

```bash
python main.py 2301.07041
python main.py https://arxiv.org/abs/2301.07041 --no-cache --workers 1
```

### 3) 检索 + 摘要 CLI

```bash
python chat_arxiv.py --query "ti:transformer" --key_word "NLP" --days 30 --max_results 5
```

## 后端状态流转

- 正常：`discovered -> summarizing -> summarized -> translating -> translated`
- 失败：`summary_failed` / `translation_failed`

Worker 串行消费任务队列，单篇失败不会阻塞其他论文。

## 关键 API

- `GET /api/stats`
- `GET /api/papers`
- `GET /api/papers/<arxiv_id>`
- `POST /api/papers/<arxiv_id>/retry`
- `POST /api/search`
- `GET /api/searches`
- `GET /api/queue/status`
- `GET /api/queue/worker`
- `GET /api/files/by-arxiv/<id>/<type>`

## 输出与数据

- 翻译输出：`output/<arxiv_id>/`
- 双语对照：`output/<arxiv_id>/comparison.pdf`
- 下载原文：`pdf_files/`
- 数据库：`arxiv_library.db`
- 日志：`arxiv_translator.log`
