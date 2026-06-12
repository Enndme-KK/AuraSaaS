"""DeepSeek multi-model client — chat, streaming, and reasoning capture."""

from __future__ import annotations

import json
import os
import re
import time
from typing import AsyncGenerator

from openai import OpenAI, Timeout
from app.core.config import get_settings

settings = get_settings()

# Supported models
MODEL_MAP = {
    "deepseek-v3": "deepseek-chat",
    "deepseek-chat": "deepseek-chat",
    "deepseek-r1": "deepseek-reasoner",
    "deepseek-reasoner": "deepseek-reasoner",
    "deepseek-v4": "deepseek-chat",          # V4 uses the same API endpoint
    "deepseek-v4-pro": "deepseek-chat",       # V4-Pro alias
}

MODEL_LABELS = {
    "deepseek-chat": "DeepSeek-V3",
    "deepseek-reasoner": "DeepSeek-R1",
    "deepseek-v3": "DeepSeek-V3",
    "deepseek-r1": "DeepSeek-R1",
    "deepseek-v4": "DeepSeek-V4",
    "deepseek-v4-pro": "DeepSeek-V4 Pro",
}


def resolve_model(model: str) -> str:
    """Resolve a user-facing model name to the API model ID."""
    return MODEL_MAP.get(model, "deepseek-chat")


def get_model_label(model: str) -> str:
    """Return the display label for a model."""
    return MODEL_LABELS.get(model, model)


def get_client(api_key: str | None = None, base_url: str | None = None) -> OpenAI:
    """Create an OpenAI-compatible client for DeepSeek."""
    key = api_key or os.getenv("DEEPSEEK_API_KEY") or settings.deepseek_api_key
    url = base_url or os.getenv("DEEPSEEK_BASE_URL") or os.getenv("OPENAI_API_BASE") or settings.deepseek_base_url
    return OpenAI(api_key=key, base_url=url)


def has_valid_api_key() -> bool:
    """Check if a real API key is configured."""
    key = os.getenv("DEEPSEEK_API_KEY") or settings.deepseek_api_key
    if not key:
        return False
    # Placeholder / demo keys — do not call real API
    placeholders = {"sk-placeholder", "sk-your-key-here", "sk-xxxx", "your-key", ""}
    return key.strip() not in placeholders


def chat(
    system: str,
    user: str,
    fallback: str,
    model: str = "deepseek-chat",
    temperature: float = 0.3,
    max_tokens: int = 800,
    api_key: str | None = None,
    base_url: str | None = None,
) -> str:
    """Synchronous chat completion with timeout and retry. Returns fallback if no valid API key."""
    if not has_valid_api_key():
        return fallback

    resolved = resolve_model(model)
    max_retries = settings.llm_max_retries
    last_error = ""

    for attempt in range(max_retries + 1):
        try:
            client = get_client(api_key, base_url)
            resp = client.chat.completions.create(
                model=resolved,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=Timeout(settings.llm_timeout_seconds),
            )
            return resp.choices[0].message.content or fallback
        except Exception as exc:
            last_error = str(exc)
            if attempt < max_retries:
                wait = 1.0 * (2 ** attempt)
                time.sleep(wait)
                continue

    return f"{fallback}\n\n[LLM 降级提示] {last_error}"


def chat_with_tools(
    messages: list[dict],
    tools: list[dict] | None = None,
    tool_choice: str = "auto",
    model: str = "deepseek-chat",
    temperature: float = 0.3,
    max_tokens: int = 1200,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict | None:
    """Chat completion with tool/function calling support.

    Returns a dict: {"role": "assistant", "content": str|None, "tool_calls": list|None}
    Returns None if no valid API key is configured.
    """
    if not has_valid_api_key():
        return None

    resolved = resolve_model(model)
    max_retries = settings.llm_max_retries
    last_error = ""

    for attempt in range(max_retries + 1):
        try:
            client = get_client(api_key, base_url)
            kwargs = {
                "model": resolved,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "timeout": Timeout(settings.llm_timeout_seconds),
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = tool_choice

            resp = client.chat.completions.create(**kwargs)
            msg = resp.choices[0].message

            tool_calls = None
            if msg.tool_calls:
                tool_calls = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ]

            return {
                "role": "assistant",
                "content": msg.content,
                "tool_calls": tool_calls,
            }
        except Exception as exc:
            last_error = str(exc)
            if attempt < max_retries:
                wait = 1.0 * (2 ** attempt)
                time.sleep(wait)
                continue

    return {
        "role": "assistant",
        "content": f"LLM 调用失败: {last_error}",
        "tool_calls": None,
    }


async def chat_stream(
    system: str,
    user: str,
    model: str = "deepseek-chat",
    temperature: float = 0.3,
    max_tokens: int = 800,
    api_key: str | None = None,
    base_url: str | None = None,
) -> AsyncGenerator[dict, None]:
    """
    Async generator that yields SSE-friendly dicts from a streaming chat completion.

    Yields dicts with:
      - type: "thinking" | "content" | "done" | "error"
      - content: str — delta text
      - think_content: str — accumulated reasoning (for R1/V4 models)
      - done: bool
    """
    resolved = resolve_model(model)

    if not has_valid_api_key():
        yield {"type": "content", "content": "[演示模式] 请在设置中配置 DeepSeek API Key 以启用 AI 功能。", "done": False}
        yield {"type": "done", "content": "", "done": True}
        return

    try:
        client = get_client(api_key, base_url)
        stream = client.chat.completions.create(
            model=resolved,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            timeout=Timeout(settings.llm_timeout_seconds),
        )

        think_buffer = ""
        content_buffer = ""
        in_think = False

        for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            text = delta.content or ""

            # Detect <think> tags for reasoning models (R1)
            if "<｜end▁of▁thinking｜><think>" in text or text.startswith("<｜end▁of▁thinking｜><think>") or " response<think>" in text:
                in_think = True
                # Strip the <｜end▁of▁thinking｜><think> prefix
                text = re.sub(r"^\s*response<think>", "", text)
            if "<｜end▁of▁thinking｜></think>" in text:
                in_think = False
                text = text.replace(" response</think>", "")
                think_buffer += text
                yield {"type": "thinking", "content": text, "think_content": think_buffer, "done": False}
                continue

            if in_think:
                think_buffer += text
                yield {"type": "thinking", "content": text, "think_content": think_buffer, "done": False}
            else:
                # Also handle the case where think tags are embedded
                if "<｜end▁of▁thinking｜><think>" in text:
                    parts = text.split(" response<think>", 1)
                    content_buffer += parts[0]
                    if parts[0]:
                        yield {"type": "content", "content": parts[0], "done": False}
                    in_think = True
                    think_buffer = parts[1] if len(parts) > 1 else ""
                    if think_buffer:
                        yield {"type": "thinking", "content": think_buffer, "think_content": think_buffer, "done": False}
                elif " response</think>" in text:
                    parts = text.split(" response</think>", 1)
                    think_buffer += parts[0]
                    yield {"type": "thinking", "content": parts[0], "think_content": think_buffer, "done": False}
                    in_think = False
                    if len(parts) > 1 and parts[1]:
                        content_buffer += parts[1]
                        yield {"type": "content", "content": parts[1], "done": False}
                else:
                    content_buffer += text
                    yield {"type": "content", "content": text, "done": False}

        yield {
            "type": "done",
            "content": content_buffer,
            "think_content": think_buffer,
            "done": True,
        }

    except Exception as exc:
        yield {"type": "error", "content": str(exc), "done": True}


async def chat_stream_sse(
    system: str,
    user: str,
    model: str = "deepseek-chat",
    temperature: float = 0.3,
    max_tokens: int = 800,
    api_key: str | None = None,
    base_url: str | None = None,
) -> AsyncGenerator[str, None]:
    """
    Convenience wrapper that yields SSE-formatted JSON strings
    suitable for EventSourceResponse.
    """
    async for event in chat_stream(system, user, model, temperature, max_tokens, api_key, base_url):
        yield json.dumps(event, ensure_ascii=False)
