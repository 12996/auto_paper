# -*- coding: utf-8 -*-
"""
================================================================================
latex_processor/latex_pickle_io.py
================================================================================
序列化工具


【功能】
安全的 pickle 序列化和反序列化，支持白名单类
================================================================================
"""

import pickle
from typing import Any


class SafeUnpickler(pickle.Unpickler):
    """
    安全的反序列化器

    只允许反序列化白名单中的类，防止恶意代码执行。
    """

    def get_safe_classes(self):
        """获取允许的安全类列表"""
        # 延迟导入避免循环依赖
        try:
            from .latex_actions import LatexPaperFileGroup, LatexPaperSplit
            from .latex_toolbox import LinkedListNode
            from numpy.core.multiarray import scalar
            from numpy import dtype

            safe_classes = {
                'LatexPaperFileGroup': LatexPaperFileGroup,
                'LatexPaperSplit': LatexPaperSplit,
                'LinkedListNode': LinkedListNode,
                'scalar': scalar,
                'dtype': dtype,
            }
            return safe_classes
        except ImportError:
            return {}

    def find_class(self, module: str, name: str):
        """
        查找类，只允许白名单中的类
        """
        self.safe_classes = self.get_safe_classes()
        match_class_name = None
        for class_name in self.safe_classes.keys():
            if class_name in f'{module}.{name}':
                match_class_name = class_name

        if match_class_name is not None:
            return self.safe_classes[match_class_name]

        raise pickle.UnpicklingError(
            f"Attempted to deserialize unauthorized class '{name}' from module '{module}'"
        )


def objdump(obj: Any, file: str = "objdump.tmp") -> None:
    """
    序列化对象到文件


    Args:
        obj: 要序列化的对象
        file: 输出文件路径
    """
    with open(file, "wb+") as f:
        pickle.dump(obj, f)


def objload(file: str = "objdump.tmp") -> Any:
    """
    从文件反序列化对象

    Args:
        file: 输入文件路径

    Returns:
        反序列化的对象
    """
    import os

    if not os.path.exists(file):
        return None

    with open(file, "rb") as f:
        unpickler = SafeUnpickler(f)
        return unpickler.load()
