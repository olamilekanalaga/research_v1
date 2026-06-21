from __future__ import annotations

import json
import math
import random
import sqlite3
from dataclasses import dataclass

from .config import get_settings
from .db import init_db


FEATURES = [
    "initial_market_cap",
    "buy1m",
    "sell1m",
    "buyers1m",
    "trades1m",
    "risk",
    "top10",
    "buy_sell_ratio",
    "mc_band_5k_20k",
    "mc_band_20k_50k",
]


@dataclass
class Example:
    token_address: str
    symbol: str
    x: list[float]
    y: int


def sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(min(z, 30), -30)))


def load_examples(conn: sqlite3.Connection) -> list[Example]:
    rows = conn.execute(
        """
        WITH dataset AS (
            SELECT
                t.token_address,
                COALESCE(t.symbol, '') AS symbol,
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
    examples: list[Example] = []
    for row in rows:
        mc = float(row["initial_market_cap"] or 0)
        buy = float(row["buy1m"] or 0)
        sell = float(row["sell1m"] or 0)
        buyers = float(row["buyers1m"] or 0)
        trades = float(row["trades1m"] or 0)
        risk = float(row["risk"] if row["risk"] is not None else 5)
        top10 = float(row["top10"] if row["top10"] is not None else 0)
        ratio = buy / max(sell, 1)
        x = [
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
        examples.append(Example(row["token_address"], row["symbol"], x, int(row["y_hit50"])))
    return examples


def standardize(train_x: list[list[float]], all_x: list[list[float]]) -> tuple[list[list[float]], list[float], list[float]]:
    means = [sum(row[i] for row in train_x) / len(train_x) for i in range(len(train_x[0]))]
    scales = []
    for i, mean in enumerate(means):
        variance = sum((row[i] - mean) ** 2 for row in train_x) / len(train_x)
        scales.append(math.sqrt(variance) or 1.0)
    transformed = [[(value - means[i]) / scales[i] for i, value in enumerate(row)] for row in all_x]
    return transformed, means, scales


def train_logreg(x: list[list[float]], y: list[int], epochs: int = 1200, lr: float = 0.08, l2: float = 0.01) -> list[float]:
    weights = [0.0] * (len(x[0]) + 1)
    pos = sum(y)
    neg = len(y) - pos
    pos_weight = neg / max(pos, 1)

    for _ in range(epochs):
        grads = [0.0] * len(weights)
        for row, label in zip(x, y):
            z = weights[0] + sum(w * value for w, value in zip(weights[1:], row))
            pred = sigmoid(z)
            sample_weight = pos_weight if label else 1.0
            error = (pred - label) * sample_weight
            grads[0] += error
            for i, value in enumerate(row, start=1):
                grads[i] += error * value
        for i in range(len(weights)):
            penalty = l2 * weights[i] if i else 0.0
            weights[i] -= lr * ((grads[i] / len(x)) + penalty)
    return weights


def predict(weights: list[float], row: list[float]) -> float:
    return sigmoid(weights[0] + sum(w * value for w, value in zip(weights[1:], row)))


def evaluate(scores: list[tuple[float, int]]) -> dict:
    scores = sorted(scores, key=lambda item: item[0], reverse=True)
    positives = sum(label for _, label in scores)
    metrics = {
        "rows": len(scores),
        "positives": positives,
        "base_rate": positives / len(scores) if scores else 0,
    }
    for pct in [5, 10, 20]:
        n = max(1, int(len(scores) * pct / 100))
        top = scores[:n]
        hits = sum(label for _, label in top)
        metrics[f"top_{pct}_pct_precision"] = hits / n
        metrics[f"top_{pct}_pct_hits"] = hits
        metrics[f"top_{pct}_pct_n"] = n
    return metrics


def main() -> None:
    settings = get_settings()
    conn = sqlite3.connect(settings.database_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)

    examples = load_examples(conn)
    if len(examples) < 200:
        print(f"Need more rows for ML. rows={len(examples)}")
        return

    random.Random(7).shuffle(examples)
    split = int(len(examples) * 0.75)
    train = examples[:split]
    test = examples[split:]
    all_x_raw = [ex.x for ex in train + test]
    x_all, means, scales = standardize([ex.x for ex in train], all_x_raw)
    x_train = x_all[: len(train)]
    x_test = x_all[len(train) :]
    y_train = [ex.y for ex in train]
    y_test = [ex.y for ex in test]

    weights = train_logreg(x_train, y_train)
    train_scores = [(predict(weights, row), label) for row, label in zip(x_train, y_train)]
    test_scores = [(predict(weights, row), label) for row, label in zip(x_test, y_test)]
    train_metrics = evaluate(train_scores)
    test_metrics = evaluate(test_scores)
    metrics = {"train": train_metrics, "test": test_metrics}

    conn.execute(
        """
        INSERT OR REPLACE INTO ml_models(
            model_name, target, feature_names, weights_json, means_json, scales_json,
            metrics_json, trained_rows, positive_rows
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (
            "hit50_logreg_v1",
            "hit_50pct_from_first_5m_features",
            json.dumps(FEATURES),
            json.dumps(weights),
            json.dumps(means),
            json.dumps(scales),
            json.dumps(metrics),
            len(train),
            sum(y_train),
        ),
    )
    conn.commit()

    print("ML logistic model trained")
    print(f"rows={len(examples)} train={len(train)} test={len(test)} positives={sum(ex.y for ex in examples)}")
    print("test metrics")
    for key, value in test_metrics.items():
        print(f"{key}={value:.4f}" if isinstance(value, float) else f"{key}={value}")

    ranked = sorted(
        ((predict(weights, row), ex) for row, ex in zip(x_test, test)),
        key=lambda item: item[0],
        reverse=True,
    )
    print("\nTop test predictions")
    for score, ex in ranked[:10]:
        symbol = ex.symbol.encode("ascii", "ignore").decode("ascii")
        print({"score": round(score, 3), "symbol": symbol, "hit50": ex.y})


if __name__ == "__main__":
    main()
