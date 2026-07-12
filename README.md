# Convo-Commerce

A **multi-agent conversational commerce platform** for **SYSCO-style food
delivery**. Customers order over **WhatsApp, Telegram, Instagram, and Facebook
Messenger** in plain language; a team of AI agents takes them from *"reorder my
usuals"* all the way to a **paid, tracked, delivered order** — with a real
catalog, real orders, real payments, and a live **Supabase** database.

The agent brain is built on the **Google Agent Development Kit (ADK)**: a root
orchestrator delegates each message to a specialist sub-agent (ordering,
checkout, tracking, refunds, recommendations). WhatsApp is integrated through
**Twilio** (3rd-party, works on a 30-day trial with no Meta app review), with
the Meta Cloud API available as an alternative path.

```bash
python scripts/seed_data.py    # seed the SYSCO food catalog (idempotent)
python demo_tools.py           # NO LLM — validates ETA/order/payment/refund/recs vs Supabase
python demo_adk.py             # full multi-agent conversation (needs google-adk + GOOGLE_API_KEY)
```

---

## What it does

| Capability | How |
|---|---|
| **Omnichannel intake** | Webhooks read messages from WhatsApp (Twilio *or* Meta), Telegram, Instagram, Messenger; redelivery is de-duped via `platform_message_id` |
| **Multi-agent brain (ADK)** | Root orchestrator → ordering / checkout / tracking / refund / recommendation specialists, each with only the tools it needs |
| **Identity** | Phone (WhatsApp), IGSID (Instagram), PSID (Messenger), chat id (Telegram) → find-or-create `customers` + `customer_profiles`; identity is injected into agent session state, never asked for or spoofable |
| **Personalised recs** | Returning customers get re-order suggestions built from their own order history (falls back to popular in-stock items) |
| **Ordering** | Multi-item food orders; server-computed pricing; atomic stock decrement (Postgres function, no oversell race) |
| **ETA before & after checkout** | Pre-checkout: a delivery *window* ("40–55 min") from the address registered to the profile. Post-checkout: a *promised arrival time* anchored to the order, saved on the order |
| **Payments** | A secure payment link at checkout; on confirmation the order is saved PAID **in real time** and the customer gets an automatic text confirmation (with ETA + invoice) on their channel |
| **Follow-ups & tracking** | Status lifecycle + event-driven notifications pushed back to the originating channel |
| **Refunds** | `process_refund` refunds the payment, cancels + restocks the order, and voids the invoice |
| **Invoicing** | Invoice auto-issued on payment confirmation |

---

## Architecture

```
 Channels        WhatsApp (Twilio / Meta) · Telegram · Instagram · Messenger
     │                     signed webhooks (HMAC / Twilio sig / secret token)
     ▼
 API Gateway     verify · parse · route          (src/gateway/app.py)
     │                     (normalised event)
     ▼
 ADK Multi-Agent   convo_commerce_root  (orchestrator / router)
     │             ├── ordering_agent        discovery → cart → address → ETA → order
     │             ├── checkout_agent         payment link + promised ETA
     │             ├── tracking_agent         status · follow-ups · invoice
     │             ├── refund_agent           refunds / aftersales
     │             └── recommendation_agent   personalised re-orders
     ▼
 Tools           find_menu_items · save_my_address · delivery_eta · place_order ·
     │           checkout · order_status · my_orders · get_order_invoice ·
     │           refund_order · recommend_for_me   (validated; no raw SQL for the model)
     ▼
 Data (Supabase) customers/customer_profiles · customer_addresses · conversations/
     │           messages · products · orders/order_items/order_status_history ·
     │           payments · invoices                     (PostgREST, schema `commerce`)
     ↺
 Event Bus       order.status_changed → real-time channel confirmation (ETA + invoice)
```

The agent can only touch the database through validated tool calls (never raw
SQL), all DB access uses the Supabase `service_role` key server-side, and the
customer's identity lives in session state — so an agent can't act as a
different customer. If `google-adk` isn't installed, the gateway falls back to
the single-loop `ConversationAgent` (`AGENT_ENGINE=legacy`).

---

## Project layout

```
convo-commerce-AI/
├── config.py                     # env-driven config (agent engine, ETA, channels)
├── demo_tools.py                 # NO-LLM validation of the new logic vs Supabase
├── demo_adk.py                   # multi-agent conversation demo
├── src/
│   ├── adk/                      # Google ADK multi-agent brain
│   │   ├── adk_tools.py          #   tools the agents call (identity from session state)
│   │   ├── agents.py             #   root orchestrator + 5 specialist sub-agents
│   │   └── runner.py             #   session mgmt + message→reply bridge (async + sync)
│   ├── tools/
│   │   ├── tools.py              # business logic incl. ETA, refunds, recs, addresses
│   │   ├── eta.py                # delivery ETA engine (pre & post checkout)
│   │   └── registry.py           # tool schemas for the legacy provider path
│   ├── connectors/
│   │   ├── __init__.py           # channel→connector factory (WhatsApp provider switch)
│   │   ├── twilio_whatsapp.py    # WhatsApp via Twilio (30-day trial)
│   │   ├── whatsapp.py           # WhatsApp via Meta Cloud API (alt path)
│   │   ├── instagram.py          # Instagram DMs (Graph API)
│   │   ├── messenger.py          # Facebook Messenger
│   │   └── telegram.py           # Telegram Bot API
│   ├── agent/                    # legacy single-loop engine + notifications
│   ├── db/
│   │   ├── migration_001.sql     # base columns + stock functions
│   │   ├── migration_003.sql     # customer_addresses + orders.promised_eta
│   │   └── database.py           # PostgREST REST wrapper
│   └── gateway/app.py            # FastAPI webhooks for every channel
├── scripts/seed_data.py          # SYSCO food catalog
└── docs/architecture.html        # architecture diagram
```

---

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # (Windows: .venv\Scripts\activate)
pip install -r requirements.txt
cp .env.example .env                                # then edit
```

Run the SQL migrations once in the Supabase SQL Editor:
`src/db/migration_001.sql` then `src/db/migration_003.sql`. Then:

```bash
python scripts/seed_data.py       # SYSCO food catalog
python demo_tools.py              # validate the flow with no LLM
```

### Agent engine

```bash
AGENT_ENGINE=adk        # Google ADK multi-agent (default)
ADK_MODEL=gemini-2.0-flash
GOOGLE_API_KEY=...      # ADK uses the Gemini Developer API by default
AGENT_ENGINE=legacy     # fall back to the single-loop ConversationAgent
```

### WhatsApp via Twilio (30-day trial)

```bash
WHATSAPP_PROVIDER=twilio
TWILIO_ACCOUNT_SID=...          # Twilio Console → Account Info
TWILIO_AUTH_TOKEN=...
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886   # Twilio WhatsApp sandbox sender
```

In the Twilio Console → *Messaging → Try it out → WhatsApp sandbox*, join the
sandbox from your phone, then point the sandbox **"When a message comes in"**
webhook at `POST https://<your-tunnel>/webhook/whatsapp`. The connector verifies
Twilio's `X-Twilio-Signature` and replies with TwiML. Set
`WHATSAPP_PROVIDER=cloud` to use the Meta Cloud API creds instead.

### Running the gateway

```bash
uvicorn src.gateway.app:app --reload --port 8000
```

| Method & path | Purpose |
|---|---|
| `POST /webhook/whatsapp` | Inbound WhatsApp (Twilio form or Meta JSON, per `WHATSAPP_PROVIDER`) |
| `GET/POST /webhook/messenger` · `/webhook/instagram` | Meta verify handshake + inbound events |
| `POST /webhook/telegram` | Inbound Telegram (secret-token header) |
| `POST /orders/{id}/status?status=SHIPPED` | Ops: advance an order (fires tracking) |
| `POST /payments/{id}/confirm?payment_reference=...` | Ops: confirm payment → saves PAID, issues invoice, sends real-time confirmation |
| `GET /health` | Liveness + active engine / WhatsApp provider |

Ops endpoints require an `X-Ops-Key` header matching `OPS_API_KEY`. For Instagram
and Messenger, point the Meta app webhooks at the URLs above; for Telegram run
`python scripts/set_telegram_webhook.py https://<your-tunnel>` once.

---

## ETA, recommendations, refunds

- **ETA** (`src/tools/eta.py`) is deterministic — no maps dependency — so a demo
  quotes stable, believable windows. Travel time is a stable function of the
  delivery zone (postal code / city) plus kitchen prep and a peak-hour surcharge
  (all tunable via `ETA_*` env vars). Swap `_travel_minutes` for a real routing
  API in production without touching callers.
- **Recommendations** (`recommend_for_customer`) rank the customer's own most-
  ordered products first (ideal for food re-orders), topping up with popular
  in-stock items so there's always a suggestion.
- **Refunds** (`process_refund`) mark the payment `REFUNDED`, cancel the order
  (which restocks it), and void the invoice — surfaced to the customer with the
  refunded amount.

---

## Notes on going to production

- Swap ADK's `InMemorySessionService` for `DatabaseSessionService` so agent
  sessions survive restarts and scale horizontally.
- Replace the in-process event bus (`notifications.py`) with SNS / PubSub / Kafka.
- Wire a real payment gateway webhook (Stripe/Razorpay/etc.) into
  `POST /payments/{id}/confirm` instead of triggering it from ops.
- Behind a proxy/tunnel, set `X-Forwarded-Proto/Host` so Twilio signature
  verification reconstructs the correct public URL.
- Rotate `OPS_API_KEY` and put the ops endpoints behind real auth before
  exposing the gateway publicly.
