"""
AI provider abstraction.

The agent speaks one normalized dialect; each provider adapter translates to
its vendor SDK and back. This is what makes Claude / ChatGPT / Gemini
interchangeable via a single AI_PROVIDER env var.

Normalized transcript format (list of dicts):
  {"role": "user",      "content": "text"}
  {"role": "assistant", "content": "text"}
  {"role": "assistant", "tool_calls": [{"id","name","input"}]}
  {"role": "tool",      "tool_call_id": "...", "name": "...", "content": "<json>"}
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class AIResponse:
    """Either free text, one or more tool calls, or both."""
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class AIProvider(Protocol):
    name: str

    def generate(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
    ) -> AIResponse:
        """One model turn given system prompt, transcript and tool schemas."""
        ...
