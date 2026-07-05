"""
Conversation agent.

Orchestrates a single inbound message end to end:
  identify user -> log inbound -> run the model+tool loop -> log outbound
  -> hand the reply text back to the connector to deliver.

The same loop runs regardless of which AI provider is configured.
"""
from __future__ import annotations

import json
import logging

from config import settings
from src.agent.prompt import build_system_prompt
from src.ai.base import AIResponse
from src.ai.factory import get_provider
from src.db.models import Channel
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
    ) -> str:
        """Process one inbound customer message; return the reply text."""
        chat_id = f"{channel}:{sender_id}"

        # 1) Identify (find-or-create) the customer.
        if channel == Channel.WHATSAPP:
            user = tools.ensure_user(phone_number=sender_id, name=name)
            identity_meta = {"phone_number": sender_id}
        else:
            user = tools.ensure_user(messenger_id=sender_id, name=name)
            identity_meta = {"messenger_id": sender_id}
        user_id = user["user_id"]

        # 2) Persist inbound message.
        tools.log_message(chat_id, user_id, text, channel=channel, direction="in")

        # 3) Build the transcript for the model (recent history + this turn).
        transcript = self._load_transcript(chat_id, identity_meta)

        # 4) Run the model + tool loop.
        reply = self._run_loop(channel, transcript)

        # 5) Persist + return the outbound reply.
        tools.log_message(chat_id, user_id, reply, channel=channel, direction="out")
        return reply

    # -- internal --------------------------------------------------------
    def _load_transcript(self, chat_id: str, identity_meta: dict) -> list[dict]:
        history = tools.get_recent_messages(chat_id, limit=12)
        transcript: list[dict] = []
        for i, m in enumerate(history):
            role = "user" if m["direction"] == "in" else "assistant"
            entry = {"role": role, "content": m["content"]}
            # Attach channel identity to the first user turn (used by providers/mock).
            if i == 0 and role == "user":
                entry["_meta"] = identity_meta
            transcript.append(entry)
        if not transcript or transcript[-1]["role"] != "user":
            # Ensure the latest inbound is present as the trailing user turn.
            pass
        # Guarantee the very first user turn carries identity metadata.
        for entry in transcript:
            if entry["role"] == "user":
                entry.setdefault("_meta", identity_meta)
                break
        return transcript

    def _run_loop(self, channel: str, transcript: list[dict]) -> str:
        system = build_system_prompt(channel)
        max_iters = settings.ai.max_tool_iterations

        for _ in range(max_iters):
            resp: AIResponse = self.provider.generate(system, transcript, SCHEMAS)

            if not resp.wants_tools:
                return resp.text or "I'm here to help — could you tell me a bit more?"

            # Record the assistant's tool-call turn.
            transcript.append({
                "role": "assistant",
                "tool_calls": [{"id": tc.id, "name": tc.name, "input": tc.input}
                               for tc in resp.tool_calls],
            })
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
