# -*- coding: utf-8 -*-
"""
================================================================================
latex_processor/latex_toolbox.py
================================================================================
Latex 处理工具箱


【功能列表】
┌─────────────────────────────────────────────────────────────────────────────┐
│ 常量定义                                                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ PRESERVE = 0          # 标记该部分保留，不进行翻译                           │
│ TRANSFORM = 1         # 标记该部分需要翻译                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│ 数据结构                                                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ LinkedListNode        # 链表节点，用于表示切分后的 Latex 片段                │
│   - string: str       # 节点内容                                             │
│   - preserve: bool    # 是否保留（不翻译）                                   │
│   - next: Node        # 下一个节点                                           │
│   - range: list       # 行号范围 [start, end]                                │
├─────────────────────────────────────────────────────────────────────────────┤
│ 切分相关函数 (第153-276行)                                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│ set_forbidden_text()           # 标记保留区域（正则匹配）                     │
│ reverse_forbidden_text()       # 反向标记（从保留区移出）                     │
│ set_forbidden_text_careful_brace()  # 带括号计数的保留标记                   │
│ reverse_forbidden_text_careful_brace() # 带括号计数的反向标记               │
│ set_forbidden_text_begin_end() # 处理 begin-end 环境                        │
│ convert_to_linklist()          # 将文本和掩码转为链表                        │
│ post_process()                 # 后处理（修复括号、合并短句）                │
├─────────────────────────────────────────────────────────────────────────────┤
│ 文件合并函数 (第285-515行)                                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│ find_main_tex_file()    # 在多文件中找到主 tex 文件                          │
│ rm_comments()           # 移除 Latex 注释                                    │
│ find_tex_file_ignore_case() # 忽略大小写查找 tex 文件                        │
│ merge_tex_files_()      # 递归合并 tex 文件（处理 \input）                   │
│ find_title_and_abs()    # 提取标题和摘要                                     │
│ merge_tex_files()       # 合并入口，添加 ctex 支持中文                       │
│ insert_abstract()       # 插入缺失的摘要                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ 后处理函数 (第524-593行)                                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ fix_content()           # 修复 GPT 翻译常见错误                              │
│ compile_latex_with_timeout() # 带超时的 Latex 编译                           │
├─────────────────────────────────────────────────────────────────────────────┤
│ PDF 合并函数 (第646-907行)                                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│ _merge_pdfs()           # PDF 合并入口                                       │
│ _merge_pdfs_ng()        # 新版 PDF 合并（保留链接）                          │
│ _merge_pdfs_legacy()    # 旧版 PDF 合并                                      │
│ merge_pdfs()            # 子进程包装（避免内存泄漏）                         │
└─────────────────────────────────────────────────────────────────────────────┘
================================================================================
"""

import glob
import os
import re
import shutil
import subprocess
import multiprocessing
import numpy as np
from loguru import logger
from typing import Optional, Tuple, List

# ============================================================================
# 常量定义
# ============================================================================

PRESERVE = 0   # 保留，不翻译
TRANSFORM = 1  # 需要翻译

# 路径拼接快捷函数
pj = os.path.join


# ============================================================================
# 数据结构
# ============================================================================

class LinkedListNode:
    """
    链表节点 - 用于表示切分后的 Latex 文本片段


    Attributes:
        string: 节点包含的文本内容
        preserve: True 表示保留不翻译，False 表示需要翻译
        next: 指向下一个节点的指针
        range: 该节点在原文中的行号范围 [start_line, end_line]
    """

    def __init__(self, string: str, preserve: bool = True) -> None:
        self.string = string
        self.preserve = preserve
        self.next: Optional['LinkedListNode'] = None
        self.range: Optional[List[int]] = None


# ============================================================================
# 切分相关函数
# ============================================================================

def convert_to_linklist(text: str, mask: np.ndarray) -> LinkedListNode:
    """
    将文本和掩码转换为链表结构

    Args:
        text: 完整的 Latex 文本
        mask: 与文本等长的掩码数组，PRESERVE(0) 表示保留，TRANSFORM(1) 表示翻译

    Returns:
        链表的头节点

    说明:
        遍历文本和掩码，根据掩码值创建链表节点。
        连续相同掩码值的字符合并到同一节点。
    """
    root = LinkedListNode("", preserve=True)
    current_node = root

    for c, m, i in zip(text, mask, range(len(text))):
        if (m == PRESERVE and current_node.preserve) or (
            m == TRANSFORM and not current_node.preserve
        ):
            # 追加到当前节点
            current_node.string += c
        else:
            # 创建新节点
            current_node.next = LinkedListNode(c, preserve=(m == PRESERVE))
            current_node = current_node.next

    return root


def post_process(root: LinkedListNode) -> LinkedListNode:
    """
    后处理链表 - 修复常见问题

    处理步骤:
        1. 修复括号不匹配问题
        2. 屏蔽空行和过短的句子（<42字符）
        3. 合并相邻的保留节点
        4. 处理前后的换行符
        5. 标注节点的行号范围

    Args:
        root: 链表头节点

    Returns:
        处理后的链表头节点
    """
    # -------- 1. 修复括号 --------
    node = root
    while True:
        string = node.string
        if node.preserve:
            node = node.next
            if node is None:
                break
            continue

        def break_check(string):
            """检查括号是否匹配，返回第一个不匹配的位置"""
            str_stack = [""]
            for i, c in enumerate(string):
                if c == "{":
                    str_stack.append("{")
                elif c == "}":
                    if len(str_stack) == 1:
                        logger.warning("fixing brace error")
                        return i
                    str_stack.pop(-1)
                else:
                    str_stack[-1] += c
            return -1

        bp = break_check(string)

        if bp == -1:
            pass
        elif bp == 0:
            node.string = string[:1]
            q = LinkedListNode(string[1:], False)
            q.next = node.next
            node.next = q
        else:
            node.string = string[:bp]
            q = LinkedListNode(string[bp:], False)
            q.next = node.next
            node.next = q

        node = node.next
        if node is None:
            break

    # -------- 2. 屏蔽空行和短句 --------
    node = root
    while True:
        if len(node.string.strip("\n").strip("")) == 0:
            node.preserve = True
        if len(node.string.strip("\n").strip("")) < 35:
            node.preserve = True
        node = node.next
        if node is None:
            break

    # -------- 3. 合并相邻保留节点 --------
    node = root
    while True:
        if node.next and node.preserve and node.next.preserve:
            node.string += node.next.string
            node.next = node.next.next
        node = node.next
        if node is None:
            break

    # -------- 4. 处理前后断行符 --------
    node = root
    prev_node = None
    while True:
        if not node.preserve:
            lstriped_ = node.string.lstrip().lstrip("\n")
            if (
                (prev_node is not None)
                and (prev_node.preserve)
                and (len(lstriped_) != len(node.string))
            ):
                prev_node.string += node.string[: -len(lstriped_)]
                node.string = lstriped_
            rstriped_ = node.string.rstrip().rstrip("\n")
            if (
                (node.next is not None)
                and (node.next.preserve)
                and (len(rstriped_) != len(node.string))
            ):
                node.next.string = node.string[len(rstriped_) :] + node.next.string
                node.string = rstriped_
        # =-=-=
        prev_node = node
        node = node.next
        if node is None:
            break

    # -------- 5. 标注行号范围 --------
    node = root
    n_line = 0
    expansion = 2
    while True:
        n_l = node.string.count("\n")
        node.range = [n_line - expansion, n_line + n_l + expansion]
        n_line = n_line + n_l
        node = node.next
        if node is None:
            break

    return root


def set_forbidden_text(text: str, mask: np.ndarray, pattern, flags=0) -> Tuple[str, np.ndarray]:
    """
    标记保留区域 - 将匹配的文本标记为 PRESERVE

    用法示例:
        # 保留所有 algorithm 环境
        text, mask = set_forbidden_text(text, mask, r"\\begin\{algorithm\}(.*?)\\end\{algorithm\}", re.DOTALL)

    Args:
        text: 完整文本
        mask: 掩码数组
        pattern: 正则表达式（字符串或列表）
        flags: 正则标志

    Returns:
        (text, mask): 处理后的文本和掩码
    """
    if isinstance(pattern, list):
        pattern = "|".join(pattern)
    pattern_compile = re.compile(pattern, flags)
    for res in pattern_compile.finditer(text):
        mask[res.span()[0] : res.span()[1]] = PRESERVE
    return text, mask


def reverse_forbidden_text(text: str, mask: np.ndarray, pattern, flags=0, forbid_wrapper: bool = True) -> Tuple[str, np.ndarray]:
    """
    反向标记 - 将匹配的文本标记为 TRANSFORM（可翻译）

    用法示例:
        # 将 abstract 环境中的内容标记为可翻译（但保留 \\begin{abstract} 和 \\end{abstract}）
        text, mask = reverse_forbidden_text(text, mask, r"\\begin\{abstract\}(.*?)\\end\{abstract\}", re.DOTALL)

    Args:
        text: 完整文本
        mask: 掩码数组
        pattern: 正则表达式
        flags: 正则标志
        forbid_wrapper: 是否保留包装标签（如 \\begin{abstract}）

    Returns:
        (text, mask): 处理后的文本和掩码
    """
    if isinstance(pattern, list):
        pattern = "|".join(pattern)
    pattern_compile = re.compile(pattern, flags)
    for res in pattern_compile.finditer(text):
        if not forbid_wrapper:
            mask[res.span()[0] : res.span()[1]] = TRANSFORM
        else:
            mask[res.regs[0][0] : res.regs[1][0]] = PRESERVE  # '\\begin{abstract}'
            mask[res.regs[1][0] : res.regs[1][1]] = TRANSFORM  # abstract content
            mask[res.regs[1][1] : res.regs[0][1]] = PRESERVE  # '\\end{abstract}'
    return text, mask


def set_forbidden_text_careful_brace(text: str, mask: np.ndarray, pattern: str, flags=0) -> Tuple[str, np.ndarray]:
    """
    带括号计数的保留标记 - 处理嵌套花括号


    用法示例:
        # 保留 \\hl{...} 中的内容，正确处理嵌套括号
        text, mask = set_forbidden_text_careful_brace(text, mask, r"\\hl\{(.*?)\}", re.DOTALL)

    Args:
        text: 完整文本
        mask: 掩码数组
        pattern: 正则表达式
        flags: 正则标志

    Returns:
        (text, mask): 处理后的文本和掩码
    """
    pattern_compile = re.compile(pattern, flags)
    for res in pattern_compile.finditer(text):
        brace_level = -1
        p = begin = end = res.regs[0][0]
        for _ in range(1024 * 16):
            if text[p] == "}" and brace_level == 0:
                break
            elif text[p] == "}":
                brace_level -= 1
            elif text[p] == "{":
                brace_level += 1
            p += 1
        end = p + 1
        mask[begin:end] = PRESERVE
    return text, mask


def reverse_forbidden_text_careful_brace(text: str, mask: np.ndarray, pattern: str, flags=0, forbid_wrapper: bool = True) -> Tuple[str, np.ndarray]:
    """
    带括号计数的反向标记 - 将嵌套括号内容标记为可翻译


    用法示例:
        # 将 \\caption{...} 中的内容标记为可翻译
        text, mask = reverse_forbidden_text_careful_brace(text, mask, r"\\caption\{(.*?)\}", re.DOTALL)

    Args:
        text: 完整文本
        mask: 掩码数组
        pattern: 正则表达式
        flags: 正则标志
        forbid_wrapper: 是否保留包装命令

    Returns:
        (text, mask): 处理后的文本和掩码
    """
    pattern_compile = re.compile(pattern, flags)
    for res in pattern_compile.finditer(text):
        brace_level = 0
        p = begin = end = res.regs[1][0]
        for _ in range(1024 * 16):
            if text[p] == "}" and brace_level == 0:
                break
            elif text[p] == "}":
                brace_level -= 1
            elif text[p] == "{":
                brace_level += 1
            p += 1
        end = p
        mask[begin:end] = TRANSFORM
        if forbid_wrapper:
            mask[res.regs[0][0] : begin] = PRESERVE
            mask[end : res.regs[0][1]] = PRESERVE
    return text, mask


def set_forbidden_text_begin_end(text: str, mask: np.ndarray, pattern: str, flags=0, limit_n_lines: int = 42) -> Tuple[str, np.ndarray]:
    """
    处理 begin-end 环境 - 根据行数决定是否保留


    对于行数少于 limit_n_lines 的环境，整体保留；
    对于行数多的环境，递归处理内部内容。

    Args:
        text: 完整文本
        mask: 掩码数组
        pattern: 正则表达式（匹配 \\begin{...}...\\end{...}）
        flags: 正则标志
        limit_n_lines: 行数阈值，默认42

    Returns:
        (text, mask): 处理后的文本和掩码
    """
    pattern_compile = re.compile(pattern, flags)

    def search_with_line_limit(text, mask):
        for res in pattern_compile.finditer(text):
            cmd = res.group(1)  # begin{what}
            this = res.group(2)  # content between begin and end
            this_mask = mask[res.regs[2][0] : res.regs[2][1]]

            # 白名单：这些环境始终不保留（需要翻译）
            white_list = [
                "document", "abstract", "lemma", "definition", "sproof",
                "em", "emph", "textit", "textbf", "itemize", "enumerate",
            ]

            if (cmd in white_list) or this.count("\n") >= limit_n_lines:
                # 行数多或在白名单中，递归处理
                this, this_mask = search_with_line_limit(this, this_mask)
                mask[res.regs[2][0] : res.regs[2][1]] = this_mask
            else:
                # 行数少，整体保留
                mask[res.regs[0][0] : res.regs[0][1]] = PRESERVE
        return text, mask

    return search_with_line_limit(text, mask)


# ============================================================================
# 文件合并函数
# ============================================================================

def find_main_tex_file(file_manifest: List[str], mode: str = "translate_zh") -> str:
    """
    在多文件中找到主 tex 文件

    主文件的判断标准：
        1. 必须包含 \\documentclass 关键字
        2. 如果有多个候选，通过评分选择（排除模板文档）

    Args:
        file_manifest: 所有 tex 文件路径列表
        mode: 处理模式

    Returns:
        主 tex 文件路径

    Raises:
        RuntimeError: 找不到主文件
    """
    candidates = []
    for texf in file_manifest:
        if os.path.basename(texf).startswith("merge"):
            continue
        with open(texf, "r", encoding="utf8", errors="ignore") as f:
            file_content = f.read()
        if r"\documentclass" in file_content:
            candidates.append(texf)
        else:
            continue

    if len(candidates) == 0:
        raise RuntimeError("无法找到一个主Tex文件（包含documentclass关键字）")
    elif len(candidates) == 1:
        return candidates[0]
    else:
        # 多个候选，通过评分选择
        candidates_score = []
        unexpected_words = [
            "\\LaTeX", "manuscript", "Guidelines", "font",
            "citations", "rejected", "blind review", "reviewers",
        ]
        expected_words = ["\\input", "\\ref", "\\cite"]

        for texf in candidates:
            candidates_score.append(0)
            with open(texf, "r", encoding="utf8", errors="ignore") as f:
                file_content = f.read()
                file_content = rm_comments(file_content)
            for uw in unexpected_words:
                if uw in file_content:
                    candidates_score[-1] -= 1
            for uw in expected_words:
                if uw in file_content:
                    candidates_score[-1] += 1

        select = np.argmax(candidates_score)
        return candidates[select]


def rm_comments(main_file: str) -> str:
    """
    移除 Latex 注释


    Args:
        main_file: Latex 文本内容

    Returns:
        移除注释后的文本
    """
    new_file_remove_comment_lines = []
    for l in main_file.splitlines():
        # 删除整行的空注释
        if l.lstrip().startswith("%"):
            pass
        else:
            new_file_remove_comment_lines.append(l)
    main_file = "\n".join(new_file_remove_comment_lines)
    # 删除半行注释
    main_file = re.sub(r"(?<!\\)%.*", "", main_file)
    return main_file


def find_tex_file_ignore_case(fp: str) -> Optional[str]:
    """
    忽略大小写查找 tex 文件


    Args:
        fp: 文件路径（可能缺少扩展名或大小写不匹配）

    Returns:
        找到的文件路径，或 None
    """
    dir_name = os.path.dirname(fp)
    base_name = os.path.basename(fp)

    # 直接匹配
    if os.path.isfile(pj(dir_name, base_name)):
        return pj(dir_name, base_name)

    # 添加 .tex 后缀
    if not base_name.endswith(".tex"):
        base_name += ".tex"
    if os.path.isfile(pj(dir_name, base_name)):
        return pj(dir_name, base_name)

    # 忽略大小写匹配
    import glob
    for f in glob.glob(dir_name + "/*.tex"):
        base_name_s = os.path.basename(fp)
        base_name_f = os.path.basename(f)
        if base_name_s.lower() == base_name_f.lower():
            return f
        if not base_name_s.endswith(".tex"):
            base_name_s += ".tex"
        if base_name_s.lower() == base_name_f.lower():
            return f

    return None


def merge_tex_files_(project_folder: str, main_file: str, mode: str) -> str:
    """
    递归合并 tex 文件 - 处理 \\input 命令

    Args:
        project_folder: 项目文件夹
        main_file: 主文件内容
        mode: 处理模式

    Returns:
        合并后的文件内容
    """
    main_file = rm_comments(main_file)
    for s in reversed([q for q in re.finditer(r"\\input\{(.*?)\}", main_file, re.M)]):
        f = s.group(1)
        fp = os.path.join(project_folder, f)
        fp_ = find_tex_file_ignore_case(fp)
        if fp_:
            try:
                with open(fp_, "r", encoding="utf-8", errors="replace") as fx:
                    c = fx.read()
            except:
                c = f"\n\nWarning from GPT-Academic: LaTex source file is missing!\n\n"
        else:
            raise RuntimeError(f"找不到{fp}，Tex源文件缺失！")
        c = merge_tex_files_(project_folder, c, mode)
        main_file = main_file[: s.span()[0]] + c + main_file[s.span()[1] :]
    return main_file


def find_title_and_abs(main_file: str) -> Tuple[Optional[str], Optional[str]]:
    """
    提取论文标题和摘要

    Args:
        main_file: Latex 文件内容

    Returns:
        (title, abstract): 标题和摘要，可能为 None
    """
    def extract_abstract_1(text):
        pattern = r"\\abstract\{(.*?)\}"
        match = re.search(pattern, text, re.DOTALL)
        return match.group(1) if match else None

    def extract_abstract_2(text):
        pattern = r"\\begin\{abstract\}(.*?)\\end\{abstract\}"
        match = re.search(pattern, text, re.DOTALL)
        return match.group(1) if match else None

    def extract_title(string):
        pattern = r"\\title\{(.*?)\}"
        match = re.search(pattern, string, re.DOTALL)
        return match.group(1) if match else None

    abstract = extract_abstract_1(main_file)
    if abstract is None:
        abstract = extract_abstract_2(main_file)
    title = extract_title(main_file)
    return title, abstract


def merge_tex_files(project_folder: str, main_file: str, mode: str = "translate_zh") -> str:
    """
    合并 tex 文件并添加中文支持


    步骤:
        1. 递归合并所有 \\input 引用的文件
        2. 移除注释
        3. 如果是翻译模式，添加 ctex 包支持中文

    Args:
        project_folder: 项目文件夹
        main_file: 主文件内容
        mode: 处理模式

    Returns:
        合并后的文件内容
    """
    main_file = merge_tex_files_(project_folder, main_file, mode)
    main_file = rm_comments(main_file)

    if mode == "translate_zh":
        # 添加 ctex 支持中文
        pattern = re.compile(r"\\documentclass.*\n")
        match = pattern.search(main_file)
        assert match is not None, "Cannot find documentclass statement!"
        position = match.end()
        add_ctex = "\\usepackage{ctex}\n"
        add_url = "\\usepackage{url}\n" if "{url}" not in main_file else ""
        main_file = main_file[:position] + add_ctex + add_url + main_file[position:]

        # 设置中文字体
        main_file = re.sub(
            r"\\documentclass\[(.*?)\]{(.*?)}",
            r"\\documentclass[\1,fontset=windows,UTF8]{\2}",
            main_file,
        )
        main_file = re.sub(
            r"\\documentclass{(.*?)}",
            r"\\documentclass[fontset=windows,UTF8]{\1}",
            main_file,
        )

        # 确保有摘要部分
        pattern_opt1 = re.compile(r"\\begin\{abstract\}.*\n")
        pattern_opt2 = re.compile(r"\\abstract\{(.*?)\}", flags=re.DOTALL)
        match_opt1 = pattern_opt1.search(main_file)
        match_opt2 = pattern_opt2.search(main_file)
        if (match_opt1 is None) and (match_opt2 is None):
            main_file = insert_abstract(main_file)

    return main_file


# 缺失摘要时插入的占位符
insert_missing_abs_str = r"""
\begin{abstract}
The GPT-Academic program cannot find abstract section in this paper.
\end{abstract}
"""


def insert_abstract(tex_content: str) -> str:
    """
    插入缺失的摘要


    Args:
        tex_content: Latex 文件内容

    Returns:
        插入摘要后的内容
    """
    if "\\maketitle" in tex_content:
        find_index = tex_content.index("\\maketitle")
        end_line_index = tex_content.find("\n", find_index)
        modified_tex = (
            tex_content[: end_line_index + 1]
            + "\n\n"
            + insert_missing_abs_str
            + "\n\n"
            + tex_content[end_line_index + 1 :]
        )
        return modified_tex
    elif r"\begin{document}" in tex_content:
        find_index = tex_content.index(r"\begin{document}")
        end_line_index = tex_content.find("\n", find_index)
        modified_tex = (
            tex_content[: end_line_index + 1]
            + "\n\n"
            + insert_missing_abs_str
            + "\n\n"
            + tex_content[end_line_index + 1 :]
        )
        return modified_tex
    else:
        return tex_content


# ============================================================================
# 后处理函数
# ============================================================================
def mod_inbraket(match):
    """
    修复 cite 中的中文标点


    GPT 有时会将 cite 中的逗号翻译成中文逗号，需要修复。
    """
    cmd = match.group(1)
    str_to_modify = match.group(2)
    str_to_modify = str_to_modify.replace("：", ":")
    str_to_modify = str_to_modify.replace("，", ",")
    return "\\" + cmd + "{" + str_to_modify + "}"


def fix_content(final_tex: str, node_string: str) -> str:
    """
    修复 GPT 翻译的常见错误


    修复内容:
        - 转义 % 符号
        - 修复多余的空格
        - 修复 cite 中的中文标点
        - 检查 begin/end 数量是否一致
        - 修复下划线转义
        - 修复括号不匹配

    Args:
        final_tex: GPT 翻译结果
        node_string: 原始文本

    Returns:
        修复后的文本
    """
    final_tex = re.sub(r"(?<!\\)%", "\\%", final_tex)
    final_tex = re.sub(r"\\([a-z]{2,10})\ \{", r"\\\1{", string=final_tex)
    final_tex = re.sub(r"\\\ ([a-z]{2,10})\{", r"\\\1{", string=final_tex)
    final_tex = re.sub(r"\\([a-z]{2,10})\{([^\}]*?)\}", mod_inbraket, string=final_tex)

    # 检查是否有错误标记
    if "Traceback" in final_tex and "[Local Message]" in final_tex:
        final_tex = node_string
    if node_string.count("\\begin") != final_tex.count("\\begin"):
        final_tex = node_string
    if node_string.count("\_") > 0 and node_string.count("\_") > final_tex.count("\_"):
        final_tex = re.sub(r"(?<!\\)_", "\\_", final_tex)

    def compute_brace_level(string):
        brace_level = 0
        for c in string:
            if c == "{":
                brace_level += 1
            elif c == "}":
                brace_level -= 1
        return brace_level

    def join_most(tex_t, tex_o):
        p_t = 0
        p_o = 0

        def find_next(string, chars, begin):
            p = begin
            while p < len(string):
                if string[p] in chars:
                    return p, string[p]
                p += 1
            return None, None

        while True:
            res1, char = find_next(tex_o, ["{", "}"], p_o)
            if res1 is None:
                break
            res2, char = find_next(tex_t, [char], p_t)
            if res2 is None:
                break
            p_o = res1 + 1
            p_t = res2 + 1
        return tex_t[:p_t] + tex_o[p_o:]

    if compute_brace_level(final_tex) != compute_brace_level(node_string):
        final_tex = join_most(final_tex, node_string)

    return final_tex


def compile_latex_with_timeout(command: str, cwd: str, timeout: int = 60) -> bool:
    """
    带超时的 Latex 编译

    Args:
        command: 编译命令
        cwd: 工作目录
        timeout: 超时时间（秒）

    Returns:
        True 表示成功，False 表示超时
    """
    process = subprocess.Popen(
        command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        logger.error("Process timed out (compile_latex_with_timeout)!")
        return False
    return True


# ============================================================================
# 子进程运行工具
# ============================================================================

def run_in_subprocess_wrapper_func(func, args, kwargs, return_dict, exception_dict):
    """子进程包装函数"""
    import sys
    try:
        result = func(*args, **kwargs)
        return_dict["result"] = result
    except Exception as e:
        exc_info = sys.exc_info()
        exception_dict["exception"] = exc_info


def run_in_subprocess(func):
    """
    在子进程中运行函数（避免内存泄漏）
    """
    def wrapper(*args, **kwargs):
        return_dict = multiprocessing.Manager().dict()
        exception_dict = multiprocessing.Manager().dict()
        process = multiprocessing.Process(
            target=run_in_subprocess_wrapper_func,
            args=(func, args, kwargs, return_dict, exception_dict),
        )
        process.start()
        process.join()
        process.close()
        if "exception" in exception_dict:
            exc_info = exception_dict["exception"]
            raise exc_info[1].with_traceback(exc_info[2])
        if "result" in return_dict.keys():
            return return_dict["result"]
    return wrapper


# ============================================================================
# PDF 合并函数
# ============================================================================

def _merge_pdfs(pdf1_path: str, pdf2_path: str, output_path: str):
    """
    合并两个 PDF（左右并排）

    """
    try:
        logger.info("Merging PDFs using _merge_pdfs_ng")
        _merge_pdfs_ng(pdf1_path, pdf2_path, output_path)
    except:
        logger.info("Merging PDFs using _merge_pdfs_legacy")
        _merge_pdfs_legacy(pdf1_path, pdf2_path, output_path)


def _merge_pdfs_ng(pdf1_path: str, pdf2_path: str, output_path: str):
    """
    新版 PDF 合并（保留链接）


    """
    import PyPDF2
    from PyPDF2.generic import NameObject, TextStringObject, ArrayObject, FloatObject, NumberObject

    Percent = 1
    with open(pdf1_path, "rb") as pdf1_file:
        pdf1_reader = PyPDF2.PdfFileReader(pdf1_file)
        with open(pdf2_path, "rb") as pdf2_file:
            pdf2_reader = PyPDF2.PdfFileReader(pdf2_file)
            output_writer = PyPDF2.PdfFileWriter()
            num_pages = max(pdf1_reader.numPages, pdf2_reader.numPages)

            for page_num in range(num_pages):
                if page_num < pdf1_reader.numPages:
                    page1 = pdf1_reader.getPage(page_num)
                else:
                    page1 = PyPDF2.PageObject.createBlankPage(pdf1_reader)

                if page_num < pdf2_reader.numPages:
                    page2 = pdf2_reader.getPage(page_num)
                else:
                    page2 = PyPDF2.PageObject.createBlankPage(pdf1_reader)

                new_page = PyPDF2.PageObject.createBlankPage(
                    width=int(int(page1.mediaBox.getWidth()) + int(page2.mediaBox.getWidth()) * Percent),
                    height=max(page1.mediaBox.getHeight(), page2.mediaBox.getHeight()),
                )
                new_page.mergeTranslatedPage(page1, 0, 0)
                new_page.mergeTranslatedPage(
                    page2,
                    int(int(page1.mediaBox.getWidth()) - int(page2.mediaBox.getWidth()) * (1 - Percent)),
                    0,
                )
                output_writer.addPage(new_page)

            with open(output_path, "wb") as output_file:
                output_writer.write(output_file)


def _merge_pdfs_legacy(pdf1_path: str, pdf2_path: str, output_path: str):
    """
    旧版 PDF 合并（简单合并）

    """
    import PyPDF2
    Percent = 0.95

    with open(pdf1_path, "rb") as pdf1_file:
        pdf1_reader = PyPDF2.PdfFileReader(pdf1_file)
        with open(pdf2_path, "rb") as pdf2_file:
            pdf2_reader = PyPDF2.PdfFileReader(pdf2_file)
            output_writer = PyPDF2.PdfFileWriter()
            num_pages = max(pdf1_reader.numPages, pdf2_reader.numPages)

            for page_num in range(num_pages):
                if page_num < pdf1_reader.numPages:
                    page1 = pdf1_reader.getPage(page_num)
                else:
                    page1 = PyPDF2.PageObject.createBlankPage(pdf1_reader)

                if page_num < pdf2_reader.numPages:
                    page2 = pdf2_reader.getPage(page_num)
                else:
                    page2 = PyPDF2.PageObject.createBlankPage(pdf1_reader)

                new_page = PyPDF2.PageObject.createBlankPage(
                    width=int(int(page1.mediaBox.getWidth()) + int(page2.mediaBox.getWidth()) * Percent),
                    height=max(page1.mediaBox.getHeight(), page2.mediaBox.getHeight()),
                )
                new_page.mergeTranslatedPage(page1, 0, 0)
                new_page.mergeTranslatedPage(
                    page2,
                    int(int(page1.mediaBox.getWidth()) - int(page2.mediaBox.getWidth()) * (1 - Percent)),
                    0,
                )
                output_writer.addPage(new_page)

            with open(output_path, "wb") as output_file:
                output_writer.write(output_file)


# 子进程包装，避免 PyPDF2 内存泄漏
merge_pdfs = run_in_subprocess(_merge_pdfs)
