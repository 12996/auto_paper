# -*- coding: utf-8 -*-
"""
api/queue.py — 后台任务队列状态路由

GET /api/queue/status   悬浮进度面板数据
"""
from flask import Blueprint, jsonify
from db import get_db_manager

queue_bp = Blueprint("queue", __name__, url_prefix="/api")


@queue_bp.get("/queue/status")
def queue_status():
    """
    返回当前任务队列状态，供前端右下角悬浮进度面板使用。

    Response:
        {
            "total": 10,
            "done": 3,
            "running": 1,
            "pending": 6,
            "percent": 30,
            "is_idle": false,
            "current": {
                "arxiv_id": "2301.07041",
                "title": "Attention Is All You Need",
                "task_type": "translate"
            },
            "pending_papers": ["FlowNet: ...", "GPT-4 ..."]
        }
    """
    db = get_db_manager()
    status = db.get_queue_status()

    total = status["total"]
    done  = status["done"]
    percent = round(done / total * 100) if total > 0 else 0

    return jsonify({
        **status,
        "percent":  percent,
        "is_idle":  status["running"] == 0 and status["pending"] == 0,
    })


@queue_bp.get("/queue/worker")
def worker_status():
    """返回后台 Worker 线程是否在运行"""
    from worker import get_scheduler
    scheduler = get_scheduler()
    return jsonify({
        "running": scheduler.is_running,
    })
