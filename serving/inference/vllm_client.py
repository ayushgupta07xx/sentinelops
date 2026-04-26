"""
Thin OpenAI-compatible client for the Modal vLLM endpoint.

Reads MODAL_VLLM_BASE_URL + MODAL_VLLM_API_KEY from environment (loaded
from .env at process start — see serving/api/main.py).

Single function `chat()` — synchronous, blocking. Use asyncio.to_thread
when calling from async FastAPI handlers (already done in main.py).
"""
import os
from typing import Optional

import httpx

DEFAULT_MODEL = "sentinelops-mistral7b"
DEFAULT_TIMEOUT = 600.0  # 10 min — covers Modal cold start


def _client_config() -> tuple[str, str]:
    base = os.environ.get("MODAL_VLLM_BASE_URL")
    key = os.environ.get("MODAL_VLLM_API_KEY")
    if not base or not key:
        raise RuntimeError(
            "MODAL_VLLM_BASE_URL and MODAL_VLLM_API_KEY must be set "
            "(check .env is loaded)."
        )
    return base.rstrip("/"), key


def chat(
    prompt: str,
    *,
    system: Optional[str] = None,
    max_tokens: int = 512,
    temperature: float = 0.3,
    model: str = DEFAULT_MODEL,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """
    Send a single-turn chat completion. Returns the assistant text.

    Caller passes a fully-formed prompt (already includes retrieved context
    if RAG is in use). System message is optional.
    """
    base, api_key = _client_config()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=timeout) as client:
        r = client.post(f"{base}/chat/completions", json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    return data["choices"][0]["message"]["content"].strip()
