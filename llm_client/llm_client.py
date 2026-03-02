# -*- coding: utf-8 -*-
"""
================================================================================
llm_client/llm_client.py
================================================================================
LLM 调用客户端

【来源说明】
本模块从 gpt_academic 项目抽取并简化：

1. predict_no_ui_long_connection()
   - 原文件: gpt_academic/request_llms/bridge_chatgpt.py
   - 功能: 调用 OpenAI API 获取响应

2. request_gpt_model_multi_threads_with_very_awesome_ui_and_high_efficiency()
   - 原文件: gpt_academic/crazy_functions/crazy_utils.py:187-350
   - 功能: 多线程批量调用 LLM

【主要修改】
- 移除 Gradio UI 依赖
- 使用 openai 库直接调用
- 简化多线程逻辑
- 添加进度回调

【使用方法】
    from llm_client import LLMClient

    client = LLMClient(
        api_base="http://127.0.0.1:30002/v1",
        api_key="sk-xxx",
        model="deepseek"
    )

    result = client.translate("Hello, world!")
================================================================================
"""

import time
import random
from typing import List, Optional, Callable, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from loguru import logger

try:
    from openai import OpenAI
except ImportError:
    raise ImportError("请安装 openai 库: pip install openai")


class LLMClient:
    """
    LLM 调用客户端

    【来源】整合自:
    - gpt_academic/request_llms/bridge_chatgpt.py
    - gpt_academic/request_llms/bridge_all.py

    支持所有 OpenAI 兼容的 API。
    """

    def __init__(
        self,
        api_base: str = "https://api.openai.com/v1",
        api_key: str = "sk-xxx",
        model: str = "gpt-3.5-turbo",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        timeout: int = 120,
    ):
        """
        初始化 LLM 客户端

        Args:
            api_base: API 基础 URL
            api_key: API 密钥
            model: 模型名称
            temperature: 温度参数
            max_tokens: 最大 token 数
            timeout: 请求超时时间（秒）
        """
        self.client = OpenAI(
            base_url=api_base,
            api_key=api_key,
            timeout=timeout,
        )
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

        logger.info(f"LLM 客户端初始化完成: model={model}, api_base={api_base}")

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        发送聊天请求

        【来源】gpt_academic/request_llms/bridge_chatgpt.py (predict_no_ui_long_connection)

        Args:
            messages: 消息列表，格式为 [{"role": "user", "content": "..."}]
            temperature: 可选的温度覆盖
            max_tokens: 可选的 max_tokens 覆盖

        Returns:
            模型响应文本
        """
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature or self.temperature,
            max_tokens=max_tokens or self.max_tokens,
        )
        return response.choices[0].message.content

    def translate(
        self,
        text: str,
        system_prompt: str = "You are a professional translator.",
        user_prompt_prefix: str = "Translate the following text to Chinese:\n\n",
    ) -> str:
        """
        翻译文本

        Args:
            text: 待翻译文本
            system_prompt: 系统提示词
            user_prompt_prefix: 用户提示词前缀

        Returns:
            翻译结果
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt_prefix + text},
        ]
        return self.chat(messages)

    def translate_with_retry(
        self,
        text: str,
        system_prompt: str,
        user_prompt: str,
        max_retries: int = 3,
        retry_delay: int = 5,
    ) -> str:
        """
        带重试的翻译

        【来源】gpt_academic/crazy_functions/crazy_utils.py:103-147
        (_req_gpt 内部逻辑)

        Args:
            text: 输入文本
            system_prompt: 系统提示词
            user_prompt: 用户提示词
            max_retries: 最大重试次数
            retry_delay: 重试延迟（秒）

        Returns:
            翻译结果
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt + "\n\n" + text},
        ]

        last_error = None
        for attempt in range(max_retries):
            try:
                return self.chat(messages)
            except Exception as e:
                last_error = e
                logger.warning(f"翻译失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    wait = retry_delay + random.randint(0, 5)
                    logger.info(f"等待 {wait} 秒后重试...")
                    time.sleep(wait)

        raise RuntimeError(f"翻译失败，已重试 {max_retries} 次: {last_error}")


def translate_batch(
    texts: List[str],
    system_prompts: List[str],
    user_prompts: List[str],
    llm_client: LLMClient,
    max_workers: int = 5,
    callback: Optional[Callable[[int, int, str], None]] = None,
) -> List[str]:
    """
    多线程批量翻译

    【来源】gpt_academic/crazy_functions/crazy_utils.py:187-350
    (request_gpt_model_multi_threads_with_very_awesome_ui_and_high_efficiency)

    Args:
        texts: 待翻译文本列表
        system_prompts: 系统提示词列表（与 texts 一一对应）
        user_prompts: 用户提示词列表（与 texts 一一对应）
        llm_client: LLM 客户端实例
        max_workers: 最大并发线程数
        callback: 进度回调函数 callback(index, total, status)

    Returns:
        翻译结果列表（与 texts 一一对应）
    """
    n_tasks = len(texts)
    results = [None] * n_tasks

    logger.info(f"开始批量翻译，共 {n_tasks} 个任务，并发数: {max_workers}")

    def _translate_task(index: int, text: str, sys_prompt: str, user_prompt: str) -> tuple:
        """单个翻译任务"""
        try:
            result = llm_client.translate_with_retry(
                text=text,
                system_prompt=sys_prompt,
                user_prompt=user_prompt,
            )
            return index, result, "success"
        except Exception as e:
            logger.error(f"任务 {index} 失败: {e}")
            return index, text, f"failed: {e}"  # 失败时返回原文

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        futures = {
            executor.submit(_translate_task, i, texts[i], system_prompts[i], user_prompts[i]): i
            for i in range(n_tasks)
        }

        # 收集结果
        completed = 0
        for future in as_completed(futures):
            index, result, status = future.result()
            results[index] = result
            completed += 1

            if callback:
                callback(index, n_tasks, status)

            logger.info(f"进度: {completed}/{n_tasks} (任务 {index}: {status})")

    return results


def generate_translation_prompts(
    text_fragments: List[str],
    mode: str = "translate_zh",
    more_requirement: str = "",
) -> tuple:
    """
    生成翻译提示词

    【来源】gpt_academic/crazy_functions/Latex_Function.py:14-41
    (switch_prompt 函数)

    Args:
        text_fragments: 文本片段列表
        mode: 模式 ('translate_zh' 或 'proofread_en')
        more_requirement: 额外要求

    Returns:
        (inputs_array, sys_prompt_array, inputs_show_user_array)
    """
    n_fragments = len(text_fragments)

    if mode == 'translate_zh':
        inputs_array = [
            r"Below is a section from an English academic paper, translate it into Chinese. " +
            more_requirement +
            r"Do not modify any latex command such as \section, \cite, \begin, \item and equations. " +
            r"Answer me only with the translated text:" +
            f"\n\n{frag}"
            for frag in text_fragments
        ]
        sys_prompt_array = ["You are a professional translator." for _ in range(n_fragments)]

    elif mode == 'proofread_en':
        inputs_array = [
            r"Below is a section from an academic paper, proofread this section." +
            r"Do not modify any latex command such as \section, \cite, \begin, \item and equations. " +
            more_requirement +
            r"Answer me only with the revised text:" +
            f"\n\n{frag}"
            for frag in text_fragments
        ]
        sys_prompt_array = ["You are a professional academic paper writer." for _ in range(n_fragments)]

    else:
        raise ValueError(f"未知模式: {mode}")

    inputs_show_user_array = [f"{mode} fragment_{i}" for i in range(n_fragments)]

    return inputs_array, sys_prompt_array, inputs_show_user_array
