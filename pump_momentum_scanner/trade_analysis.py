from __future__ import annotations

import sqlite3

from .config import get_settings


def main() -> None:
    conn = sqlite3.connect(get_settings().database_path)
    conn.row_factory = sqlite3.Row

    print("Paper trade groups")
    for row in conn.execute(
        """
        SELECT
            CASE
                WHEN pnl_pct >= 50 THEN 'tp_50_plus'
                WHEN pnl_pct > 0 THEN 'green_below_50'
                ELSE 'loss'
            END AS group_name,
            COUNT(*) AS trades,
            ROUND(AVG(pnl_pct), 1) AS avg_pnl,
            ROUND(AVG(entry_market_cap), 1) AS avg_entry_mc,
            ROUND(AVG(max_runup_pct), 1) AS avg_max_runup,
            ROUND(AVG(max_drawdown_pct), 1) AS avg_max_drawdown,
            ROUND(SUM(paper_pnl_usd), 2) AS paper_pnl
        FROM paper_trades
        WHERE status='closed'
        GROUP BY group_name
        ORDER BY paper_pnl DESC
        """
    ):
        print(dict(row))

    print("\nEntry feature comparison")
    for row in conn.execute(
        """
        SELECT
            CASE
                WHEN p.pnl_pct >= 50 THEN 'tp_50_plus'
                WHEN p.pnl_pct > 0 THEN 'green_below_50'
                ELSE 'loss'
            END AS group_name,
            COUNT(*) AS trades,
            ROUND(AVG(s.buy_volume_1m), 1) AS avg_buy1m,
            ROUND(AVG(s.sell_volume_1m), 1) AS avg_sell1m,
            ROUND(AVG(s.buy_volume_1m / MAX(s.sell_volume_1m, 1)), 2) AS avg_buy_sell_ratio,
            ROUND(AVG(s.unique_buyers_1m), 1) AS avg_buyers1m,
            ROUND(AVG(s.trade_count_1m), 1) AS avg_trades1m,
            ROUND(AVG(s.risk_score), 1) AS avg_risk,
            ROUND(AVG(s.top_10_holder_pct), 1) AS avg_top10,
            ROUND(AVG(s.age_seconds), 1) AS avg_age
        FROM paper_trades p
        LEFT JOIN snapshots s ON s.id=p.snapshot_id
        WHERE p.status='closed'
        GROUP BY group_name
        ORDER BY trades DESC
        """
    ):
        print(dict(row))

    print("\nWorst losses")
    for row in conn.execute(
        """
        SELECT t.symbol, ROUND(p.pnl_pct, 1) AS pnl, ROUND(p.entry_market_cap, 1) AS entry_mc,
               ROUND(p.exit_market_cap, 1) AS exit_mc, p.exit_reason, p.entry_reason
        FROM paper_trades p
        LEFT JOIN tokens t ON t.token_address=p.token_address
        WHERE p.status='closed'
        ORDER BY p.pnl_pct ASC
        LIMIT 10
        """
    ):
        safe = {k: (v.encode("ascii", "ignore").decode("ascii") if isinstance(v, str) else v) for k, v in dict(row).items()}
        print(safe)


if __name__ == "__main__":
    main()
