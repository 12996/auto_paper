# -*- coding: utf-8 -*-
"""
================================================================================
latex_processor/latex_actions.py
================================================================================
Latex 论文处理核心逻辑


【核心类和函数】
┌─────────────────────────────────────────────────────────────────────────────┐
│ 类                                                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│ LatexPaperSplit (第84-168行)                                                │
│   - 功能: 将 Latex 文件智能切分为可翻译片段                                  │
│   - 方法:                                                                   │
│     - read_title_and_abstract(): 读取标题和摘要                             │
│     - split(): 执行切分                                                     │
│     - merge_result(): 合并翻译结果                                          │
├─────────────────────────────────────────────────────────────────────────────┤
│ LatexPaperFileGroup (第171-215行)                                           │
│   - 功能: 按 token 限制对文本进行分组                                       │
│   - 方法:                                                                   │
│     - run_file_split(): 按 token 限制拆分                                   │
│     - merge_result(): 合并结果                                              │
│     - write_result(): 写入文件                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│ 核心函数                                                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│ split_subprocess() (第19-82行)                                              │
│   - 功能: 在子进程中执行切分，避免超时                                      │
│   - 切分规则:                                                               │
│     - 保留: title, maketitle, iffalse, 短 begin-end, 公式, 表格, 图片等     │
│     - 翻译: 正文段落, abstract 内容, caption 内容                           │
├─────────────────────────────────────────────────────────────────────────────┤
│ Latex精细分解与转化() (第218-317行)                                         │
│   - 功能: 完整的 Latex 翻译流程                                             │
│   - 步骤: 找主文件 → 合并 → 切分 → 调用LLM → 合并结果                       │
├─────────────────────────────────────────────────────────────────────────────┤
│ 编译Latex() (第347-478行)                                                   │
│   - 功能: 编译 Latex 生成 PDF                                               │
│   - 支持: pdflatex, xelatex, bibtex                                         │
│   - 特性: 自动检测编译器, 错误行回退重试                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│ 辅助函数                                                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│ remove_buggy_lines() (第320-344行)                                          │
│   - 功能: 从编译日志中提取错误行，并回退翻译                                │
│ write_html() (第481-506行)                                                  │
│   - 功能: 生成翻译对比 HTML 报告                                            │
└─────────────────────────────────────────────────────────────────────────────┘
================================================================================
"""

import os
import re
import glob
import shutil
import multiprocessing
import numpy as np
from pathlib import Path
from typing import List, Optional, Tuple, Callable
from functools import partial
from loguru import logger

# 导入工具函数
from .latex_toolbox import (
    PRESERVE, TRANSFORM, pj,
    LinkedListNode,
    set_forbidden_text,
    reverse_forbidden_text,
    set_forbidden_text_careful_brace,
    reverse_forbidden_text_careful_brace,
    set_forbidden_text_begin_end,
    convert_to_linklist,
    post_process,
    fix_content,
    find_main_tex_file,
    merge_tex_files,
    find_title_and_abs,
    compile_latex_with_timeout,
    merge_pdfs,
)
from .latex_pickle_io import objdump, objload


# ============================================================================
# 切分子进程
# ============================================================================

def split_subprocess(txt: str, project_folder: str, return_dict: dict, opts: list):
    """
    在子进程中执行 Latex 文件切分


    切分规则说明:
        1. 保留区域 (PRESERVE) - 不翻译:
           - \\maketitle 以上部分
           - \\begin{document} 以上部分
           - \\iffalse ... \\fi 注释块
           - 行数少于42的 begin-end 环境
           - 公式: $$...$$, \\[...\\]
           - 章节: \\section, \\subsection 等
           - 参考文献: \\bibliography, thebibliography 环境
           - 代码: lstlisting 环境
           - 表格: table, wraptable 环境
           - 图片: figure, wrapfigure 环境
           - 算法: algorithm 环境

        2. 翻译区域 (TRANSFORM) - 需要翻译:
           - 正文段落
           - \\caption{...} 内容
           - \\abstract{...} 内容
           - \\begin{abstract}...\\end{abstract} 内容

    Args:
        txt: 完整的 Latex 文本
        project_folder: 项目文件夹路径
        return_dict: 多进程共享字典，用于返回结果
        opts: 额外选项
    """
    text = txt
    mask = np.zeros(len(txt), dtype=np.uint8) + TRANSFORM

    # -------- 保留规则 --------

    # 1. 吸收 title 与作者以上的部分
    text, mask = set_forbidden_text(text, mask, r"^(.*?)\\maketitle", re.DOTALL)
    text, mask = set_forbidden_text(text, mask, r"^(.*?)\\begin{document}", re.DOTALL)

    # 2. 吸收 iffalse 注释
    text, mask = set_forbidden_text(text, mask, r"\\iffalse(.*?)\\fi", re.DOTALL)

    # 3. 吸收在 42 行以内的 begin-end 组合
    text, mask = set_forbidden_text_begin_end(
        text, mask, r"\\begin\{([a-z\*]*)\}(.*?)\\end\{\1\}", re.DOTALL, limit_n_lines=42
    )

    # 4. 吸收匿名公式
    text, mask = set_forbidden_text(
        text, mask, [r"\$\$([^$]+)\$\$", r"\\\[.*?\\\]"], re.DOTALL
    )

    # 5. 吸收章节标题
    text, mask = set_forbidden_text(
        text, mask,
        [r"\\section\{(.*?)\}", r"\\section\*\{(.*?)\}",
         r"\\subsection\{(.*?)\}", r"\\subsubsection\{(.*?)\}"]
    )

    # 6. 吸收参考文献相关
    text, mask = set_forbidden_text(text, mask, [r"\\bibliography\{(.*?)\}", r"\\bibliographystyle\{(.*?)\}"])
    text, mask = set_forbidden_text(text, mask, r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}", re.DOTALL)

    # 7. 吸收代码环境
    text, mask = set_forbidden_text(text, mask, r"\\begin\{lstlisting\}(.*?)\\end\{lstlisting\}", re.DOTALL)

    # 8. 吸收表格环境
    text, mask = set_forbidden_text(text, mask, r"\\begin\{wraptable\}(.*?)\\end\{wraptable\}", re.DOTALL)
    text, mask = set_forbidden_text(text, mask, [r"\\begin\{table\}(.*?)\\end\{table\}", r"\\begin\{table\*\}(.*?)\\end\{table\*\}"], re.DOTALL)

    # 9. 吸收图片环境
    text, mask = set_forbidden_text(text, mask, [r"\\begin\{wrapfigure\}(.*?)\\end\{wrapfigure\}", r"\\begin\{wrapfigure\*\}(.*?)\\end\{wrapfigure\*\}"], re.DOTALL)
    text, mask = set_forbidden_text(text, mask, [r"\\begin\{figure\}(.*?)\\end\{figure\}", r"\\begin\{figure\*\}(.*?)\\end\{figure\*\}"], re.DOTALL)

    # 10. 吸收算法环境
    text, mask = set_forbidden_text(text, mask, r"\\begin\{algorithm\}(.*?)\\end\{algorithm\}", re.DOTALL)

    # 11. 吸收公式环境
    text, mask = set_forbidden_text(text, mask, [r"\\begin\{multline\}(.*?)\\end\{multline\}", r"\\begin\{multline\*\}(.*?)\\end\{multline\*\}"], re.DOTALL)
    text, mask = set_forbidden_text(text, mask, [r"\\begin\{align\*\}(.*?)\\end\{align\*\}", r"\\begin\{align\}(.*?)\\end\{align\}"], re.DOTALL)
    text, mask = set_forbidden_text(text, mask, [r"\\begin\{equation\}(.*?)\\end\{equation\}", r"\\begin\{equation\*\}(.*?)\\end\{equation\*\}"], re.DOTALL)

    # 12. 吸收其他杂项
    text, mask = set_forbidden_text(
        text, mask,
        [r"\\includepdf\[(.*?)\]\{(.*?)\}", r"\\clearpage", r"\\newpage",
         r"\\appendix", r"\\tableofcontents", r"\\include\{(.*?)\}"]
    )
    text, mask = set_forbidden_text(
        text, mask,
        [r"\\vspace\{(.*?)\}", r"\\hspace\{(.*?)\}", r"\\label\{(.*?)\}",
         r"\\begin\{(.*?)\}", r"\\end\{(.*?)\}", r"\\item "]
    )

    # 13. 高亮命令
    text, mask = set_forbidden_text_careful_brace(text, mask, r"\\hl\{(.*?)\}", re.DOTALL)

    # -------- 反向操作（标记为翻译）--------

    # 14. caption 内容需要翻译
    text, mask = reverse_forbidden_text_careful_brace(text, mask, r"\\caption\{(.*?)\}", re.DOTALL, forbid_wrapper=True)

    # 15. abstract 命令内容需要翻译
    text, mask = reverse_forbidden_text_careful_brace(text, mask, r"\\abstract\{(.*?)\}", re.DOTALL, forbid_wrapper=True)

    # 16. abstract 环境内容需要翻译
    text, mask = reverse_forbidden_text(text, mask, r"\\begin\{abstract\}(.*?)\\end\{abstract\}", re.DOTALL, forbid_wrapper=True)

    # -------- 转换为链表 --------
    root = convert_to_linklist(text, mask)

    # -------- 后处理 --------
    root = post_process(root)

    # -------- 输出调试文件 --------
    with open(pj(project_folder, 'debug_log.html'), 'w', encoding='utf8') as f:
        segment_parts_for_gpt = []
        nodes = []
        node = root
        while True:
            nodes.append(node)
            show_html = node.string.replace('\n', '<br/>')
            if not node.preserve:
                segment_parts_for_gpt.append(node.string)
                f.write(f'<p style="color:black;">#{node.range}{show_html}#</p>')
            else:
                f.write(f'<p style="color:red;">{show_html}</p>')
            node = node.next
            if node is None:
                break

    for n in nodes:
        n.next = None  # break links for pickling

    return_dict['nodes'] = nodes
    return_dict['segment_parts_for_gpt'] = segment_parts_for_gpt
    return return_dict


# ============================================================================
# LatexPaperSplit 类
# ============================================================================

class LatexPaperSplit:
    """
    Latex 文件智能切分器

    功能:
        - 将 Latex 文件切分为链表结构
        - 标记哪些部分需要翻译，哪些需要保留
        - 合并翻译结果

    Attributes:
        nodes: 切分后的节点列表
        msg: 翻译警告信息
        title: 论文标题
        abstract: 论文摘要
    """

    def __init__(self) -> None:
        self.nodes = None
        self.msg = "*{\\scriptsize\\textbf{警告：该" + \
            "版权归原文作者所有。翻译内容可靠性无保障，请仔细鉴别并以原文为准。" + \
            ""
        # 历史模板会在 merge_result() 中拼接 msg_declare，默认给空串避免属性缺失。
        self.msg_declare = ""
        self.title = "unknown"
        self.abstract = "unknown"

    def read_title_and_abstract(self, txt: str):
        """
        读取论文标题和摘要
        """
        try:
            title, abstract = find_title_and_abs(txt)
            if title is not None:
                self.title = title.replace('\n', ' ').replace('\\\\', ' ').replace('  ', '').replace('  ', '')
            if abstract is not None:
                self.abstract = abstract.replace('\n', ' ').replace('\\\\', ' ').replace('  ', '').replace('  ', '')
        except:
            pass

    def merge_result(self, arr: List[str], mode: str, msg: str, buggy_lines: List[int] = [], buggy_line_surgery_n_lines: int = 10) -> str:
        """
        合并翻译结果


        Args:
            arr: 翻译结果数组
            mode: 模式 ('translate_zh' 或 'proofread_en')
            msg: 附加信息
            buggy_lines: 出错的行号列表
            buggy_line_surgery_n_lines: 回退行数

        Returns:
            合并后的完整 Latex 文本
        """
        result_string = ""
        node_cnt = 0
        line_cnt = 0

        for node in self.nodes:
            if node.preserve:
                line_cnt += node.string.count('\n')
                result_string += node.string
            else:
                translated_txt = fix_content(arr[node_cnt], node.string)
                begin_line = line_cnt
                end_line = line_cnt + translated_txt.count('\n')

                # 如果有错误，回退翻译
                if any([begin_line - buggy_line_surgery_n_lines <= b_line <= end_line + buggy_line_surgery_n_lines for b_line in buggy_lines]):
                    translated_txt = node.string

                result_string += translated_txt
                node_cnt += 1
                line_cnt += translated_txt.count('\n')

        # 插入警告信息
        if mode == 'translate_zh':
            pattern = re.compile(r'\\begin\{abstract\}.*\n')
            match = pattern.search(result_string)
            if not match:
                pattern_compile = re.compile(r"\\abstract\{(.*?)\}", flags=re.DOTALL)
                match = pattern_compile.search(result_string)
                position = match.regs[1][0]
            else:
                position = match.end()
            result_string = result_string[:position] + self.msg + msg + self.msg_declare + result_string[position:]

        return result_string

    def split(self, txt: str, project_folder: str, opts: list = []) -> List[str]:
        """
        执行切分



        使用多进程避免超时。

        Args:
            txt: 完整的 Latex 文本
            project_folder: 项目文件夹
            opts: 额外选项

        Returns:
            需要翻译的文本片段列表
        """
        manager = multiprocessing.Manager()
        return_dict = manager.dict()
        p = multiprocessing.Process(
            target=split_subprocess,
            args=(txt, project_folder, return_dict, opts)
        )
        p.start()
        p.join()
        p.close()
        self.nodes = return_dict['nodes']
        self.sp = return_dict['segment_parts_for_gpt']
        return self.sp


# ============================================================================
# LatexPaperFileGroup 类
# ============================================================================

class LatexPaperFileGroup:
    """
    按 token 限制对文本进行分组

    功能:
        - 将文本片段按 token 数量分组
        - 超过限制的片段会被拆分

    Attributes:
        file_paths: 文件路径列表
        file_contents: 文件内容列表
        sp_file_contents: 拆分后的内容列表
        sp_file_index: 拆分后的文件索引
        sp_file_tag: 拆分后的标签
    """

    def __init__(self):
        self.file_paths = []
        self.file_contents = []
        self.sp_file_contents = []
        self.sp_file_index = []
        self.sp_file_tag = []
        self.file_result = []
        self.sp_file_result = []

        # 初始化 tokenizer
        import tiktoken
        enc = tiktoken.encoding_for_model("gpt-3.5-turbo")
        def get_token_num(txt): return len(enc.encode(txt, disallowed_special=()))
        self.get_token_num = get_token_num

    def run_file_split(self, max_token_limit: int = 1900):
        """
        按 token 限制拆分文件

        Args:
            max_token_limit: 每个 fragment 的最大 token 数
        """
        for index, file_content in enumerate(self.file_contents):
            if self.get_token_num(file_content) < max_token_limit:
                self.sp_file_contents.append(file_content)
                self.sp_file_index.append(index)
                self.sp_file_tag.append(self.file_paths[index])
            else:
                # 需要拆分
                from .text_splitter import breakdown_text_to_satisfy_token_limit
                segments = breakdown_text_to_satisfy_token_limit(file_content, max_token_limit, self.get_token_num)
                for j, segment in enumerate(segments):
                    self.sp_file_contents.append(segment)
                    self.sp_file_index.append(index)
                    self.sp_file_tag.append(self.file_paths[index] + f".part-{j}.tex")

    def merge_result(self):
        """
        合并拆分后的结果

        """
        self.file_result = ["" for _ in range(len(self.file_paths))]
        for r, k in zip(self.sp_file_result, self.sp_file_index):
            self.file_result[k] += r

    def write_result(self) -> List[str]:
        """
        写入结果文件


        Returns:
            生成的文件路径列表
        """
        manifest = []
        for path, res in zip(self.file_paths, self.file_result):
            with open(path + '.polish.tex', 'w', encoding='utf8') as f:
                manifest.append(path + '.polish.tex')
                f.write(res)
        return manifest


# ============================================================================
# 核心处理函数
# ============================================================================

def Latex精细分解与转化(
    file_manifest: List[str],
    project_folder: str,
    llm_kwargs: dict,
    plugin_kwargs: dict,
    mode: str = 'translate_zh',
    switch_prompt: Callable = None,
    opts: list = [],
    callback=None,
) -> str:
    """
    Latex 精细分解与转化的主函数


    完整流程:
        1. 找到主 tex 文件
        2. 合并多文件工程为单文件
        3. 精细切分 Latex
        4. 按 token 限制分组
        5. 调用 LLM 翻译
        6. 合并结果

    Args:
        file_manifest: 所有 tex 文件路径列表
        project_folder: 项目文件夹
        llm_kwargs: LLM 参数（包含 model, temperature 等）
        plugin_kwargs: 插件参数
        mode: 模式 ('translate_zh' 或 'proofread_en')
        switch_prompt: 生成 prompt 的函数
        opts: 额外选项
        callback: 回调函数，用于报告进度 (可选)

    Returns:
        生成的 tex 文件路径
    """
    import time

    # -------- 1. 找到主 tex 文件 --------
    maintex = find_main_tex_file(file_manifest, mode)
    logger.info(f"定位主 Latex 文件: {maintex}")
    if callback:
        callback(f"主文件: {maintex}")
    time.sleep(1)

    # -------- 2. 合并多文件 --------
    main_tex_basename = os.path.basename(maintex)
    assert main_tex_basename.endswith('.tex')
    main_tex_basename_bare = main_tex_basename[:-4]

    # 复制 bbl 文件（如果有）
    may_exist_bbl = pj(project_folder, f'{main_tex_basename_bare}.bbl')
    if os.path.exists(may_exist_bbl):
        shutil.copyfile(may_exist_bbl, pj(project_folder, f'merge.bbl'))
        shutil.copyfile(may_exist_bbl, pj(project_folder, f'merge_{mode}.bbl'))

    # 读取并合并
    with open(maintex, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
        merged_content = merge_tex_files(project_folder, content, mode)

    with open(project_folder + '/merge.tex', 'w', encoding='utf-8', errors='replace') as f:
        f.write(merged_content)

    logger.info("Latex 文件融合完成")

    # -------- 3. 精细切分 --------
    logger.info("正在精细切分 Latex 文件...")
    if callback:
        callback("正在切分 Latex 文件...")

    lps = LatexPaperSplit()
    lps.read_title_and_abstract(merged_content)
    res = lps.split(merged_content, project_folder, opts)

    # -------- 4. 按 token 分组 --------
    pfg = LatexPaperFileGroup()
    for index, r in enumerate(res):
        pfg.file_paths.append('segment-' + str(index))
        pfg.file_contents.append(r)

    pfg.run_file_split(max_token_limit=1024)
    n_split = len(pfg.sp_file_contents)

    logger.info(f"切分完成，共 {n_split} 个片段")

    # -------- 5. 生成 prompt --------
    inputs_array, sys_prompt_array = switch_prompt(pfg, mode) if switch_prompt else ([], [])
    inputs_show_user_array = [f"{mode} {f}" for f in pfg.sp_file_tag]

    return {
        'lps': lps,
        'pfg': pfg,
        'inputs_array': inputs_array,
        'sys_prompt_array': sys_prompt_array,
        'inputs_show_user_array': inputs_show_user_array,
        'n_split': n_split,
        'project_folder': project_folder,
        'mode': mode,
    }


def remove_buggy_lines(
    file_path: str,
    log_path: str,
    tex_name: str,
    tex_name_pure: str,
    n_fix: int,
    work_folder_modified: str,
    fixed_line: List[int] = []
) -> Tuple[bool, str, List[int]]:
    """
    从编译日志中提取错误行，并回退翻译

    Args:
        file_path: tex 文件路径
        log_path: 编译日志路径
        tex_name: tex 文件名
        tex_name_pure: 纯文件名（无扩展名）
        n_fix: 修复次数
        work_folder_modified: 工作文件夹
        fixed_line: 已修复的行号列表

    Returns:
        (can_retry, new_tex_name, buggy_lines)
    """
    try:
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            log = f.read()

        # 检测无法通过行回退修复的错误
        # 这些错误需要人工干预或不同的修复策略
        unrecoverable_errors = [
            r"File `.*\.sty' not found",       # 缺少 .sty 文件
            r"File `.*\.cls' not found",       # 缺少 .cls 文件
            r"Could not find file",            # 缺少图片或其他文件
            r"Image inclusion failed",         # 图片包含失败
            r"Emergency stop",                 # 紧急停止（通常是致命错误）
        ]
        for pattern in unrecoverable_errors:
            if re.search(pattern, log):
                logger.error(f"检测到无法自动修复的错误: {pattern}")
                logger.error("请手动检查编译日志并添加缺失的文件")
                return False, "", []

        buggy_lines = re.findall(tex_name + ':([0-9]{1,5}):', log)
        buggy_lines = [int(l) for l in buggy_lines]

        if not buggy_lines:
            # 没有找到具体的错误行，可能是其他类型的错误
            logger.error("编译失败但无法定位错误行")
            return False, "", []

        buggy_lines = sorted(buggy_lines)
        buggy_line = buggy_lines[0] - 1
        logger.warning(f"reversing tex line that has errors: {buggy_line}")

        if buggy_line not in fixed_line:
            fixed_line.append(buggy_line)

        # 重组，逆转出错的段落
        lps, file_result, mode, msg = objload(file=pj(work_folder_modified, 'merge_result.pkl'))
        final_tex = lps.merge_result(file_result, mode, msg, buggy_lines=fixed_line, buggy_line_surgery_n_lines=5 * n_fix)

        with open(pj(work_folder_modified, f"{tex_name_pure}_fix_{n_fix}.tex"), 'w', encoding='utf-8', errors='replace') as f:
            f.write(final_tex)

        return True, f"{tex_name_pure}_fix_{n_fix}", buggy_lines
    except:
        logger.error("Fatal error occurred, but we cannot identify error")
        return False, "", []


def 编译Latex(
    project_folder: str,
    main_file_original: str = 'merge',
    main_file_modified: str = 'merge_translate_zh',
    mode: str = 'translate_zh',
    callback=None,
) -> bool:
    """
    编译 Latex 生成 PDF


    支持的编译器:
        - pdflatex (默认)
        - xelatex (自动检测是否需要)

    编译流程:
        1. 检测是否需要 xelatex
        2. 编译原始 PDF
        3. 编译翻译 PDF
        4. 编译 BibTeX
        5. 交叉引用编译
        6. 生成对比 PDF（可选）

    Args:
        project_folder: 工作文件夹
        main_file_original: 原始主文件名（无扩展名）
        main_file_modified: 翻译后主文件名（无扩展名）
        mode: 模式
        callback: 回调函数

    Returns:
        True 表示编译成功
    """
    import time

    n_fix = 1
    fixed_line = []
    max_try = 32

    work_folder_original = project_folder
    work_folder_modified = project_folder
    work_folder = project_folder

    logger.info(f"开始编译 PDF，工作路径: {work_folder}")
    if callback:
        callback("开始编译 PDF...")

    # 检查是否需要 xelatex
    def check_if_need_xelatex(tex_path):
        try:
            with open(tex_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read(5000)
                need_xelatex = any(
                    pkg in content
                    for pkg in ['fontspec', 'xeCJK', 'xetex', 'unicode-math', 'xltxtra', 'xunicode']
                )
                if need_xelatex:
                    logger.info("检测到需要 xelatex 编译")
                return need_xelatex
        except Exception:
            return False

    # 确定编译器
    compiler = 'pdflatex'
    if check_if_need_xelatex(pj(work_folder_modified, f'{main_file_modified}.tex')):
        try:
            import subprocess
            subprocess.run(['xelatex', '--version'], capture_output=True, check=True)
            compiler = 'xelatex'
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise RuntimeError("检测到需要使用 xelatex 编译，但系统中未安装")

    def get_compile_command(compiler, filename):
        cmd = f'{compiler} -interaction=batchmode -file-line-error {filename}.tex'
        logger.info(f'Latex 编译指令: {cmd}')
        return cmd

    while True:
        # 复制 bbl 文件
        may_exist_bbl = pj(work_folder_modified, f'merge.bbl')
        target_bbl = pj(work_folder_modified, f'{main_file_modified}.bbl')
        if os.path.exists(may_exist_bbl) and not os.path.exists(target_bbl):
            shutil.copyfile(may_exist_bbl, target_bbl)

        # 编译原始 PDF
        if callback:
            callback(f'编译原始 PDF (第 {n_fix} 次尝试)...')
        ok = compile_latex_with_timeout(get_compile_command(compiler, main_file_original), work_folder_original)

        # 编译翻译 PDF
        if callback:
            callback(f'编译翻译 PDF (第 {n_fix} 次尝试)...')
        ok = compile_latex_with_timeout(get_compile_command(compiler, main_file_modified), work_folder_modified)

        if ok and os.path.exists(pj(work_folder_modified, f'{main_file_modified}.pdf')):
            # 编译 BibTeX
            if callback:
                callback('编译 BibTeX...')
            if not os.path.exists(pj(work_folder_original, f'{main_file_original}.bbl')):
                ok = compile_latex_with_timeout(f'bibtex {main_file_original}.aux', work_folder_original)
            if not os.path.exists(pj(work_folder_modified, f'{main_file_modified}.bbl')):
                ok = compile_latex_with_timeout(f'bibtex {main_file_modified}.aux', work_folder_modified)

            # 交叉引用
            if callback:
                callback('编译交叉引用...')
            ok = compile_latex_with_timeout(get_compile_command(compiler, main_file_original), work_folder_original)
            ok = compile_latex_with_timeout(get_compile_command(compiler, main_file_modified), work_folder_modified)
            ok = compile_latex_with_timeout(get_compile_command(compiler, main_file_original), work_folder_original)
            ok = compile_latex_with_timeout(get_compile_command(compiler, main_file_modified), work_folder_modified)

        # 检查结果
        original_pdf_success = os.path.exists(pj(work_folder_original, f'{main_file_original}.pdf'))
        modified_pdf_success = os.path.exists(pj(work_folder_modified, f'{main_file_modified}.pdf'))

        logger.info(f"编译结果: 原始PDF={original_pdf_success}, 翻译PDF={modified_pdf_success}")

        if modified_pdf_success:
            # 生成双语对照 PDF
            if original_pdf_success:
                try:
                    concat_pdf = pj(work_folder_modified, 'comparison.pdf')
                    merge_pdfs(
                        pj(work_folder_original, f'{main_file_original}.pdf'),
                        pj(work_folder_modified, f'{main_file_modified}.pdf'),
                        concat_pdf
                    )
                    logger.info(f"对比 PDF 已生成: {concat_pdf}")
                except Exception as e:
                    logger.error(f"合并 PDF 失败: {e}")

            if callback:
                callback('编译完成！')
            return True
        else:
            if n_fix >= max_try:
                # 达到最大重试次数，输出错误摘要
                logger.error(f"编译失败，已达到最大重试次数 ({max_try})")
                log_path = pj(work_folder_modified, f'{main_file_modified}.log')
                if os.path.exists(log_path):
                    try:
                        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                            log_content = f.read()
                        # 提取关键错误信息
                        error_lines = []
                        for line in log_content.split('\n'):
                            if line.startswith('!') or 'Error' in line or 'error' in line:
                                error_lines.append(line)
                        if error_lines:
                            logger.error("编译错误摘要:")
                            for err in error_lines[:10]:  # 只显示前10个错误
                                logger.error(f"  {err}")
                    except Exception as e:
                        logger.error(f"无法读取编译日志: {e}")
                break
            n_fix += 1

            # 尝试修复错误
            can_retry, main_file_modified, buggy_lines = remove_buggy_lines(
                file_path=pj(work_folder_modified, f'{main_file_modified}.tex'),
                log_path=pj(work_folder_modified, f'{main_file_modified}.log'),
                tex_name=f'{main_file_modified}.tex',
                tex_name_pure=f'{main_file_modified}',
                n_fix=n_fix,
                work_folder_modified=work_folder_modified,
                fixed_line=fixed_line
            )

            if callback:
                if buggy_lines:
                    callback(f'编译失败，尝试修复第 {buggy_lines} 行...')
                else:
                    callback(f'编译失败，尝试修复...')

            if not can_retry:
                break

    if callback:
        callback('编译失败')
    return False


def write_html(sp_file_contents: List[str], sp_file_result: List[str], project_folder: str) -> str:
    """
    生成翻译对比 HTML 报告

    Args:
        sp_file_contents: 原文片段列表
        sp_file_result: 翻译结果列表
        project_folder: 项目文件夹

    Returns:
        HTML 文件路径
    """
    try:
        import time
        gen_time_str = lambda: time.strftime("%Y%m%d_%H%M%S")

        html_content = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Translation Report</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .row { display: flex; margin-bottom: 10px; border: 1px solid #ddd; }
        .original, .translated { flex: 1; padding: 10px; }
        .original { background-color: #f9f9f9; }
        .translated { background-color: #e8f5e9; }
        pre { white-space: pre-wrap; word-wrap: break-word; margin: 0; }
    </style>
</head>
<body>
    <h1>Translation Report</h1>
"""

        for orig, trans in zip(sp_file_contents, sp_file_result):
            html_content += f"""
    <div class="row">
        <div class="original"><pre>{orig}</pre></div>
        <div class="translated"><pre>{trans}</pre></div>
    </div>
"""

        html_content += """
</body>
</html>
"""
        filename = f"{gen_time_str()}.trans.html"
        filepath = pj(project_folder, filename)

        with open(filepath, 'w', encoding='utf8') as f:
            f.write(html_content)

        logger.info(f"HTML 报告已生成: {filepath}")
        return filepath

    except Exception as e:
        logger.error(f"生成 HTML 报告失败: {e}")
        return ""
