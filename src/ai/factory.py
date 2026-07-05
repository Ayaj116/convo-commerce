"""
Factory: return the configured AI provider.

    AI_PROVIDER=mock    -> offline deterministic (default, no keys needed)
    AI_PROVIDER=claude  -> Anthropic Claude
    AI_PROVIDER=openai  -> OpenAI ChatGPT
    AI_PROVIDER=gemini  -> Google Gemini
"""
from __future__ import annotations

from functools import lru_cache

from config import settings
from src.ai.base import AIProvider


@lru_cache(maxsize=None)
def get_provider(name: str | None = None) -> AIProvider:
    provider = (name or settings.ai.provider).lower()

    if provider == "mock":
        from src.ai.mock_provider import MockProvider
        return MockProvider()
    if provider == "claude":
        from src.ai.claude_provider import ClaudeProvider
        return ClaudeProvider()
    if provider == "openai":
        from src.ai.openai_provider import OpenAIProvider
        return OpenAIProvider()
    if provider == "gemini":
        from src.ai.gemini_provider import GeminiProvider
        return GeminiProvider()

    raise ValueError(f"Unknown AI_PROVIDER '{provider}'. "
                     f"Use one of: mock, claude, openai, gemini.")
