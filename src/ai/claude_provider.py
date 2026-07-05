"""Anthropic Claude adapter (Messages API with tool use)."""
from __future__ import annotations

import json

from config import settings
from src.ai.base import AIProvider, AIResponse, ToolCall


class ClaudeProvider(AIProvider):
    name = "claude"

    def __init__(self) -> None:
        try:
            import anthropic  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pip install anthropic to use the Claude provider") from exc
        from anthropic import Anthropic

        self._client = Anthropic(api_key=settings.ai.anthropic_api_key)
        self._model = settings.ai.claude_model

    def _to_anthropic(self, messages: list[dict]) -> list[dict]:
        out: list[dict] = []
        for m in messages:
            role = m["role"]
            if role == "user":
                out.append({"role": "user", "content": m["content"]})
            elif role == "assistant" and m.get("tool_calls"):
                out.append({"role": "assistant", "content": [
                    {"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["input"]}
                    for tc in m["tool_calls"]]})
            elif role == "assistant":
                out.append({"role": "assistant", "content": m["content"]})
            elif role == "tool":
                out.append({"role": "user", "content": [{
                    "type": "tool_result", "tool_use_id": m["tool_call_id"],
                    "content": m["content"]}]})
        return out

    def generate(self, system: str, messages: list[dict], tools: list[dict]) -> AIResponse:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            temperature=settings.ai.temperature,
            system=system,
            tools=tools,  # already Anthropic input_schema format
            messages=self._to_anthropic(messages),
        )
        text_parts, calls = [], []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                calls.append(ToolCall(id=block.id, name=block.name, input=dict(block.input)))
        return AIResponse(text="\n".join(text_parts) or None, tool_calls=calls)
