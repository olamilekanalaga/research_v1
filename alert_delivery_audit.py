import sqlite3
from pathlib import Path

DB = Path(r"C:\Users\alaga\Desktop\My Script Library\My Telegram Bot\data\research.sqlite")
START = "2026-06-08T23:00:00+00:00"

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

print("summary")
print(
    dict(
        conn.execute(
            """
            SELECT COUNT(*) total,
                   SUM(CASE WHEN telegram_message_id IS NOT NULL THEN 1 ELSE 0 END) with_msg_id,
                   MIN(alert_time) first_alert,
                   MAX(alert_time) last_alert
            FROM bot_alerts
            WHERE alert_time >= ?
            """,
            (START,),
        ).fetchone()
    )
)

print("hourly_utc")
for row in conn.execute(
    """
    SELECT substr(alert_time, 1, 13) || ':00' AS hour_utc, COUNT(*) AS alerts
    FROM bot_alerts
    WHERE alert_time >= ?
    GROUP BY hour_utc
    ORDER BY hour_utc
    """,
    (START,),
):
    print(dict(row))

print("latest")
for row in conn.execute(
    """
    SELECT alert_id, token_address, alert_time, ROUND(alert_fdv, 2) AS fdv, telegram_message_id
    FROM bot_alerts
    WHERE alert_time >= ?
    ORDER BY alert_time DESC
    LIMIT 15
    """,
    (START,),
):
    print(dict(row))

conn.close()
