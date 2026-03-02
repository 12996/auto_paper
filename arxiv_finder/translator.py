"""
论文翻译模块 — 使用 LLM 对论文进行翻译/润色。

迁移自 chat_translate.py 的核心逻辑。
"""

import os
import re
import sys
from typing import Optional

import tenacity

from core.llm_client import LLMClient, LLMResponse
from core.utils import LazyloadTiktoken


# =============================================================================
# 论文翻译器
# =============================================================================

class PaperTranslator:
    """
    使用 LLM 对 PDF 论文进行逐章节翻译或润色。

    Parameters
    ----------
    llm_client : LLMClient
        统一 LLM 调用客户端。
    """

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client
        self.tokenizer = LazyloadTiktoken("gpt-3.5-turbo")

    # -----------------------------------------------------------------
    # 公共接口
    # -----------------------------------------------------------------

    def translate_paper(self, pdf_path: str, output_path: str = './',
                        task: str = "翻译") -> str:
        """
        翻译整篇 PDF 论文并输出为 Markdown 文件。

        Parameters
        ----------
        pdf_path : str
            PDF 文件路径。
        output_path : str
            输出目录。
        task : str
            任务类型："翻译" 或 "润色"。

        Returns
        -------
        str
            生成的 Markdown 文件路径。
        """
        paper_pdf = self._parse_pdf(pdf_path)
        md_file = os.path.join(output_path, os.path.basename(pdf_path).replace(".pdf", '.md'))
        md_str = "\n"
        token_consumed = 0
        session_id = None

        # 判断论文领域
        domains = ""
        if "title" in paper_pdf and "abstract" in paper_pdf:
            text = "Title:" + paper_pdf['title'] + "Abstract:" + paper_pdf['abstract']
            result = self.check_domain(text)
            domains = result.result
            token_consumed += result.total_tokens

        print("Paper domain:", domains)

        # 翻译标题
        if "title" in paper_pdf:
            resp = self._translate_part(paper_pdf['title'], title=True, domain=domains,
                                        session_id=session_id)
            md_str += resp.result + "\n\n"
            session_id = resp.session_id or session_id
            token_consumed += resp.total_tokens

        with open(md_file, 'w', encoding="utf-8") as f:
            f.write(md_str)

        # 翻译摘要
        if "abstract" in paper_pdf:
            text = "Section Name:Abstract\n Section text:" + paper_pdf['abstract']
            resp = self._translate_part(text, domain=domains, task=task, session_id=session_id)
            session_id = resp.session_id or session_id
            cur_str = "\n" + resp.result + "\n"
            token_consumed += resp.total_tokens
            with open(md_file, 'a', encoding="utf-8") as f:
                f.write(cur_str)

        # 翻译各章节
        for section_index, section_name in enumerate(paper_pdf.get('section_names', [])):
            print(section_index, section_name)
            section_text = paper_pdf['section_texts'][section_index]
            if len(section_text) > 0:
                text = "Section Name:" + section_name + "\n Section text:" + section_text
                resp = self._translate_part(text, domain=domains, task=task, session_id=session_id)
                session_id = resp.session_id or session_id
                cur_str = "\n" + resp.result + "\n"
                token_consumed += resp.total_tokens

                # 修复 ## 格式
                pattern = r'([^\\n])##([^\\n]{1,18}\W+)'
                cur_str = re.sub(pattern, r'\1\n##\2', cur_str)

                with open(md_file, 'a', encoding="utf-8") as f:
                    f.write(cur_str)

        print(f"Total tokens consumed: {token_consumed}")
        return md_file

    def check_domain(self, text: str, session_id=None) -> LLMResponse:
        """
        根据标题和摘要判断论文领域。

        Parameters
        ----------
        text : str
            标题 + 摘要文本。

        Returns
        -------
        LLMResponse
        """
        messages = [
            {"role": "system",
             "content": "You are now a professional Science and technology editor"},
            {"role": "assistant",
             "content": "Your task is to judge the subject and domain of the paper based on the title and abstract of the paper, and your output should not exceed five words!"},
            {"role": "user", "content": "Input Contents:" + text},
        ]
        return self.llm.chat(messages, session_id=session_id)

    # -----------------------------------------------------------------
    # 内部方法
    # -----------------------------------------------------------------

    @tenacity.retry(wait=tenacity.wait_exponential(multiplier=1, min=4, max=10),
                    stop=tenacity.stop_after_attempt(8),
                    reraise=True)
    def _translate_part(self, text: str, title: bool = False, domain: str = "",
                        task: str = "翻译", session_id=None) -> LLMResponse:
        """翻译论文的一个部分。"""
        if title:
            messages = [
                {"role": "system",
                 "content": "You are now a professional Science and technology editor"},
                {"role": "assistant",
                 "content": "Your task now is to translate title of the paper, the paper is about " + domain},
                {"role": "user", "content": "Input Contents:" + text + """
                你需要把输入的标题，翻译成中文，且加上原标题。
                注意，一些专业的词汇，或者缩写，还是需要保留为英文。
                输出中文翻译部分的时候，只保留翻译的标题，不要有任何其他的多余内容，不要重复，不要解释。
                输出原标题的时候，完整输出即可，不要多也不要少。
                你的输出格式如下：
                Output format is (你需要根据上面的要求，xxx是中文翻译的占位符，yyy是英文原标题的占位符，你需要将内容填充进去):
                \\n

                # xxx

                ## yyy
                \\n

                """},
            ]
        else:
            messages = [
                {"role": "system",
                 "content": "You are a professional academic paper translator."},
                {"role": "assistant",
                 "content": f"Your task now is to {task} the Input Contents, which a section, part of a paper, the paper is about {domain}"},
                {"role": "user", "content": f"""
                你的任务是口语化{task}输入的论文章节，{task}的内容要遵循下面的要求：
                1. 在保证术语严谨的同时，文字表述需要更加口语化。
                2. 需要地道的中文{task}，逻辑清晰且连贯，少用倒装句式。
                3. 对于简短的Input Contents，不要画蛇添足，增加多余的解释和扩展。
                4. 对于本领域的专业术语，需要标注英文，便于读者参考。这篇论文的领域是{domain}。
                5. 适当使用MarkDown语法，比如有序列表、加粗等。

                你的输出内容格式需要遵循下面的要求：
                1. ## 章节名称，中文{task}(Original English section name)
                2. 章节内容的{task}

                Output format is (你需要根据上面的要求，自动填充xxx和yyy的占位符):
                \\n

                ## xxx

                yyy
                \\n

                Input include section name and section text, Input Contents: {text}
                """},
            ]
        return self.llm.chat(messages, session_id=session_id)

    @staticmethod
    def _parse_pdf(path: str) -> dict:
        """使用 scipdf 解析 PDF 论文。"""
        import scipdf
        try:
            pdf = scipdf.parse_pdf_to_dict(path, as_list=False)
            pdf['authors'] = pdf['authors'].split('; ')
            pdf['section_names'] = [it['heading'] for it in pdf['sections']]
            pdf['section_texts'] = [it['text'] for it in pdf['sections']]
        except Exception as e:
            print("parse_pdf_to_dict error:", e)
            exc_type, exc_obj, exc_tb = sys.exc_info()
            if exc_tb:
                fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
                print(exc_type, fname, exc_tb.tb_lineno)
            pdf = {}
        return pdf
