"""
Conversation agent.

Orchestrates a single inbound message end to end:
  identify customer -> open/find conversation -> skip if already processed
  (webhook redelivery) -> log inbound -> run the model+tool loop -> log
  outbound -> hand the reply text back to the connector to deliver.

The same loop runs regardless of which AI provider is configured.
"""
from __future__ import annotations

import json
import logging

from config import settings
from src.agent.prompt import build_system_prompt
from src.ai.base import AIResponse
from src.ai.factory import get_provider
from src.db.models import MessageDirection
from src.tools import tools
from src.tools.registry import SCHEMAS, dispatch

log = logging.getLogger("agent")


class ConversationAgent:
    def __init__(self, provider_name: str | None = None) -> None:
        self.provider = get_provider(provider_name)

    # -- public API used by the connectors -------------------------------
    def handle_message(
        self,
        channel: str,
        sender_id: str,
        text: str,
        name: str | None = None,
        platform_message_id: str | None = None,
    ) -> str | None:
        """Process one inbound customer message; return the reply text (or
        None if this delivery was a duplicate and was skipped)."""
        # 1) Identify (find-or-create) the customer + their open conversation.
        profile = tools.ensure_customer_profile(
            channel=channel,
            platform_user_id=sender_id,
            display_name=name,
            phone_number=sender_id if channel == "whatsapp" else None,
        )
        conversation = tools.ensure_conversation(profile["profile_id"])
        conversation_id = conversation["id"]

        # 2) Guard against Meta's at-least-once webhook redelivery.
        if tools.message_already_processed(platform_message_id):
            log.info("duplicate delivery for platform_message_id=%s — skipping", platform_message_id)
            return None

        # 3) Persist inbound message.
        tools.log_message(conversation_id, text, direction=MessageDirection.INBOUND,
                          platform_message_id=platform_message_id)

        # 4) Build the transcript for the model (recent history + this turn).
        identity_meta = {
            "customer_id": profile["customer_id"],
            "conversation_id": conversation_id,
            "channel": channel,
        }
        transcript = self._load_transcript(conversation_id, identity_meta)

        # 5) Run the model + tool loop.
        reply = self._run_loop(channel, transcript)

        # 6) Persist + return the outbound reply.
        tools.log_message(conversation_id, reply, direction=MessageDirection.OUTBOUND)
        return reply

    # -- internal --------------------------------------------------------
    def _load_transcript(self, conversation_id: str, identity_meta: dict) -> list[dict]:
        history = tools.get_recent_messages(conversation_id, limit=12)
        transcript: list[dict] = []
        for i, m in enumerate(history):
            role = "user" if m["direction"] == MessageDirection.INBOUND else "assistant"
            content = m["message"]
            # Prepend identity context to the very first user message
            if i == 0 and role == "user":
                id_str = ", ".join(f"{k}={v}" for k, v in identity_meta.items())
                content = f"[Customer identity: {id_str}]\n{content}"
            transcript.append({"role": role, "content": content})
        return transcript

    def _run_loop(self, channel: str, transcript: list[dict]) -> str:
        system = build_system_prompt(channel)
        max_iters = settings.ai.max_tool_iterations

        for _ in range(max_iters):
            resp: AIResponse = self.provider.generate(system, transcript, SCHEMAS)
            log.info("iter resp: text=%s tools=%s", bool(resp.text), [tc.name for tc in resp.tool_calls])

            if not resp.wants_tools:
                return resp.text or "I'm here to help — could you tell me a bit more?"

            # Record the assistant's tool-call turn (preserve raw content for Gemini thought_signature).
            assistant_turn = {
                "role": "assistant",
                "tool_calls": [{"id": tc.id, "name": tc.name, "input": tc.input}
                               for tc in resp.tool_calls],
            }
            if hasattr(resp, "_raw_content") and resp._raw_content is not None:
                assistant_turn["_raw_content"] = resp._raw_content
            transcript.append(assistant_turn)
            # Execute each tool and append results.
            for tc in resp.tool_calls:
                result = dispatch(tc.name, tc.input)
                log.info("tool %s(%s) -> %s", tc.name, tc.input, _preview(result))
                transcript.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": json.dumps(result, default=str),
                })

        return ("I'm still working on that — let me connect you with a team member "
                "to finish up. Thanks for your patience!")


def _preview(obj) -> str:
    s = json.dumps(obj, default=str)
    return s if len(s) < 160 else s[:157] + "..."
