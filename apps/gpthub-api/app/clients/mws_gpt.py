from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx

from app.core.settings import get_settings


class MWSGPTClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.base_url = self.settings.mws_gpt_base_url.rstrip("/")

    async def list_models(self) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self.settings.mws_gpt_api_key}"}
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(f"{self.base_url}/models", headers=headers)
            response.raise_for_status()
            return response.json()

    async def chat_completions(
        self,
        model: str,
        messages: Sequence[dict[str, Any]],
        temperature: float = 0.6,
        max_tokens: int = 400,
        stream: bool = False,
    ) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.settings.mws_gpt_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(f"{self.base_url}/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            return response.json()
