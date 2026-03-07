# -*- coding: utf-8 -*-
"""
================================================================================
arxiv_downloader/downloader.py
================================================================================
ArXiv 论文下载器实现



【主要修改】
- 移除对 chatbot/UI 的依赖，改为日志输出
- 移除 update_ui 等 Gradio 相关调用
- 简化代理配置，使用简单的 proxies 参数
- 保留核心下载逻辑

【使用方法】
    from arxiv_downloader import ArxivDownloader

    downloader = ArxivDownloader(cache_dir="./arxiv_cache")
    extract_path, arxiv_id = downloader.download("2301.07041")
================================================================================
"""

import os
import re
import time
import tarfile
import requests
from pathlib import Path
from typing import Optional, Tuple
from loguru import logger


class ArxivDownloader:
    """
    ArXiv 论文下载器

    【原类】无（原为独立函数 arxiv_download）
    【重构】将函数逻辑封装为类，便于管理状态和配置

    Attributes:
        cache_dir: 缓存目录，用于存储下载的论文
        proxies: 代理配置，格式为 {"http": "...", "https": "..."}
    """

    # ArXiv 源码下载 URL 模板
    ARXIV_SRC_URL_TEMPLATE = "https://arxiv.org/src/"
    ARXIV_EPRINT_URL_TEMPLATE = "https://arxiv.org/e-print/"
    ARXIV_ABS_URL_TEMPLATE = "https://arxiv.org/abs/"

    def __init__(self, cache_dir: str = "./arxiv_cache", proxies: Optional[dict] = None):
        """
        初始化下载器

        Args:
            cache_dir: 缓存目录路径
            proxies: 代理配置，如 {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}
        """
        self.cache_dir = Path(cache_dir)
        self.proxies = proxies or {}

        # 确保缓存目录存在
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"ArXiv 下载器初始化完成，缓存目录: {self.cache_dir.absolute()}")

    def _is_float(self, s: str) -> bool:
        """
        判断字符串是否为浮点数

        """
        try:
            float(s)
            return True
        except ValueError:
            return False

    def _parse_arxiv_id(self, input_str: str) -> Tuple[str, str]:
        """
        解析输入，提取 arxiv ID 和构建标准 URL

        【修改】返回 (arxiv_id, abs_url) 元组

        支持的输入格式：
        - 纯 ID: "2301.07041" 或 "2301.07041v2"
        - PDF URL: "https://arxiv.org/pdf/2301.07041v2.pdf"
        - 摘要 URL: "https://arxiv.org/abs/2301.07041"

        Args:
            input_str: 用户输入的 arxiv ID 或 URL

        Returns:
            (arxiv_id, abs_url): 论文 ID 和摘要页 URL
        """
        txt = input_str.strip()

        # 处理 PDF URL 格式
        if txt.startswith('https://arxiv.org/pdf/'):
            arxiv_id = txt.split('/')[-1]  # 2402.14207v2.pdf
            arxiv_id = arxiv_id.split('v')[0]  # 2402.14207
            txt = arxiv_id

        # 处理纯 ID 格式（包含点号，不包含斜杠，且是浮点数格式）
        if ('.' in txt) and ('/' not in txt) and self._is_float(txt):
            txt = self.ARXIV_ABS_URL_TEMPLATE + txt.strip()
        if ('.' in txt) and ('/' not in txt) and self._is_float(txt[:10]):
            txt = self.ARXIV_ABS_URL_TEMPLATE + txt[:10]

        # 检查是否是 arxiv URL
        if not txt.startswith('https://arxiv.org'):
            # 不是 arxiv 链接，可能是本地文件路径
            return "", ""

        # 解析 URL 获取 ID
        if not txt.startswith(self.ARXIV_ABS_URL_TEMPLATE):
            logger.error(f"解析 arxiv 网址失败，期望格式: https://arxiv.org/abs/1707.06690，实际: {txt}")
            raise ValueError(f"无效的 arxiv URL 格式: {txt}")

        arxiv_id = txt.split('/abs/')[-1]
        # 处理版本号 (如 2301.07041v2 -> 2301.07041)
        if 'v' in arxiv_id and len(arxiv_id) > 10:
            arxiv_id = arxiv_id[:10]

        logger.info(f"解析 arxiv ID: {arxiv_id}")
        return arxiv_id, txt

    def _check_cache(self, arxiv_id: str) -> Optional[Path]:
        """
        检查是否已有缓存的翻译结果

        【修改】返回 Path 对象而非字符串

        Args:
            arxiv_id: arxiv 论文 ID

        Returns:
            如果存在翻译好的 PDF 则返回路径，否则返回 None
        """
        translation_dir = self.cache_dir / arxiv_id / 'translation'
        translation_dir.mkdir(parents=True, exist_ok=True)

        target_file = translation_dir / 'translate_zh.pdf'
        if target_file.exists():
            logger.info(f"发现已缓存的翻译结果: {target_file}")
            return target_file
        return None

    def _download_source(self, arxiv_id: str, abs_url: str) -> Path:
        """
        下载 arxiv 论文源码
        【修改】移除 yield 生成器模式，改为直接返回

        Args:
            arxiv_id: arxiv 论文 ID
            abs_url: arxiv 摘要页 URL

        Returns:
            下载文件的路径
        """
        eprint_dir = self.cache_dir / arxiv_id / 'e-print'
        eprint_dir.mkdir(parents=True, exist_ok=True)

        dst = eprint_dir / f"{arxiv_id}.tar"

        # 如果已缓存，直接返回
        if dst.exists():
            logger.info(f"使用缓存文件: {dst}")
            return dst

        # 尝试下载（先尝试 /src/，再尝试 /e-print/）
        logger.info(f"开始下载 arxiv 论文: {arxiv_id}")

        for path in ['/src/', '/e-print/']:
            url_tar = abs_url.replace('/abs/', path)
            logger.info(f"尝试下载: {url_tar}")

            try:
                response = requests.get(url_tar, proxies=self.proxies, timeout=60)
                if response.status_code == 200:
                    with open(dst, 'wb') as f:
                        f.write(response.content)
                    logger.info(f"下载成功: {dst}")
                    return dst
            except Exception as e:
                logger.warning(f"下载失败 ({url_tar}): {e}")
                continue

        raise RuntimeError(f"无法下载 arxiv 论文: {arxiv_id}")

    def _extract_tar(self, tar_path: Path, arxiv_id: str) -> Path:
        """
        解压 tar 文件

        【修改】添加更详细的错误处理

        Args:
            tar_path: tar 文件路径
            arxiv_id: arxiv 论文 ID

        Returns:
            解压目录路径
        """
        extract_dst = self.cache_dir / arxiv_id / 'extract'
        extract_dst.mkdir(parents=True, exist_ok=True)

        logger.info(f"解压文件到: {extract_dst}")

        try:
            import tarfile
            with tarfile.open(tar_path, 'r:*') as tar:
                tar.extractall(path=extract_dst)
            logger.info("解压完成")
            return extract_dst
        except tarfile.ReadError as e:
            # 删除损坏的文件
            if tar_path.exists():
                tar_path.unlink()
            raise RuntimeError(f"解压失败，文件可能损坏: {e}")

    def download(self, input_str: str, use_cache: bool = True) -> Tuple[Path, str]:
        """
        下载 arxiv 论文并解压

        【修改】整合所有步骤为单一方法，返回解压路径和 arxiv ID

        Args:
            input_str: arxiv ID 或 URL
            use_cache: 是否使用缓存

        Returns:
            (extract_path, arxiv_id): 解压目录路径和论文 ID

        Raises:
            ValueError: 输入格式无效
            RuntimeError: 下载或解压失败
        """
        # 1. 解析输入
        arxiv_id, abs_url = self._parse_arxiv_id(input_str)

        if not arxiv_id:
            # 不是 arxiv 链接，可能是本地文件
            local_path = Path(input_str)
            if local_path.exists():
                logger.info(f"使用本地文件: {local_path}")
                return local_path, ""
            raise ValueError(f"无效的输入: {input_str}")

        # 2. 检查缓存
        if use_cache:
            cached_pdf = self._check_cache(arxiv_id)
            if cached_pdf:
                logger.info(f"使用缓存的翻译结果，跳过下载")
                return cached_pdf.parent.parent / 'extract', arxiv_id

        # 3. 下载源码
        tar_path = self._download_source(arxiv_id, abs_url)

        # 4. 解压
        extract_path = self._extract_tar(tar_path, arxiv_id)

        return extract_path, arxiv_id


def download_arxiv_paper(
    arxiv_id_or_url: str,
    cache_dir: str = "./arxiv_cache",
    proxies: Optional[dict] = None,
    use_cache: bool = True
) -> Tuple[Path, str]:
    """
    便捷函数：下载 arxiv 论文


    【说明】这是 ArxivDownloader.download() 的快捷包装

    Args:
        arxiv_id_or_url: arxiv ID 或 URL
        cache_dir: 缓存目录
        proxies: 代理配置
        use_cache: 是否使用缓存

    Returns:
        (extract_path, arxiv_id): 解压目录路径和论文 ID

    Example:
        >>> path, aid = download_arxiv_paper("2301.07041")
        >>> print(f"论文已下载到: {path}")
    """
    downloader = ArxivDownloader(cache_dir=cache_dir, proxies=proxies)
    return downloader.download(arxiv_id_or_url, use_cache=use_cache)


if __name__ == "__main__":
    # 测试代码
    import sys

    if len(sys.argv) < 2:
        print("用法: python downloader.py <arxiv_id_or_url>")
        print("示例: python downloader.py 2301.07041")
        sys.exit(1)

    arxiv_input = sys.argv[1]
    path, aid = download_arxiv_paper(arxiv_input)
    print(f"\n下载完成!")
    print(f"  ArXiv ID: {aid}")
    print(f"  解压路径: {path}")
