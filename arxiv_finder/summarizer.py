"""
论文总结模块 — 使用 LLM 对论文进行结构化总结。

合并自 chat_arxiv.py 和 chat_paper.py 中的 Reader 总结逻辑。
"""

import datetime
import os
import sys
from dataclasses import dataclass, field
from typing import List

import tiktoken

from llm_client import LLMClient
from arxiv_finder.paper import Paper
from arxiv_finder.utils import validate_title, export_to_markdown


# =============================================================================
# 数据类
# =============================================================================

@dataclass
class SummaryResult:
    """单篇论文的总结结果。"""
    summary_text: str = ''
    method_text: str = ''
    conclusion_text: str = ''


# =============================================================================
# 论文总结器
# =============================================================================

class PaperSummarizer:
    """
    使用 LLM 对论文进行三步总结：概要 → 方法 → 结论。

    Parameters
    ----------
    llm_client : LLMClient
        统一 LLM 调用客户端。
    key_word : str
        用户的研究领域关键词。
    language : str
        输出语言，'zh' 或 'en'。
    max_token_num : int
        最大 token 数限制。
    """

    def __init__(self, llm_client: LLMClient, key_word: str = '',
                 language: str = 'zh', max_token_num: int = 4096):
        self.llm = llm_client
        self.key_word = key_word
        self.language = 'Chinese' if language == 'zh' else 'English'
        self.max_token_num = max_token_num
        self.encoding = tiktoken.get_encoding("gpt2")

    # -----------------------------------------------------------------
    # 公共接口
    # -----------------------------------------------------------------

    def summarize(self, paper: Paper) -> SummaryResult:
        """
        对单篇论文进行完整的三步总结。

        Returns
        -------
        SummaryResult
        """
        result = SummaryResult()

        # Step 1: Summary
        text = self._build_summary_text(paper)
        try:
            result.summary_text = self._chat_summary(text)
        except Exception as e:
            print("summary_error:", e)
            self._print_exception()
            if "maximum context" in str(e):
                token_offset = self._extract_token_offset(e)
                result.summary_text = self._chat_summary(
                    text, summary_prompt_token=token_offset + 1000 + 150
                )

        # Step 2: Method
        method_key = self._find_section_key(paper, ['method', 'approach'])
        if method_key:
            text = "<summary>" + result.summary_text + "\n\n<Methods>:\n\n" + paper.section_text_dict[method_key]
            try:
                result.method_text = self._chat_method(text)
            except Exception as e:
                print("method_error:", e)
                self._print_exception()
                if "maximum context" in str(e):
                    token_offset = self._extract_token_offset(e)
                    result.method_text = self._chat_method(
                        text, method_prompt_token=token_offset + 800 + 150
                    )

        # Step 3: Conclusion
        conclusion_key = self._find_section_key(paper, ['conclu'])
        summary_text = "<summary>" + result.summary_text + "\n <Method summary>:\n" + result.method_text
        if conclusion_key:
            text = summary_text + "\n\n<Conclusion>:\n\n" + paper.section_text_dict[conclusion_key]
        else:
            text = summary_text
        try:
            result.conclusion_text = self._chat_conclusion(text)
        except Exception as e:
            print("conclusion_error:", e)
            self._print_exception()
            if "maximum context" in str(e):
                token_offset = self._extract_token_offset(e)
                result.conclusion_text = self._chat_conclusion(
                    text, conclusion_prompt_token=token_offset + 800 + 150
                )

        return result

    def summarize_batch(self, papers: List[Paper], export_dir: str = './export',
                        query: str = '', file_format: str = 'md') -> None:
        """
        批量总结论文并导出到文件。

        Parameters
        ----------
        papers : list[Paper]
            论文列表。
        export_dir : str
            导出目录。
        query : str
            搜索查询（用于文件名）。
        file_format : str
            输出格式，'md' 或 'txt'。
        """
        for paper_index, paper in enumerate(papers):
            print(f"\n{'=' * 60}")
            print(f"Processing Paper {paper_index + 1}: {paper.title}")
            print('=' * 60)

            result = self.summarize(paper)

            # 组装 Markdown
            htmls = []
            htmls.append('## Paper:' + str(paper_index + 1))
            if result.summary_text:
                htmls.append(result.summary_text)
            htmls.append('\n\n\n')
            if result.method_text:
                htmls.append(result.method_text)
            htmls.append("\n" * 4)
            if result.conclusion_text:
                htmls.append(result.conclusion_text)
            htmls.append("\n" * 4)

            # 写文件
            os.makedirs(export_dir, exist_ok=True)
            date_str = str(datetime.datetime.now())[:13].replace(' ', '-')
            file_label = validate_title(query or paper.title[:80])
            file_name = os.path.join(export_dir, f"{date_str}-{file_label}.{file_format}")
            mode = 'w' if paper_index == 0 else 'a'
            export_to_markdown("\n".join(htmls), file_name=file_name, mode=mode)

    # -----------------------------------------------------------------
    # LLM Chat 方法
    # -----------------------------------------------------------------

    def _clip_text(self, text: str, prompt_token: int) -> str:
        """
        根据大模型的 Token 上限，按比例裁剪输入的超长文本。
        
        工作原理（比例截断法）：
        1. 由于使用 tiktoken 逐个 Token 裁剪并解码回字符串非常耗时，这里采用了一种基于字符长度和 Token 数量比例的快速估算方法。
        2. 计算目标最大可用 Token 数：max_token_num（模型支持的最大 Token 数） - prompt_token（Prompt 提示词预留的 Token 数，例如 System Msg 和固定指令）。
        3. 根据当前文本的 字符长度 / Token 数量 的比例，估算出目标 Token 数量对应的字符索引。
        4. 直接使用字符串切片截取文本前部，舍弃溢出部分。

        Parameters
        ----------
        text : str
            需要被裁剪的原文（例如整篇论文或某个超长章节）。
        prompt_token : int
            为指令提示词（Prompt / System Message 等）预留的安全 Token 阈值，需保留这部分空间给 AI 理解任务。

        Returns
        -------
        str
            裁剪后符合模型 Context 限制的文本（保留了原文前半部分）。
        """
        # 第一步：计算输入原文的实际 Token 数量 (基于 gpt2 的 encoding，作为通用英文估算)
        text_token = len(self.encoding.encode(text))
        if text_token == 0:
            text_token = 1
            
        # 第二步：按比例估算截断位置
        # (self.max_token_num - prompt_token) = 正文能够占据的剩余安全 Token数
        # len(text) / text_token = 平均每个 Token 包含多少个字符
        # 二者相乘，计算出能够容纳的安全字符长度索引
        clip_index = int(len(text) * (self.max_token_num - prompt_token) / text_token)
        
        # 第三步：利用字符串切片保留前半部分
        return text[:clip_index]

    def _chat_summary(self, text: str, summary_prompt_token: int = 1100) -> str:
        clip_text = self._clip_text(text, summary_prompt_token)
        messages = [
            {"role": "system",
             "content": f"You are a researcher in the field of [{self.key_word}] who is good at summarizing papers using concise statements. You MUST NOT attempt to fetch any URLs. All necessary information is provided in the text."},
            {"role": "user", "content": f"This is the title, author, link, abstract and introduction of an English document. I need your help to read and summarize the following questions based ONLY on the provided text:\n\n<document>\n{clip_text}\n</document>\n\n" + """
                 1. Mark the title of the paper (with Chinese translation)
                 2. list all the authors' names (use English)
                 3. mark the first author's affiliation (output {} translation only)
                 4. mark the keywords of this article (use English)
                 5. link to the paper, Github code link (if available, fill in Github:None if not)
                 6. summarize according to the following four points.Be sure to use {} answers (proper nouns need to be marked in English)
                    - (1):What is the research background of this article?
                    - (2):What are the past methods? What are the problems with them? Is the approach well motivated?
                    - (3):What is the research methodology proposed in this paper?
                    - (4):On what task and what performance is achieved by the methods in this paper? Can the performance support their goals?
                 Follow the format of the output that follows:
                 1. Title: xxx\n\n
                 2. Authors: xxx\n\n
                 3. Affiliation: xxx\n\n
                 4. Keywords: xxx\n\n
                 5. Urls: xxx or xxx , xxx \n\n
                 6. Summary: \n\n
                    - (1):xxx;\n
                    - (2):xxx;\n
                    - (3):xxx;\n
                    - (4):xxx.\n\n

                 Be sure to use {} answers (proper nouns need to be marked in English), statements as concise and academic as possible, do not have too much repetitive information, numerical values using the original numbers, be sure to strictly follow the format, the corresponding content output to xxx, in accordance with \n line feed.
                 """.format(self.language, self.language, self.language)},
        ]
        return self.llm.chat(messages)

    def _chat_method(self, text: str, method_prompt_token: int = 800) -> str:
        clip_text = self._clip_text(text, method_prompt_token)
        messages = [
            {"role": "system",
             "content": f"You are a researcher in the field of [{self.key_word}] who is good at summarizing papers using concise statements. You MUST NOT attempt to fetch any URLs. All necessary information is provided in the text."},
            {"role": "user", "content": f"This is the <summary> and <Method> part of an English document, where <summary> you have summarized, but the <Methods> part, I need your help to read and summarize the following questions based ONLY on the provided text:\n\n<document>\n{clip_text}\n</document>\n\n" + """
                 7. Describe in detail the methodological idea of this article. Be sure to use {} answers (proper nouns need to be marked in English). For example, its steps are.
                    - (1):...
                    - (2):...
                    - (3):...
                    - .......
                 Follow the format of the output that follows:
                 7. Methods: \n\n
                    - (1):xxx;\n
                    - (2):xxx;\n
                    - (3):xxx;\n
                    ....... \n\n

                 Be sure to use {} answers (proper nouns need to be marked in English), statements as concise and academic as possible, do not repeat the content of the previous <summary>, the value of the use of the original numbers, be sure to strictly follow the format, the corresponding content output to xxx, in accordance with \n line feed, ....... means fill in according to the actual requirements, if not, you can not write.
                 """.format(self.language, self.language)},
        ]
        return self.llm.chat(messages)

    def _chat_conclusion(self, text: str, conclusion_prompt_token: int = 800) -> str:
        clip_text = self._clip_text(text, conclusion_prompt_token)
        messages = [
            {"role": "system",
             "content": f"You are a reviewer in the field of [{self.key_word}] and you need to critically review this article. You MUST NOT attempt to fetch any URLs. All necessary information is provided in the text."},
            {"role": "user", "content": f"This is the <summary> and <conclusion> part of an English literature, where <summary> you have already summarized, but <conclusion> part, I need your help to summarize the following questions based ONLY on the provided text:\n\n<document>\n{clip_text}\n</document>\n\n" + """
                 8. Make the following summary.Be sure to use {} answers (proper nouns need to be marked in English).
                    - (1):What is the significance of this piece of work?
                    - (2):Summarize the strengths and weaknesses of this article in three dimensions: innovation point, performance, and workload.
                    .......
                 Follow the format of the output later:
                 8. Conclusion: \n\n
                    - (1):xxx;\n
                    - (2):Innovation point: xxx; Performance: xxx; Workload: xxx;\n

                 Be sure to use {} answers (proper nouns need to be marked in English), statements as concise and academic as possible, do not repeat the content of the previous <summary>, the value of the use of the original numbers, be sure to strictly follow the format, the corresponding content output to xxx, in accordance with \n line feed, ....... means fill in according to the actual requirements, if not, you can not write.
                 """.format(self.language, self.language)},
        ]
        return self.llm.chat(messages)

    # -----------------------------------------------------------------
    # 辅助方法
    # -----------------------------------------------------------------

    @staticmethod
    def _build_summary_text(paper: Paper) -> str:
        """构建用于首次总结的文本（标题+URL+摘要+论文信息+引言）。"""
        text = ''
        text += 'Title:' + paper.title
        text += 'Url:' + paper.url
        text += 'Abstract:' + paper.abs
        text += 'Paper_info:' + paper.section_text_dict.get('paper_info', '')
        # 取第一个 section 的内容（通常是 Introduction）
        section_values = list(paper.section_text_dict.values())
        if section_values:
            text += section_values[0]
        return text

    @staticmethod
    def _find_section_key(paper: Paper, keywords: list) -> str:
        """在论文章节中查找匹配关键词的 section key。"""
        for parse_key in paper.section_text_dict.keys():
            for kw in keywords:
                if kw in parse_key.lower():
                    return parse_key
        return ''

    @staticmethod
    def _extract_token_offset(e: Exception) -> int:
        """从 token 超限异常中提取 offset。"""
        try:
            msg = str(e)
            idx = msg.find("your messages resulted in") + len("your messages resulted in") + 1
            return int(msg[idx:idx + 4])
        except (ValueError, IndexError):
            return 0

    @staticmethod
    def _print_exception():
        exc_type, exc_obj, exc_tb = sys.exc_info()
        if exc_tb:
            fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
            print(exc_type, fname, exc_tb.tb_lineno)
