# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

ArXiv 论文翻译器 - 从 [gpt_academic](https://github.com/binary-husky/gpt_academic) 抽取的独立命令行工具，将 ArXiv 英文论文翻译为中文 PDF。

## 常用命令

```bash
# 基本翻译
python main.py 2301.07041
python main.py https://arxiv.org/abs/2301.07041

# 常用选项
python main.py 2301.07041 --workers 10          # 并发数
python main.py 2301.07041 --no-compile          # 只生成 tex，不编译 PDF
python main.py 2301.07041 --no-cache            # 不使用缓存
python main.py 2301.07041 --proxy http://127.0.0.1:7890  # 代理
python main.py 2301.07041 --model deepseek-chat --api-base http://localhost:8080/v1  # 指定 API
```

## 配置

编辑 `config.py` 修改默认配置：
- `API_BASE`, `API_KEY`, `MODEL_NAME` - LLM API 配置
- `MAX_WORKERS` - 并发线程数（默认 2）
- `MAX_TOKEN_PER_FRAGMENT` - 每个片段最大 token 数（默认 1024）
- `MORE_REQUIREMENT` - 额外翻译要求（专业词汇等）

## 架构

```
main.py                          # 命令行入口，协调整个流程
config.py                        # 所有配置项

arxiv_downloader/
  downloader.py                  # ArxivDownloader 类：下载、解压论文

latex_processor/
  latex_toolbox.py               # 核心工具：掩码标记、链表转换、tex 合并、PDF 编译
  latex_actions.py               # LatexPaperSplit（切分）、LatexPaperFileGroup（分组）、翻译流程
  latex_pickle_io.py             # 序列化/反序列化

llm_client/
  llm_client.py                  # LLMClient 类、translate_batch（多线程翻译）
  prompts.py                     # 翻译/润色提示词
```

## 处理流程

1. **下载** (`ArxivDownloader`) → 下载 tar 源码并解压
2. **合并** (`merge_tex_files`) → 递归合并所有 tex 文件
3. **切分** (`LatexPaperSplit.split`) → 用掩码标记保留/翻译区域，转为链表
4. **分组** (`LatexPaperFileGroup`) → 按 token 限制分组
5. **翻译** (`translate_batch`) → 多线程调用 LLM
6. **合并结果** (`LatexPaperSplit.merge_result`) → 替换原文
7. **编译** (`编译Latex`) → xelatex 生成中文 PDF

## 关键概念

### 掩码机制 (`latex_toolbox.py`)

- `PRESERVE = 0` - 保留不翻译（公式、表格、章节标题等）
- `TRANSFORM = 1` - 需要翻译（正文、caption、abstract 内容）

核心函数：
- `set_forbidden_text()` - 标记为保留
- `reverse_forbidden_text()` - 反向标记为翻译（用于 caption、abstract 等）
- `set_forbidden_text_begin_end()` - 处理 begin-end 环境，行数 < 42 的整体保留

### 链表结构 (`LinkedListNode`)

每个节点包含 `string`、`preserve` 标志、`next` 指针。`post_process()` 会把 < 42 字符的短片段标记为保留。

## 输出文件

翻译后文件在 `arxiv_cache/<paper_id>/workfolder/`：
- `merge.tex` - 原始合并的 tex
- `merge_translate_zh.tex` - 翻译后的 tex
- `merge_translate_zh.pdf` - 最终 PDF
- `debug_log.html` - 切分调试（红色=保留，黑色=翻译）
- `merge_result.pkl` - 翻译结果缓存

## 依赖

- Python: openai, loguru, numpy, requests
- 系统: Latex (xelatex + ctex 支持中文)
