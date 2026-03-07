# -*- coding: utf-8 -*-
"""
================================================================================
arxiv_downloader/__init__.py
================================================================================
ArXiv 论文下载模块

【来源说明】


【功能说明】
1. 解析 arxiv 论文 ID 或 URL
2. 下载 arxiv 论文的 Latex 源码包 (.tar)
3. 解压源码包到指定目录
4. 支持缓存已下载的论文

【依赖关系】
- requests: HTTP 请求
- tarfile: 解压 tar 文件
- os/pathlib: 文件系统操作
================================================================================
"""

from .downloader import ArxivDownloader, download_arxiv_paper

__all__ = ['ArxivDownloader', 'download_arxiv_paper']
