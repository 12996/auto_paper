# -*- coding: utf-8 -*-
"""
================================================================================
db/models.py  — SQLAlchemy ORM 模型定义
================================================================================

【表说明】
  papers        — 论文主表，存储所有爬取到的论文元数据与处理状态
  search_history — 搜索历史表，记录每次用户发起的搜索参数
  task_queue    — 任务队列表，记录后台总结/翻译任务的执行状态

【状态枚举】
  PaperStatus: discovered → summarizing → summarized → translating → translated
                                ↓ (failed)           ↓ (failed)
                         summary_failed         translation_failed

  TaskType:  summarize | translate
  TaskStatus: pending | running | completed | failed
"""

import enum
from datetime import datetime

from sqlalchemy import (
    Column, String, Text, Integer, DateTime, Enum as SAEnum,
    ForeignKey, JSON, Index, UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


# =============================================================================
# 枚举定义
# =============================================================================

class PaperStatus(str, enum.Enum):
    """论文生命周期状态"""
    DISCOVERED       = "discovered"        # 已发现，刚爬取入库
    SUMMARIZING      = "summarizing"       # 总结生成中
    SUMMARIZED       = "summarized"        # 已生成中文摘要
    SUMMARY_FAILED   = "summary_failed"    # 摘要生成失败
    TRANSLATING      = "translating"       # 全文翻译中
    TRANSLATED       = "translated"        # 已完成翻译，comparison.pdf 可用
    TRANSLATION_FAILED = "translation_failed"  # 翻译/编译失败


class TaskType(str, enum.Enum):
    """后台任务类型"""
    SUMMARIZE = "summarize"   # 生成中文摘要（调用 chat_arxiv PaperSummarizer）
    TRANSLATE = "translate"   # 全文翻译 + 编译 PDF（调用 main.translate_arxiv_paper）


class TaskStatus(str, enum.Enum):
    """任务队列状态"""
    PENDING   = "pending"    # 等待执行
    RUNNING   = "running"    # 正在执行
    COMPLETED = "completed"  # 已完成
    FAILED    = "failed"     # 执行失败


# =============================================================================
# 论文主表
# =============================================================================

class PaperRecord(Base):
    """
    论文主表 — 每篇 ArXiv 论文一条记录。

    主键: arxiv_id（如 "2301.07041"），全局唯一标识。
    """
    __tablename__ = "papers"

    # -------------------------------------------------------------------------
    # 基础标识
    # -------------------------------------------------------------------------
    arxiv_id    = Column(String(20), primary_key=True,
                         comment="ArXiv 论文 ID，如 2301.07041")
    title       = Column(String(512), nullable=False,
                         comment="论文英文标题")
    authors     = Column(JSON, nullable=True,
                         comment="作者列表，JSON 数组，如 ['Author A', 'Author B']")
    abstract_en = Column(Text, nullable=True,
                         comment="英文摘要（从 ArXiv 爬取）")
    arxiv_url   = Column(String(256), nullable=True,
                         comment="论文 ArXiv 详情页 URL，如 https://arxiv.org/abs/2301.07041")
    published_at = Column(DateTime, nullable=True,
                          comment="论文发布日期（ArXiv 上的提交日期）")

    # -------------------------------------------------------------------------
    # 搜索来源
    # -------------------------------------------------------------------------
    search_query   = Column(String(256), nullable=True,
                            comment="发现该论文时使用的 query 参数")
    search_keyword = Column(String(256), nullable=True,
                            comment="发现该论文时使用的 keyword 参数")

    # -------------------------------------------------------------------------
    # 处理状态
    # -------------------------------------------------------------------------
    status = Column(
        SAEnum(PaperStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=PaperStatus.DISCOVERED,
        comment="当前处理状态，见 PaperStatus 枚举"
    )

    # -------------------------------------------------------------------------
    # 总结结果（US-03 步骤A）
    # -------------------------------------------------------------------------
    summary_zh    = Column(Text, nullable=True,
                           comment="LLM 生成的中文摘要，在首页列表中展示（前2行）")
    summary_error = Column(Text, nullable=True,
                           comment="总结失败时的错误信息，用于前端展示")

    # -------------------------------------------------------------------------
    # 翻译结果（US-03 步骤B）
    # -------------------------------------------------------------------------
    # 文件路径均为相对于项目根目录的相对路径，或绝对路径
    original_pdf_path    = Column(String(512), nullable=True,
                                  comment="原始英文 PDF 本地路径（ArxivWebCrawler 下载）")
    translated_pdf_path  = Column(String(512), nullable=True,
                                  comment="中文翻译 PDF 本地路径（main.py 编译产物）")
    comparison_pdf_path  = Column(String(512), nullable=True,
                                  comment="双语对照 PDF 本地路径（comparison.pdf，详情页展示用）")
    latex_cache_dir      = Column(String(512), nullable=True,
                                  comment="LaTeX 源码缓存目录（arxiv_cache/<arxiv_id>/）")
    translation_error    = Column(Text, nullable=True,
                                  comment="翻译失败时的错误信息，用于前端展示")

    # -------------------------------------------------------------------------
    # 时间戳
    # -------------------------------------------------------------------------
    discovered_at  = Column(DateTime, default=datetime.utcnow, nullable=False,
                            comment="论文入库时间（UTC）")
    summarized_at  = Column(DateTime, nullable=True,
                            comment="摘要生成完成时间（UTC）")
    translated_at  = Column(DateTime, nullable=True,
                            comment="翻译完成时间（UTC）")
    updated_at     = Column(DateTime, default=datetime.utcnow,
                            onupdate=datetime.utcnow, nullable=False,
                            comment="记录最后更新时间（UTC）")

    # -------------------------------------------------------------------------
    # 关联
    # -------------------------------------------------------------------------
    tasks = relationship("TaskQueue", back_populates="paper",
                         cascade="all, delete-orphan",
                         order_by="TaskQueue.created_at")

    # -------------------------------------------------------------------------
    # 索引
    # -------------------------------------------------------------------------
    __table_args__ = (
        Index("ix_papers_status", "status"),
        Index("ix_papers_published_at", "published_at"),
        Index("ix_papers_discovered_at", "discovered_at"),
    )

    def __repr__(self) -> str:
        return f"<PaperRecord arxiv_id={self.arxiv_id!r} status={self.status!r}>"


# =============================================================================
# 搜索历史表
# =============================================================================

class SearchHistory(Base):
    """
    搜索历史表 — 记录每次用户在前端发起的搜索操作。

    用于：
    - 前端"最近搜索"快捷填充
    - 统计分析（可选）
    """
    __tablename__ = "search_history"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    query        = Column(String(256), nullable=False,
                          comment="ArXiv 搜索字符串，如 'ti:attention transformer'")
    keyword      = Column(String(256), nullable=True,
                          comment="研究领域关键词，用于引导摘要生成")
    days         = Column(Integer, nullable=False, default=30,
                          comment="只搜索最近 N 天内发布的论文")
    max_results  = Column(Integer, nullable=False, default=10,
                          comment="最多处理的论文数量上限")
    results_count = Column(Integer, nullable=True,
                           comment="本次搜索实际爬取到的论文数量")
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False,
                          comment="搜索发起时间（UTC）")

    __table_args__ = (
        Index("ix_search_history_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<SearchHistory id={self.id} query={self.query!r}>"


# =============================================================================
# 任务队列表
# =============================================================================

class TaskQueue(Base):
    """
    任务队列表 — 记录每篇论文的后台处理任务（总结 / 翻译）。

    设计说明：
    - 每篇论文最多同时有 1 个 RUNNING 状态的任务（串行保证）
    - 重试时插入新的任务记录，旧的 FAILED 记录保留（历史可追溯）
    - 任务执行器按 created_at ASC 顺序串行消费 PENDING 任务
    """
    __tablename__ = "task_queue"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    arxiv_id   = Column(String(20), ForeignKey("papers.arxiv_id", ondelete="CASCADE"),
                        nullable=False, comment="关联的论文 ID")
    task_type  = Column(
        SAEnum(TaskType, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        comment="任务类型：summarize（总结）或 translate（翻译）"
    )
    status     = Column(
        SAEnum(TaskStatus, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
        default=TaskStatus.PENDING,
        comment="任务状态：pending / running / completed / failed"
    )
    error_msg  = Column(Text, nullable=True,
                        comment="失败时的错误堆栈或描述，用于诊断和前端展示")
    created_at  = Column(DateTime, default=datetime.utcnow, nullable=False,
                         comment="任务创建时间，决定执行顺序（ASC）")
    started_at  = Column(DateTime, nullable=True,
                         comment="任务开始执行时间（UTC）")
    finished_at = Column(DateTime, nullable=True,
                         comment="任务完成或失败时间（UTC）")

    # -------------------------------------------------------------------------
    # 关联
    # -------------------------------------------------------------------------
    paper = relationship("PaperRecord", back_populates="tasks")

    # -------------------------------------------------------------------------
    # 索引
    # -------------------------------------------------------------------------
    __table_args__ = (
        Index("ix_task_queue_status_created", "status", "created_at"),
        Index("ix_task_queue_arxiv_id",       "arxiv_id"),
    )

    def __repr__(self) -> str:
        return (f"<TaskQueue id={self.id} arxiv_id={self.arxiv_id!r} "
                f"type={self.task_type!r} status={self.status!r}>")
