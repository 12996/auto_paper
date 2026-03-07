# -*- coding: utf-8 -*-
"""
api/papers.py — 论文相关路由

GET  /api/stats           首页统计卡片
GET  /api/papers          论文列表（分页 + 状态过滤）
GET  /api/papers/<id>     论文详情
POST /api/papers/<id>/retry  失败重试
POST /api/papers/<id>/translate  手动触发翻译
POST /api/papers/<id>/interrupt  中断翻译任务
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

    refreshed = db.get_paper(arxiv_id)

    # 通知 Worker 有新任务
    from worker import get_scheduler
    get_scheduler().start()  # 如果已经在跑，是幂等的

    return jsonify({
        "message":    f"已将 {len(new_tasks)} 个任务重新入队",
        "tasks":      [{"id": t.id, "type": t.task_type.value} for t in new_tasks],
        "new_status": refreshed.status.value if refreshed else paper.status.value,
    })


# ---------------------------------------------------------------------------
# POST /api/papers/<arxiv_id>/translate
# ---------------------------------------------------------------------------

@papers_bp.post("/papers/<arxiv_id>/translate")
def translate_paper(arxiv_id: str):
    """手动触发翻译（仅 summarized / translation_failed 状态允许）。"""
    db = get_db_manager()
    paper = db.get_paper(arxiv_id)
    if paper is None:
        return jsonify({"error": f"论文不存在: {arxiv_id}"}), 404

    try:
        task = db.enqueue_translate_task(arxiv_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if task is None:
        return jsonify({
            "message": f"论文 {arxiv_id} 当前状态为 {paper.status.value}，无需重复触发翻译",
            "new_status": paper.status.value,
        }), 200

    from worker import get_scheduler
    get_scheduler().start()

    return jsonify({
        "message": "已创建翻译任务",
        "task": {"id": task.id, "type": task.task_type.value},
        "new_status": "summarized",
    }), 202


# ---------------------------------------------------------------------------
# POST /api/papers/<arxiv_id>/interrupt
# ---------------------------------------------------------------------------

@papers_bp.post("/papers/<arxiv_id>/interrupt")
def interrupt_translate(arxiv_id: str):
    """中断翻译任务：取消 pending 翻译，并向 running 翻译发送中断信号。"""
    db = get_db_manager()
    paper = db.get_paper(arxiv_id)
    if paper is None:
        return jsonify({"error": f"论文不存在: {arxiv_id}"}), 404

    cancelled_pending = db.cancel_pending_translate_tasks(arxiv_id)
    running = db.has_running_translate_task(arxiv_id)

    if running:
        from worker.translate_job import request_translate_interrupt
        flag = request_translate_interrupt(arxiv_id)
        return jsonify({
            "message": "已发送中断信号，任务将在当前子步骤结束后停止",
            "cancelled_pending": cancelled_pending,
            "interrupt_flag": flag,
        }), 202

    if cancelled_pending > 0:
        return jsonify({
            "message": f"已取消 {cancelled_pending} 个待执行翻译任务",
            "cancelled_pending": cancelled_pending,
        }), 200

    return jsonify({"error": "当前没有可中断的翻译任务"}), 409


# ---------------------------------------------------------------------------
# DELETE /api/papers/<arxiv_id>
# ---------------------------------------------------------------------------

@papers_bp.delete("/papers/<arxiv_id>")
def delete_paper(arxiv_id: str):
    """
    删除单篇论文（含磁盘文件）。

    Query params:
        force=true  — 强制取消 RUNNING 任务后删除（默认 false）
    """
    db = get_db_manager()
    force = request.args.get("force", "false").lower() == "true"

    paper = db.get_paper(arxiv_id)
    if paper is None:
        return jsonify({"error": f"论文不存在: {arxiv_id}"}), 404

    if force:
        # 先强制取消所有活跃任务，再删除
        db.force_cancel_running_tasks(arxiv_id)

    try:
        result = db.delete_paper(arxiv_id, delete_files=True)
    except RuntimeError as e:
        # RUNNING 任务存在，未使用 force
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    freed_mb = result["freed_bytes"] / (1024 * 1024)
    return jsonify({
        "message":       f"论文 {arxiv_id} 已删除",
        "freed_bytes":   result["freed_bytes"],
        "freed_mb":      round(freed_mb, 2),
        "deleted_files": result["deleted_files"],
    })


# ---------------------------------------------------------------------------
# POST /api/papers/<arxiv_id>/reset
# ---------------------------------------------------------------------------

@papers_bp.post("/papers/<arxiv_id>/reset")
def reset_paper(arxiv_id: str):
    """
    将论文状态重置为 DISCOVERED，清空错误信息，并重新触发摘要流程。
    适用于调试：保留元数据记录但重走摘要；翻译需用户后续手动触发。
    """
    db = get_db_manager()
    paper = db.get_paper(arxiv_id)
    if paper is None:
        return jsonify({"error": f"论文不存在: {arxiv_id}"}), 404

    db.reset_paper_for_reprocess(arxiv_id)
    # 重新入队
    new_tasks = db.enqueue_tasks(arxiv_id)

    from worker import get_scheduler
    get_scheduler().start()

    return jsonify({
        "message":    f"论文 {arxiv_id} 已重置，重新入队 {len(new_tasks)} 个摘要任务",
        "new_status": "discovered",
    })


# ---------------------------------------------------------------------------
# DELETE /api/papers  (批量删除失败项)
# ---------------------------------------------------------------------------

@papers_bp.delete("/papers")
def delete_papers_batch():
    """
    批量删除论文。

    Query params:
        status=failed  — 清空所有失败状态的论文（summary_failed + translation_failed）

    目前只支持 status=failed，防误操作。
    """
    db = get_db_manager()
    status_filter = request.args.get("status", "")

    if status_filter != "failed":
        return jsonify({
            "error": "批量删除只支持 status=failed，请明确指定要清空的范围"
        }), 400

    # 查询所有失败状态的论文
    failed_statuses = [PaperStatus.SUMMARY_FAILED, PaperStatus.TRANSLATION_FAILED]
    deleted_ids = []
    errors = []
    total_freed = 0

    for status in failed_statuses:
        papers, _ = db.list_papers(status=status, page=1, page_size=10000)
        for paper in papers:
            try:
                result = db.delete_paper(paper.arxiv_id, delete_files=True)
                deleted_ids.append(paper.arxiv_id)
                total_freed += result["freed_bytes"]
            except Exception as e:
                errors.append({"arxiv_id": paper.arxiv_id, "error": str(e)})

    return jsonify({
        "message":     f"已清空 {len(deleted_ids)} 篇失败论文",
        "deleted":     deleted_ids,
        "errors":      errors,
        "freed_bytes": total_freed,
        "freed_mb":    round(total_freed / (1024 * 1024), 2),
    })
