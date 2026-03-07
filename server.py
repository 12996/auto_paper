# -*- coding: utf-8 -*-
"""
================================================================================
server.py — ArXiv 论文翻译系统后端入口
================================================================================

启动方式:
    conda activate chatpaper
    cd f:\claude\arxiv_translator
    python server.py

默认地址: http://localhost:5000

API 接口一览:
    GET  /api/stats                           首页统计卡片
    GET  /api/papers                          论文列表（?status=&page=&page_size=）
    GET  /api/papers/<arxiv_id>               论文详情
    POST /api/papers/<arxiv_id>/retry         失败重试
    POST /api/papers/<arxiv_id>/translate     手动触发翻译
    POST /api/papers/<arxiv_id>/interrupt     中断翻译任务
    POST /api/papers/<arxiv_id>/reset         重置并重新摘要
    DELETE /api/papers/<arxiv_id>             删除单篇论文
    DELETE /api/papers?status=failed          批量清空失败论文
    POST /api/search                          触发搜索（body: query/keyword/days/max）
    GET  /api/searches                        最近搜索历史
    GET  /api/queue/status                    后台队列进度
    GET  /api/queue/worker                    Worker 运行状态
    GET  /api/files/<path>                    本地 PDF 文件服务（URL 编码路径）
    GET  /api/files/by-arxiv/<id>/<type>      按论文 ID 服务 PDF（type=comparison/translated/original）
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from loguru import logger
from api import create_app
from worker import get_scheduler
from db import get_db_manager


def setup_logging(verbose: bool = False) -> None:
    """为 server 模式配置终端 + 文件日志输出。"""
    level = "DEBUG" if verbose else "INFO"
    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}:{function}:{line}</cyan> - <level>{message}</level>",
    )
    logger.add(
        ROOT / "arxiv_translator.log",
        level="DEBUG",
        rotation="10 MB",
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=False,
    )


def main():
    setup_logging()
    # 初始化数据库（首次运行自动建表）
    db = get_db_manager()
    logger.info(f"数据库已就绪: {db.db_path}")

    # 修复上次崩溃遗留的僵尸 RUNNING 任务
    fixed = db.reset_stuck_tasks()
    if fixed:
        logger.warning(f"[启动检查] 发现并修复了 {fixed} 个僵尸任务（RUNNING → PENDING）")
    else:
        logger.info("[启动检查] 无僵尸任务")

    # 启动后台 Worker
    scheduler = get_scheduler()
    scheduler.start()
    logger.info("后台 Worker 已启动")

    # 创建 Flask 应用
    app = create_app()

    logger.info("=" * 60)
    logger.info("ArXiv 论文翻译系统后端已启动")
    logger.info("访问地址: http://localhost:5000")
    logger.info("API 文档: 见 server.py 头部注释")
    logger.info("=" * 60)

    # 启动服务（use_reloader=False 避免 Worker 线程被启动两次）
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
        use_reloader=False,
        threaded=True,
    )


if __name__ == "__main__":
    main()
