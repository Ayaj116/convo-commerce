# Conversational Commerce Agent

An AI shopping assistant that runs inside **WhatsApp Business** and **Facebook
Messenger**. It takes a customer from *“I want shoes”* all the way to a **paid,
tracked order** — using a real product catalog, real orders, and a pluggable AI
brain you can switch between **Claude, ChatGPT (OpenAI), and Gemini**.

The whole flow runs **offline with zero API keys** using a built-in deterministic
`mock` provider, so you can demo it in seconds.

```bash
python demo.py        # full discovery → order → payment → tracking demo
python tests/test_flow.py
```

---

## What it does

| Capability | How |
|---|---|
| **User initiation** | Webhooks detect a new WhatsApp / Messenger message |
| **User identification** | Phone number (WhatsApp) or PSID (Messenger) → find-or-create user |
| **Product discovery** | AI queries the catalog and recommends real items |
| **Order placement** | Confirms product, qty, address; validates stock & price; reserves stock |
| **Payment** | WhatsApp Pay / Messenger checkout / external payment link |
| **Confirmation & tracking** | Order stored, order ID returned, event-driven status updates |
| **Aftersales** | Order lookup, returns/refunds via status lifecycle |
| **Compliance** | WhatsApp 24-hour window enforced; Messenger message tags out of window |
| **Model choice** | `AI_PROVIDER = mock | claude | openai | gemini` |

---

## Architecture

Five layers, one continuous conversation. See **`docs/architecture.html`** for the
presentation-ready diagram.

```
 Customer Channels     WhatsApp Business API  ·  Facebook Messenger
        │                       (signed webhooks)
        ▼
 API Gateway           verify signature · parse · 24h-window policy · route
        │                       (normalised event)
        ▼
 Conversation Agent    identify → reason → act loop
        │              pluggable AI provider  [ claude | openai | gemini | mock ]
        ▼
 Internal Tools        getUser · getProducts · createOrder · updateOrderStatus
        │              createPaymentLink · getOrder · logMessage
        ▼
 Data Model            Users · Products · Orders · Messages  (+ order_events)
        ↺
 Event Bus             order.status_changed → push tracking update to channel
```

**Design principles:** modular channel connectors, a single API gateway,
event-driven notifications, and a database that the AI can *only* reach through
validated tool calls — never raw SQL.

---

## Project layout

```
convo-commerce/
├── config.py                  # env-driven config incl. AI provider selection
├── demo.py                    # runnable end-to-end demo (offline)
├── requirements.txt
├── .env.example
├── src/
│   ├── db/
│   │   ├── schema.sql         # relational schema (portable to Postgres)
│   │   ├── database.py        # sqlite connection + transactions
│   │   └── models.py          # domain models + OrderStatus lifecycle
│   ├── tools/
│   │   ├── tools.py           # the internal CRUD tool calls
│   │   └── registry.py        # provider-agnostic JSON tool schemas + dispatch
│   ├── ai/
│   │   ├── base.py            # normalized message/response + provider protocol
│   │   ├── factory.py         # picks provider from AI_PROVIDER
│   │   ├── mock_provider.py   # offline deterministic brain (default)
│   │   ├── claude_provider.py
│   │   ├── openai_provider.py
│   │   └── gemini_provider.py
│   ├── connectors/
│   │   ├── base.py            # HMAC signature verification
│   │   ├── whatsapp.py        # Cloud API + 24h window enforcement
│   │   └── messenger.py       # Send API + message tags
│   ├── agent/
│   │   ├── prompt.py          # system prompt / persona / guardrails
│   │   ├── conversation.py    # the identify → tool-loop orchestrator
│   │   └── notifications.py   # event bus + tracking notifier
│   └── gateway/
│       └── app.py             # FastAPI webhooks for both channels
├── scripts/seed_data.py       # demo catalog + sample customer
├── tests/test_flow.py
└── docs/architecture.html     # executive-ready architecture diagram
```

---

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # only needed for real providers / gateway
cp .env.example .env                   # then edit

python scripts/seed_data.py            # load demo catalog
```

### Choosing the AI model

Set one environment variable:

```bash
AI_PROVIDER=mock      # offline, no keys (default)
AI_PROVIDER=claude    # needs ANTHROPIC_API_KEY   (+ CLAUDE_MODEL)
AI_PROVIDER=openai    # needs OPENAI_API_KEY       (+ OPENAI_MODEL)
AI_PROVIDER=gemini    # needs GOOGLE_API_KEY       (+ GEMINI_MODEL)
```

All four providers implement the **same tool-calling loop** — the agent code path
never changes, only the adapter behind `get_provider()`.

### Running the webhook gateway

```bash
uvicorn src.gateway.app:app --reload --port 8000
```

| Method & path | Purpose |
|---|---|
| `GET  /webhook/whatsapp` · `/webhook/messenger` | Meta verification handshake |
| `POST /webhook/whatsapp` · `/webhook/messenger` | Inbound customer events |
| `POST /orders/{id}/status?status=SHIPPED` | Ops: advance an order (fires tracking) |
| `GET  /health` | Liveness + active AI provider |

Point your Meta app's webhook at these URLs (use a tunnel like ngrok in dev).

---

## The internal tool calls

The model can only act through these validated functions:

```python
getUserByPhoneOrProfileID(phone_number=…, messenger_id=…)   # fetch user
getProductsByCategoryOrSearch(query=…, category=…)          # query catalog
createOrder(user_id, product_id, quantity, delivery_address) # place order (reserves stock)
updateOrderStatus(order_id, status)                          # tracking lifecycle
createPaymentLink(order_id, method)                          # whatsapp_pay | messenger_pay | external
getOrder(order_id)                                           # tracking / aftersales
logMessage(chat_id, user_id, content)                        # conversation context
```

Order lifecycle: `PENDING_PAYMENT → PAID → PACKED → SHIPPED → OUT_FOR_DELIVERY →
DELIVERED` (or `CANCELLED` / `REFUNDED`, which restock automatically).

---

## Compliance notes

- **WhatsApp 24-hour window** — outside the window the connector refuses free-form
  text and signals that an approved **template** must be used instead.
- **Messenger** — order/shipping notifications sent outside the window use the
  `POST_PURCHASE_UPDATE` message tag.
- **Webhook security** — every inbound POST is verified against the app secret
  (`X-Hub-Signature-256`).

---

## Notes on going to production

- Swap SQLite for Postgres: replace `src/db/database.py`; the schema DDL is portable.
- Replace the in-process event bus in `notifications.py` with SNS / PubSub / Kafka.
- Add per-provider rate-limit handling, retries, and structured logging/metrics.
- Wire real WhatsApp Pay `order_details` payloads / Messenger webviews in
  `create_payment_link` and the connectors.
