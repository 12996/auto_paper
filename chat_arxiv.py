"""
chat_arxiv.py — 通过 arXiv 网页搜索论文并使用 LLM 生成总结。

重构后使用 core/ 模块，保持命令行接口完全兼容。
"""

import argparse
import os
import sys
from collections import namedtuple

from arxiv_finder.config import AppConfig
from arxiv_finder.llm_client import LLMClient
from arxiv_finder.crawler import ArxivWebCrawler
from arxiv_finder.summarizer import PaperSummarizer


# =============================================================================
# 命令行参数结构
# =============================================================================

ArxivParams = namedtuple(
    "ArxivParams",
    [
        "query",
        "key_word",
        "page_num",
        "max_results",
        "days",
        "sort",
        "save_image",
        "file_format",
        "language",
    ],
)


# =============================================================================
# 主函数
# =============================================================================

def chat_arxiv_main(args):
    """使用 arXiv 网页搜索论文并生成 LLM 总结。"""
    config = AppConfig()
    llm = LLMClient(config)

    # 爬取论文
    crawler = ArxivWebCrawler(root_path='./')
    paper_list = crawler.search(
        query=args.query,
        page_num=args.page_num,
        days=args.days,
        max_results=args.max_results,
    )
    print("paper_url:", [paper.url for paper in paper_list])
    max_token_num = 81920
    # 总结论文
    summarizer = PaperSummarizer(
        llm_client=llm,
        key_word=args.key_word,
        language=args.language,
        max_token_num=max_token_num,
    )
    export_path = os.path.join('./', 'export')
    summarizer.summarize_batch(
        papers=paper_list,
        export_dir=export_path,
        query=args.query,
        file_format=args.file_format,
    )


# =============================================================================
# 命令行入口
# =============================================================================

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='ChatPaper Arxiv 论文搜索与摘要生成工具')

    parser.add_argument("--query", type=str, default='traffic flow prediction',
                        help="Arxiv 搜索查询字符串。支持语法：ti:标题搜索, au:作者搜索, all:全文搜索")
    parser.add_argument("--key_word", type=str, default='GPT robot',
                        help="用户的研究领域关键词，用于指导 AI 生成更专业的摘要")
    parser.add_argument("--page_num", type=int, default=2,
                        help="要搜索的 Arxiv 结果页数，每页约 50 篇论文")
    parser.add_argument("--max_results", type=int, default=3,
                        help="最终要生成摘要的论文数量上限")
    parser.add_argument("--days", type=int, default=10,
                        help="只搜索最近 N 天内发布的论文")
    parser.add_argument("--sort", type=str, default="web",
                        help="搜索结果排序方式（可选：web 或 LastUpdatedDate）")
    parser.add_argument("--save_image", default=False, action="store_true",
                        help="是否从 PDF 提取图片并保存到图床（需要配置 Gitee API）")
    parser.add_argument("--file_format", type=str, default='md',
                        help="输出文件格式（md: Markdown, txt: 纯文本）")
    parser.add_argument("--language", type=str, default='zh',
                        help="摘要输出语言（zh: 中文, en: 英文）")

    arxiv_args = ArxivParams(**vars(parser.parse_args()))

    import time
    start_time = time.time()
    chat_arxiv_main(args=arxiv_args)
    print("summary time:", time.time() - start_time)
