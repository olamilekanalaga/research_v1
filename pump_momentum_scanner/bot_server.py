from __future__ import annotations

import sqlite3
import time

from .config import get_settings
from .db import init_db
from .scanner import command_reply, scalar
from .telegram_alerts import TelegramAlerts


def poll_once(conn: sqlite3.Connection, alerts: TelegramAlerts) -> int:
    raw_offset = scalar(conn, "SELECT value FROM bot_state WHERE key='telegram_update_offset'")
    offset = int(raw_offset) if raw_offset else None
    updates = alerts.get_updates(offset)
    max_update_id = None
    answered = 0

    for update in updates:
        max_update_id = max(max_update_id or update["update_id"], update["update_id"])
        message = update.get("message") or update.get("edited_message") or {}
        text = (message.get("text") or "").strip()
        chat = message.get("chat") or {}
        if not text or str(chat.get("id")) != str(alerts.chat_id):
            continue
        alerts.send(command_reply(conn, text))
        answered += 1

    if max_update_id is not None:
        conn.execute(
            "INSERT OR REPLACE INTO bot_state(key, value) VALUES('telegram_update_offset', ?)",
            (str(max_update_id + 1),),
        )
        conn.commit()
    return answered


def main() -> None:
    settings = get_settings()
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    alerts = TelegramAlerts(settings.telegram_bot_token, settings.telegram_chat_id)
    alerts.send("BOT COMMAND LISTENER STARTED\n\nCommands now answer separately from the scanner.")

    while True:
        try:
            poll_once(conn, alerts)
        except Exception as exc:
            conn.execute(
                "INSERT INTO api_logs(timestamp, source, endpoint, error_message, latency_ms) VALUES(?,?,?,?,?)",
                (int(time.time()), "telegram", "bot_server", str(exc), 0),
            )
            conn.commit()
            time.sleep(5)
        time.sleep(2)


if __name__ == "__main__":
    main()
