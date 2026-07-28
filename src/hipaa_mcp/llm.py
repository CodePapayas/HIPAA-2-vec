from __future__ import annotations

import json
import sys
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
as a short, precise search query using regulatory terminology.

Do not answer the question. Do not explain the regulation. Output only search \
keywords, nothing else.

User question: {question}
Rewritten query:"""

_warned = False


def _warn_once(exc: Exception) -> None:
    """Report an LLM failure once per process, on stderr, so stdio MCP stays clean."""
    global _warned
    if _warned:
        return
    _warned = True
    print(
        f"[llm] Query rewriting unavailable ({type(exc).__name__}: {exc}). "
        "Falling back to the original question; retrieval is unaffected.",
        file=sys.stderr,
    )


async def rewrite_query(question: str, client: BaseLLMClient | None = None) -> str:
    settings = get_settings()
    if not settings.use_llm_for_query_understanding:
        return question
    llm = client or OllamaClient()
    prompt = QUERY_REWRITE_PROMPT.format(question=question)
    try:
        result = await llm.complete(prompt)
        return result.strip() or question
    except (httpx.HTTPError, json.JSONDecodeError, ValueError, OSError) as exc:
        # The LLM is an optional enhancement — a dead or misconfigured Ollama
        # (connection refused, read timeout, 404 for an unpulled model, garbage
        # JSON) must degrade to the original question, never fail the search.
        _warn_once(exc)
        return question
