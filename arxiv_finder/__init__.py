# core/ — ChatPaper 核心可复用模块
#
# 提供论文爬取、PDF 解析、LLM 调用、总结和翻译的独立接口。
#
# 用法示例:
#   from arxiv_finder.config import AppConfig
#   from arxiv_finder.paper import Paper
#   from llm_client import LLMClient
#   from arxiv_finder.crawler import ArxivWebCrawler
#   from arxiv_finder.summarizer import PaperSummarizer
#   from arxiv_finder.translator import PaperTranslator
#
# 按需导入各子模块，避免不必要的依赖加载。
