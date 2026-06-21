from __future__ import annotations

import argparse

from .config import get_settings
from .db import connect, init_db


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize paper-trade scanner results")
    parser.parse_args()

    settings = get_settings()
    conn = connect(settings.database_path)
    init_db(conn)

    trades = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN status='open' THEN 1 ELSE 0 END) AS open_trades,
            SUM(CASE WHEN status='closed' AND pnl_pct >= 20 THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN status='closed' AND pnl_pct < 0 THEN 1 ELSE 0 END) AS losses,
            AVG(CASE WHEN status='closed' THEN pnl_pct END) AS avg_pnl,
            MAX(pnl_pct) AS best_pnl,
            MIN(pnl_pct) AS worst_pnl,
            SUM(CASE WHEN status='closed' THEN paper_pnl_usd ELSE 0 END) AS realized_pnl_usd,
            SUM(CASE WHEN status='open' THEN entry_notional_usd ELSE 0 END) AS open_notional_usd
        FROM paper_trades
        """
    ).fetchone()
    decisions = conn.execute(
        """
        SELECT
            COUNT(*) AS total,
            SUM(passed_filter) AS passed
        FROM scanner_decisions
        """
    ).fetchone()
    api_errors = conn.execute("SELECT COUNT(*) AS total FROM api_logs WHERE error_message IS NOT NULL AND error_message != ''").fetchone()

    total = trades["total"] or 0
    wins = trades["wins"] or 0
    closed = (trades["wins"] or 0) + (trades["losses"] or 0)
    win_rate = (wins / closed * 100) if closed else 0

    print("Paper trade summary")
    print(f"trades={total} open={trades['open_trades'] or 0} wins={wins} losses={trades['losses'] or 0} win_rate={win_rate:.1f}%")
    print(f"avg_pnl={trades['avg_pnl'] or 0:.1f}% best={trades['best_pnl'] or 0:.1f}% worst={trades['worst_pnl'] or 0:.1f}%")
    print(f"realized_pnl_usd=${trades['realized_pnl_usd'] or 0:.2f} open_notional_usd=${trades['open_notional_usd'] or 0:.2f}")
    print(f"scanner_decisions={decisions['total'] or 0} passed={decisions['passed'] or 0} api_errors={api_errors['total'] or 0}")


if __name__ == "__main__":
    main()
