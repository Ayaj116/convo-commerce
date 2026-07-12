"""
API Gateway (FastAPI) — single ingress for every channel.

  GET  /webhook/whatsapp       -> Meta verification handshake (Cloud API path)
  POST /webhook/whatsapp       -> inbound WhatsApp (Twilio form OR Meta JSON,
                                  chosen by WHATSAPP_PROVIDER)
  GET  /webhook/messenger      -> Meta verification handshake
  POST /webhook/messenger      -> inbound Messenger events
  GET  /webhook/instagram      -> Meta verification handshake
  POST /webhook/instagram      -> inbound Instagram DM events
  POST /webhook/telegram       -> inbound Telegram updates (secret-token header)
  POST /orders/{id}/status     -> ops: advance an order (emits tracking)
  POST /payments/{id}/confirm  -> ops: confirm a payment (marks PAID, invoice,
                                  and fires the real-time customer confirmation)
  GET  /health                 -> liveness + engine/provider info

The conversation is driven by the ADK multi-agent engine when AGENT_ENGINE=adk
(and google-adk is installed); otherwise it falls back to the single-loop
ConversationAgent. Either way the reply is delivered back over the originating
channel. Ops endpoints require an X-Ops-Key header matching OPS_API_KEY.

Run:  uvicorn src.gateway.app:app --reload --port 8000
"""
from __future__ import annotations

import logging
from xml.sax.saxutils import escape

from config import settings
from src.agent.notifications import advance_and_notify
from src.connectors import get_connector
from src.connectors.instagram import InstagramConnector
from src.connectors.messenger import MessengerConnector
from src.connectors.telegram import TelegramConnector
from src.connectors.twilio_whatsapp import TwilioWhatsAppConnector
from src.connectors.whatsapp import WhatsAppConnector
from src.db.database import init_db
from src.db.models import Channel
from src.tools import tools

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("gateway")

try:
    from fastapi import FastAPI, Header, HTTPException, Request, Response
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("pip install fastapi uvicorn to run the gateway") from exc

app = FastAPI(title="Convo-Commerce Gateway")

# --- Conversation engine: ADK multi-agent, or legacy single-loop fallback ----
_USE_ADK = False
_legacy_agent = None
if settings.agent_engine == "adk":
    try:
        from src.adk import runner as adk_runner
        _USE_ADK = adk_runner.is_available()
    except Exception as exc:  # noqa: BLE001
        log.warning("ADK engine could not load (%s) — using legacy agent", exc)

if not _USE_ADK:
    from src.agent.conversation import ConversationAgent
    _legacy_agent = ConversationAgent()

ENGINE_NAME = "adk-multi-agent" if _USE_ADK else "legacy-single-loop"


async def _process(channel: str, evt: dict) -> str | None:
    """Route one normalised inbound event to the active conversation engine."""
    if _USE_ADK:
        return await adk_runner.handle_message_async(
            channel, evt["sender_id"], evt["text"], evt.get("name"), evt.get("platform_message_id"))
    return _legacy_agent.handle_message(
        channel, evt["sender_id"], evt["text"], evt.get("name"), evt.get("platform_message_id"))


# Channel connectors (WhatsApp chosen by provider).
messenger = MessengerConnector()
instagram = InstagramConnector()
telegram = TelegramConnector()
whatsapp_cloud = WhatsAppConnector()
whatsapp_twilio = TwilioWhatsAppConnector()
_WA_TWILIO = settings.whatsapp.provider == "twilio"


@app.on_event("startup")
def _startup() -> None:
    init_db()
    log.info("Gateway ready. engine=%s whatsapp_provider=%s", ENGINE_NAME, settings.whatsapp.provider)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "engine": ENGINE_NAME, "whatsapp_provider": settings.whatsapp.provider}


def _require_ops_key(x_ops_key: str | None) -> None:
    if not settings.ops_api_key:
        return  # no key configured — ops endpoints open (dev only)
    if x_ops_key != settings.ops_api_key:
        raise HTTPException(status_code=401, detail="invalid or missing X-Ops-Key")


def _tool_result_or_4xx(result: dict):
    if isinstance(result, dict) and result.get("error"):
        status = 404 if "not_found" in result["error"] else 400
        raise HTTPException(status_code=status, detail=result)
    return result


def _public_url(request: Request) -> str:
    """Reconstruct the public URL Twilio signed against (honours a reverse
    proxy / tunnel via X-Forwarded-* headers)."""
    proto = request.headers.get("X-Forwarded-Proto", request.url.scheme)
    host = request.headers.get("X-Forwarded-Host", request.headers.get("host", request.url.netloc))
    return f"{proto}://{host}{request.url.path}"


# --- WhatsApp --------------------------------------------------------------
@app.get("/webhook/whatsapp")
def wa_verify(request: Request):
    p = request.query_params
    challenge = whatsapp_cloud.verify_webhook(
        p.get("hub.mode", ""), p.get("hub.verify_token", ""), p.get("hub.challenge", ""))
    return Response(content=challenge or "forbidden", status_code=200 if challenge else 403)


@app.post("/webhook/whatsapp")
async def wa_events(request: Request):
    raw = await request.body()

    # Twilio path: form-encoded body, X-Twilio-Signature, reply via TwiML.
    if _WA_TWILIO:
        from urllib.parse import parse_qs
        form = {k: v[0] for k, v in parse_qs(raw.decode("utf-8")).items()}
        if not whatsapp_twilio.verify_signature(
                _public_url(request), form, request.headers.get("X-Twilio-Signature")):
            return Response(status_code=403, content="bad twilio signature")
        reply_text = ""
        for evt in whatsapp_twilio.parse_events(form):
            reply = await _process(Channel.WHATSAPP, evt)
            if reply:
                reply_text = reply
        twiml = ('<?xml version="1.0" encoding="UTF-8"?><Response>'
                 + (f"<Message>{escape(reply_text)}</Message>" if reply_text else "")
                 + "</Response>")
        return Response(content=twiml, media_type="application/xml")

    # Meta Cloud API path: JSON body, X-Hub-Signature-256, reply via Graph API.
    if not whatsapp_cloud.verify_signature(raw, request.headers.get("X-Hub-Signature-256")):
        return Response(status_code=403, content="bad signature")
    body = await request.json()
    for evt in whatsapp_cloud.parse_events(body):
        reply = await _process(Channel.WHATSAPP, evt)
        if reply is not None:
            whatsapp_cloud.send_text(evt["sender_id"], reply)
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
        reply = await _process(Channel.MESSENGER, evt)
        if reply is not None:
            messenger.send_text(evt["sender_id"], reply)
    return {"status": "ok"}


# --- Instagram -------------------------------------------------------------
@app.get("/webhook/instagram")
def ig_verify(request: Request):
    p = request.query_params
    challenge = instagram.verify_webhook(
        p.get("hub.mode", ""), p.get("hub.verify_token", ""), p.get("hub.challenge", ""))
    return Response(content=challenge or "forbidden", status_code=200 if challenge else 403)


@app.post("/webhook/instagram")
async def ig_events(request: Request):
    raw = await request.body()
    if not instagram.verify_signature(raw, request.headers.get("X-Hub-Signature-256")):
        return Response(status_code=403, content="bad signature")
    body = await request.json()
    for evt in instagram.parse_events(body):
        reply = await _process(Channel.INSTAGRAM, evt)
        if reply is not None:
            instagram.send_text(evt["sender_id"], reply)
    return {"status": "ok"}


# --- Telegram ----------------------------------------------------------------
@app.post("/webhook/telegram")
async def tg_events(request: Request):
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if not telegram.verify_secret_token(secret):
        return Response(status_code=403, content="bad secret token")
    body = await request.json()
    for evt in telegram.parse_events(body):
        reply = await _process(Channel.TELEGRAM, evt)
        if reply is not None:
            telegram.send_text(evt["sender_id"], reply)
    return {"status": "ok"}


# --- Ops: advance an order (fulfilment systems call this) ------------------
@app.post("/orders/{order_id}/status")
def set_status(order_id: str, status: str, note: str | None = None,
               x_ops_key: str | None = Header(default=None)):
    _require_ops_key(x_ops_key)
    return _tool_result_or_4xx(advance_and_notify(order_id, status, note))


# --- Ops: confirm a payment (payment gateway / back office calls this) -----
@app.post("/payments/{payment_id}/confirm")
def confirm_payment(payment_id: str, payment_reference: str | None = None,
                    x_ops_key: str | None = Header(default=None)):
    _require_ops_key(x_ops_key)
    result = tools.mark_payment_paid(payment_id, payment_reference)
    result = _tool_result_or_4xx(result)
    if isinstance(result, dict) and result.get("id"):
        # Real-time: save to DB happened above; now push the PAID confirmation
        # (with ETA + invoice) to the customer's channel.
        from src.agent.notifications import publish
        publish("order.status_changed", {"order": result, "status": result["status"]})
    return result


# Keep an unused-import warning quiet — get_connector is used by notifications
# and available for ad-hoc outbound sends.
_ = get_connector
