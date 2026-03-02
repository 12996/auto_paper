"""
统一 LLM 调用层 — 封装本地模型 / OpenAI / Azure OpenAI 的 API 调用。
"""

import http.client
import json
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from urllib.parse import urlparse

import openai
import tenacity

from arxiv_finder.config import AppConfig


# =============================================================================
# 响应数据类
# =============================================================================

@dataclass
class LLMResponse:
    """LLM 调用的统一响应格式。"""
    result: str = ''
    session_id: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    response_time: float = 0.0


# =============================================================================
# LLM 调用客户端
# =============================================================================

class LLMClient:
    """
    统一封装本地模型、OpenAI、Azure OpenAI 的调用。

    Parameters
    ----------
    config : AppConfig
        应用配置对象。
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.use_local_model = config.use_local_model

        if self.use_local_model:
            lmc = config.local_model_config
            self.api_base = lmc['api_base']
            self.api_key = lmc['api_key']
            self.model = lmc['model']
            self._api_keys: List[str] = [self.api_key]
            # 设置 openai.api_base 以便兼容
            openai.api_base = self.api_base
            print(f"[LLMClient] 使用本地模型: {self.model} @ {self.api_base}")
        else:
            oai = config.openai_config
            self.api_base = oai.get('api_base', 'https://api.openai.com/v1')
            self._api_keys = oai.get('api_keys', [])
            self.model = oai.get('model', 'gpt-3.5-turbo')
            self.api_key = None  # 每次动态选择

            # 如果没有 OpenAI key，尝试 Azure
            az = config.azure_config
            if not self._api_keys and az.get('api_key'):
                self._api_keys = [az['api_key']]
                self.model = az.get('model', '')
                self.api_base = az.get('api_base', '')
                openai.api_base = self.api_base
                openai.api_type = 'azure'
                openai.api_version = az.get('api_version', '')
                print(f"[LLMClient] 使用 Azure OpenAI: {self.model} @ {self.api_base}")
            else:
                openai.api_base = self.api_base
                print(f"[LLMClient] 使用 OpenAI: {self.model} @ {self.api_base}")

        self._cur_api_index = 0

    # -----------------------------------------------------------------
    # 公共接口
    # -----------------------------------------------------------------

    @tenacity.retry(wait=tenacity.wait_exponential(multiplier=1, min=4, max=10),
                    stop=tenacity.stop_after_attempt(5),
                    reraise=True)
    def chat(self, messages: List[Dict], session_id: Optional[str] = None) -> LLMResponse:
        """
        发送消息列表给 LLM 并返回统一格式的响应。

        Parameters
        ----------
        messages : list[dict]
            OpenAI 格式的消息列表 (role/content)。
        session_id : str, optional
            本地模型多轮对话的 session_id。

        Returns
        -------
        LLMResponse
        """
        if self.use_local_model:
            return self._call_local(messages, session_id)
        else:
            return self._call_openai(messages)

    # -----------------------------------------------------------------
    # 内部实现
    # -----------------------------------------------------------------

    def _next_api_key(self) -> str:
        """轮询获取下一个 API key。"""
        if not self._api_keys:
            raise ValueError("没有可用的 API key，请检查 apikey.ini 配置")
        key = self._api_keys[self._cur_api_index]
        self._cur_api_index = (self._cur_api_index + 1) % len(self._api_keys)
        return key

    def _call_local(self, messages: List[Dict], session_id: Optional[str] = None) -> LLMResponse:
        """通过 HTTP 直接调用本地模型（支持 session_id）。"""
        request_body = {
            "model": self.model,
            "messages": messages,
        }
        if session_id:
            request_body["session_id"] = session_id

        parsed = urlparse(self.api_base)
        host = parsed.hostname
        port = parsed.port or 80

        conn = http.client.HTTPConnection(host, port, timeout=120)
        conn.request(
            "POST",
            "/v1/chat/completions",
            json.dumps(request_body),
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        http_response = conn.getresponse()
        response_data = json.loads(http_response.read().decode('utf-8'))
        conn.close()

        result = ''
        for choice in response_data.get('choices', []):
            result += choice['message']['content']

        new_session_id = response_data.get('session_id')
        usage = response_data.get('usage', {})
        response_time = response_data.get('response_ms', 0) / 1000.0

        resp = LLMResponse(
            result=result,
            session_id=new_session_id,
            prompt_tokens=usage.get('prompt_tokens', 0),
            completion_tokens=usage.get('completion_tokens', 0),
            total_tokens=usage.get('total_tokens', 0),
            response_time=response_time,
        )
        self._print_usage("llm", resp)
        return resp

    def _call_openai(self, messages: List[Dict]) -> LLMResponse:
        """通过 openai SDK 调用 OpenAI / Azure。"""
        api_key = self._next_api_key()
        openai.api_key = api_key

        if getattr(openai, 'api_type', None) == 'azure':
            response = openai.ChatCompletion.create(
                engine=self.model,
                messages=messages,
            )
        else:
            response = openai.ChatCompletion.create(
                model=self.model,
                messages=messages,
            )

        result = ''
        for choice in response.choices:
            result += choice.message.content

        resp = LLMResponse(
            result=result,
            session_id=None,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            total_tokens=response.usage.total_tokens,
            response_time=getattr(response, 'response_ms', 0) / 1000.0,
        )
        self._print_usage("llm", resp)
        return resp

    @staticmethod
    def _print_usage(tag: str, resp: LLMResponse):
        print(f"{tag}_result:\n", resp.result)
        print(f"prompt_token_used: {resp.prompt_tokens}, "
              f"completion_token_used: {resp.completion_tokens}, "
              f"total_token_used: {resp.total_tokens}")
        if resp.response_time:
            print(f"response_time: {resp.response_time}s")
        if resp.session_id:
            print(f"Session ID: {resp.session_id}")
