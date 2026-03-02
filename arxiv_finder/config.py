"""
统一配置管理 — 读取 apikey.ini 并提供结构化配置访问接口。
"""

import configparser
import os


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
