"""
通用工具函数
- 文件名清理
- Markdown 导出
- 延迟加载 Tiktoken
"""

import os
import re
from functools import lru_cache

import tiktoken


# =============================================================================
# 文件名清理
# =============================================================================

def validate_title(title: str) -> str:
    """将论文标题中不合法的文件名字符替换为下划线。"""
    rstr = r'[\/\\:\*\?\"<>\|]'  # / \ : * ? " < > |
    return re.sub(rstr, "_", title)


# =============================================================================
# Markdown 导出
# =============================================================================

def export_to_markdown(text: str, file_name: str, mode: str = 'w') -> None:
    """将文本写入 Markdown 文件。"""
    os.makedirs(os.path.dirname(file_name) or '.', exist_ok=True)
    with open(file_name, mode, encoding="utf-8") as f:
        f.write(text)


# =============================================================================
# 延迟加载 Tiktoken
# =============================================================================

class LazyloadTiktoken:
    """延迟初始化 tiktoken 编码器，避免模块加载时产生网络下载。"""

    def __init__(self, model: str = "gpt-3.5-turbo"):
        self.model = model
        self._encoder = None

    @staticmethod
    @lru_cache(maxsize=128)
    def _get_encoder(model: str):
        print('正在加载tokenizer，如果是第一次运行，可能需要一点时间下载参数')
        tmp = tiktoken.encoding_for_model(model)
        print('加载tokenizer完毕')
        return tmp

    @property
    def encoder(self):
        if self._encoder is None:
            self._encoder = self._get_encoder(self.model)
        return self._encoder

    def encode(self, *args, **kwargs):
        return self.encoder.encode(*args, **kwargs)

    def decode(self, *args, **kwargs):
        return self.encoder.decode(*args, **kwargs)
