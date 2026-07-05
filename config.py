"""
Central configuration.

Everything is driven by environment variables so the same build runs in dev,
staging and prod without code changes. Copy .env.example to .env and fill in.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _env(key: str, default: str | None = None) -> str | None:
    val = os.getenv(key, default)
    return val.strip() if isinstance(val, str) else val


@dataclass
class AIConfig:
    # Which brain drives the conversation. One of: mock | claude | openai | gemini
    provider: str = field(default_factory=lambda: (_env("AI_PROVIDER", "mock") or "mock").lower())

    # Per-provider model names (sensible defaults; override via env)
    claude_model: str = field(default_factory=lambda: _env("CLAUDE_MODEL", "claude-sonnet-4-5") or "claude-sonnet-4-5")
    openai_model: str = field(default_factory=lambda: _env("OPENAI_MODEL", "gpt-4o") or "gpt-4o")
    gemini_model: str = field(default_factory=lambda: _env("GEMINI_MODEL", "gemini-1.5-pro") or "gemini-1.5-pro")

    anthropic_api_key: str | None = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    openai_api_key: str | None = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    google_api_key: str | None = field(default_factory=lambda: _env("GOOGLE_API_KEY"))

    max_tool_iterations: int = field(default_factory=lambda: int(_env("AI_MAX_TOOL_ITERATIONS", "6") or 6))
    temperature: float = field(default_factory=lambda: float(_env("AI_TEMPERATURE", "0.3") or 0.3))


@dataclass
class WhatsAppConfig:
    access_token: str | None = field(default_factory=lambda: _env("WHATSAPP_ACCESS_TOKEN"))
    phone_number_id: str | None = field(default_factory=lambda: _env("WHATSAPP_PHONE_NUMBER_ID"))
    verify_token: str | None = field(default_factory=lambda: _env("WHATSAPP_VERIFY_TOKEN"))
    app_secret: str | None = field(default_factory=lambda: _env("WHATSAPP_APP_SECRET"))
    graph_version: str = field(default_factory=lambda: _env("GRAPH_API_VERSION", "v21.0") or "v21.0")


@dataclass
class MessengerConfig:
    page_access_token: str | None = field(default_factory=lambda: _env("MESSENGER_PAGE_ACCESS_TOKEN"))
    verify_token: str | None = field(default_factory=lambda: _env("MESSENGER_VERIFY_TOKEN"))
    app_secret: str | None = field(default_factory=lambda: _env("MESSENGER_APP_SECRET"))
    graph_version: str = field(default_factory=lambda: _env("GRAPH_API_VERSION", "v21.0") or "v21.0")


@dataclass
class AppConfig:
    db_path: str = field(default_factory=lambda: _env("DB_PATH", "convo_commerce.db") or "convo_commerce.db")
    store_name: str = field(default_factory=lambda: _env("STORE_NAME", "Aurora Store") or "Aurora Store")
    currency: str = field(default_factory=lambda: _env("STORE_CURRENCY", "USD") or "USD")
    payment_link_base: str = field(default_factory=lambda: _env("PAYMENT_LINK_BASE", "https://pay.example.com/checkout") or "https://pay.example.com/checkout")

    ai: AIConfig = field(default_factory=AIConfig)
    whatsapp: WhatsAppConfig = field(default_factory=WhatsAppConfig)
    messenger: MessengerConfig = field(default_factory=MessengerConfig)


# Import this everywhere.
settings = AppConfig()
