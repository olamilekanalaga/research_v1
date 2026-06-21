from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass

from .config import get_settings
from .ml_train import FEATURES, load_examples, predict, standardize, train_logreg


@dataclass
class ModelBundle:
    weights: list[float]
    means: list[float]
    scales: list[float]


def transform(raw: list[float], means: list[float], scales: list[float]) -> list[float]:
    return [(value - means[i]) / scales[i] for i, value in enumerate(raw)]


def train_model(conn: sqlite3.Connection) -> tuple[ModelBundle, dict]:
    examples = load_examples(conn)
    split = int(len(examples) * 0.75)
    train = examples[:split]
    test = examples[split:]
    all_x_raw = [ex.x for ex in train + test]
    x_all, means, scales = standardize([ex.x for ex in train], all_x_raw)
    x_train = x_all[: len(train)]
    x_test = x_all[len(train) :]
    y_train = [ex.y for ex in train]
    weights = train_logreg(x_train, y_train)

    test_scores = [(predict(weights, row), ex.y) for row, ex in zip(x_test, test)]
    test_scores.sort(key=lambda item: item[0], reverse=True)
    positives = sum(label for _, label in test_scores)
    metrics = {
        "rows": len(examples),
        "train_rows": len(train),
        "test_rows": len(test),
        "positives": sum(ex.y for ex in examples),
        "test_positives": positives,
        "test_base_rate": positives / len(test_scores) if test_scores else 0,
    }
    for pct in [5, 10, 20, 30]:
        n = max(1, int(len(test_scores) * pct / 100))
        top = test_scores[:n]
        hits = sum(label for _, label in top)
        metrics[f"top_{pct}_precision"] = hits / n
        metrics[f"top_{pct}_hits"] = hits
        metrics[f"top_{pct}_n"] = n

    return ModelBundle(weights, means, scales), metrics


def feature_importance(bundle: ModelBundle) -> list[tuple[str, float]]:
    pairs = list(zip(FEATURES, bundle.weights[1:]))
    return sorted(pairs, key=lambda item: abs(item[1]), reverse=True)


def paper_trade_raw_features(row: sqlite3.Row) -> list[float]:
    mc = float(row["entry_market_cap"] or 0)
    buy = float(row["buy_volume_1m"] or 0)
    sell = float(row["sell_volume_1m"] or 0)
    buyers = float(row["unique_buyers_1m"] or 0)
    trades = float(row["trade_count_1m"] or 0)
    risk = float(row["risk_score"] if row["risk_score"] is not None else 5)
    top10 = float(row["top_10_holder_pct"] if row["top_10_holder_pct"] is not None else 0)
    ratio = buy / max(sell, 1)
    return [
        math.log1p(mc),
        math.log1p(buy),
        math.log1p(sell),
        math.log1p(buyers),
        math.log1p(trades),
        risk,
        top10,
        min(ratio, 20),
        1.0 if 5_000 <= mc < 20_000 else 0.0,
        1.0 if 20_000 <= mc < 50_000 else 0.0,
    ]


def paper_trade_scores(conn: sqlite3.Connection, bundle: ModelBundle) -> list[dict]:
    rows = conn.execute(
        """
        SELECT p.id, p.token_address, COALESCE(t.symbol, '') AS symbol, p.pnl_pct,
               p.paper_pnl_usd, p.exit_reason, p.entry_market_cap,
               s.buy_volume_1m, s.sell_volume_1m, s.unique_buyers_1m,
               s.trade_count_1m, s.risk_score, s.top_10_holder_pct
        FROM paper_trades p
        JOIN snapshots s ON s.id=p.snapshot_id
        LEFT JOIN tokens t ON t.token_address=p.token_address
        WHERE p.status='closed'
        ORDER BY p.id
        """
    ).fetchall()
    scored = []
    for row in rows:
        x = transform(paper_trade_raw_features(row), bundle.means, bundle.scales)
        score = predict(bundle.weights, x)
        data = dict(row)
        data["ml_score"] = score
        scored.append(data)
    return scored


def summarize_paper_threshold(scored: list[dict], threshold: float) -> dict:
    kept = [row for row in scored if row["ml_score"] >= threshold]
    skipped = [row for row in scored if row["ml_score"] < threshold]
    wins = [row for row in kept if (row["pnl_pct"] or 0) > 0]
    tp = [row for row in kept if (row["pnl_pct"] or 0) >= 50]
    pnl = sum(row["paper_pnl_usd"] or 0 for row in kept)
    avoided_loss = -sum(row["paper_pnl_usd"] or 0 for row in skipped if (row["paper_pnl_usd"] or 0) < 0)
    missed_profit = sum(row["paper_pnl_usd"] or 0 for row in skipped if (row["paper_pnl_usd"] or 0) > 0)
    return {
        "threshold": threshold,
        "kept": len(kept),
        "skipped": len(skipped),
        "wins": len(wins),
        "tp50": len(tp),
        "win_rate": len(wins) / len(kept) if kept else 0,
        "paper_pnl": pnl,
        "avoided_loss": avoided_loss,
        "missed_profit": missed_profit,
    }


def fmt_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def main() -> None:
    settings = get_settings()
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row

    bundle, metrics = train_model(conn)
    scored = paper_trade_scores(conn, bundle)
    total_pnl = sum(row["paper_pnl_usd"] or 0 for row in scored)
    total_wins = sum(1 for row in scored if (row["pnl_pct"] or 0) > 0)

    print("ML Learning Report")
    print("==================")
    print()
    print("1. What data did ML learn from?")
    print(f"Token examples: {metrics['rows']}")
    print(f"Tokens that hit +50%: {metrics['positives']}")
    print(f"Paper trades available for scoring: {len(scored)}")
    print()
    print("Plain English: token examples teach ML what winners looked like; paper trades show whether ML would have filtered our entries.")
    print()

    print("2. Is the model finding signal?")
    print(f"Unseen test base rate: {fmt_pct(metrics['test_base_rate'])}")
    for pct in [5, 10, 20, 30]:
        print(
            f"Top {pct}% model picks: {fmt_pct(metrics[f'top_{pct}_precision'])} "
            f"({metrics[f'top_{pct}_hits']}/{metrics[f'top_{pct}_n']}) hit +50%"
        )
    print()

    print("3. Which features is ML leaning on most?")
    for name, weight in feature_importance(bundle)[:8]:
        direction = "raises score" if weight > 0 else "lowers score"
        print(f"{name}: {weight:.3f} ({direction})")
    print()

    print("4. What would ML have done to paper trades?")
    print(f"Current paper trades: {len(scored)}")
    print(f"Current winning trades: {total_wins}")
    print(f"Current paper PnL: ${total_pnl:.2f}")
    for threshold in [0.5, 0.6, 0.7, 0.8, 0.9]:
        result = summarize_paper_threshold(scored, threshold)
        print(
            f"ML >= {threshold:.1f}: keep {result['kept']}, win rate {fmt_pct(result['win_rate'])}, "
            f"TP50 {result['tp50']}, PnL ${result['paper_pnl']:.2f}, "
            f"avoided losses ${result['avoided_loss']:.2f}, missed profit ${result['missed_profit']:.2f}"
        )
    print()

    print("5. Biggest ML-approved losses")
    losses = sorted(
        [row for row in scored if (row["pnl_pct"] or 0) < 0],
        key=lambda row: row["ml_score"],
        reverse=True,
    )[:5]
    for row in losses:
        symbol = (row["symbol"] or "").encode("ascii", "ignore").decode("ascii")
        print(
            f"{symbol or row['token_address'][:6]} score={row['ml_score']:.2f} "
            f"pnl={row['pnl_pct']:.1f}% sell1m=${row['sell_volume_1m'] or 0:,.0f} "
            f"buy1m=${row['buy_volume_1m'] or 0:,.0f}"
        )
    print()

    print("6. Recommendation")
    print("Use ML as a filter, not as the driver yet.")
    print("Next live experiment should be a new rule version that requires:")
    print("- existing fast-breakout rule passes")
    print("- ML score >= chosen threshold")
    print("- sell pressure tightened versus current rule")

    conn.execute(
        """
        INSERT OR REPLACE INTO bot_state(key, value) VALUES('last_ml_report_json', ?)
        """,
        (
            json.dumps(
                {
                    "metrics": metrics,
                    "paper_thresholds": [summarize_paper_threshold(scored, t) for t in [0.5, 0.6, 0.7, 0.8, 0.9]],
                }
            ),
        ),
    )
    conn.commit()


if __name__ == "__main__":
    main()
