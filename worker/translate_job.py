# -*- coding: utf-8 -*-
"""
worker/translate_job.py — 翻译任务
调用 main.translate_arxiv_paper() 对单篇论文进行全文翻译并编译 PDF。
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from loguru import logger
from db import get_db_manager, PaperStatus
import config as cfg


def run_translate(arxiv_id: str) -> dict:
    """
    对单篇论文执行全文翻译 + PDF 编译任务。

    Returns:
        {
            "comparison_pdf": str,   # comparison.pdf 绝对路径
            "translated_pdf": str,   # 中文 PDF 绝对路径（可能不存在）
            "output_dir": str,
        }

    Raises:
        Exception: 翻译或编译失败时抛出，由 Worker 捕获并写回 translation_failed 状态
    """
    from main import translate_arxiv_paper

    db = get_db_manager()
    paper_record = db.get_paper(arxiv_id)
    if paper_record is None:
        raise ValueError(f"论文不存在于数据库: {arxiv_id}")

    logger.info(f"[翻译] 开始处理: {arxiv_id} - {paper_record.title[:60]}")

    # 调用核心翻译流程
    output_dir = translate_arxiv_paper(
        arxiv_input=arxiv_id,
        api_base=cfg.API_BASE,
        api_key=cfg.API_KEY,
        model=cfg.MODEL_NAME,
        cache_dir=str(cfg.CACHE_DIR),
        output_dir=str(cfg.OUTPUT_DIR / arxiv_id),
        use_cache=True,
        compile_pdf=True,
        max_workers=cfg.MAX_WORKERS,
        proxies=cfg.PROXIES if cfg.USE_PROXY else None,
        more_requirement=cfg.MORE_REQUIREMENT,
    )

    output_dir = Path(output_dir)

    # 查找生成的 PDF 文件
    result = {"output_dir": str(output_dir)}

    comparison_pdf = output_dir / "comparison.pdf"
    result["comparison_pdf"] = str(comparison_pdf) if comparison_pdf.exists() else ""

    # 找中文 PDF（非 comparison.pdf 的第一个 PDF）
    translated_pdf = ""
    for pdf_file in output_dir.glob("*.pdf"):
        if pdf_file.name != "comparison.pdf":
            translated_pdf = str(pdf_file)
            break
    result["translated_pdf"] = translated_pdf

    logger.info(f"[翻译] 完成: {arxiv_id}, comparison_pdf={result['comparison_pdf']!r}")
    return result
