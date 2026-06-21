from __future__ import annotations

import sqlite3

from .config import get_settings


def main() -> None:
    conn = sqlite3.connect(get_settings().database_path)
    conn.row_factory = sqlite3.Row
    active_rule = conn.execute("SELECT value FROM bot_state WHERE key='active_rule_version'").fetchone()
    active_rule_version = active_rule["value"] if active_rule else "v3_fast_breakout_50_before_minus_20"

    print("paper trades by rule/status")
    for row in conn.execute(
        "SELECT rule_version, status, COUNT(*) AS c FROM paper_trades GROUP BY rule_version, status"
    ):
        print(dict(row))

    print(f"\nactive rule decisions: {active_rule_version}")
    for row in conn.execute(
        """
        SELECT passed_filter, failed_reason, COUNT(*) AS c
        FROM scanner_decisions
        WHERE rule_version=?
        GROUP BY passed_filter, failed_reason
        ORDER BY c DESC
        LIMIT 12
        """,
        (active_rule_version,),
    ):
        print(dict(row))

    print("\nactive rule passed")
    for row in conn.execute(
        """
        SELECT t.symbol, s.token_address, s.age_seconds, s.market_cap, s.buy_volume_1m,
               s.sell_volume_1m, s.unique_buyers_1m, s.trade_count_1m, s.risk_score,
               s.top_10_holder_pct, d.consecutive_passes
        FROM scanner_decisions d
        JOIN snapshots s ON s.id=d.snapshot_id
        LEFT JOIN tokens t ON t.token_address=s.token_address
        WHERE d.rule_version=?
          AND d.passed_filter=1
        ORDER BY d.id DESC
        LIMIT 10
        """,
        (active_rule_version,),
    ):
        print(dict(row))


if __name__ == "__main__":
    main()
