# -*- coding: utf-8 -*-
"""
================================================================================
db/database.py  — 数据库连接管理 & 常用 CRUD 操作
================================================================================

使用方式:
    from db import get_db_manager

    db = get_db_manager()           # 全局单例，路径来自 config.DB_PATH
    db.upsert_paper(arxiv_id, ...) # 幂等写入论文
    papers = db.list_papers(...)   # 带过滤+分页的查询

设计原则:
- 所有写操作封装在本模块，业务层不直接操作 Session
- 每次调用自动处理 session open/commit/rollback/close
- 重试插入任务时自动把旧的 FAILED 记录标记为 superseded（保留历史）
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator, List, Optional

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker, Session

from .models import Base, PaperRecord, PaperStatus, SearchHistory, TaskQueue, TaskStatus, TaskType


# =============================================================================
# 数据库路径配置
# =============================================================================

_DEFAULT_DB_PATH = Path(__file__).parent.parent / "arxiv_library.db"
_GLOBAL_MANAGER: Optional["DatabaseManager"] = None


def get_db_manager(db_path: Optional[str] = None) -> "DatabaseManager":
    """
    获取全局 DatabaseManager 单例。

    第一次调用时初始化（创建数据库文件和表结构）；
    后续调用直接返回缓存的实例。

    Args:
        db_path: SQLite 文件路径。仅首次调用时有效，后续传入会被忽略。
    """
    global _GLOBAL_MANAGER
    if _GLOBAL_MANAGER is None:
        path = db_path or os.environ.get("ARXIV_DB_PATH") or str(_DEFAULT_DB_PATH)
        _GLOBAL_MANAGER = DatabaseManager(path)
    return _GLOBAL_MANAGER


# =============================================================================
# DatabaseManager
# =============================================================================

class DatabaseManager:
    """SQLite 数据库管理器，封装所有 CRUD 操作。"""

    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        engine_url = f"sqlite:///{self.db_path}"
        self._engine = create_engine(
            engine_url,
            connect_args={"check_same_thread": False},  # SQLite 跨线程访问
            echo=False,
        )
        Base.metadata.create_all(self._engine)   # 自动建表（幂等）
        self._SessionFactory = sessionmaker(bind=self._engine, expire_on_commit=False)

    def close(self) -> None:
        """显式释放连接池（进程退出或测试清理时调用）。"""
        self._engine.dispose()

    # -------------------------------------------------------------------------
    # Session 上下文管理
    # -------------------------------------------------------------------------

    @contextmanager
    def _session(self) -> Generator[Session, None, None]:
        """提供一个自动 commit/rollback 的 Session 上下文。"""
        session: Session = self._SessionFactory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # =========================================================================
    # PaperRecord CRUD
    # =========================================================================

    def upsert_paper(
        self,
        arxiv_id: str,
        title: str,
        arxiv_url: str,
        abstract_en: str = "",
        authors: Optional[List[str]] = None,
        published_at: Optional[datetime] = None,
        search_query: str = "",
        search_keyword: str = "",
        original_pdf_path: str = "",
    ) -> PaperRecord:
        """
        幂等写入论文记录。

        - 若 arxiv_id 不存在：插入新记录，状态为 DISCOVERED
        - 若 arxiv_id 已存在：**跳过**（不覆盖已有的处理状态和结果）

        Returns:
            PaperRecord 对象（新建或已存在）
        """
        with self._session() as s:
            paper = s.get(PaperRecord, arxiv_id)
            if paper is None:
                paper = PaperRecord(
                    arxiv_id=arxiv_id,
                    title=title,
                    arxiv_url=arxiv_url,
                    abstract_en=abstract_en,
                    authors=authors or [],
                    published_at=published_at,
                    search_query=search_query,
                    search_keyword=search_keyword,
                    original_pdf_path=original_pdf_path,
                    status=PaperStatus.DISCOVERED,
                )
                s.add(paper)
            return paper

    def update_paper_status(
        self,
        arxiv_id: str,
        status: PaperStatus,
        *,
        summary_zh: Optional[str] = None,
        summary_error: Optional[str] = None,
        translated_pdf_path: Optional[str] = None,
        comparison_pdf_path: Optional[str] = None,
        latex_cache_dir: Optional[str] = None,
        translation_error: Optional[str] = None,
    ) -> None:
        """更新论文状态及相关字段。"""
        with self._session() as s:
            paper = s.get(PaperRecord, arxiv_id)
            if paper is None:
                raise ValueError(f"论文不存在: {arxiv_id}")

            paper.status = status
            paper.updated_at = datetime.utcnow()

            if summary_zh is not None:
                paper.summary_zh = summary_zh
                paper.summarized_at = datetime.utcnow()
            if summary_error is not None:
                paper.summary_error = summary_error
            if translated_pdf_path is not None:
                paper.translated_pdf_path = translated_pdf_path
                paper.translated_at = datetime.utcnow()
            if comparison_pdf_path is not None:
                paper.comparison_pdf_path = comparison_pdf_path
            if latex_cache_dir is not None:
                paper.latex_cache_dir = latex_cache_dir
            if translation_error is not None:
                paper.translation_error = translation_error

    def get_paper(self, arxiv_id: str) -> Optional[PaperRecord]:
        """按 arxiv_id 获取单篇论文。"""
        with self._session() as s:
            return s.get(PaperRecord, arxiv_id)

    def list_papers(
        self,
        status: Optional[PaperStatus] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[List[PaperRecord], int]:
        """
        分页查询论文列表，按 discovered_at 倒序。

        Returns:
            (papers, total_count)
        """
        with self._session() as s:
            q = s.query(PaperRecord)
            if status is not None:
                q = q.filter(PaperRecord.status == status)
            total = q.count()
            papers = (
                q.order_by(PaperRecord.discovered_at.desc())
                 .offset((page - 1) * page_size)
                 .limit(page_size)
                 .all()
            )
            return papers, total

    def get_stats(self) -> dict:
        """
        返回首页统计面板所需的聚合数据。

        Returns:
            {
                "total": 42,
                "summarized": 31,
                "translated": 18,
                "in_progress": 3,
                "failed": 2,
            }
        """
        with self._session() as s:
            rows = (
                s.query(PaperRecord.status, func.count(PaperRecord.arxiv_id))
                 .group_by(PaperRecord.status)
                 .all()
            )
            count_map = {row[0]: row[1] for row in rows}

            total      = sum(count_map.values())
            summarized = sum(
                count_map.get(st, 0)
                for st in [PaperStatus.SUMMARIZED, PaperStatus.TRANSLATING,
                            PaperStatus.TRANSLATED, PaperStatus.TRANSLATION_FAILED]
            )
            translated  = count_map.get(PaperStatus.TRANSLATED, 0)
            in_progress = count_map.get(PaperStatus.SUMMARIZING, 0) + count_map.get(PaperStatus.TRANSLATING, 0)
            failed      = count_map.get(PaperStatus.SUMMARY_FAILED, 0) + count_map.get(PaperStatus.TRANSLATION_FAILED, 0)

            return {
                "total":       total,
                "summarized":  summarized,
                "translated":  translated,
                "in_progress": in_progress,
                "failed":      failed,
            }

    # =========================================================================
    # SearchHistory CRUD
    # =========================================================================

    def add_search_history(
        self,
        query: str,
        keyword: str,
        days: int,
        max_results: int,
        results_count: int = 0,
    ) -> SearchHistory:
        """记录一次搜索操作。"""
        with self._session() as s:
            record = SearchHistory(
                query=query,
                keyword=keyword,
                days=days,
                max_results=max_results,
                results_count=results_count,
            )
            s.add(record)
            return record

    def get_recent_searches(self, limit: int = 5) -> List[SearchHistory]:
        """获取最近 N 条搜索记录，用于前端快捷填充。"""
        with self._session() as s:
            return (
                s.query(SearchHistory)
                 .order_by(SearchHistory.created_at.desc())
                 .limit(limit)
                 .all()
            )

    # =========================================================================
    # TaskQueue CRUD
    # =========================================================================

    def enqueue_tasks(self, arxiv_id: str) -> List[TaskQueue]:
        """
        为论文创建串行任务队列：先 summarize，再 translate。

        若该论文已有 PENDING/RUNNING 的同类任务，则跳过（防止重复入队）。

        Returns:
            新创建的 TaskQueue 列表
        """
        with self._session() as s:
            created = []
            for task_type in [TaskType.SUMMARIZE, TaskType.TRANSLATE]:
                # 检查是否已有活跃任务
                existing = (
                    s.query(TaskQueue)
                     .filter(
                         TaskQueue.arxiv_id == arxiv_id,
                         TaskQueue.task_type == task_type,
                         TaskQueue.status.in_([TaskStatus.PENDING, TaskStatus.RUNNING]),
                     )
                     .first()
                )
                if existing:
                    continue

                task = TaskQueue(
                    arxiv_id=arxiv_id,
                    task_type=task_type,
                    status=TaskStatus.PENDING,
                )
                s.add(task)
                created.append(task)
            return created

    def retry_paper(self, arxiv_id: str) -> List[TaskQueue]:
        """
        重试失败的论文：
        1. 根据当前状态决定从哪一步重试
           - SUMMARY_FAILED → 重新入队 summarize + translate
           - TRANSLATION_FAILED → 重新入队 translate（跳过 summarize）
        2. 将论文状态重置为 DISCOVERED

        Returns:
            新创建的 TaskQueue 列表
        """
        with self._session() as s:
            paper = s.get(PaperRecord, arxiv_id)
            if paper is None:
                raise ValueError(f"论文不存在: {arxiv_id}")

            if paper.status == PaperStatus.SUMMARY_FAILED:
                task_types = [TaskType.SUMMARIZE, TaskType.TRANSLATE]
                paper.status = PaperStatus.DISCOVERED
            elif paper.status == PaperStatus.TRANSLATION_FAILED:
                task_types = [TaskType.TRANSLATE]
                paper.status = PaperStatus.SUMMARIZED
            else:
                return []

            paper.updated_at = datetime.utcnow()
            created = []
            for task_type in task_types:
                task = TaskQueue(
                    arxiv_id=arxiv_id,
                    task_type=task_type,
                    status=TaskStatus.PENDING,
                )
                s.add(task)
                created.append(task)
            return created

    def next_pending_task(self) -> Optional[TaskQueue]:
        """
        获取并锁定下一个待执行任务（PENDING → RUNNING）。

        任务按 created_at ASC 串行消费，每次只处理一个。

        Returns:
            TaskQueue 对象，或 None（队列为空）
        """
        with self._session() as s:
            task = (
                s.query(TaskQueue)
                 .filter(TaskQueue.status == TaskStatus.PENDING)
                 .order_by(TaskQueue.created_at.asc())
                 .with_for_update(skip_locked=True)
                 .first()
            )
            if task is None:
                return None
            task.status     = TaskStatus.RUNNING
            task.started_at = datetime.utcnow()
            return task

    def complete_task(self, task_id: int, success: bool, error_msg: str = "") -> None:
        """将任务标记为完成或失败。"""
        with self._session() as s:
            task = s.get(TaskQueue, task_id)
            if task is None:
                return
            task.status      = TaskStatus.COMPLETED if success else TaskStatus.FAILED
            task.finished_at = datetime.utcnow()
            task.error_msg   = error_msg or None

    def get_queue_status(self) -> dict:
        """
        返回悬浮进度面板所需的队列状态数据。

        Returns:
            {
                "total":   10,       # 本批次任务总数
                "done":    3,        # 已完成（含失败）
                "running": 1,        # 正在执行
                "pending": 6,        # 等待中
                "current": {         # 当前正在执行的任务，None 表示空闲
                    "arxiv_id": "2301.07041",
                    "title":    "Attention Is All You Need",
                    "task_type": "translate",
                },
                "pending_papers": [  # 等待中的论文标题列表（最多5个）
                    "FlowNet: ...",
                    "GPT-4 ...",
                ],
            }
        """
        with self._session() as s:
            total   = s.query(func.count(TaskQueue.id)).scalar()
            done    = s.query(func.count(TaskQueue.id)).filter(
                TaskQueue.status.in_([TaskStatus.COMPLETED, TaskStatus.FAILED])
            ).scalar()
            running = s.query(func.count(TaskQueue.id)).filter(
                TaskQueue.status == TaskStatus.RUNNING
            ).scalar()
            pending = s.query(func.count(TaskQueue.id)).filter(
                TaskQueue.status == TaskStatus.PENDING
            ).scalar()

            # 当前执行中的任务
            current_task = (
                s.query(TaskQueue, PaperRecord.title)
                 .join(PaperRecord, TaskQueue.arxiv_id == PaperRecord.arxiv_id)
                 .filter(TaskQueue.status == TaskStatus.RUNNING)
                 .first()
            )
            current = None
            if current_task:
                task, title = current_task
                current = {
                    "arxiv_id":  task.arxiv_id,
                    "title":     title,
                    "task_type": task.task_type.value,
                }

            # 等待中的论文（前5条）
            pending_rows = (
                s.query(PaperRecord.title)
                 .join(TaskQueue, PaperRecord.arxiv_id == TaskQueue.arxiv_id)
                 .filter(TaskQueue.status == TaskStatus.PENDING)
                 .order_by(TaskQueue.created_at.asc())
                 .limit(5)
                 .all()
            )
            pending_papers = [row[0] for row in pending_rows]

            return {
                "total":          total,
                "done":           done,
                "running":        running,
                "pending":        pending,
                "current":        current,
                "pending_papers": pending_papers,
            }
