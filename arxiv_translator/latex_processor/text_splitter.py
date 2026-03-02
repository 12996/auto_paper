# -*- coding: utf-8 -*-
"""
================================================================================
latex_processor/text_splitter.py
================================================================================
文本拆分工具

【来源说明】
本模块从 gpt_academic 项目抽取：
- 原文件: gpt_academic/crazy_functions/pdf_fns/breakdown_txt.py
- 原方法: breakdown_text_to_satisfy_token_limit()

【功能】
将长文本按 token 限制拆分成多个片段
================================================================================
"""

from typing import List, Callable


def breakdown_text_to_satisfy_token_limit(
    text: str,
    max_token_limit: int,
    get_token_num: Callable[[str], int]
) -> List[str]:
    """
    按 token 限制拆分文本

    【来源】gpt_academic/crazy_functions/pdf_fns/breakdown_txt.py

    Args:
        text: 待拆分的文本
        max_token_limit: 每个 fragment 的最大 token 数
        get_token_num: 计算 token 数的函数

    Returns:
        拆分后的文本片段列表
    """
    if get_token_num(text) <= max_token_limit:
        return [text]

    # 按段落拆分
    paragraphs = text.split('\n\n')
    current_chunk = []
    current_tokens = 0
    result = []

    for para in paragraphs:
        para_tokens = get_token_num(para)

        # 如果单个段落就超限，需要进一步拆分
        if para_tokens > max_token_limit:
            # 先保存当前 chunk
            if current_chunk:
                result.append('\n\n'.join(current_chunk))
                current_chunk = []
                current_tokens = 0

            # 按句子拆分
            sentences = para.replace('。', '。\n').replace('！', '！\n').replace('？', '？\n').split('\n')
            for sent in sentences:
                sent = sent.strip()
                if not sent:
                    continue
                sent_tokens = get_token_num(sent)
                if current_tokens + sent_tokens > max_token_limit:
                    if current_chunk:
                        result.append('\n\n'.join(current_chunk))
                    current_chunk = [sent]
                    current_tokens = sent_tokens
                else:
                    current_chunk.append(sent)
                    current_tokens += sent_tokens
        else:
            if current_tokens + para_tokens > max_token_limit:
                result.append('\n\n'.join(current_chunk))
                current_chunk = [para]
                current_tokens = para_tokens
            else:
                current_chunk.append(para)
                current_tokens += para_tokens

    if current_chunk:
        result.append('\n\n'.join(current_chunk))

    return result
