# -*- coding: utf-8 -*-
"""
================================================================================
llm_client/__init__.py
================================================================================
LLM 调用模块

【来源说明】
本模块从 gpt_academic 项目抽取，主要来源：
- gpt_academic/crazy_functions/crazy_utils.py
- gpt_academic/request_llms/bridge_all.py
- gpt_academic/request_llms/bridge_chatgpt.py

【功能说明】
1. OpenAI 兼容 API 调用
2. 多线程批量翻译
3. 支持自定义 API 端点
================================================================================
"""

from .llm_client import LLMClient, translate_batch, generate_translation_prompts
from .prompts import get_translate_prompt, get_proofread_prompt

__all__ = ['LLMClient', 'translate_batch', 'generate_translation_prompts', 'get_translate_prompt', 'get_proofread_prompt']
