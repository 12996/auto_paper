"""
arxiv_finder LLM adapter.

This module keeps the old `LLMClient(config)` + `LLMResponse` interface used by
arxiv_finder, while delegating actual calls to the shared implementation in
project root `llm_client/`.
"""

from dataclasses import dataclass
from time import perf_counter
from typing import Dict, List, Optional

from arxiv_finder.config import AppConfig
from llm_client import LLMClient as SharedLLMClient


@dataclass
class LLMResponse:
    """Compatibility response shape used by arxiv_finder callers."""

    result: str = ""
    session_id: Optional[str] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    response_time: float = 0.0


class LLMClient:
    """
    Compatibility wrapper around shared `llm_client.LLMClient`.

    Existing arxiv_finder callsites can still use:
      client = LLMClient(AppConfig(...))
      resp = client.chat(messages, session_id=...)
      text = resp.result
    """

    def __init__(self, config: AppConfig):
        self.config = config

        api_base, api_key, model = self._resolve_runtime_config(config)
        self._client = SharedLLMClient(
            api_base=api_base,
            api_key=api_key,
            model=model,
        )

    @staticmethod
    def _resolve_runtime_config(config: AppConfig) -> tuple[str, str, str]:
        """Resolve config priority: LocalModel > OpenAI > Azure OpenAI."""
        if config.use_local_model:
            local = config.local_model_config
            return local["api_base"], local["api_key"], local["model"]

        openai_cfg = config.openai_config
        api_keys = openai_cfg.get("api_keys", []) if openai_cfg else []
        if openai_cfg and api_keys:
            return (
                openai_cfg.get("api_base", "https://api.openai.com/v1"),
                api_keys[0],
                openai_cfg.get("model", "gpt-3.5-turbo"),
            )

        azure_cfg = config.azure_config
        if azure_cfg and azure_cfg.get("api_key"):
            return (
                azure_cfg.get("api_base", "https://api.openai.com/v1"),
                azure_cfg["api_key"],
                azure_cfg.get("model", "gpt-3.5-turbo"),
            )

        raise ValueError("No available LLM config found in apikey.ini.")

    def chat(self, messages: List[Dict], session_id: Optional[str] = None) -> LLMResponse:
        """
        Execute chat request via shared client.

        Note:
        - shared client currently returns plain text only.
        - token usage/session fields are kept for compatibility and set to 0/None.
        """
        start = perf_counter()
        text = self._client.chat(messages=messages)
        elapsed = perf_counter() - start

        return LLMResponse(
            result=text or "",
            session_id=session_id,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            response_time=elapsed,
        )

