# -*- coding: utf-8 -*-
"""
worker/summarize_job.py — 摘要任务
调用 PaperSummarizer 对单篇论文生成中文摘要，写回数据库。
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

# 确保项目根目录在 sys.path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from loguru import logger
from arxiv_finder.config import AppConfig
from arxiv_finder.llm_client import LLMClient
from arxiv_finder.paper import Paper
from arxiv_finder.summarizer import PaperSummarizer
from db import get_db_manager, PaperStatus


def run_summarize(arxiv_id: str) -> str:
    """
    对单篇论文执行摘要生成任务。

    Args:
        arxiv_id: 论文的 ArXiv ID

    Returns:
        生成的中文摘要文本

    Raises:
        Exception: 摘要生成失败时抛出，由 Worker 捕获并写回 summary_failed 状态
    """
    db = get_db_manager()
    paper_record = db.get_paper(arxiv_id)
    if paper_record is None:
        raise ValueError(f"论文不存在于数据库: {arxiv_id}")

    if not paper_record.original_pdf_path or not os.path.exists(paper_record.original_pdf_path):
        raise FileNotFoundError(
            f"原始 PDF 不存在: {paper_record.original_pdf_path!r}. "
            f"论文: {arxiv_id}"
        )

    logger.info(f"[摘要] 开始处理: {arxiv_id} - {paper_record.title[:60]}")

    # 初始化 LLM 和摘要器
    config = AppConfig()
    llm = LLMClient(config)
    summarizer = PaperSummarizer(
        llm_client=llm,
        key_word=paper_record.search_keyword or '',
        language='zh',
        max_token_num=81920,
    )

    # 解析 PDF
    paper = Paper(
        path=paper_record.original_pdf_path,
        title=paper_record.title,
        url=paper_record.arxiv_url or '',
        abs=paper_record.abstract_en or '',
        authers=paper_record.authors or [],
    )

    # 生成摘要
    result = summarizer.summarize(paper)

    # 组合摘要文本
    parts = []
    if result.summary_text:
        parts.append(result.summary_text)
    if result.method_text:
        parts.append(result.method_text)
    if result.conclusion_text:
        parts.append(result.conclusion_text)
    summary_zh = "\n\n".join(parts) if parts else "（摘要生成为空）"

    logger.info(f"[摘要] 完成: {arxiv_id}, 摘要长度: {len(summary_zh)} 字符")
    return summary_zh
