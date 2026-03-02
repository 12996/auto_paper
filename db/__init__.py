# -*- coding: utf-8 -*-
"""
数据库模块 — 基于 SQLite + SQLAlchemy 的本地论文库管理。
"""

from .models import Base, PaperRecord, SearchHistory, TaskQueue, PaperStatus, TaskType, TaskStatus
from .database import DatabaseManager, get_db_manager

__all__ = [
    "Base",
    "PaperRecord",
    "SearchHistory",
    "TaskQueue",
    "PaperStatus",
    "TaskType",
    "TaskStatus",
    "DatabaseManager",
    "get_db_manager",
]
