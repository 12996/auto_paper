# -*- coding: utf-8 -*-
"""
================================================================================
config.py
================================================================================
配置文件


【配置项说明】
- API 相关: API 地址、密钥、模型名称
- 代理设置: 如需翻墙访问
- 缓存目录: 存储下载的论文和翻译结果
- 编译设置: Latex 编译器选择

【环境变量支持】
可以通过环境变量覆盖配置：
- ARXIV_API_BASE: API 基础地址
- ARXIV_API_KEY: API 密钥
- ARXIV_MODEL: 模型名称
- ARXIV_PROXY: 代理地址
================================================================================
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root before reading environment variables.
_PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(dotenv_path=_PROJECT_ROOT / ".env")

# ============================================================================
# API 配置（支持环境变量覆盖）
# ============================================================================

def _normalize_base_url(url: str) -> str:
    base = (url or "").strip().rstrip("/")
    # 兼容误填为 /v1/models 的配置，避免 OpenAI SDK 拼接后 404。
    if base.endswith("/models"):
        base = base[:-len("/models")]
    return base


def resolve_llm_runtime_from_env() -> tuple[str, str, str, str]:
    """
    从 .env / 环境变量解析 LLM 运行时。

    返回: (provider, api_base, api_key, model)
    provider: local | deepseek | gemini | custom
    """
    provider = os.environ.get("ARXIV_LLM_PROVIDER", "custom").strip().lower()

    # 默认保留现有行为：读取 ARXIV_API_*，用于本地 OpenAI-compatible 网关。
    if provider in ("", "custom", "local"):
        api_base = _normalize_base_url(
            os.environ.get("ARXIV_API_BASE", "http://127.0.0.1:8317/v1/")
        )
        api_key = os.environ.get("ARXIV_API_KEY", "")
        model = os.environ.get("ARXIV_MODEL", "gpt-5")
        return "local" if provider == "local" else "custom", api_base, api_key, model

    if provider == "deepseek":
        api_base = _normalize_base_url(
            os.environ.get("ARXIV_DEEPSEEK_API_BASE", "https://api.deepseek.com/v1")
        )
        api_key = (
            os.environ.get("ARXIV_DEEPSEEK_API_KEY")
            or os.environ.get("DEEPSEEK_API_KEY")
            or ""
        )
        model = os.environ.get("ARXIV_DEEPSEEK_MODEL", "deepseek-chat")
        return provider, api_base, api_key, model

    if provider == "gemini":
        # Gemini OpenAI-compatible endpoint.
        api_base = _normalize_base_url(
            os.environ.get(
                "ARXIV_GEMINI_API_BASE",
                "https://generativelanguage.googleapis.com/v1beta/openai",
            )
        )
        api_key = (
            os.environ.get("ARXIV_GEMINI_API_KEY")
            or os.environ.get("GEMINI_API_KEY")
            or ""
        )
        model = os.environ.get("ARXIV_GEMINI_MODEL", "gemini-2.5-pro")
        return provider, api_base, api_key, model

    raise ValueError(
        f"Unsupported ARXIV_LLM_PROVIDER={provider!r}. Use local/deepseek/gemini/custom."
    )


LLM_PROVIDER, API_BASE, API_KEY, MODEL_NAME = resolve_llm_runtime_from_env()

# 模型参数
TEMPERATURE = 0.3  # 翻译任务建议使用较低温度
MAX_TOKENS = 4096  # 最大输出 token 数
TIMEOUT = 120  # 请求超时时间（秒）

# ============================================================================
# 代理配置
# ============================================================================

# 如果需要代理访问 arxiv，设置为 True
USE_PROXY = False

# 代理地址配置
PROXIES = {
    "http": "http://127.0.0.1:7890",
    "https": "http://127.0.0.1:7890",
}

# ============================================================================
# 缓存和输出配置
# ============================================================================

# 缓存目录（存储下载的论文和翻译结果）
CACHE_DIR = Path("./arxiv_cache")

# 翻译结果输出目录
OUTPUT_DIR = Path("./output")

# ============================================================================
# Latex 编译配置
# ============================================================================

# 默认编译器: "pdflatex" 或 "xelatex"
# 翻译为中文时自动使用 xelatex
LATEX_COMPILER = "pdflatex"

# 编译超时时间（秒）
COMPILE_TIMEOUT = 60

# 最大编译重试次数
MAX_COMPILE_RETRY = 32

# ============================================================================
# 翻译配置
# ============================================================================

# 每个 fragment 的最大 token 数
MAX_TOKEN_PER_FRAGMENT = 1024

# 多线程并发数
MAX_WORKERS = 1

# 翻译重试次数
MAX_RETRIES = 5

# ============================================================================
# 额外翻译要求
# ============================================================================

# 专业词汇提示（会添加到提示词中）
MORE_REQUIREMENT = ""

# 示例：指定专业词汇翻译
# MORE_REQUIREMENT = 'If the term "agent" is used in this section, it should be translated to "智能体". '
