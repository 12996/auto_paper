"""
统一配置管理 — 读取 apikey.ini 并提供结构化配置访问接口。
"""

import configparser
import os
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=_PROJECT_ROOT / ".env")


class AppConfig:
    """
    一次性从 ``apikey.ini`` 加载所有配置并以属性方式暴露。

    Parameters
    ----------
    config_path : str
        配置文件路径，默认为当前目录下的 ``apikey.ini``。
    """

    def __init__(self, config_path: str = 'apikey.ini'):
        self._config = configparser.ConfigParser()
        self._config.read(config_path, encoding='utf-8')

    # -----------------------------------------------------------------
    # 本地模型
    # -----------------------------------------------------------------

    @property
    def use_local_model(self) -> bool:
        """是否使用本地模型。"""
        if self._config.has_section('LocalModel'):
            return self._config.get('LocalModel', 'USE_LOCAL_MODEL', fallback='false').lower() == 'true'
        return False

    @property
    def local_model_config(self) -> dict:
        """本地模型配置 dict：api_base, api_key, model。"""
        if not self.use_local_model:
            return {}
        return {
            'use_local_model': True,
            'api_base': self._config.get('LocalModel', 'LOCAL_API_BASE'),
            'api_key': self._config.get('LocalModel', 'LOCAL_API_KEY'),
            'model': self._config.get('LocalModel', 'LOCAL_MODEL'),
        }

    # -----------------------------------------------------------------
    # OpenAI
    # -----------------------------------------------------------------

    @property
    def openai_config(self) -> dict:
        """OpenAI 配置 dict：api_base, api_keys (list), model。"""
        if not self._config.has_section('OpenAI'):
            return {}
        api_keys_raw = self._config.get('OpenAI', 'OPENAI_API_KEYS', fallback='[]')
        api_keys = [k.strip() for k in api_keys_raw[1:-1].replace("'", '').split(',') if len(k.strip()) > 20]
        # 追加环境变量中的 key
        env_key = os.environ.get('OPENAI_KEY', '')
        if len(env_key) > 20:
            api_keys.append(env_key)
        return {
            'api_base': self._config.get('OpenAI', 'OPENAI_API_BASE', fallback='https://api.openai.com/v1'),
            'api_keys': api_keys,
            'model': self._config.get('OpenAI', 'CHATGPT_MODEL', fallback='gpt-3.5-turbo'),
        }

    # -----------------------------------------------------------------
    # Azure OpenAI
    # -----------------------------------------------------------------

    @property
    def azure_config(self) -> dict:
        """Azure OpenAI 配置 dict。"""
        if not self._config.has_section('AzureOPenAI'):
            return {}
        return {
            'api_base': self._config.get('AzureOPenAI', 'OPENAI_API_BASE', fallback=''),
            'api_key': self._config.get('AzureOPenAI', 'OPENAI_API_KEYS', fallback=''),
            'model': self._config.get('AzureOPenAI', 'CHATGPT_MODEL', fallback=''),
            'api_version': self._config.get('AzureOPenAI', 'OPENAI_API_VERSION', fallback=''),
        }

    # -----------------------------------------------------------------
    # Gitee 图床
    # -----------------------------------------------------------------

    @property
    def gitee_config(self) -> dict:
        """Gitee 图床配置 dict。"""
        if not self._config.has_section('Gitee'):
            return {}
        return {
            'api': self._config.get('Gitee', 'api', fallback=''),
            'owner': self._config.get('Gitee', 'owner', fallback=''),
            'repo': self._config.get('Gitee', 'repo', fallback=''),
            'path': self._config.get('Gitee', 'path', fallback=''),
        }

    def resolve_llm_runtime(self) -> tuple[str, str, str]:
        # 优先使用统一环境变量配置（与主翻译链路一致）。
        provider = os.environ.get("ARXIV_LLM_PROVIDER", "").strip().lower()
        if provider:
            if provider in ("local", "custom"):
                api_base = (os.environ.get("ARXIV_API_BASE", "http://127.0.0.1:8317/v1/") or "").strip().rstrip("/")
                if api_base.endswith("/models"):
                    api_base = api_base[:-len("/models")]
                return (
                    api_base,
                    os.environ.get("ARXIV_API_KEY", ""),
                    os.environ.get("ARXIV_MODEL", "gpt-5"),
                )
            if provider == "deepseek":
                api_base = (os.environ.get("ARXIV_DEEPSEEK_API_BASE", "https://api.deepseek.com/v1") or "").strip().rstrip("/")
                return (
                    api_base,
                    os.environ.get("ARXIV_DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_API_KEY", ""),
                    os.environ.get("ARXIV_DEEPSEEK_MODEL", "deepseek-chat"),
                )
            if provider == "gemini":
                api_base = (
                    os.environ.get(
                        "ARXIV_GEMINI_API_BASE",
                        "https://generativelanguage.googleapis.com/v1beta/openai",
                    )
                    or ""
                ).strip().rstrip("/")
                return (
                    api_base,
                    os.environ.get("ARXIV_GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY", ""),
                    os.environ.get("ARXIV_GEMINI_MODEL", "gemini-2.5-pro"),
                )
            raise ValueError(
                f"Unsupported ARXIV_LLM_PROVIDER={provider!r}. Use local/deepseek/gemini/custom."
            )

        if self.use_local_model:
            local = self.local_model_config
            return local["api_base"], local["api_key"], local["model"]

        openai_cfg = self.openai_config
        api_keys = openai_cfg.get("api_keys", []) if openai_cfg else []
        if openai_cfg and api_keys:
            return (
                openai_cfg.get("api_base", "https://api.openai.com/v1"),
                api_keys[0],
                openai_cfg.get("model", "gpt-3.5-turbo"),
            )

        azure_cfg = self.azure_config
        if azure_cfg and azure_cfg.get("api_key"):
            return (
                azure_cfg.get("api_base", "https://api.openai.com/v1"),
                azure_cfg["api_key"],
                azure_cfg.get("model", "gpt-3.5-turbo"),
            )

        raise ValueError("No available LLM config found in apikey.ini.")
