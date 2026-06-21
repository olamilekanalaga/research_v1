from __future__ import annotations

import math
import sqlite3

from .config import get_settings


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-max(min(x, 30), -30)))


def main() -> None:
    conn = sqlite3.connect(get_settings().database_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        WITH dataset AS (
            SELECT
                t.token_address,
                t.symbol,
                t.initial_market_cap,
                MAX(s.market_cap) AS max_mc,
                MAX(CASE WHEN s.age_seconds <= 300 THEN s.buy_volume_1m END) AS buy1m,
                MAX(CASE WHEN s.age_seconds <= 300 THEN s.sell_volume_1m END) AS sell1m,
                MAX(CASE WHEN s.age_seconds <= 300 THEN s.unique_buyers_1m END) AS buyers1m,
                MAX(CASE WHEN s.age_seconds <= 300 THEN s.trade_count_1m END) AS trades1m,
                MIN(CASE WHEN s.age_seconds <= 300 THEN s.risk_score END) AS risk,
                MIN(CASE WHEN s.age_seconds <= 300 THEN s.top_10_holder_pct END) AS top10
            FROM tokens t
            JOIN snapshots s ON s.token_address=t.token_address
            WHERE t.initial_market_cap > 0
            GROUP BY t.token_address
        )
        SELECT *,
               CASE WHEN max_mc >= initial_market_cap * 1.5 THEN 1 ELSE 0 END AS y_hit50
        FROM dataset
        WHERE buy1m IS NOT NULL
        """
    ).fetchall()

    if not rows:
        print("No ML rows yet.")
        return

    # Lightweight hand-scored baseline: not a trained model yet, but ML-ready
    # feature scoring that lets us rank tokens by the same columns a model will use.
    scored = []
    for row in rows:
        buy1m = row["buy1m"] or 0
        sell1m = row["sell1m"] or 0
        buyers = row["buyers1m"] or 0
        trades = row["trades1m"] or 0
        mc = row["initial_market_cap"] or 0
        buy_sell_ratio = buy1m / max(sell1m, 1)
        score = (
            math.log1p(buy1m) * 0.9
            + math.log1p(buyers) * 1.6
            + math.log1p(trades) * 1.2
            + min(buy_sell_ratio, 10) * 0.25
            + (1.0 if 5_000 <= mc <= 20_000 else 0.0)
            - (1.0 if mc < 2_000 else 0.0)
        )
        scored.append((score, row))

    scored.sort(key=lambda item: item[0], reverse=True)
    total = len(scored)
    positives = sum(row["y_hit50"] for _, row in scored)
    print("ML baseline dataset")
    print(f"rows={total} hit50={positives} hit50_rate={positives / total * 100:.1f}%")

    for top_pct in [5, 10, 20]:
        n = max(1, int(total * top_pct / 100))
        top = scored[:n]
        hits = sum(row["y_hit50"] for _, row in top)
        print(f"top_{top_pct}% n={n} hit50={hits} hit50_rate={hits / n * 100:.1f}%")

    print("\nTop scored tokens")
    for score, row in scored[:12]:
        symbol = (row["symbol"] or "").encode("ascii", "ignore").decode("ascii")
        print(
            {
                "score": round(score, 2),
                "symbol": symbol,
                "initial_mc": round(row["initial_market_cap"] or 0, 1),
                "buy1m": round(row["buy1m"] or 0, 1),
                "buyers1m": row["buyers1m"] or 0,
                "trades1m": row["trades1m"] or 0,
                "hit50": row["y_hit50"],
            }
        )


if __name__ == "__main__":
    main()
