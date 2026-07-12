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
    # WHATSAPP_PROVIDER selects the delivery path: 'twilio' (default, 30-day
    # trial, 3rd party) or 'cloud' (Meta WhatsApp Cloud API).
    provider: str = field(default_factory=lambda: (_env("WHATSAPP_PROVIDER", "twilio") or "twilio").lower())
    access_token: str | None = field(default_factory=lambda: _env("WHATSAPP_ACCESS_TOKEN"))
    phone_number_id: str | None = field(default_factory=lambda: _env("WHATSAPP_PHONE_NUMBER_ID"))
    verify_token: str | None = field(default_factory=lambda: _env("WHATSAPP_VERIFY_TOKEN"))
    app_secret: str | None = field(default_factory=lambda: _env("WHATSAPP_APP_SECRET"))
    graph_version: str = field(default_factory=lambda: _env("GRAPH_API_VERSION", "v21.0") or "v21.0")


@dataclass
class TwilioConfig:
    """Twilio WhatsApp (3rd-party, 30-day trial). Uses the Twilio-hosted
    WhatsApp sandbox number in trial mode, or a purchased sender in prod."""
    account_sid: str | None = field(default_factory=lambda: _env("TWILIO_ACCOUNT_SID"))
    auth_token: str | None = field(default_factory=lambda: _env("TWILIO_AUTH_TOKEN"))
    # E.g. 'whatsapp:+14155238886' (the shared Twilio trial sandbox sender).
    whatsapp_from: str | None = field(default_factory=lambda: _env("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886"))


@dataclass
class InstagramConfig:
    """Instagram Messaging via the Meta Graph API (Instagram Professional
    account linked to a Facebook Page). Shares Meta's HMAC webhook signing."""
    page_access_token: str | None = field(default_factory=lambda: _env("INSTAGRAM_PAGE_ACCESS_TOKEN"))
    verify_token: str | None = field(default_factory=lambda: _env("INSTAGRAM_VERIFY_TOKEN"))
    app_secret: str | None = field(default_factory=lambda: _env("INSTAGRAM_APP_SECRET"))
    graph_version: str = field(default_factory=lambda: _env("GRAPH_API_VERSION", "v21.0") or "v21.0")


@dataclass
class MessengerConfig:
    page_access_token: str | None = field(default_factory=lambda: _env("MESSENGER_PAGE_ACCESS_TOKEN"))
    verify_token: str | None = field(default_factory=lambda: _env("MESSENGER_VERIFY_TOKEN"))
    app_secret: str | None = field(default_factory=lambda: _env("MESSENGER_APP_SECRET"))
    graph_version: str = field(default_factory=lambda: _env("GRAPH_API_VERSION", "v21.0") or "v21.0")


@dataclass
class TelegramConfig:
    bot_token: str | None = field(default_factory=lambda: _env("TELEGRAM_BOT_TOKEN"))
    # Set when calling setWebhook(secret_token=...); Telegram echoes it back
    # as X-Telegram-Bot-Api-Secret-Token on every webhook POST.
    webhook_secret: str | None = field(default_factory=lambda: _env("TELEGRAM_WEBHOOK_SECRET"))


@dataclass
class SupabaseConfig:
    url: str | None = field(default_factory=lambda: _env("SUPABASE_URL"))
    service_key: str | None = field(default_factory=lambda: _env("SUPABASE_SERVICE_KEY"))
    schema: str = field(default_factory=lambda: _env("SUPABASE_SCHEMA", "commerce") or "commerce")


@dataclass
class ADKConfig:
    """Google Agent Development Kit — the multi-agent brain of Convo-Commerce.

    A root orchestrator delegates to specialist sub-agents (ordering, checkout,
    tracking, refunds, recommendations). AGENT_ENGINE=adk turns it on; falling
    back to 'legacy' uses the single-loop ConversationAgent."""
    model: str = field(default_factory=lambda: _env("ADK_MODEL", "gemini-2.0-flash") or "gemini-2.0-flash")
    app_name: str = field(default_factory=lambda: _env("ADK_APP_NAME", "convo-commerce") or "convo-commerce")
    # 'false' -> use the Gemini Developer API (GOOGLE_API_KEY); 'true' -> Vertex AI.
    use_vertex: bool = field(default_factory=lambda: (_env("GOOGLE_GENAI_USE_VERTEXAI", "false") or "false").lower() == "true")


@dataclass
class DeliveryConfig:
    """Drives the ETA engine (before & after checkout) for food delivery."""
    base_prep_minutes: int = field(default_factory=lambda: int(_env("ETA_BASE_PREP_MINUTES", "20") or 20))
    min_travel_minutes: int = field(default_factory=lambda: int(_env("ETA_MIN_TRAVEL_MINUTES", "12") or 12))
    max_travel_minutes: int = field(default_factory=lambda: int(_env("ETA_MAX_TRAVEL_MINUTES", "45") or 45))
    # Peak windows (local hour) add extra minutes to reflect kitchen/road load.
    peak_hours: str = field(default_factory=lambda: _env("ETA_PEAK_HOURS", "11,12,13,18,19,20") or "11,12,13,18,19,20")
    peak_surcharge_minutes: int = field(default_factory=lambda: int(_env("ETA_PEAK_SURCHARGE_MINUTES", "15") or 15))


@dataclass
class AppConfig:
    store_name: str = field(default_factory=lambda: _env("STORE_NAME", "SYSCO Convo-Commerce") or "SYSCO Convo-Commerce")
    currency: str = field(default_factory=lambda: _env("STORE_CURRENCY", "USD") or "USD")
    payment_link_base: str = field(default_factory=lambda: _env("PAYMENT_LINK_BASE", "https://pay.example.com/checkout") or "https://pay.example.com/checkout")
    ops_api_key: str | None = field(default_factory=lambda: _env("OPS_API_KEY"))
    # 'adk' (Google ADK multi-agent) | 'legacy' (single-loop ConversationAgent)
    agent_engine: str = field(default_factory=lambda: (_env("AGENT_ENGINE", "adk") or "adk").lower())

    ai: AIConfig = field(default_factory=AIConfig)
    adk: ADKConfig = field(default_factory=ADKConfig)
    delivery: DeliveryConfig = field(default_factory=DeliveryConfig)
    whatsapp: WhatsAppConfig = field(default_factory=WhatsAppConfig)
    twilio: TwilioConfig = field(default_factory=TwilioConfig)
    messenger: MessengerConfig = field(default_factory=MessengerConfig)
    instagram: InstagramConfig = field(default_factory=InstagramConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    supabase: SupabaseConfig = field(default_factory=SupabaseConfig)


# Import this everywhere.
settings = AppConfig()
