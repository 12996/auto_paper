"""
Paper 类 — PDF 论文解析。

合并自 chat_arxiv.py 和 chat_paper.py 中的重复 Paper 类。
"""

import io
import os

import fitz
from PIL import Image


class Paper:
    """
    PDF 论文对象，负责解析 PDF 文档的标题、章节和图片。

    Parameters
    ----------
    path : str
        PDF 文件路径。
    title : str, optional
        预设标题，为空时自动从 PDF 中提取。
    url : str, optional
        论文链接。
    abs : str, optional
        摘要文本。
    authers : list, optional
        作者列表。
    """

    def __init__(self, path: str, title: str = '', url: str = '', abs: str = '', authers: list = None):
        self.url = url
        self.path = path
        self.section_names = []
        self.section_texts = {}
        self.abs = abs
        self.title_page = 0
        self.authers = authers or []
        self.roman_num = ["I", "II", 'III', "IV", "V", "VI", "VII", "VIII", "IIX", "IX", "X"]
        self.digit_num = [str(d + 1) for d in range(10)]
        self.first_image = ''

        if title == '':
            self.pdf = fitz.open(self.path)
            self.title = self.get_title()
            self.parse_pdf()
        else:
            self.title = title
            self.parse_pdf()

    # -----------------------------------------------------------------
    # 解析入口
    # -----------------------------------------------------------------

    def parse_pdf(self):
        """解析 PDF，提取章节结构和文本内容。"""
        self.pdf = fitz.open(self.path)
        self.text_list = [page.get_text() for page in self.pdf]
        self.all_text = ' '.join(self.text_list)
        self.section_page_dict = self._get_all_page_index()
        print("section_page_dict", self.section_page_dict)
        self.section_text_dict = self._get_all_page()
        self.section_text_dict.update({"title": self.title})
        self.section_text_dict.update({"paper_info": self.get_paper_info()})
        self.pdf.close()

    # -----------------------------------------------------------------
    # 信息提取
    # -----------------------------------------------------------------

    def get_paper_info(self) -> str:
        """获取论文首页信息（去除摘要部分）。"""
        first_page_text = self.pdf[self.title_page].get_text()
        if "Abstract" in self.section_text_dict.keys():
            abstract_text = self.section_text_dict['Abstract']
        else:
            abstract_text = self.abs
        first_page_text = first_page_text.replace(abstract_text, "")
        return first_page_text

    def get_image_path(self, image_path: str = ''):
        """
        提取 PDF 中最大的图片并保存。

        Parameters
        ----------
        image_path : str
            图片保存目录。

        Returns
        -------
        tuple
            (图片路径, 扩展名) 或 (None, None)。
        """
        max_size = 0
        image_list = []
        ext = 'png'
        with fitz.Document(self.path) as my_pdf_file:
            for page_number in range(1, len(my_pdf_file) + 1):
                page = my_pdf_file[page_number - 1]
                for image_number, image in enumerate(page.get_images(), start=1):
                    xref_value = image[0]
                    base_image = my_pdf_file.extract_image(xref_value)
                    image_bytes = base_image["image"]
                    ext = base_image["ext"]
                    img = Image.open(io.BytesIO(image_bytes))
                    image_size = img.size[0] * img.size[1]
                    if image_size > max_size:
                        max_size = image_size
                    image_list.append(img)

        for img in image_list:
            image_size = img.size[0] * img.size[1]
            if image_size == max_size:
                image_name = f"image.{ext}"
                im_path = os.path.join(image_path, image_name)
                print("im_path:", im_path)

                max_pix = 480
                if img.size[0] > img.size[1]:
                    min_pix = int(img.size[1] * (max_pix / img.size[0]))
                    newsize = (max_pix, min_pix)
                else:
                    min_pix = int(img.size[0] * (max_pix / img.size[1]))
                    newsize = (min_pix, max_pix)
                img = img.resize(newsize)
                img.save(open(im_path, "wb"))
                return im_path, ext

        return None, None

    def get_chapter_names(self) -> list:
        """根据文本格式识别章节名称列表。"""
        doc = fitz.open(self.path)
        text_list = [page.get_text() for page in doc]
        all_text = ''
        for text in text_list:
            all_text += text

        chapter_names = []
        for line in all_text.split('\n'):
            if '.' in line:
                point_split_list = line.split('.')
                space_split_list = line.split(' ')
                if 1 < len(space_split_list) < 5:
                    if 1 < len(point_split_list) < 5 and (
                            point_split_list[0] in self.roman_num or point_split_list[0] in self.digit_num):
                        print("line:", line)
                        chapter_names.append(line)
                    elif 1 < len(point_split_list) < 5:
                        print("line:", line)
                        chapter_names.append(line)

        doc.close()
        return chapter_names

    def get_title(self) -> str:
        """从 PDF 中提取标题（基于最大字体检测）。"""
        doc = self.pdf
        max_font_size = 0
        max_font_sizes = [0]

        for page_index, page in enumerate(doc):
            text = page.get_text("dict")
            blocks = text["blocks"]
            for block in blocks:
                if block["type"] == 0 and len(block['lines']):
                    if len(block["lines"][0]["spans"]):
                        font_size = block["lines"][0]["spans"][0]["size"]
                        max_font_sizes.append(font_size)
                        if font_size > max_font_size:
                            max_font_size = font_size

        max_font_sizes.sort()
        print("max_font_sizes", max_font_sizes[-10:])

        cur_title = ''
        for page_index, page in enumerate(doc):
            text = page.get_text("dict")
            blocks = text["blocks"]
            for block in blocks:
                if block["type"] == 0 and len(block['lines']):
                    if len(block["lines"][0]["spans"]):
                        cur_string = block["lines"][0]["spans"][0]["text"]
                        font_size = block["lines"][0]["spans"][0]["size"]
                        if abs(font_size - max_font_sizes[-1]) < 0.3 or abs(font_size - max_font_sizes[-2]) < 0.3:
                            if len(cur_string) > 4 and "arXiv" not in cur_string:
                                if cur_title == '':
                                    cur_title += cur_string
                                else:
                                    cur_title += ' ' + cur_string
                            self.title_page = page_index

        title = cur_title.replace('\n', ' ')
        return title

    # -----------------------------------------------------------------
    # 内部方法
    # -----------------------------------------------------------------

    def _get_all_page_index(self) -> dict:
        """
        扫描 PDF，找到各章节名称与对应页码。
        
        改进版：通过分析字体大小来区分"标题"和"正文"，只对字体明显大于正文基准的行进行章节匹配，
        避免正文中出现同名词汇时（如在引用、摘要中提到"Method"）造成的误匹配。
        """
        section_list = [
            "Abstract",
            'Introduction', 'Related Work', 'Background',
            "Introduction and Motivation", "Computation Function", " Routing Function",
            "Preliminary", "Problem Formulation",
            'Methods', 'Methodology', "Method", 'Approach', 'Approaches',
            "Materials and Methods", "Experiment Settings",
            'Experiment', "Experimental Results", "Evaluation", "Experiments",
            "Results", 'Findings', 'Data Analysis',
            "Discussion", "Results and Discussion", "Conclusion",
            'References',
        ]

        # ------------------------------------------------------------------
        # 第一步：统计整篇 PDF 所有文字的字体大小，确定"正文基准字号"
        # 做法：收集所有 span 的 size，取中位数代表正文的普通字号
        # ------------------------------------------------------------------
        all_font_sizes = []
        for page in self.pdf:
            blocks = page.get_text("dict").get("blocks", [])
            for block in blocks:
                if block.get("type") != 0:   # 只处理文字类型的 block
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        size = span.get("size", 0)
                        if size > 0:
                            all_font_sizes.append(size)
        
        if all_font_sizes:
            all_font_sizes.sort()
            # 中位数作为正文字号基准
            body_font_size = all_font_sizes[len(all_font_sizes) // 2]
        else:
            body_font_size = 10.0  # 兜底默认值

        # 标题识别阈值：字体大小超过正文基准一定比例（此处取 5%，即基本确定是标题或副标题）
        heading_size_threshold = body_font_size * 1.05

        # ------------------------------------------------------------------
        # 第二步：逐页扫描，仅在"标题级文字"中匹配预设章节名称
        # ------------------------------------------------------------------
        section_page_dict = {}
        for page_index, page in enumerate(self.pdf):
            blocks = page.get_text("dict").get("blocks", [])
            for block in blocks:
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    # 取本行所有 span 的最大字体大小，代表这一行的字号
                    line_max_size = max(
                        (span.get("size", 0) for span in line.get("spans", [])),
                        default=0
                    )
                    # 只处理字号明显大于正文基准的行（即视觉上的"标题行"）
                    if line_max_size < heading_size_threshold:
                        continue

                    # 合并本行所有 span 的文本并清理首尾空白
                    line_text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
                    if not line_text:
                        continue

                    # 在已识别的"标题行"中检查是否匹配预设的章节名称列表
                    for section_name in section_list:
                        # 只记录第一次出现的页码，避免后文引用覆盖
                        if section_name in section_page_dict:
                            continue
                        # 精确匹配（整行等于章节名）或者以章节名开头（如 "III. Method"）
                        if (line_text == section_name or
                                line_text.upper() == section_name.upper() or
                                line_text.startswith(section_name) or
                                line_text.upper().startswith(section_name.upper())):
                            section_page_dict[section_name] = page_index

        # ------------------------------------------------------------------
        # 第三步：按页码排序，保证 _get_all_page 中 start/end 计算始终递进
        # ------------------------------------------------------------------
        sorted_list = sorted(section_page_dict.items(), key=lambda x: x[1])
        return dict(sorted_list)

    def _get_all_page(self) -> dict:
        """
        获取 PDF 中每个章节的文本内容。

        Returns
        -------
        dict
            章节名 -> 章节文本。
        """
        section_dict = {}
        text_list = [page.get_text() for page in self.pdf]

        for sec_index, sec_name in enumerate(self.section_page_dict):
            if sec_index <= 0 and self.abs:
                continue

            start_page = self.section_page_dict[sec_name]
            if sec_index < len(list(self.section_page_dict.keys())) - 1:
                end_page = self.section_page_dict[list(self.section_page_dict.keys())[sec_index + 1]]
            else:
                end_page = len(text_list)

            print("start_page, end_page:", start_page, end_page)
            cur_sec_text = ''

            if end_page - start_page == 0:
                if sec_index < len(list(self.section_page_dict.keys())) - 1:
                    next_sec = list(self.section_page_dict.keys())[sec_index + 1]
                    if text_list[start_page].find(sec_name) == -1:
                        start_i = text_list[start_page].find(sec_name.upper())
                    else:
                        start_i = text_list[start_page].find(sec_name)
                    if text_list[start_page].find(next_sec) == -1:
                        end_i = text_list[start_page].find(next_sec.upper())
                    else:
                        end_i = text_list[start_page].find(next_sec)
                    cur_sec_text += text_list[start_page][start_i:end_i]
            else:
                for page_i in range(start_page, end_page):
                    if page_i == start_page:
                        if text_list[start_page].find(sec_name) == -1:
                            start_i = text_list[start_page].find(sec_name.upper())
                        else:
                            start_i = text_list[start_page].find(sec_name)
                        cur_sec_text += text_list[page_i][start_i:]
                    elif page_i < end_page:
                        cur_sec_text += text_list[page_i]
                    elif page_i == end_page:
                        if sec_index < len(list(self.section_page_dict.keys())) - 1:
                            next_sec = list(self.section_page_dict.keys())[sec_index + 1]
                            if text_list[start_page].find(next_sec) == -1:
                                end_i = text_list[start_page].find(next_sec.upper())
                            else:
                                end_i = text_list[start_page].find(next_sec)
                            cur_sec_text += text_list[page_i][:end_i]

            section_dict[sec_name] = cur_sec_text.replace('-\n', '').replace('\n', ' ')

        return section_dict


if __name__ == "__main__":
    paper = Paper("./2602.02257.pdf")
    paper.parse_pdf()
    print(paper.section_page_dict)
    print(paper.get_all_page())
