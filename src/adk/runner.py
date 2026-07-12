"""
ADK runtime for Convo-Commerce.

Bridges an inbound channel message to the multi-agent system and returns the
reply text — the same contract the gateway/connectors already expect from the
legacy ConversationAgent (`handle_message(...) -> str | None`).

Responsibilities per message (mirrors ConversationAgent so behaviour is
consistent across engines):
  identify customer -> ensure conversation -> dedupe webhook redelivery ->
  log inbound -> run the ADK agents (identity injected into session state) ->
  log outbound -> return the reply.

ADK sessions are keyed by conversation_id and hold the model-side transcript in
memory, so a multi-turn conversation keeps context within a running process.
For horizontal scaling swap InMemorySessionService for ADK's
DatabaseSessionService (same interface).
"""
from __future__ import annotations

import asyncio
import logging
import os

from config import settings
from src.db.models import MessageDirection
from src.tools import tools

log = logging.getLogger("adk")

# Imported lazily inside _build so a missing google-adk install degrades to the
# legacy engine instead of crashing import of the whole gateway.
_ENGINE: "_ADKEngine | None" = None


class _ADKEngine:
    def __init__(self) -> None:
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.genai import types  # noqa: F401 — imported for _content

        from src.adk.agents import build_root_agent

        # ADK reads these at model-call time.
        if settings.ai.google_api_key and not os.getenv("GOOGLE_API_KEY"):
            os.environ["GOOGLE_API_KEY"] = settings.ai.google_api_key
        os.environ.setdefault(
            "GOOGLE_GENAI_USE_VERTEXAI", "true" if settings.adk.use_vertex else "false"
        )

        self._types = types
        self.app_name = settings.adk.app_name
        self.session_service = InMemorySessionService()
        self.runner = Runner(
            app_name=self.app_name,
            agent=build_root_agent(),
            session_service=self.session_service,
        )
        log.info("ADK multi-agent engine ready (model=%s)", settings.adk.model)

    async def _ensure_session(self, user_id: str, session_id: str, state: dict) -> None:
        existing = await self.session_service.get_session(
            app_name=self.app_name, user_id=user_id, session_id=session_id
        )
        if existing is None:
            await self.session_service.create_session(
                app_name=self.app_name, user_id=user_id, session_id=session_id, state=state
            )

    async def run(self, user_id: str, session_id: str, state: dict, text: str) -> str:
        await self._ensure_session(user_id, session_id, state)
        content = self._types.Content(role="user", parts=[self._types.Part(text=text)])
        reply_parts: list[str] = []
        async for event in self.runner.run_async(
            user_id=user_id, session_id=session_id, new_message=content
        ):
            if event.is_final_response() and event.content and event.content.parts:
                for part in event.content.parts:
                    if getattr(part, "text", None):
                        reply_parts.append(part.text)
        return "".join(reply_parts).strip()


def _engine() -> _ADKEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = _ADKEngine()
    return _ENGINE


def is_available() -> bool:
    """True if google-adk is importable and an engine can be constructed."""
    try:
        _engine()
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("ADK engine unavailable (%s) — falling back to legacy agent", exc)
        return False


async def handle_message_async(
    channel: str,
    sender_id: str,
    text: str,
    name: str | None = None,
    platform_message_id: str | None = None,
) -> str | None:
    """Process one inbound message through the ADK multi-agent system."""
    profile = tools.ensure_customer_profile(
        channel=channel,
        platform_user_id=sender_id,
        display_name=name,
        phone_number=sender_id if channel == "whatsapp" else None,
    )
    conversation = tools.ensure_conversation(profile["profile_id"])
    conversation_id = conversation["id"]

    if tools.message_already_processed(platform_message_id):
        log.info("duplicate delivery platform_message_id=%s — skipping", platform_message_id)
        return None

    tools.log_message(conversation_id, text, direction=MessageDirection.INBOUND,
                      platform_message_id=platform_message_id)

    state = {
        "customer_id": profile["customer_id"],
        "conversation_id": conversation_id,
        "channel": channel,
        "display_name": profile.get("display_name") or profile.get("full_name"),
    }
    reply = await _engine().run(
        user_id=f"{channel}:{sender_id}", session_id=conversation_id, state=state, text=text
    )
    reply = reply or "I'm here to help — could you tell me a bit more?"

    tools.log_message(conversation_id, reply, direction=MessageDirection.OUTBOUND)
    return reply


def handle_message(
    channel: str,
    sender_id: str,
    text: str,
    name: str | None = None,
    platform_message_id: str | None = None,
) -> str | None:
    """Synchronous wrapper (for scripts/demos). In async contexts such as the
    FastAPI gateway, await handle_message_async directly instead."""
    return asyncio.run(handle_message_async(channel, sender_id, text, name, platform_message_id))
