# -*- coding: utf-8 -*-
"""
api/papers.py — 论文相关路由

GET  /api/stats           首页统计卡片
GET  /api/papers          论文列表（分页 + 状态过滤）
GET  /api/papers/<id>     论文详情
POST /api/papers/<id>/retry  失败重试
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from db import get_db_manager, PaperStatus

papers_bp = Blueprint("papers", __name__, url_prefix="/api")


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _serialize_paper(p) -> dict:
    """将 PaperRecord ORM 对象序列化为 JSON-safe dict"""
    return {
        "arxiv_id":           p.arxiv_id,
        "title":              p.title,
        "authors":            p.authors or [],
        "abstract_en":        p.abstract_en or "",
        "arxiv_url":          p.arxiv_url or "",
        "published_at":       p.published_at.isoformat() if p.published_at else None,
        "status":             p.status.value if p.status else "discovered",
        "summary_zh":         p.summary_zh or "",
        "summary_error":      p.summary_error or "",
        "translation_error":  p.translation_error or "",
        "original_pdf_path":  p.original_pdf_path or "",
        "translated_pdf_path": p.translated_pdf_path or "",
        "comparison_pdf_path": p.comparison_pdf_path or "",
        "discovered_at":      p.discovered_at.isoformat() if p.discovered_at else None,
        "summarized_at":      p.summarized_at.isoformat() if p.summarized_at else None,
        "translated_at":      p.translated_at.isoformat() if p.translated_at else None,
    }


# ---------------------------------------------------------------------------
# GET /api/stats
# ---------------------------------------------------------------------------

@papers_bp.get("/stats")
def get_stats():
    """首页统计卡片：已发现/已总结/已翻译/处理中/失败"""
    db = get_db_manager()
    stats = db.get_stats()
    return jsonify(stats)


# ---------------------------------------------------------------------------
# GET /api/papers
# ---------------------------------------------------------------------------

@papers_bp.get("/papers")
def list_papers():
    """
    论文列表，支持：
    - status 过滤（query param，可选）
    - page / page_size 分页（默认 page=1, page_size=20）
    """
    db = get_db_manager()
    status_str = request.args.get("status")
    page       = int(request.args.get("page", 1))
    page_size  = int(request.args.get("page_size", 20))

    status = None
    if status_str:
        try:
            status = PaperStatus(status_str)
        except ValueError:
            return jsonify({"error": f"无效的 status 值: {status_str}"}), 400

    papers, total = db.list_papers(status=status, page=page, page_size=page_size)
    return jsonify({
        "papers":    [_serialize_paper(p) for p in papers],
        "total":     total,
        "page":      page,
        "page_size": page_size,
        "pages":     (total + page_size - 1) // page_size,
    })


# ---------------------------------------------------------------------------
# GET /api/papers/<arxiv_id>
# ---------------------------------------------------------------------------

@papers_bp.get("/papers/<arxiv_id>")
def get_paper(arxiv_id: str):
    """单篇论文详情"""
    db = get_db_manager()
    paper = db.get_paper(arxiv_id)
    if paper is None:
        return jsonify({"error": f"论文不存在: {arxiv_id}"}), 404
    return jsonify(_serialize_paper(paper))


# ---------------------------------------------------------------------------
# POST /api/papers/<arxiv_id>/retry
# ---------------------------------------------------------------------------

@papers_bp.post("/papers/<arxiv_id>/retry")
def retry_paper(arxiv_id: str):
    """对失败的论文重新入队（支持 summary_failed / translation_failed）"""
    db = get_db_manager()
    paper = db.get_paper(arxiv_id)
    if paper is None:
        return jsonify({"error": f"论文不存在: {arxiv_id}"}), 404

    try:
        new_tasks = db.retry_paper(arxiv_id)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    if not new_tasks:
        return jsonify({"message": f"论文 {arxiv_id} 当前状态无需重试: {paper.status.value}"}), 200

    # 通知 Worker 有新任务
    from worker import get_scheduler
    get_scheduler().start()  # 如果已经在跑，是幂等的

    return jsonify({
        "message":    f"已将 {len(new_tasks)} 个任务重新入队",
        "tasks":      [{"id": t.id, "type": t.task_type.value} for t in new_tasks],
        "new_status": paper.status.value,
    })
