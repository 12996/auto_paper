# -*- coding: utf-8 -*-
"""
================================================================================
latex_processor/__init__.py
================================================================================
Latex 论文处理模块


【功能说明】
1. Latex 文件智能切分（保留公式、表格、引用等）
2. 多文件 Latex 工程合并为单文件
3. 翻译结果合并
4. PDF 编译

【核心类】
- LatexPaperSplit: Latex 文件智能切分器
- LatexPaperFileGroup: 按 token 限制分组
================================================================================
"""

from .latex_toolbox import (
    LinkedListNode,
    PRESERVE,
    TRANSFORM,
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

from .latex_actions import (
    LatexPaperSplit,
    LatexPaperFileGroup,
    Latex精细分解与转化,
    编译Latex,
)

from .latex_pickle_io import objdump, objload

__all__ = [
    # 常量
    'PRESERVE', 'TRANSFORM',
    # 数据结构
    'LinkedListNode',
    # 工具函数
    'set_forbidden_text',
    'reverse_forbidden_text',
    'set_forbidden_text_careful_brace',
    'reverse_forbidden_text_careful_brace',
    'set_forbidden_text_begin_end',
    'convert_to_linklist',
    'post_process',
    'fix_content',
    'find_main_tex_file',
    'merge_tex_files',
    'find_title_and_abs',
    'compile_latex_with_timeout',
    'merge_pdfs',
    # 核心类
    'LatexPaperSplit',
    'LatexPaperFileGroup',
    # 核心函数
    'Latex精细分解与转化',
    '编译Latex',
    # 序列化
    'objdump', 'objload',
]
