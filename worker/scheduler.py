# -*- coding: utf-8 -*-
"""
worker/scheduler.py — 后台串行任务调度器

设计：
- 一个 daemon=True 的后台线程持续轮询 task_queue
- 每次取一个 PENDING 任务（FIFO），串行执行，完成后继续取下一个
- 某篇论文失败不影响后续论文的处理
- 线程通过 stop_event 优雅退出
"""
from __future__ import annotations

import sys
import time
import threading
import traceback
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from loguru import logger

from db import get_db_manager, PaperStatus, TaskType
from worker.summarize_job import run_summarize
from worker.translate_job import run_translate


POLL_INTERVAL = 2  # 秒：无任务时的轮询间隔


class TaskScheduler:
    """后台串行任务调度器"""

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self):
        """启动后台调度线程（幂等，重复调用安全）"""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="TaskScheduler",
            daemon=True,
        )
        self._thread.start()
        logger.info("[Worker] 后台任务调度器已启动")

    def stop(self):
        """停止调度线程（等待当前任务完成）"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("[Worker] 后台任务调度器已停止")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -------------------------------------------------------------------------
    # 主循环
    # -------------------------------------------------------------------------

    def _loop(self):
        """任务消费主循环"""
        logger.info("[Worker] 调度循环开始")
        db = get_db_manager()

        while not self._stop_event.is_set():
            try:
                task = db.next_pending_task()
                if task is None:
                    # 队列为空，等待
                    self._stop_event.wait(POLL_INTERVAL)
                    continue

                logger.info(
                    f"[Worker] 取到任务: id={task.id} arxiv_id={task.arxiv_id} "
                    f"type={task.task_type.value}"
                )
                self._run_task(task)

            except Exception as e:
                logger.error(f"[Worker] 调度循环异常: {e}")
                logger.debug(traceback.format_exc())
                self._stop_event.wait(POLL_INTERVAL)

        logger.info("[Worker] 调度循环结束")

    def _run_task(self, task):
        """执行单个任务，捕获异常并更新状态"""
        db = get_db_manager()
        arxiv_id = task.arxiv_id
        
        try:
            if task.task_type == TaskType.SUMMARIZE:
                self._run_summarize(db, task, arxiv_id)
            elif task.task_type == TaskType.TRANSLATE:
                self._run_translate(db, task, arxiv_id)
            else:
                logger.warning(f"[Worker] 未知任务类型: {task.task_type}")
                db.complete_task(task.id, success=False, error_msg="未知任务类型")

        except Exception as e:
            error_msg = traceback.format_exc()
            logger.error(f"[Worker] 任务执行失败: {e}")
            db.complete_task(task.id, success=False, error_msg=str(e))

    def _run_summarize(self, db, task, arxiv_id: str):
        """执行摘要任务"""
        # 更新论文状态为 SUMMARIZING
        db.update_paper_status(arxiv_id, PaperStatus.SUMMARIZING)
        try:
            summary_zh = run_summarize(arxiv_id)
            db.update_paper_status(arxiv_id, PaperStatus.SUMMARIZED, summary_zh=summary_zh)
            db.complete_task(task.id, success=True)
            logger.info(f"[Worker] 摘要完成: {arxiv_id}")
        except Exception as e:
            err = traceback.format_exc()
            db.update_paper_status(arxiv_id, PaperStatus.SUMMARY_FAILED, summary_error=str(e))
            db.complete_task(task.id, success=False, error_msg=str(e))
            logger.error(f"[Worker] 摘要失败: {arxiv_id} — {e}")
            # 摘要失败时，对应的 translate 任务也不再执行，需要把 PENDING translate 标记为 failed
            self._cancel_pending_translate(db, arxiv_id)

    def _run_translate(self, db, task, arxiv_id: str):
        """执行翻译任务"""
        db.update_paper_status(arxiv_id, PaperStatus.TRANSLATING)
        try:
            result = run_translate(arxiv_id)
            db.update_paper_status(
                arxiv_id,
                PaperStatus.TRANSLATED,
                comparison_pdf_path=result.get("comparison_pdf", ""),
                translated_pdf_path=result.get("translated_pdf", ""),
            )
            db.complete_task(task.id, success=True)
            logger.info(f"[Worker] 翻译完成: {arxiv_id}")
        except Exception as e:
            err = traceback.format_exc()
            db.update_paper_status(arxiv_id, PaperStatus.TRANSLATION_FAILED, translation_error=str(e))
            db.complete_task(task.id, success=False, error_msg=str(e))
            logger.error(f"[Worker] 翻译失败: {arxiv_id} — {e}")

    @staticmethod
    def _cancel_pending_translate(db, arxiv_id: str):
        """摘要失败后，取消该论文待执行的翻译任务"""
        from db.models import TaskQueue, TaskType as TT, TaskStatus as TS
        from db.database import DatabaseManager
        from sqlalchemy.orm import Session

        # 直接操作 session 更新状态
        with db._session() as s:
            s.query(TaskQueue).filter(
                TaskQueue.arxiv_id == arxiv_id,
                TaskQueue.task_type == TT.TRANSLATE,
                TaskQueue.status == TS.PENDING,
            ).update({"status": TS.FAILED, "error_msg": "摘要步骤失败，跳过翻译"})


# 全局单例
_scheduler: TaskScheduler | None = None


def get_scheduler() -> TaskScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = TaskScheduler()
    return _scheduler
