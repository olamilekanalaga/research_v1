import sqlite3
from datetime import datetime, timezone
from pathlib import Path


DB = Path(r"C:\Users\alaga\Desktop\My Script Library\My Telegram Bot\data\research.sqlite")


def main() -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    local_tz = timezone.utc
    now_local = datetime.now(local_tz)
    # London is BST (UTC+1) on 2026-06-09. Avoid requiring the optional tzdata package.
    now_local = now_local.replace() + (datetime.now(timezone.utc) - datetime.now(timezone.utc))
    start_local = now_local.replace(hour=23, minute=0, second=0, microsecond=0)
    if now_local.hour >= 23:
        start_local = start_local
    else:
        start_local = start_local.replace(day=start_local.day - 1)
    start_utc = start_local.astimezone(timezone.utc).isoformat()
    now_utc = now_local.astimezone(timezone.utc).isoformat()

    def one(sql: str, params=()):
        return conn.execute(sql, params).fetchone()[0]

    alerts = one(
        "SELECT COUNT(*) FROM bot_alerts WHERE alert_time >= ? AND alert_time < ?",
        (start_utc, now_utc),
    )
    hit2 = one(
        """
        SELECT COUNT(DISTINCT b.alert_id)
        FROM bot_alerts b
        JOIN token_milestone_alerts m ON m.alert_id = b.alert_id
        WHERE b.alert_time >= ? AND b.alert_time < ?
          AND m.milestone_x >= 2 AND m.milestone_x <= 1000
        """,
        (start_utc, now_utc),
    )
    hit5 = one(
        """
        SELECT COUNT(DISTINCT b.alert_id)
        FROM bot_alerts b
        JOIN token_milestone_alerts m ON m.alert_id = b.alert_id
        WHERE b.alert_time >= ? AND b.alert_time < ?
          AND m.milestone_x >= 5 AND m.milestone_x <= 1000
        """,
        (start_utc, now_utc),
    )
    hit10 = one(
        """
        SELECT COUNT(DISTINCT b.alert_id)
        FROM bot_alerts b
        JOIN token_milestone_alerts m ON m.alert_id = b.alert_id
        WHERE b.alert_time >= ? AND b.alert_time < ?
          AND m.milestone_x >= 10 AND m.milestone_x <= 1000
        """,
        (start_utc, now_utc),
    )
    best = one(
        """
        SELECT COALESCE(MAX(m.milestone_x), 0)
        FROM bot_alerts b
        JOIN token_milestone_alerts m ON m.alert_id = b.alert_id
        WHERE b.alert_time >= ? AND b.alert_time < ?
          AND m.milestone_x <= 1000
        """,
        (start_utc, now_utc),
    )
    stalled_60 = one(
        """
        SELECT COUNT(*)
        FROM bot_alerts b
        WHERE b.alert_time >= ?
          AND b.alert_time < datetime('now', '-60 minutes')
          AND NOT EXISTS (
            SELECT 1 FROM token_milestone_alerts m
            WHERE m.alert_id = b.alert_id
              AND m.milestone_x >= 2 AND m.milestone_x <= 1000
          )
        """,
        (start_utc,),
    )

    vol_rows = conn.execute(
        """
        WITH outcomes AS (
          SELECT b.alert_id, COALESCE(f.buy_volume_1m,0) AS v1m,
                 COALESCE(MAX(CASE WHEN m.milestone_x <= 1000 THEN m.milestone_x END),0) AS max_x
          FROM bot_alerts b
          LEFT JOIN alert_feature_snapshots f ON f.alert_id = b.alert_id
          LEFT JOIN token_milestone_alerts m ON m.alert_id = b.alert_id
          WHERE b.alert_time >= ? AND b.alert_time < ?
          GROUP BY b.alert_id, v1m
        )
        SELECT CASE
            WHEN v1m < 10000 THEN '<10k'
            WHEN v1m < 15000 THEN '10k-15k'
            WHEN v1m < 25000 THEN '15k-25k'
            ELSE '25k+'
          END AS bucket,
          COUNT(*) alerts,
          SUM(CASE WHEN max_x >= 2 THEN 1 ELSE 0 END) hit2,
          ROUND(100.0 * SUM(CASE WHEN max_x >= 2 THEN 1 ELSE 0 END) / COUNT(*), 2) hit_rate,
          ROUND(MAX(max_x), 2) best
        FROM outcomes
        GROUP BY bucket
        ORDER BY CASE bucket WHEN '<10k' THEN 1 WHEN '10k-15k' THEN 2 WHEN '15k-25k' THEN 3 ELSE 4 END
        """,
        (start_utc, now_utc),
    ).fetchall()

    shadow_total = conn.execute(
        """
        SELECT COUNT(*) c,
               SUM(CASE WHEN status = 'OPEN' THEN 1 ELSE 0 END) open_c,
               SUM(CASE WHEN status = 'CLOSED' THEN 1 ELSE 0 END) closed_c,
               SUM(CASE WHEN status = 'SKIPPED' THEN 1 ELSE 0 END) skipped_c,
               ROUND(SUM(CASE WHEN status = 'CLOSED' THEN COALESCE(pnl_usd,0) ELSE 0 END), 2) realized_pnl,
               SUM(CASE WHEN status = 'CLOSED' AND COALESCE(pnl_usd,0) > 0 THEN 1 ELSE 0 END) wins,
               SUM(CASE WHEN status = 'CLOSED' AND COALESCE(pnl_usd,0) < 0 THEN 1 ELSE 0 END) losses
        FROM execution_positions
        WHERE opened_at >= ? AND opened_at < ?
        """,
        (start_utc, now_utc),
    ).fetchone()
    shadow_rows = conn.execute(
        """
        SELECT status, exit_reason, COUNT(*) c,
               ROUND(SUM(COALESCE(pnl_usd,0)), 2) pnl_usd,
               ROUND(AVG(COALESCE(pnl_pct,0)), 2) avg_pnl_pct
        FROM execution_positions
        WHERE opened_at >= ? AND opened_at < ?
        GROUP BY status, exit_reason
        ORDER BY c DESC
        """,
        (start_utc, now_utc),
    ).fetchall()
    open_rows = conn.execute(
        """
        SELECT execution_id, token_symbol, token_address, entry_usd, entry_fdv,
               current_fdv, highest_fdv, pnl_usd, pnl_pct, opened_at
        FROM execution_positions
        WHERE opened_at >= ? AND opened_at < ? AND status = 'OPEN'
        ORDER BY opened_at DESC
        """,
        (start_utc, now_utc),
    ).fetchall()

    print("WINDOW", start_local.isoformat(), now_local.isoformat())
    print("ALERTS", alerts, hit2, hit5, hit10, round(float(best or 0), 2), alerts - hit2, stalled_60)
    print("VOLUME_BUCKETS")
    for row in vol_rows:
        print(dict(row))
    print("SHADOW_TOTAL", dict(shadow_total))
    print("SHADOW_BY_STATUS")
    for row in shadow_rows:
        print(dict(row))
    print("SHADOW_OPEN")
    for row in open_rows:
        print(dict(row))
    conn.close()


if __name__ == "__main__":
    main()
