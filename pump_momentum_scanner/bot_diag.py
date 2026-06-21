from __future__ import annotations

import sqlite3

from .config import get_settings
from .telegram_alerts import TelegramAlerts


def main() -> None:
    settings = get_settings()
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row

    print("bot_state")
    for row in conn.execute("SELECT key, value FROM bot_state"):
        print(dict(row))

    print("\ntelegram api logs")
    for row in conn.execute(
        "SELECT timestamp, endpoint, status_code, error_message FROM api_logs WHERE source='telegram' ORDER BY id DESC LIMIT 10"
    ):
        print(dict(row))

    alerts = TelegramAlerts(settings.telegram_bot_token, settings.telegram_chat_id)
    print("\ngetUpdates")
    updates = alerts.get_updates()
    print(f"updates={len(updates)}")
    for update in updates[-5:]:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        print(
            {
                "update_id": update.get("update_id"),
                "chat_id": chat.get("id"),
                "text": message.get("text"),
            }
        )


if __name__ == "__main__":
    main()
