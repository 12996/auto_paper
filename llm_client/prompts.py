# -*- coding: utf-8 -*-
"""
================================================================================
llm_client/prompts.py
================================================================================
翻译提示词模板

【来源说明】
本模块从 gpt_academic 项目抽取：
- 原文件: gpt_academic/crazy_functions/Latex_Function.py:14-41
- 原方法: switch_prompt()

【功能】
生成翻译和润色的提示词
================================================================================
"""

from typing import List, Tuple
from functools import partial


def get_translate_prompt(
    text_fragments: List[str],
    more_requirement: str = "",
) -> Tuple[List[str], List[str]]:
    """
    生成中译提示词

    【来源】gpt_academic/crazy_functions/Latex_Function.py:32-38

    Args:
        text_fragments: 文本片段列表
        more_requirement: 额外要求（如专业词汇说明）

    Returns:
        (inputs_array, sys_prompt_array)
    """
    n_fragments = len(text_fragments)

    inputs_array = [
        r"Below is a section from an English academic paper, translate it into Chinese. " +
        more_requirement +
        r"Do not modify any latex command such as \section, \cite, \begin, \item and equations. " +
        r"Answer me only with the translated text:" +
        f"\n\n{frag}"
        for frag in text_fragments
    ]

    sys_prompt_array = ["You are a professional translator." for _ in range(n_fragments)]

    return inputs_array, sys_prompt_array


def get_proofread_prompt(
    text_fragments: List[str],
    more_requirement: str = "",
) -> Tuple[List[str], List[str]]:
    """
    生成润色提示词

    【来源】gpt_academic/crazy_functions/Latex_Function.py:26-31

    Args:
        text_fragments: 文本片段列表
        more_requirement: 额外要求

    Returns:
        (inputs_array, sys_prompt_array)
    """
    n_fragments = len(text_fragments)

    inputs_array = [
        r"Below is a section from an academic paper, proofread this section." +
        r"Do not modify any latex command such as \section, \cite, \begin, \item and equations. " +
        more_requirement +
        r"Answer me only with the revised text:" +
        f"\n\n{frag}"
        for frag in text_fragments
    ]

    sys_prompt_array = ["You are a professional academic paper writer." for _ in range(n_fragments)]

    return inputs_array, sys_prompt_array


def switch_prompt(
    pfg,  # LatexPaperFileGroup 实例
    mode: str,
    more_requirement: str = "",
) -> Tuple[List[str], List[str]]:
    """
    根据模式生成提示词

    【来源】gpt_academic/crazy_functions/Latex_Function.py:14-41
    (完整函数)

    Args:
        pfg: LatexPaperFileGroup 实例
        mode: 模式 ('translate_zh' 或 'proofread_en')
        more_requirement: 额外要求

    Returns:
        (inputs_array, sys_prompt_array)
    """
    n_split = len(pfg.sp_file_contents)

    # 通用的 LaTeX 格式要求
    latex_rules = (
        r"CRITICAL LaTeX RULES: " +
        r"(1) Do NOT modify any latex command such as \section, \cite, \begin, \item, equations. " +
        r"(2) Do NOT add extra braces inside commands - keep \cmd{text} NOT \cmd{{text}}. " +
        r"(3) Do NOT change the structure of \mathtt{}, \textbf{}, \textit{} etc. " +
        r"(4) Keep all mathematical expressions ($...$, $$...$$, \[...\]) exactly as they are. "
    )

    if mode == 'proofread_en':
        inputs_array = [
            r"Below is a section from an academic paper, proofread this section." +
            latex_rules +
            more_requirement +
            r"Answer me only with the revised text:" +
            f"\n\n{frag}"
            for frag in pfg.sp_file_contents
        ]
        sys_prompt_array = ["You are a professional academic paper writer." for _ in range(n_split)]

    elif mode == 'translate_zh':
        inputs_array = [
            r"Below is a section from an English academic paper, translate it into Chinese. " +
            latex_rules +
            more_requirement +
            r"Answer me only with the translated text:" +
            f"\n\n{frag}"
            for frag in pfg.sp_file_contents
        ]
        sys_prompt_array = ["You are a professional translator." for _ in range(n_split)]

    else:
        raise ValueError(f"未知指令: {mode}")

    return inputs_array, sys_prompt_array


# 预定义的专业词汇提示词
VOCABULARY_HINTS = {
    "agent": 'If the term "agent" is used in this section, it should be translated to "智能体". ',
    "model": 'If the term "model" is used in this section, it should be translated to "模型". ',
    "network": 'If the term "network" is used in this section, it should be translated to "网络". ',
    "learning": 'If the term "learning" is used in this section, it should be translated to "学习". ',
    "attention": 'If the term "attention" is used in this section, it should be translated to "注意力". ',
    "transformer": 'If the term "transformer" is used in this section, keep it as "Transformer". ',
}
