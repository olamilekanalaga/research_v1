import sqlite3
from pathlib import Path


DB = Path(r"C:\Users\alaga\Desktop\My Script Library\My Telegram Bot\data\research.sqlite")


WINDOWS = [
    ("June 9", "2026-06-08T23:00:00+00:00", "2026-06-09T23:00:00+00:00"),
    ("June 10 so far", "2026-06-09T23:00:00+00:00", "9999-12-31T00:00:00+00:00"),
]


def q1(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()[0]


def day_report(conn, label, start, end):
    params = (start, end)
    alerts = q1(conn, "SELECT COUNT(*) FROM bot_alerts WHERE alert_time >= ? AND alert_time < ?", params)
    first_last = conn.execute(
        "SELECT MIN(alert_time) first_alert, MAX(alert_time) last_alert FROM bot_alerts WHERE alert_time >= ? AND alert_time < ?",
        params,
    ).fetchone()
    hit2 = q1(
        conn,
        """
        SELECT COUNT(DISTINCT b.alert_id)
        FROM bot_alerts b JOIN token_milestone_alerts m ON m.alert_id = b.alert_id
        WHERE b.alert_time >= ? AND b.alert_time < ?
          AND m.milestone_x >= 2 AND m.milestone_x <= 1000
        """,
        params,
    )
    hit5 = q1(
        conn,
        """
        SELECT COUNT(DISTINCT b.alert_id)
        FROM bot_alerts b JOIN token_milestone_alerts m ON m.alert_id = b.alert_id
        WHERE b.alert_time >= ? AND b.alert_time < ?
          AND m.milestone_x >= 5 AND m.milestone_x <= 1000
        """,
        params,
    )
    hit10 = q1(
        conn,
        """
        SELECT COUNT(DISTINCT b.alert_id)
        FROM bot_alerts b JOIN token_milestone_alerts m ON m.alert_id = b.alert_id
        WHERE b.alert_time >= ? AND b.alert_time < ?
          AND m.milestone_x >= 10 AND m.milestone_x <= 1000
        """,
        params,
    )
    best = q1(
        conn,
        """
        SELECT COALESCE(MAX(m.milestone_x), 0)
        FROM bot_alerts b JOIN token_milestone_alerts m ON m.alert_id = b.alert_id
        WHERE b.alert_time >= ? AND b.alert_time < ? AND m.milestone_x <= 1000
        """,
        params,
    )
    avg_features = conn.execute(
        """
        WITH outcomes AS (
          SELECT b.alert_id, COALESCE(MAX(CASE WHEN m.milestone_x <= 1000 THEN m.milestone_x END), 0) max_x
          FROM bot_alerts b
          LEFT JOIN token_milestone_alerts m ON m.alert_id = b.alert_id
          WHERE b.alert_time >= ? AND b.alert_time < ?
          GROUP BY b.alert_id
        )
        SELECT CASE WHEN o.max_x >= 2 THEN 'winner' ELSE 'loser' END outcome,
               COUNT(*) alerts,
               ROUND(AVG(f.buy_volume_1m), 2) avg_v1m,
               ROUND(AVG(f.buy_volume_10m), 2) avg_v10m,
               ROUND(AVG(f.buy_acceleration), 2) avg_accel,
               ROUND(AVG(f.unique_buyers_1m), 2) avg_ub1m,
               ROUND(AVG(f.unique_buyers_10m), 2) avg_ub10m,
               ROUND(AVG(f.fdv_at_alert), 2) avg_fdv
        FROM outcomes o
        JOIN alert_feature_snapshots f ON f.alert_id = o.alert_id
        GROUP BY outcome
        ORDER BY outcome
        """,
        params,
    ).fetchall()
    buckets = conn.execute(
        """
        WITH outcomes AS (
          SELECT b.alert_id, COALESCE(f.buy_volume_1m,0) v1m,
                 COALESCE(MAX(CASE WHEN m.milestone_x <= 1000 THEN m.milestone_x END),0) max_x
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
          END bucket,
          COUNT(*) alerts,
          SUM(CASE WHEN max_x >= 2 THEN 1 ELSE 0 END) hit2,
          ROUND(100.0 * SUM(CASE WHEN max_x >= 2 THEN 1 ELSE 0 END) / COUNT(*), 2) hit_rate,
          ROUND(MAX(max_x), 2) best
        FROM outcomes
        GROUP BY bucket
        ORDER BY CASE bucket WHEN '<10k' THEN 1 WHEN '10k-15k' THEN 2 WHEN '15k-25k' THEN 3 ELSE 4 END
        """,
        params,
    ).fetchall()
    shadow = conn.execute(
        """
        SELECT COUNT(*) trades,
               SUM(CASE WHEN status='OPEN' THEN 1 ELSE 0 END) open_trades,
               SUM(CASE WHEN status='CLOSED' THEN 1 ELSE 0 END) closed_trades,
               SUM(CASE WHEN status='CLOSED' AND COALESCE(pnl_usd,0) > 0 THEN 1 ELSE 0 END) wins,
               SUM(CASE WHEN status='CLOSED' AND COALESCE(pnl_usd,0) < 0 THEN 1 ELSE 0 END) losses,
               ROUND(SUM(CASE WHEN status='CLOSED' THEN COALESCE(pnl_usd,0) ELSE 0 END), 2) pnl
        FROM execution_positions
        WHERE opened_at >= ? AND opened_at < ?
        """,
        params,
    ).fetchone()
    routes = conn.execute(
        """
        SELECT
          COALESCE(json_extract(entry_quote_json, '$.provider'), 'UNKNOWN') provider,
          COUNT(*) trades,
          ROUND(SUM(CASE WHEN status='CLOSED' THEN COALESCE(pnl_usd,0) ELSE 0 END), 2) pnl
        FROM execution_positions
        WHERE opened_at >= ? AND opened_at < ?
        GROUP BY provider
        ORDER BY trades DESC
        """,
        params,
    ).fetchall()
    return {
        "label": label,
        "start": start,
        "end": end,
        "alerts": alerts,
        "first_alert": first_last["first_alert"],
        "last_alert": first_last["last_alert"],
        "hit2": hit2,
        "hit5": hit5,
        "hit10": hit10,
        "best": best,
        "avg_features": [dict(r) for r in avg_features],
        "buckets": [dict(r) for r in buckets],
        "shadow": dict(shadow),
        "routes": [dict(r) for r in routes],
    }


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    for report in [day_report(conn, *window) for window in WINDOWS]:
        print("DAY", report["label"])
        print("window", report["start"], report["end"])
        print("first_last", report["first_alert"], report["last_alert"])
        print("alerts", report["alerts"], "hit2", report["hit2"], "hit5", report["hit5"], "hit10", report["hit10"], "best", report["best"])
        print("avg_features")
        for row in report["avg_features"]:
            print(row)
        print("buckets")
        for row in report["buckets"]:
            print(row)
        print("shadow", report["shadow"])
        print("routes")
        for row in report["routes"]:
            print(row)
        print()
    conn.close()


if __name__ == "__main__":
    main()
