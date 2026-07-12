"""
One-time setup: register the gateway's public URL as this bot's Telegram
webhook. Run once after deploying (or after changing the tunnel/domain).

    python scripts/set_telegram_webhook.py https://your-domain.example.com

Requires TELEGRAM_BOT_TOKEN (and TELEGRAM_WEBHOOK_SECRET, recommended) in .env.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.connectors.telegram import TelegramConnector


def run(base_url: str) -> None:
    url = base_url.rstrip("/") + "/webhook/telegram"
    result = TelegramConnector().set_webhook(url)
    print(result)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/set_telegram_webhook.py https://your-domain.example.com")
        sys.exit(1)
    run(sys.argv[1])
