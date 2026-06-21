from __future__ import annotations

import sqlite3

from .config import get_settings


def pct(numerator: float, denominator: float) -> float:
    return (numerator / denominator * 100) if denominator else 0.0


def print_rows(title: str, rows: list[sqlite3.Row]) -> None:
    print(f"\n{title}")
    for row in rows:
        safe = {
            key: (value.encode("ascii", "ignore").decode("ascii") if isinstance(value, str) else value)
            for key, value in dict(row).items()
        }
        print(safe)


def main() -> None:
    conn = sqlite3.connect(get_settings().database_path)
    conn.row_factory = sqlite3.Row

    summary = conn.execute(
        """
        WITH token_runs AS (
            SELECT
                t.token_address,
                t.symbol,
                t.initial_market_cap,
                MAX(s.market_cap) AS max_mc,
                MIN(CASE WHEN s.market_cap >= t.initial_market_cap * 1.2 THEN s.age_seconds END) AS time_to_20,
                MIN(CASE WHEN s.market_cap >= t.initial_market_cap * 1.5 THEN s.age_seconds END) AS time_to_50,
                MAX(CASE WHEN s.age_seconds <= 300 THEN s.buy_volume_1m END) AS max_buy1m_5m,
                MAX(CASE WHEN s.age_seconds <= 300 THEN s.sell_volume_1m END) AS max_sell1m_5m,
                MAX(CASE WHEN s.age_seconds <= 300 THEN s.unique_buyers_1m END) AS max_buyers1m_5m,
                MAX(CASE WHEN s.age_seconds <= 300 THEN s.trade_count_1m END) AS max_trades1m_5m,
                MIN(CASE WHEN s.age_seconds <= 300 THEN s.risk_score END) AS min_risk_5m,
                MIN(CASE WHEN s.age_seconds <= 300 THEN s.top_10_holder_pct END) AS min_top10_5m
            FROM tokens t
            JOIN snapshots s ON s.token_address=t.token_address
            WHERE t.initial_market_cap > 0
            GROUP BY t.token_address
        )
        SELECT
            COUNT(*) AS tokens,
            SUM(CASE WHEN max_mc >= initial_market_cap * 1.2 THEN 1 ELSE 0 END) AS hit20,
            SUM(CASE WHEN max_mc >= initial_market_cap * 1.5 THEN 1 ELSE 0 END) AS hit50,
            SUM(CASE WHEN max_mc >= initial_market_cap * 2 THEN 1 ELSE 0 END) AS hit100,
            AVG(CASE WHEN max_mc >= initial_market_cap * 1.5 THEN time_to_50 END) AS avg_time_to_50,
            AVG(CASE WHEN max_mc < initial_market_cap * 1.2 THEN max_buy1m_5m END) AS dead_avg_buy1m_5m,
            AVG(CASE WHEN max_mc >= initial_market_cap * 1.5 THEN max_buy1m_5m END) AS hit50_avg_buy1m_5m,
            AVG(CASE WHEN max_mc < initial_market_cap * 1.2 THEN max_buyers1m_5m END) AS dead_avg_buyers1m_5m,
            AVG(CASE WHEN max_mc >= initial_market_cap * 1.5 THEN max_buyers1m_5m END) AS hit50_avg_buyers1m_5m
        FROM token_runs
        """
    ).fetchone()
    print("Overall")
    print(dict(summary))
    print(f"hit20_rate={pct(summary['hit20'], summary['tokens']):.1f}%")
    print(f"hit50_rate={pct(summary['hit50'], summary['tokens']):.1f}%")
    print(f"hit100_rate={pct(summary['hit100'], summary['tokens']):.1f}%")

    print_rows(
        "Market-cap band outcomes",
        conn.execute(
            """
            WITH token_runs AS (
                SELECT t.token_address, t.initial_market_cap, MAX(s.market_cap) AS max_mc
                FROM tokens t
                JOIN snapshots s ON s.token_address=t.token_address
                WHERE t.initial_market_cap > 0
                GROUP BY t.token_address
            )
            SELECT
                CASE
                    WHEN initial_market_cap < 5000 THEN '<5k'
                    WHEN initial_market_cap < 20000 THEN '5k-20k'
                    WHEN initial_market_cap < 50000 THEN '20k-50k'
                    ELSE '50k+'
                END AS band,
                COUNT(*) AS tokens,
                SUM(CASE WHEN max_mc >= initial_market_cap * 1.2 THEN 1 ELSE 0 END) AS hit20,
                ROUND(SUM(CASE WHEN max_mc >= initial_market_cap * 1.2 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS hit20_rate,
                SUM(CASE WHEN max_mc >= initial_market_cap * 1.5 THEN 1 ELSE 0 END) AS hit50,
                ROUND(SUM(CASE WHEN max_mc >= initial_market_cap * 1.5 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS hit50_rate
            FROM token_runs
            GROUP BY band
            ORDER BY tokens DESC
            """
        ).fetchall(),
    )

    print_rows(
        "Early feature averages: hit50 vs did not hit20",
        conn.execute(
            """
            WITH token_runs AS (
                SELECT
                    t.token_address,
                    t.initial_market_cap,
                    MAX(s.market_cap) AS max_mc,
                    MAX(CASE WHEN s.age_seconds <= 300 THEN s.buy_volume_1m END) AS max_buy1m,
                    MAX(CASE WHEN s.age_seconds <= 300 THEN s.sell_volume_1m END) AS max_sell1m,
                    MAX(CASE WHEN s.age_seconds <= 300 THEN s.unique_buyers_1m END) AS max_buyers1m,
                    MAX(CASE WHEN s.age_seconds <= 300 THEN s.trade_count_1m END) AS max_trades1m,
                    MIN(CASE WHEN s.age_seconds <= 300 THEN s.risk_score END) AS min_risk,
                    MIN(CASE WHEN s.age_seconds <= 300 THEN s.top_10_holder_pct END) AS min_top10
                FROM tokens t
                JOIN snapshots s ON s.token_address=t.token_address
                WHERE t.initial_market_cap > 0
                GROUP BY t.token_address
            )
            SELECT
                CASE
                    WHEN max_mc >= initial_market_cap * 1.5 THEN 'hit50'
                    WHEN max_mc < initial_market_cap * 1.2 THEN 'did_not_hit20'
                    ELSE 'middle'
                END AS group_name,
                COUNT(*) AS tokens,
                ROUND(AVG(max_buy1m), 1) AS avg_max_buy1m,
                ROUND(AVG(max_sell1m), 1) AS avg_max_sell1m,
                ROUND(AVG(max_buyers1m), 1) AS avg_max_buyers1m,
                ROUND(AVG(max_trades1m), 1) AS avg_max_trades1m,
                ROUND(AVG(min_risk), 1) AS avg_min_risk,
                ROUND(AVG(min_top10), 1) AS avg_min_top10
            FROM token_runs
            GROUP BY group_name
            ORDER BY tokens DESC
            """
        ).fetchall(),
    )

    print_rows(
        "Fastest hit50 tokens",
        conn.execute(
            """
            SELECT
                t.symbol,
                t.token_address,
                ROUND(t.initial_market_cap, 1) AS initial_mc,
                ROUND(MAX(s.market_cap), 1) AS max_mc,
                ROUND((MAX(s.market_cap)-t.initial_market_cap)*100.0/t.initial_market_cap, 1) AS runup_pct,
                MIN(CASE WHEN s.market_cap >= t.initial_market_cap * 1.5 THEN s.age_seconds END) AS time_to_50,
                ROUND(MAX(CASE WHEN s.age_seconds <= 300 THEN s.buy_volume_1m END), 1) AS max_buy1m_5m,
                MAX(CASE WHEN s.age_seconds <= 300 THEN s.unique_buyers_1m END) AS max_buyers1m_5m,
                MAX(CASE WHEN s.age_seconds <= 300 THEN s.trade_count_1m END) AS max_trades1m_5m
            FROM tokens t
            JOIN snapshots s ON s.token_address=t.token_address
            WHERE t.initial_market_cap > 0
            GROUP BY t.token_address
            HAVING MAX(s.market_cap) >= t.initial_market_cap * 1.5
            ORDER BY time_to_50 ASC
            LIMIT 15
            """
        ).fetchall(),
    )


if __name__ == "__main__":
    main()
