# -*- coding: utf-8 -*-
"""
api/search.py — 搜索相关路由

POST /api/search     触发关键词搜索，论文入库，创建任务队列
GET  /api/searches   最近搜索历史（前端快捷填充）
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from flask import Blueprint, jsonify, request
from loguru import logger

from db import get_db_manager

search_bp = Blueprint("search", __name__, url_prefix="/api")


@search_bp.post("/search")
def trigger_search():
    """
    触发一次 ArXiv 搜索，将结果入库并创建串行任务队列。

    Request Body (JSON):
        query    : str  — ArXiv 搜索字符串（必填）
        keyword  : str  — 研究领域关键词（可选，用于摘要质量）
        days     : int  — 只搜索最近 N 天（默认 30）
        max      : int  — 最多处理论文数（默认 10）
        page_num : int  — 搜索页数（默认 1）

    Returns:
        202 Accepted + {queued: N, skipped: N, search_id: int}
    """
    data = request.get_json(silent=True) or {}
    query    = data.get("query", "").strip()
    keyword  = data.get("keyword", "").strip()
    days     = int(data.get("days", 30))
    max_results = int(data.get("max", 10))
    page_num = int(data.get("page_num", 1))

    if not query:
        return jsonify({"error": "query 不能为空"}), 400

    logger.info(f"[Search] 触发搜索: query={query!r} keyword={keyword!r} days={days} max={max_results}")

    db = get_db_manager()

    # 记录搜索历史
    history = db.add_search_history(query, keyword, days, max_results)

    # 在后台线程中执行爬取 + 入库（避免接口超时）
    import threading
    def _crawl_and_enqueue():
        try:
            from core.config import AppConfig
            from core.llm_client import LLMClient
            from core.crawler import ArxivWebCrawler

            crawler = ArxivWebCrawler(root_path=str(ROOT))
            papers = crawler.search(
                query=query,
                page_num=page_num,
                days=days,
                max_results=max_results,
            )

            queued = 0
            skipped = 0
            for paper in papers:
                # 从 URL 提取 arxiv_id
                arxiv_id = _extract_arxiv_id(paper.url)
                if not arxiv_id:
                    logger.warning(f"[Search] 无法提取 arxiv_id from url={paper.url!r}")
                    skipped += 1
                    continue

                # 获取 published_at（ArxivWebCrawler 返回的 Paper 没有直接带日期，暂置 None）
                existing = db.get_paper(arxiv_id)
                if existing:
                    skipped += 1
                    logger.debug(f"[Search] 跳过已存在论文: {arxiv_id}")
                    continue

                db.upsert_paper(
                    arxiv_id=arxiv_id,
                    title=paper.title,
                    arxiv_url=paper.url,
                    abstract_en=paper.abs,
                    authors=paper.authers,
                    published_at=None,
                    search_query=query,
                    search_keyword=keyword,
                    original_pdf_path=paper.path,
                )
                db.enqueue_tasks(arxiv_id)
                queued += 1
                logger.info(f"[Search] 入库 + 入队: {arxiv_id} — {paper.title[:50]}")

            # 更新搜索历史的结果数
            with db._session() as s:
                from db.models import SearchHistory
                h = s.get(SearchHistory, history.id)
                if h:
                    h.results_count = queued + skipped

            # 确保 Worker 在运行
            from worker import get_scheduler
            get_scheduler().start()

            logger.info(f"[Search] 完成: queued={queued} skipped={skipped}")
        except Exception as e:
            import traceback
            logger.error(f"[Search] 爬取失败: {e}\n{traceback.format_exc()}")

    thread = threading.Thread(target=_crawl_and_enqueue, daemon=True, name="Crawler")
    thread.start()

    return jsonify({
        "message":   "搜索已触发，正在后台爬取论文并入队",
        "query":     query,
        "keyword":   keyword,
        "days":      days,
        "max":       max_results,
        "search_id": history.id,
    }), 202


@search_bp.get("/searches")
def get_searches():
    """最近搜索历史（最多 10 条）"""
    db = get_db_manager()
    limit = int(request.args.get("limit", 10))
    records = db.get_recent_searches(limit=limit)
    return jsonify([
        {
            "id":            r.id,
            "query":         r.query,
            "keyword":       r.keyword or "",
            "days":          r.days,
            "max_results":   r.max_results,
            "results_count": r.results_count,
            "created_at":    r.created_at.isoformat(),
        }
        for r in records
    ])


def _extract_arxiv_id(url: str) -> str:
    """
    从 ArXiv URL 提取论文 ID。
    例：https://arxiv.org/abs/2301.07041 → 2301.07041
    """
    import re
    if not url:
        return ""
    # 匹配 /abs/ 或 /pdf/ 后面的 ID
    m = re.search(r'arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]+)', url)
    if m:
        return m.group(1)
    # 直接就是 ID
    m = re.match(r'^([0-9]{4}\.[0-9]+)$', url.strip())
    if m:
        return m.group(1)
    return ""
