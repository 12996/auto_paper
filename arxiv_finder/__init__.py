# core/ — ChatPaper 核心可复用模块
#
# 提供论文爬取、PDF 解析、LLM 调用、总结和翻译的独立接口。
#
# 用法示例:
#   from core.config import AppConfig
#   from core.paper import Paper
#   from core.llm_client import LLMClient
#   from core.crawler import ArxivWebCrawler
#   from core.summarizer import PaperSummarizer
#   from core.translator import PaperTranslator
#
# 按需导入各子模块，避免不必要的依赖加载。
