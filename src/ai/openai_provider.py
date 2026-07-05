"""OpenAI (ChatGPT) adapter — Chat Completions API with function/tool calling."""
from __future__ import annotations

import json

from config import settings
from src.ai.base import AIProvider, AIResponse, ToolCall


def _to_openai_tools(tools: list[dict]) -> list[dict]:
    return [{
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        },
    } for t in tools]


class OpenAIProvider(AIProvider):
    name = "openai"

    def __init__(self) -> None:
        try:
            import openai  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pip install openai to use the ChatGPT provider") from exc
        from openai import OpenAI

        self._client = OpenAI(api_key=settings.ai.openai_api_key)
        self._model = settings.ai.openai_model

    def _to_openai_messages(self, system: str, messages: list[dict]) -> list[dict]:
        out: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            role = m["role"]
            if role == "user":
                out.append({"role": "user", "content": m["content"]})
            elif role == "assistant" and m.get("tool_calls"):
                out.append({"role": "assistant", "content": None, "tool_calls": [
                    {"id": tc["id"], "type": "function",
                     "function": {"name": tc["name"], "arguments": json.dumps(tc["input"])}}
                    for tc in m["tool_calls"]]})
            elif role == "assistant":
                out.append({"role": "assistant", "content": m["content"]})
            elif role == "tool":
                out.append({"role": "tool", "tool_call_id": m["tool_call_id"],
                            "content": m["content"]})
        return out

    def generate(self, system: str, messages: list[dict], tools: list[dict]) -> AIResponse:
        resp = self._client.chat.completions.create(
            model=self._model,
            temperature=settings.ai.temperature,
            tools=_to_openai_tools(tools),
            messages=self._to_openai_messages(system, messages),
        )
        msg = resp.choices[0].message
        calls = []
        for tc in (msg.tool_calls or []):
            calls.append(ToolCall(id=tc.id, name=tc.function.name,
                                  input=json.loads(tc.function.arguments or "{}")))
        return AIResponse(text=msg.content, tool_calls=calls)
