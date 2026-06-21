import sqlite3
from pathlib import Path

conn = sqlite3.connect(Path(r"C:\Users\alaga\Desktop\My Script Library\My Telegram Bot\data\research.sqlite"))
conn.row_factory = sqlite3.Row
for row in conn.execute(
    """
    SELECT alert_id, token_address, alert_time, ROUND(alert_fdv, 2) AS fdv
    FROM bot_alerts
    ORDER BY alert_time DESC
    LIMIT 8
    """
):
    print(dict(row))
conn.close()
