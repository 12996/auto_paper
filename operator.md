# ArXiv 论文翻译器 - 使用指南

> 将 ArXiv 英文论文翻译为中文 PDF 的命令行工具

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 安装 Latex

| 系统 | 安装方式 |
|------|----------|
| Windows | 安装 [MiKTeX](https://miktex.org/) 或 [TeX Live](https://tug.org/texlive/) |
| Linux | `sudo apt-get install texlive-full texlive-lang-chinese` |
| macOS | `brew install --cask mactex` |

### 3. 配置 API

编辑 `config.py`：

```python
# 本地 API
API_BASE = "http://127.0.0.1:30002/v1"
API_KEY = "sk-local"
MODEL_NAME = "deepseek"

# 或使用 OpenAI
API_BASE = "https://api.openai.com/v1"
API_KEY = "sk-your-api-key"
MODEL_NAME = "gpt-4"
```

---

## 命令使用

### 基本命令

```bash
# 使用 ArXiv ID
python main.py 2301.07041

# 使用完整 URL
python main.py https://arxiv.org/abs/2301.07041
```

### 参数说明

| 参数 | 说明 | 示例 |
|------|------|------|
| `--api-base` | 指定 API 地址 | `--api-base http://localhost:8080/v1` |
| `--model` | 指定模型 | `--model gpt-4` |
| `--no-compile` | 不编译 PDF，只生成 tex | `--no-compile` |
| `--no-cache` | 不使用缓存 | `--no-cache` |
| `--workers` | 并发线程数 | `--workers 10` |
| `--proxy` | 使用代理 | `--proxy http://127.0.0.1:7890` |
| `--requirement` | 添加翻译要求 | `--requirement 'If "agent" appears, translate to "智能体"'` |
| `--output-dir` | 指定输出目录 | `--output-dir D:/translations` |
| `--output-name` | 自定义输出文件名 | `--output-name "我的论文"` |

### 自定义输出

```bash
# 指定输出目录和文件名
python main.py 2301.07041 --output-dir "D:/my_translations" --output-name "FHE论文"

# 生成文件：
# - D:/my_translations/FHE论文.tex
# - D:/my_translations/FHE论文.pdf
# - D:/my_translations/comparison.pdf（双语对照）
```

---

## 处理流程

```
下载论文 → 解析 Latex → 智能切分 → LLM 翻译 → 合并结果 → 编译 PDF → 双语对照
```

---

## 输出文件

| 文件 | 说明 |
|------|------|
| `{文件名}.tex` | 翻译后的 Latex 源文件 |
| `{文件名}.pdf` | 翻译后的中文 PDF |
| `comparison.pdf` | **双语对照 PDF**（原文在左，译文在右） |

---

## 常见问题

| 问题 | 解决方案 |
|------|----------|
| PDF 编译失败 | 检查 Latex 安装；查看 `*.log` 文件 |
| 翻译质量不佳 | 在 `config.py` 添加专业词汇；使用 `--requirement` |
| 下载失败 | 检查网络；使用 `--proxy` 设置代理 |
| 部分内容未翻译 | 检查 `debug_log.html`，红色=保留，黑色=已翻译 |
| 图片丢失 | 程序会自动复制 `images/fig/assets` 等目录 |

---

## 更新日志

### 2026-02-26

**修复的问题：**

1. **语法错误修复**
   - `latex_toolbox.py:399` - 修复字符串引号缺失
   - `llm_client/__init__.py` - 添加缺失的 `generate_translation_prompts` 导出
   - `latex_toolbox.py` - 添加缺失的 `import glob`

2. **URL 下载问题**
   - 修复 ArXiv 下载 URL 重复拼接问题（`arxiv.org/src/` 路径处理）

3. **双语 PDF 生成**
   - 修复 `mode != 'translate_zh'` 条件导致中文翻译模式下不生成双语 PDF
   - 修复 PyPDF2 3.0.0+ 版本兼容性问题（`PdfFileReader` → `PdfReader`）
   - 修复 Windows 下 `multiprocessing` 子进程兼容性问题

4. **翻译覆盖问题**
   - 降低短片段过滤阈值（42 → 10 字符），避免有效内容被跳过

5. **图片资源复制**
   - 自动扫描 tex 文件中的 `\includegraphics` 路径
   - 支持复制多种图片目录：`images`, `fig`, `figures`, `assets`, `img`, `pics`, `sup_mat`

6. **文件名和输出路径**
   - 支持从论文标题自动生成文件名
   - 新增 `--output-name` 参数自定义文件名
   - 新增 `--output-dir` 参数指定输出目录

7. **其他修复**
   - 修复 `shutil` 模块导入位置问题
   - 修复变量命名冲突（`output_filename` → `final_output_filename`）
