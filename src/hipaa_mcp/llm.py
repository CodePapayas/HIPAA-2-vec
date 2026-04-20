from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from hipaa_mcp.config import get_settings


class BaseLLMClient(ABC):
    @abstractmethod
    async def complete(self, prompt: str) -> str: ...


class OllamaClient(BaseLLMClient):
    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self._base_url = base_url or settings.ollama_url
        self._model = model or settings.llm_model

    async def complete(self, prompt: str) -> str:
        url = f"{self._base_url}/api/generate"
        payload = {"model": self._model, "prompt": prompt, "stream": False}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return str(data.get("response", ""))


QUERY_REWRITE_PROMPT = """\
You are a HIPAA regulation search assistant. Rewrite the following user question \
as a short, precise search query using regulatory terminology. Output only the \
rewritten query, nothing else.

User question: {question}
Rewritten query:"""


async def rewrite_query(question: str, client: BaseLLMClient | None = None) -> str:
    settings = get_settings()
    if not settings.use_llm_for_query_understanding:
        return question
    llm = client or OllamaClient()
    prompt = QUERY_REWRITE_PROMPT.format(question=question)
    try:
        result = await llm.complete(prompt)
        return result.strip() or question
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError):
        return question
