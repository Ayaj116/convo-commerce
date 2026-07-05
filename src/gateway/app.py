"""
API Gateway (FastAPI).

Single ingress for both channels:
  GET  /webhook/whatsapp   -> Meta verification handshake
  POST /webhook/whatsapp   -> inbound WhatsApp events
  GET  /webhook/messenger  -> Meta verification handshake
  POST /webhook/messenger  -> inbound Messenger events
  POST /orders/{id}/status -> ops endpoint to advance an order (emits tracking)
  GET  /health             -> liveness

Each POST verifies the X-Hub-Signature-256 header, parses events, runs the
ConversationAgent, and delivers the reply back over the originating channel.

Run:  uvicorn src.gateway.app:app --reload --port 8000
"""
from __future__ import annotations

import logging

from src.agent.conversation import ConversationAgent
from src.agent.notifications import advance_and_notify
from src.connectors.messenger import MessengerConnector
from src.connectors.whatsapp import WhatsAppConnector
from src.db.database import init_db
from src.db.models import Channel

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("gateway")

try:
    from fastapi import FastAPI, Request, Response
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("pip install fastapi uvicorn to run the gateway") from exc

app = FastAPI(title="Conversational Commerce Gateway")

agent = ConversationAgent()
whatsapp = WhatsAppConnector()
messenger = MessengerConnector()


@app.on_event("startup")
def _startup() -> None:
    init_db()
    log.info("Gateway ready. AI provider = %s", agent.provider.name)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "ai_provider": agent.provider.name}


# --- WhatsApp --------------------------------------------------------------
@app.get("/webhook/whatsapp")
def wa_verify(request: Request):
    p = request.query_params
    challenge = whatsapp.verify_webhook(
        p.get("hub.mode", ""), p.get("hub.verify_token", ""), p.get("hub.challenge", ""))
    return Response(content=challenge or "forbidden", status_code=200 if challenge else 403)


@app.post("/webhook/whatsapp")
async def wa_events(request: Request):
    raw = await request.body()
    if not whatsapp.verify_signature(raw, request.headers.get("X-Hub-Signature-256")):
        return Response(status_code=403, content="bad signature")
    body = await request.json()
    for evt in whatsapp.parse_events(body):
        reply = agent.handle_message(Channel.WHATSAPP, evt["sender_id"],
                                     evt["text"], evt.get("name"))
        whatsapp.send_text(evt["sender_id"], reply)
    return {"status": "ok"}


# --- Messenger -------------------------------------------------------------
@app.get("/webhook/messenger")
def ms_verify(request: Request):
    p = request.query_params
    challenge = messenger.verify_webhook(
        p.get("hub.mode", ""), p.get("hub.verify_token", ""), p.get("hub.challenge", ""))
    return Response(content=challenge or "forbidden", status_code=200 if challenge else 403)


@app.post("/webhook/messenger")
async def ms_events(request: Request):
    raw = await request.body()
    if not messenger.verify_signature(raw, request.headers.get("X-Hub-Signature-256")):
        return Response(status_code=403, content="bad signature")
    body = await request.json()
    for evt in messenger.parse_events(body):
        reply = agent.handle_message(Channel.MESSENGER, evt["sender_id"],
                                     evt["text"], evt.get("name"))
        messenger.send_text(evt["sender_id"], reply)
    return {"status": "ok"}


# --- Ops: advance an order (fulfilment systems call this) ------------------
@app.post("/orders/{order_id}/status")
def set_status(order_id: int, status: str, note: str | None = None):
    order = advance_and_notify(order_id, status, note)
    return order
