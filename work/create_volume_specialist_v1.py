from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


MIGRATION_PROJECT = Path(r"C:\Users\alaga\Desktop\My Script Library\Behaviour Labeling\migration_specialist")
PROJECT = Path(r"C:\Users\alaga\Desktop\My Script Library\Behaviour Labeling\volume_specialist")
RAW = MIGRATION_PROJECT / "data" / "raw"
NOTEBOOKS = PROJECT / "notebooks"
OUTPUTS = PROJECT / "outputs" / "v1"


def money(x: float) -> str:
    if pd.isna(x):
        return ""
    return f"{x:,.2f}"


def create_notebook(cells: list[dict], path: Path) -> None:
    notebook = {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {
                "name": "python",
                "pygments_lexer": "ipython3",
            },
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    path.write_text(json.dumps(notebook, indent=2), encoding="utf-8")


def md(source: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(True)}


def code(source: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": source.splitlines(True),
    }


def build_outputs() -> dict[str, pd.DataFrame]:
    trades = pd.read_csv(
        RAW / "token_trades.csv",
        usecols=[
            "token_address",
            "wallet_address",
            "tx_hash",
            "trade_time",
            "trade_type",
            "usd_volume",
            "market_cap_at_trade_usd",
            "migration_phase",
        ],
    )
    tokens = pd.read_csv(
        RAW / "tokens.csv",
        usecols=[
            "token_address",
            "symbol",
            "name",
            "created_time",
            "migration_time",
            "ath_market_cap_usd",
            "ath_market_cap_bucket",
            "current_market_cap_usd",
        ],
    )

    for col in ["token_address", "wallet_address"]:
        trades[col] = trades[col].astype(str).str.strip()
    tokens["token_address"] = tokens["token_address"].astype(str).str.strip()

    trades["trade_time"] = pd.to_datetime(trades["trade_time"], errors="coerce", utc=True)
    tokens["created_time"] = pd.to_datetime(tokens["created_time"], errors="coerce", utc=True)
    tokens["migration_time"] = pd.to_datetime(tokens["migration_time"], errors="coerce", utc=True)

    buys = trades[
        (trades["trade_type"].str.lower() == "buy")
        & (
            (trades["migration_phase"] == "pre_migration")
            | (trades["market_cap_at_trade_usd"] <= 40_000)
        )
    ].copy()

    token_volume = (
        buys.groupby("token_address")
        .agg(
            token_early_buy_volume_usd=("usd_volume", "sum"),
            token_early_buy_trade_count=("usd_volume", "size"),
            token_early_wallet_count=("wallet_address", "nunique"),
            token_first_early_trade_time=("trade_time", "min"),
        )
        .reset_index()
    )

    wallet_token = (
        buys.groupby(["wallet_address", "token_address"])
        .agg(
            wallet_early_buy_volume_usd=("usd_volume", "sum"),
            wallet_early_buy_trade_count=("usd_volume", "size"),
            first_buy_time=("trade_time", "min"),
            last_buy_time=("trade_time", "max"),
            first_buy_market_cap_usd=("market_cap_at_trade_usd", "min"),
            max_buy_market_cap_usd=("market_cap_at_trade_usd", "max"),
        )
        .reset_index()
        .merge(token_volume, on="token_address", how="left")
        .merge(tokens, on="token_address", how="left")
    )
    wallet_token["early_volume_share_pct"] = (
        100
        * wallet_token["wallet_early_buy_volume_usd"]
        / wallet_token["token_early_buy_volume_usd"].replace(0, np.nan)
    ).fillna(0)
    wallet_token["meaningful_volume_token"] = wallet_token["wallet_early_buy_volume_usd"] >= 100
    wallet_token["strong_volume_token"] = wallet_token["wallet_early_buy_volume_usd"] >= 250
    wallet_token["high_share_token"] = (
        (wallet_token["wallet_early_buy_volume_usd"] >= 100)
        & (wallet_token["early_volume_share_pct"] >= 5)
    )
    wallet_token["first_buy_under_20k"] = wallet_token["first_buy_market_cap_usd"] <= 20_000
    wallet_token["ath_over_500k"] = wallet_token["ath_market_cap_usd"] >= 500_000
    wallet_token["ath_over_1m"] = wallet_token["ath_market_cap_usd"] >= 1_000_000

    wallet_token_pnl = (
        trades.groupby(["wallet_address", "token_address", "trade_type"])
        .agg(total_usd_volume=("usd_volume", "sum"))
        .reset_index()
        .pivot_table(
            index=["wallet_address", "token_address"],
            columns="trade_type",
            values="total_usd_volume",
            aggfunc="sum",
            fill_value=0,
        )
        .reset_index()
        .rename(columns={"buy": "total_buy_usd", "sell": "total_sell_usd"})
    )
    for col in ["total_buy_usd", "total_sell_usd"]:
        if col not in wallet_token_pnl.columns:
            wallet_token_pnl[col] = 0.0
    wallet_token_pnl["realized_pnl_usd"] = (
        wallet_token_pnl["total_sell_usd"] - wallet_token_pnl["total_buy_usd"]
    )
    wallet_token_pnl["roi_pct"] = (
        100
        * wallet_token_pnl["realized_pnl_usd"]
        / wallet_token_pnl["total_buy_usd"].replace(0, np.nan)
    ).fillna(0)
    wallet_token_pnl["profitable_token"] = wallet_token_pnl["realized_pnl_usd"] > 0
    wallet_token = wallet_token.merge(
        wallet_token_pnl,
        on=["wallet_address", "token_address"],
        how="left",
    )
    pnl_cols = ["total_buy_usd", "total_sell_usd", "realized_pnl_usd", "roi_pct"]
    wallet_token[pnl_cols] = wallet_token[pnl_cols].fillna(0)
    wallet_token["profitable_token"] = wallet_token["profitable_token"].fillna(False)

    wallet_features = (
        wallet_token.groupby("wallet_address")
        .agg(
            early_volume_token_count=("token_address", "nunique"),
            meaningful_volume_token_count=("meaningful_volume_token", "sum"),
            strong_volume_token_count=("strong_volume_token", "sum"),
            high_share_token_count=("high_share_token", "sum"),
            first_buy_under_20k_count=("first_buy_under_20k", "sum"),
            ath_over_500k_count=("ath_over_500k", "sum"),
            ath_over_1m_count=("ath_over_1m", "sum"),
            profitable_volume_token_count=("profitable_token", "sum"),
            total_early_buy_volume_usd=("wallet_early_buy_volume_usd", "sum"),
            total_realized_pnl_usd=("realized_pnl_usd", "sum"),
            avg_roi_pct=("roi_pct", "mean"),
            median_roi_pct=("roi_pct", "median"),
            avg_wallet_token_early_buy_usd=("wallet_early_buy_volume_usd", "mean"),
            median_wallet_token_early_buy_usd=("wallet_early_buy_volume_usd", "median"),
            std_wallet_token_early_buy_usd=("wallet_early_buy_volume_usd", "std"),
            max_wallet_token_early_buy_usd=("wallet_early_buy_volume_usd", "max"),
            avg_early_volume_share_pct=("early_volume_share_pct", "mean"),
            max_early_volume_share_pct=("early_volume_share_pct", "max"),
            early_trade_count=("wallet_early_buy_trade_count", "sum"),
            first_seen_time=("first_buy_time", "min"),
            last_seen_time=("last_buy_time", "max"),
        )
        .reset_index()
    )
    wallet_features["avg_early_buy_size_usd"] = (
        wallet_features["total_early_buy_volume_usd"]
        / wallet_features["early_trade_count"].replace(0, np.nan)
    ).fillna(0)
    wallet_features["early_entry_rate"] = (
        wallet_features["first_buy_under_20k_count"]
        / wallet_features["early_volume_token_count"].replace(0, np.nan)
    ).fillna(0)
    wallet_features["quality_token_rate"] = (
        wallet_features["ath_over_500k_count"]
        / wallet_features["early_volume_token_count"].replace(0, np.nan)
    ).fillna(0)
    wallet_features["profit_win_rate"] = (
        wallet_features["profitable_volume_token_count"]
        / wallet_features["early_volume_token_count"].replace(0, np.nan)
    ).fillna(0)
    wallet_features["volume_size_cv"] = (
        wallet_features["std_wallet_token_early_buy_usd"].fillna(0)
        / wallet_features["avg_wallet_token_early_buy_usd"].replace(0, np.nan)
    ).fillna(0)
    wallet_features["volume_size_consistency"] = (1 / (1 + wallet_features["volume_size_cv"])).clip(0, 1)

    conditions = [
        (
            "Elite Volume Specialist",
            (wallet_features["meaningful_volume_token_count"] >= 12)
            & (wallet_features["total_early_buy_volume_usd"] >= 10_000)
            & (wallet_features["high_share_token_count"] >= 5),
        ),
        (
            "Strong Volume Specialist",
            (wallet_features["meaningful_volume_token_count"] >= 8)
            & (wallet_features["total_early_buy_volume_usd"] >= 5_000)
            & (wallet_features["high_share_token_count"] >= 3),
        ),
        (
            "Volume Specialist V1",
            (wallet_features["meaningful_volume_token_count"] >= 5)
            & (wallet_features["total_early_buy_volume_usd"] >= 2_500)
            & (wallet_features["avg_early_volume_share_pct"] >= 2),
        ),
        (
            "Volume Specialist Candidate",
            (wallet_features["meaningful_volume_token_count"] >= 3)
            & (wallet_features["total_early_buy_volume_usd"] >= 1_000),
        ),
        (
            "Volume Pattern Observed",
            (wallet_features["early_volume_token_count"] >= 2)
            & (wallet_features["total_early_buy_volume_usd"] >= 250),
        ),
    ]

    wallet_features["volume_label_v1"] = "Not Volume Specialist"
    for label, mask in conditions:
        wallet_features.loc[
            (wallet_features["volume_label_v1"] == "Not Volume Specialist") & mask,
            "volume_label_v1",
        ] = label

    wallet_features["is_volume_specialist_v1"] = wallet_features["volume_label_v1"].isin(
        ["Volume Specialist V1", "Strong Volume Specialist", "Elite Volume Specialist"]
    )

    def pct_rank(series: pd.Series) -> pd.Series:
        return series.rank(pct=True).fillna(0) * 100

    def add_score_columns(features: pd.DataFrame, source_wallet_token: pd.DataFrame) -> pd.DataFrame:
        features = features.copy()
        features["repeatability_score"] = pct_rank(features["meaningful_volume_token_count"])
        features["volume_depth_score"] = pct_rank(np.log1p(features["total_early_buy_volume_usd"]))
        features["early_share_score"] = (
            0.65 * pct_rank(features["avg_early_volume_share_pct"])
            + 0.35 * pct_rank(features["high_share_token_count"])
        )
        features["token_outcome_score"] = (
            0.70 * pct_rank(features["quality_token_rate"])
            + 0.30 * pct_rank(features["ath_over_1m_count"])
        )
        features["behavior_consistency_score"] = (
            0.55 * pct_rank(features["early_entry_rate"])
            + 0.45 * pct_rank(features["volume_size_consistency"])
        )
        tiny_buy_ratio = (
            source_wallet_token.assign(tiny_buy=source_wallet_token["wallet_early_buy_volume_usd"] < 25)
            .groupby("wallet_address")["tiny_buy"]
            .mean()
            .reindex(features["wallet_address"])
            .fillna(0)
            .to_numpy()
        )
        features["tiny_buy_ratio"] = tiny_buy_ratio
        features["noise_penalty_score"] = (
            0.40 * pct_rank(features["early_volume_token_count"])
            + 0.30 * pct_rank(features["early_trade_count"])
            + 0.30 * (features["tiny_buy_ratio"] * 100)
        ).clip(0, 100)
        raw_score = (
            0.25 * features["repeatability_score"]
            + 0.20 * features["volume_depth_score"]
            + 0.20 * features["early_share_score"]
            + 0.20 * features["token_outcome_score"]
            + 0.10 * features["behavior_consistency_score"]
            - 0.15 * features["noise_penalty_score"]
        )
        features["volume_specialist_score"] = raw_score.clip(0, 100).round(2)
        features["volume_score"] = features["volume_specialist_score"]
        features["volume_score_confidence_tier"] = np.select(
            [
                (features["volume_specialist_score"] >= 85)
                & (features["meaningful_volume_token_count"] >= 5),
                (features["volume_specialist_score"] >= 70)
                & (features["meaningful_volume_token_count"] >= 3),
                (features["volume_specialist_score"] >= 55)
                & (features["early_volume_token_count"] >= 2),
            ],
            [
                "Elite Score Confidence",
                "Strong Score Confidence",
                "Candidate Score Confidence",
            ],
            default="Research Score Confidence",
        )
        features["volume_specialist_tier"] = features["volume_score_confidence_tier"]
        return features

    wallet_features = add_score_columns(wallet_features, wallet_token)

    label_order = [
        "Not Volume Specialist",
        "Volume Pattern Observed",
        "Volume Specialist Candidate",
        "Volume Specialist V1",
        "Strong Volume Specialist",
        "Elite Volume Specialist",
    ]
    label_summary = (
        wallet_features["volume_label_v1"]
        .value_counts()
        .reindex(label_order, fill_value=0)
        .rename_axis("volume_label_v1")
        .reset_index(name="wallet_count")
    )
    label_summary["wallet_pct"] = (
        100 * label_summary["wallet_count"] / len(wallet_features)
    ).round(4)

    feature_cols = [
        "early_volume_token_count",
        "meaningful_volume_token_count",
        "strong_volume_token_count",
        "high_share_token_count",
        "total_early_buy_volume_usd",
        "avg_wallet_token_early_buy_usd",
        "median_wallet_token_early_buy_usd",
        "avg_early_volume_share_pct",
        "early_trade_count",
        "early_entry_rate",
        "quality_token_rate",
        "profit_win_rate",
        "total_realized_pnl_usd",
        "median_roi_pct",
        "repeatability_score",
        "volume_depth_score",
        "early_share_score",
        "token_outcome_score",
        "behavior_consistency_score",
        "noise_penalty_score",
        "volume_specialist_score",
        "volume_score",
    ]
    distribution = (
        wallet_features[feature_cols]
        .describe(percentiles=[0.5, 0.75, 0.9, 0.95, 0.975, 0.99])
        .T.reset_index()
        .rename(columns={"index": "feature"})
    )

    sensitivity_rows = []
    for token_count in [2, 3, 5, 8, 12]:
        for volume_floor in [250, 1_000, 2_500, 5_000, 10_000]:
            count = int(
                (
                    (wallet_features["meaningful_volume_token_count"] >= token_count)
                    & (wallet_features["total_early_buy_volume_usd"] >= volume_floor)
                ).sum()
            )
            sensitivity_rows.append(
                {
                    "meaningful_volume_token_count_threshold": token_count,
                    "total_early_buy_volume_usd_threshold": volume_floor,
                    "wallet_count": count,
                    "wallet_pct": round(100 * count / len(wallet_features), 4),
                }
            )
    threshold_sensitivity = pd.DataFrame(sensitivity_rows)

    rule_summary = pd.DataFrame(
        [
            {
                "label": "Volume Pattern Observed",
                "rule": "early_volume_token_count >= 2 AND total_early_buy_volume_usd >= 250",
                "purpose": "Wallet has repeated early-volume behavior, but evidence is still weak.",
            },
            {
                "label": "Volume Specialist Candidate",
                "rule": "meaningful_volume_token_count >= 3 AND total_early_buy_volume_usd >= 1000",
                "purpose": "Wallet has repeated meaningful early buys across multiple tokens.",
            },
            {
                "label": "Volume Specialist V1",
                "rule": "meaningful_volume_token_count >= 5 AND total_early_buy_volume_usd >= 2500 AND avg_early_volume_share_pct >= 2",
                "purpose": "Wallet repeatedly contributes meaningful early buy volume and has non-trivial share of early token volume.",
            },
            {
                "label": "Strong Volume Specialist",
                "rule": "meaningful_volume_token_count >= 8 AND total_early_buy_volume_usd >= 5000 AND high_share_token_count >= 3",
                "purpose": "Wallet repeats the behavior at higher scale and sometimes dominates token early volume.",
            },
            {
                "label": "Elite Volume Specialist",
                "rule": "meaningful_volume_token_count >= 12 AND total_early_buy_volume_usd >= 10000 AND high_share_token_count >= 5",
                "purpose": "Rare wallet with repeated, high-scale, high-share early volume behavior.",
            },
        ]
    )

    validation = []
    specialists = wallet_features[wallet_features["is_volume_specialist_v1"]]
    non_specialists = wallet_features[~wallet_features["is_volume_specialist_v1"]]
    for cohort_name, cohort in [
        ("Volume Specialist V1+", specialists),
        ("Non Specialist", non_specialists),
        ("All Early-Volume Wallets", wallet_features),
    ]:
        validation.append(
            {
                "cohort": cohort_name,
                "wallet_count": len(cohort),
                "median_total_early_buy_volume_usd": cohort["total_early_buy_volume_usd"].median(),
                "median_meaningful_volume_token_count": cohort["meaningful_volume_token_count"].median(),
                "median_avg_early_volume_share_pct": cohort["avg_early_volume_share_pct"].median(),
                "median_quality_token_rate": cohort["quality_token_rate"].median(),
                "median_profit_win_rate": cohort["profit_win_rate"].median(),
                "median_total_realized_pnl_usd": cohort["total_realized_pnl_usd"].median(),
                "median_volume_score": cohort["volume_score"].median(),
            }
        )
    validation_summary = pd.DataFrame(validation)

    component_summary = (
        wallet_features[
            [
                "repeatability_score",
                "volume_depth_score",
                "early_share_score",
                "token_outcome_score",
                "behavior_consistency_score",
                "noise_penalty_score",
                "volume_specialist_score",
            ]
        ]
        .describe(percentiles=[0.5, 0.75, 0.9, 0.95, 0.975, 0.99])
        .T.reset_index()
        .rename(columns={"index": "score_component"})
    )
    tier_summary = (
        wallet_features["volume_score_confidence_tier"]
        .value_counts()
        .rename_axis("volume_score_confidence_tier")
        .reset_index(name="wallet_count")
    )
    tier_summary["wallet_pct"] = (
        100 * tier_summary["wallet_count"] / len(wallet_features)
    ).round(4)

    def tier_validation_frame(group_col: str) -> pd.DataFrame:
        rows = []
        for tier, cohort in wallet_features.groupby(group_col, dropna=False):
            rows.append(
                {
                    group_col: tier,
                    "wallet_count": len(cohort),
                    "strict_v1_wallet_count": int(cohort["is_volume_specialist_v1"].sum()),
                    "strict_v1_wallet_pct": round(100 * cohort["is_volume_specialist_v1"].mean(), 4),
                    "median_ath_over_500k_rate": cohort["quality_token_rate"].median(),
                    "median_ath_over_1m_count": cohort["ath_over_1m_count"].median(),
                    "median_profit_win_rate": cohort["profit_win_rate"].median(),
                    "median_total_realized_pnl_usd": cohort["total_realized_pnl_usd"].median(),
                    "median_early_entry_rate": cohort["early_entry_rate"].median(),
                    "median_noise_penalty_score": cohort["noise_penalty_score"].median(),
                    "median_volume_specialist_score": cohort["volume_specialist_score"].median(),
                    "median_meaningful_volume_token_count": cohort["meaningful_volume_token_count"].median(),
                    "median_total_early_buy_volume_usd": cohort["total_early_buy_volume_usd"].median(),
                }
            )
        return pd.DataFrame(rows).sort_values("median_volume_specialist_score", ascending=False)

    v11_validation_summary = tier_validation_frame("volume_score_confidence_tier")
    label_vs_confidence = (
        pd.crosstab(
            wallet_features["volume_label_v1"],
            wallet_features["volume_score_confidence_tier"],
        )
        .reset_index()
    )

    tier_metric_rows = []
    tier_metrics = [
        "quality_token_rate",
        "profit_win_rate",
        "total_realized_pnl_usd",
        "median_roi_pct",
        "early_entry_rate",
        "noise_penalty_score",
        "meaningful_volume_token_count",
        "total_early_buy_volume_usd",
        "avg_early_volume_share_pct",
        "volume_specialist_score",
    ]
    for tier, cohort in wallet_features.groupby("volume_score_confidence_tier"):
        for metric in tier_metrics:
            values = cohort[metric].dropna()
            tier_metric_rows.append(
                {
                    "volume_score_confidence_tier": tier,
                    "metric": metric,
                    "wallet_count": len(cohort),
                    "p25": values.quantile(0.25),
                    "median": values.median(),
                    "p75": values.quantile(0.75),
                    "mean": values.mean(),
                }
            )
    tier_metric_distribution = pd.DataFrame(tier_metric_rows)

    def aggregate_from_wallet_token(source: pd.DataFrame) -> pd.DataFrame:
        if source.empty:
            return pd.DataFrame()
        features = (
            source.groupby("wallet_address")
            .agg(
                early_volume_token_count=("token_address", "nunique"),
                meaningful_volume_token_count=("meaningful_volume_token", "sum"),
                strong_volume_token_count=("strong_volume_token", "sum"),
                high_share_token_count=("high_share_token", "sum"),
                first_buy_under_20k_count=("first_buy_under_20k", "sum"),
                ath_over_500k_count=("ath_over_500k", "sum"),
                ath_over_1m_count=("ath_over_1m", "sum"),
                profitable_volume_token_count=("profitable_token", "sum"),
                total_early_buy_volume_usd=("wallet_early_buy_volume_usd", "sum"),
                total_realized_pnl_usd=("realized_pnl_usd", "sum"),
                avg_roi_pct=("roi_pct", "mean"),
                median_roi_pct=("roi_pct", "median"),
                avg_wallet_token_early_buy_usd=("wallet_early_buy_volume_usd", "mean"),
                median_wallet_token_early_buy_usd=("wallet_early_buy_volume_usd", "median"),
                std_wallet_token_early_buy_usd=("wallet_early_buy_volume_usd", "std"),
                max_wallet_token_early_buy_usd=("wallet_early_buy_volume_usd", "max"),
                avg_early_volume_share_pct=("early_volume_share_pct", "mean"),
                max_early_volume_share_pct=("early_volume_share_pct", "max"),
                early_trade_count=("wallet_early_buy_trade_count", "sum"),
                first_seen_time=("first_buy_time", "min"),
                last_seen_time=("last_buy_time", "max"),
            )
            .reset_index()
        )
        features["avg_early_buy_size_usd"] = (
            features["total_early_buy_volume_usd"]
            / features["early_trade_count"].replace(0, np.nan)
        ).fillna(0)
        features["early_entry_rate"] = (
            features["first_buy_under_20k_count"]
            / features["early_volume_token_count"].replace(0, np.nan)
        ).fillna(0)
        features["quality_token_rate"] = (
            features["ath_over_500k_count"]
            / features["early_volume_token_count"].replace(0, np.nan)
        ).fillna(0)
        features["profit_win_rate"] = (
            features["profitable_volume_token_count"]
            / features["early_volume_token_count"].replace(0, np.nan)
        ).fillna(0)
        features["volume_size_cv"] = (
            features["std_wallet_token_early_buy_usd"].fillna(0)
            / features["avg_wallet_token_early_buy_usd"].replace(0, np.nan)
        ).fillna(0)
        features["volume_size_consistency"] = (1 / (1 + features["volume_size_cv"])).clip(0, 1)
        return features

    token_times = tokens[["token_address", "created_time"]].dropna()
    split_cutoff = token_times["created_time"].quantile(0.70)
    train_tokens = set(token_times.loc[token_times["created_time"] <= split_cutoff, "token_address"])
    validation_tokens = set(token_times.loc[token_times["created_time"] > split_cutoff, "token_address"])
    train_wallet_token = wallet_token[wallet_token["token_address"].isin(train_tokens)].copy()
    validation_wallet_token = wallet_token[wallet_token["token_address"].isin(validation_tokens)].copy()
    train_features = aggregate_from_wallet_token(train_wallet_token)
    train_scored = add_score_columns(train_features, train_wallet_token) if not train_features.empty else train_features
    validation_outcomes = aggregate_from_wallet_token(validation_wallet_token)
    if not validation_outcomes.empty and not train_scored.empty:
        time_split = train_scored[
            [
                "wallet_address",
                "volume_score_confidence_tier",
                "volume_specialist_score",
                "meaningful_volume_token_count",
                "total_early_buy_volume_usd",
            ]
        ].merge(
            validation_outcomes[
                [
                    "wallet_address",
                    "early_volume_token_count",
                    "quality_token_rate",
                    "ath_over_1m_count",
                    "profit_win_rate",
                    "total_realized_pnl_usd",
                    "median_roi_pct",
                    "early_entry_rate",
                    "noise_penalty_score" if "noise_penalty_score" in validation_outcomes.columns else "early_volume_token_count",
                ]
            ],
            on="wallet_address",
            how="inner",
            suffixes=("_train", "_validation"),
        )
        validation_summary_rows = []
        for tier, cohort in time_split.groupby("volume_score_confidence_tier"):
            validation_summary_rows.append(
                {
                    "train_volume_score_confidence_tier": tier,
                    "wallets_with_later_trades": len(cohort),
                    "median_later_quality_token_rate": cohort["quality_token_rate"].median(),
                    "median_later_ath_over_1m_count": cohort["ath_over_1m_count"].median(),
                    "median_later_profit_win_rate": cohort["profit_win_rate"].median(),
                    "median_later_total_realized_pnl_usd": cohort["total_realized_pnl_usd"].median(),
                    "median_later_roi_pct": cohort["median_roi_pct"].median(),
                    "median_later_early_entry_rate": cohort["early_entry_rate"].median(),
                    "median_train_score": cohort["volume_specialist_score"].median(),
                }
            )
        time_split_validation = pd.DataFrame(validation_summary_rows).sort_values(
            "median_train_score", ascending=False
        )
    else:
        time_split_validation = pd.DataFrame()
    time_split_metadata = pd.DataFrame(
        [
            {
                "split_method": "token_created_time_70_30",
                "split_cutoff_utc": split_cutoff.isoformat() if pd.notna(split_cutoff) else "",
                "train_token_count": len(train_tokens),
                "validation_token_count": len(validation_tokens),
                "train_wallet_count": len(train_scored),
                "validation_wallet_count": validation_wallet_token["wallet_address"].nunique(),
            }
        ]
    )

    top_wallets = wallet_features.sort_values(
        ["is_volume_specialist_v1", "volume_score", "meaningful_volume_token_count"],
        ascending=[False, False, False],
    ).head(100)

    return {
        "volume_wallet_token_features.csv": wallet_token,
        "volume_wallet_features_v1.csv": wallet_features.sort_values(
            "volume_score", ascending=False
        ),
        "volume_specialists_v1_labeled_wallets.csv": wallet_features[
            wallet_features["is_volume_specialist_v1"]
        ].sort_values("volume_score", ascending=False),
        "volume_scored_wallets_v1.csv": wallet_features.sort_values(
            "volume_specialist_score", ascending=False
        ),
        "volume_high_confidence_wallets_v1.csv": wallet_features[
            wallet_features["volume_score_confidence_tier"] == "Elite Score Confidence"
        ].sort_values("volume_specialist_score", ascending=False),
        "volume_label_funnel_summary.csv": label_summary,
        "volume_feature_distributions.csv": distribution,
        "volume_threshold_sensitivity.csv": threshold_sensitivity,
        "volume_specialist_v1_rule_summary.csv": rule_summary,
        "volume_v1_validation_summary.csv": validation_summary,
        "volume_score_component_summary.csv": component_summary,
        "volume_score_tier_summary.csv": tier_summary,
        "volume_v11_confidence_validation_summary.csv": v11_validation_summary,
        "volume_v11_tier_metric_distribution.csv": tier_metric_distribution,
        "volume_v11_time_split_validation.csv": time_split_validation,
        "volume_v11_time_split_metadata.csv": time_split_metadata,
        "volume_v1_label_vs_v11_confidence.csv": label_vs_confidence,
        "top_volume_wallets_for_review.csv": top_wallets,
    }


def write_notebooks() -> None:
    shared_setup = r"""from pathlib import Path
import pandas as pd
import numpy as np

PROJECT = Path(r"C:\Users\alaga\Desktop\My Script Library\Behaviour Labeling\volume_specialist")
MIGRATION_PROJECT = Path(r"C:\Users\alaga\Desktop\My Script Library\Behaviour Labeling\migration_specialist")
RAW = MIGRATION_PROJECT / "data" / "raw"
OUT = PROJECT / "outputs" / "v1"
OUT.mkdir(parents=True, exist_ok=True)
"""

    create_notebook(
        [
            md("# Volume Specialist V1 - Data Prep\n\nPurpose: prepare a real-data early-volume research table from `token_trades.csv`.\n\nA Volume Specialist is not the same as a Migration Specialist. This label studies wallets that repeatedly contribute meaningful early buy-side volume across tokens."),
            code(shared_setup),
            code("""trades = pd.read_csv(
    RAW / "token_trades.csv",
    usecols=["token_address", "wallet_address", "tx_hash", "trade_time", "trade_type", "usd_volume", "market_cap_at_trade_usd", "migration_phase"],
)
tokens = pd.read_csv(
    RAW / "tokens.csv",
    usecols=["token_address", "symbol", "name", "created_time", "migration_time", "ath_market_cap_usd", "ath_market_cap_bucket", "current_market_cap_usd"],
)

print("trades", trades.shape)
print("tokens", tokens.shape)
trades.head()"""),
            md("## Early Volume Definition\n\nV1 only uses real historical trades. Early volume is defined as buy-side volume where the trade happened before migration or while market cap was at or below $40k."),
            code("""early_buys = trades[
    (trades["trade_type"].str.lower() == "buy")
    & (
        (trades["migration_phase"] == "pre_migration")
        | (trades["market_cap_at_trade_usd"] <= 40_000)
    )
].copy()

early_buys["usd_volume"].describe(percentiles=[.5, .75, .9, .95, .975, .99])"""),
            code("""token_volume = early_buys.groupby("token_address").agg(
    token_early_buy_volume_usd=("usd_volume", "sum"),
    token_early_buy_trade_count=("usd_volume", "size"),
    token_early_wallet_count=("wallet_address", "nunique"),
).reset_index()

wallet_token = early_buys.groupby(["wallet_address", "token_address"]).agg(
    wallet_early_buy_volume_usd=("usd_volume", "sum"),
    wallet_early_buy_trade_count=("usd_volume", "size"),
    first_buy_time=("trade_time", "min"),
    last_buy_time=("trade_time", "max"),
    first_buy_market_cap_usd=("market_cap_at_trade_usd", "min"),
).reset_index().merge(token_volume, on="token_address", how="left")

wallet_token["early_volume_share_pct"] = (
    100 * wallet_token["wallet_early_buy_volume_usd"] / wallet_token["token_early_buy_volume_usd"].replace(0, np.nan)
).fillna(0)

wallet_token.to_csv(OUT / "volume_wallet_token_features.csv", index=False)
wallet_token.head()"""),
            md("## Wallet-Level Feature Table\n\nThis step makes the pipeline reproducible. The next notebooks depend on `volume_wallet_features_v1.csv`, so it must be created here from the wallet-token table."),
            code("""wallet_token["meaningful_volume_token"] = wallet_token["wallet_early_buy_volume_usd"] >= 100
wallet_token["strong_volume_token"] = wallet_token["wallet_early_buy_volume_usd"] >= 250
wallet_token["high_share_token"] = (
    (wallet_token["wallet_early_buy_volume_usd"] >= 100)
    & (wallet_token["early_volume_share_pct"] >= 5)
)
wallet_token["first_buy_under_20k"] = wallet_token["first_buy_market_cap_usd"] <= 20_000

wallet_features = wallet_token.groupby("wallet_address").agg(
    early_volume_token_count=("token_address", "nunique"),
    meaningful_volume_token_count=("meaningful_volume_token", "sum"),
    strong_volume_token_count=("strong_volume_token", "sum"),
    high_share_token_count=("high_share_token", "sum"),
    first_buy_under_20k_count=("first_buy_under_20k", "sum"),
    total_early_buy_volume_usd=("wallet_early_buy_volume_usd", "sum"),
    avg_wallet_token_early_buy_usd=("wallet_early_buy_volume_usd", "mean"),
    median_wallet_token_early_buy_usd=("wallet_early_buy_volume_usd", "median"),
    avg_early_volume_share_pct=("early_volume_share_pct", "mean"),
    early_trade_count=("wallet_early_buy_trade_count", "sum"),
).reset_index()

wallet_features["early_entry_rate"] = (
    wallet_features["first_buy_under_20k_count"]
    / wallet_features["early_volume_token_count"].replace(0, np.nan)
).fillna(0)

wallet_features.to_csv(OUT / "volume_wallet_features_v1.csv", index=False)
wallet_features.head()"""),
        ],
        NOTEBOOKS / "01_data_prep.ipynb",
    )

    create_notebook(
        [
            md("# Volume Specialist V1 Framework\n\nPurpose: define the first rule-based label using distributions, not guesses."),
            code(shared_setup),
            code("""wallets = pd.read_csv(OUT / "volume_wallet_features_v1.csv")
wallets.shape, wallets.head()"""),
            md("## Distribution Review\n\nThe threshold must be rare, repeatable, and explainable."),
            code("""features = [
    "early_volume_token_count",
    "meaningful_volume_token_count",
    "strong_volume_token_count",
    "high_share_token_count",
    "total_early_buy_volume_usd",
    "avg_early_volume_share_pct",
    "volume_score",
]
wallets[features].describe(percentiles=[.5, .75, .9, .95, .975, .99]).T"""),
            md("## V1 Label Rules\n\nV1 focuses on repeatable meaningful early buy volume. It does not claim the wallet is profitable yet."),
            code("""pd.read_csv(OUT / "volume_specialist_v1_rule_summary.csv")"""),
            code("""pd.read_csv(OUT / "volume_label_funnel_summary.csv")"""),
            code("""pd.read_csv(OUT / "volume_threshold_sensitivity.csv").pivot(
    index="meaningful_volume_token_count_threshold",
    columns="total_early_buy_volume_usd_threshold",
    values="wallet_count",
)"""),
            md("## Official V1 Output\n\nFreeze this file as the first benchmark dataset for Volume Specialist."),
            code("""specialists = pd.read_csv(OUT / "volume_specialists_v1_labeled_wallets.csv")
specialists.head(25)"""),
        ],
        NOTEBOOKS / "02_v1_framework.ipynb",
    )

    create_notebook(
        [
            md("# Volume Specialist V1 Validation\n\nQuestion: do the labeled wallets meaningfully differ from non-specialists?"),
            code(shared_setup),
            code("""wallets = pd.read_csv(OUT / "volume_wallet_features_v1.csv")
summary = pd.read_csv(OUT / "volume_v1_validation_summary.csv")
summary"""),
            md("## Cohort Comparison\n\nThis validation is intentionally simple for V1. It checks whether the label creates a materially different wallet population."),
            code("""specialists = wallets[wallets["is_volume_specialist_v1"]]
non_specialists = wallets[~wallets["is_volume_specialist_v1"]]

comparison_cols = [
    "total_early_buy_volume_usd",
    "meaningful_volume_token_count",
    "avg_early_volume_share_pct",
    "quality_token_rate",
    "volume_score",
]
pd.DataFrame({
    "specialist_median": specialists[comparison_cols].median(),
    "non_specialist_median": non_specialists[comparison_cols].median(),
    "specialist_mean": specialists[comparison_cols].mean(),
    "non_specialist_mean": non_specialists[comparison_cols].mean(),
})"""),
            md("## Review List\n\nUse this table to inspect the top wallets before any live or scoring work."),
            code("""pd.read_csv(OUT / "top_volume_wallets_for_review.csv").head(50)"""),
        ],
        NOTEBOOKS / "03_validation.ipynb",
    )

    create_notebook(
        [
            md("# Volume Specialist V1.1 - Scoring Layer\n\nPurpose: rank early-volume wallets by confidence without changing the V1 baseline rule.\n\nV1 answers: did the behavior happen repeatedly?\n\nV1.1 answers: how convincing is the behavior?"),
            code(shared_setup),
            code("""wallets = pd.read_csv(OUT / "volume_scored_wallets_v1.csv")
wallets.shape, wallets.head()"""),
            md("## Score Architecture\n\nWeights:\n\n```text\nrepeatability_score          25%\nvolume_depth_score           20%\nearly_share_score            20%\ntoken_outcome_score          20%\nbehavior_consistency_score   10%\nnoise_penalty_score         -15%\n```\n\n`token_outcome_score` asks whether the wallet repeatedly appears early in tokens that later become meaningful. It is not the same thing as wallet profitability."),
            code("""score_cols = [
    "repeatability_score",
    "volume_depth_score",
    "early_share_score",
    "token_outcome_score",
    "behavior_consistency_score",
    "noise_penalty_score",
    "volume_specialist_score",
]
wallets[score_cols].describe(percentiles=[.5, .75, .9, .95, .975, .99]).T"""),
            md("## Tier Summary\n\nThe score creates confidence tiers. These do not replace the V1 rule; they help prioritize review and future live alerts."),
            code("""pd.read_csv(OUT / "volume_score_tier_summary.csv")"""),
            code("""wallets.groupby(["volume_score_confidence_tier", "volume_label_v1"]).size().reset_index(name="wallet_count").sort_values(
    ["volume_score_confidence_tier", "wallet_count"], ascending=[True, False]
)"""),
            md("## Top Scored Wallets\n\nReview this table for likely high-confidence Volume Specialists and possible noisy wallets."),
            code("""review_cols = [
    "wallet_address",
    "volume_label_v1",
    "volume_score_confidence_tier",
    "volume_specialist_score",
    "repeatability_score",
    "volume_depth_score",
    "early_share_score",
    "token_outcome_score",
    "behavior_consistency_score",
    "noise_penalty_score",
    "meaningful_volume_token_count",
    "total_early_buy_volume_usd",
    "avg_early_volume_share_pct",
    "quality_token_rate",
    "early_entry_rate",
]
wallets[review_cols].head(50)"""),
            md("## Baseline vs Score\n\nThis is the important research split:\n\n```text\nV1 label = observed repeated volume behavior\nV1.1 score = confidence and priority ranking\n```"),
            code("""pd.crosstab(wallets["volume_label_v1"], wallets["volume_score_confidence_tier"], margins=True)"""),
        ],
        NOTEBOOKS / "04_scoring_layer.ipynb",
    )

    create_notebook(
        [
            md("# Volume Specialist V1.1 Validation\n\nPurpose: validate the scoring confidence tiers, not only the strict V1 rule.\n\nImportant distinction:\n\n```text\nvolume_label_v1 = behavior label\nvolume_score_confidence_tier = ranking confidence\n```\n\nA wallet can be `Strong Score Confidence` without being strict `Volume Specialist V1`. That means it scores well enough for research review, not that it passed the strict rule."),
            code(shared_setup),
            code("""wallets = pd.read_csv(OUT / "volume_scored_wallets_v1.csv")
validation = pd.read_csv(OUT / "volume_v11_confidence_validation_summary.csv")
label_vs_confidence = pd.read_csv(OUT / "volume_v1_label_vs_v11_confidence.csv")
tier_distribution = pd.read_csv(OUT / "volume_v11_tier_metric_distribution.csv")
time_split = pd.read_csv(OUT / "volume_v11_time_split_validation.csv")
time_split_meta = pd.read_csv(OUT / "volume_v11_time_split_metadata.csv")

wallets.shape, wallets.head()"""),
            md("## Confidence Tier Summary\n\nThis is the official V1.1 validation table."),
            code("""validation"""),
            md("## Strict Label vs Score Confidence\n\nThis answers the key confusion: how many high-scoring wallets also pass the strict V1 label?"),
            code("""label_vs_confidence"""),
            md("## Outcome Comparison\n\nCompare tiers against token outcome, wallet PnL, early-entry behavior, repeatability, and noise penalty."),
            code("""metric_cols = [
    "quality_token_rate",
    "ath_over_1m_count",
    "profit_win_rate",
    "total_realized_pnl_usd",
    "early_entry_rate",
    "noise_penalty_score",
    "meaningful_volume_token_count",
    "total_early_buy_volume_usd",
    "volume_specialist_score",
]
wallets.groupby("volume_score_confidence_tier")[metric_cols].median().sort_values(
    "volume_specialist_score", ascending=False
)"""),
            md("## Distribution Checks\n\nMedians alone are not enough. This table adds p25, median, p75, and mean for every key metric by score-confidence tier."),
            code("""tier_distribution"""),
            md("## Historical Time Split\n\nEarlier tokens build the wallet scores. Later tokens test whether those wallet tiers still show better outcomes. This is historical out-of-sample validation, not live prospective validation."),
            code("""time_split_meta"""),
            code("""time_split"""),
            md("## Strong Confidence Review\n\nThese wallets are not automatically final specialists. They are the priority set for manual review and later live testing."),
            code("""review_cols = [
    "wallet_address",
    "volume_label_v1",
    "volume_score_confidence_tier",
    "volume_specialist_score",
    "meaningful_volume_token_count",
    "early_volume_token_count",
    "total_early_buy_volume_usd",
    "avg_early_volume_share_pct",
    "quality_token_rate",
    "profit_win_rate",
    "early_entry_rate",
    "noise_penalty_score",
]
wallets[wallets["volume_score_confidence_tier"].isin([
    "Elite Score Confidence",
    "Strong Score Confidence",
])][review_cols].head(100)"""),
            md("## Interpretation\n\nUse V1.1 to decide which wallets deserve more attention. Do not move Volume to live alerts until the score-confidence tiers prove they separate better outcomes from noisy behavior."),
        ],
        NOTEBOOKS / "05_v11_validation.ipynb",
    )


def write_readme() -> None:
    readme = """# Volume Specialist

Volume Specialist is a separate behavior family from Migration Specialist.

V1 objective:

```text
Find wallets that repeatedly contribute meaningful early buy-side volume across tokens.
```

Current structure:

```text
volume_specialist/
  notebooks/
    01_data_prep.ipynb
    02_v1_framework.ipynb
    03_validation.ipynb
    04_scoring_layer.ipynb
    05_v11_validation.ipynb
  outputs/
    v1/
```

The project currently reads shared raw data from:

```text
../migration_specialist/data/raw/
```

V1 label logic:

```text
Volume Specialist V1 =
meaningful_volume_token_count >= 5
AND total_early_buy_volume_usd >= 2500
AND avg_early_volume_share_pct >= 2
```

V1.1 scoring layer:

```text
repeatability_score          25%
volume_depth_score           20%
early_share_score            20%
token_outcome_score          20%
behavior_consistency_score   10%
noise_penalty_score         -15%
volume_score_confidence_tier
```

This label measures repeatable early-volume behavior. The score ranks confidence and signal quality. `Strong`, `Candidate`, and `Research` are score-confidence tiers, not replacements for the strict V1 label. It does not yet claim live persistence.
"""
    (PROJECT / "README.md").write_text(readme, encoding="utf-8")


def main() -> None:
    NOTEBOOKS.mkdir(parents=True, exist_ok=True)
    OUTPUTS.mkdir(parents=True, exist_ok=True)

    outputs = build_outputs()
    for name, df in outputs.items():
        df.to_csv(OUTPUTS / name, index=False)

    write_notebooks()
    write_readme()

    summary = pd.read_csv(OUTPUTS / "volume_label_funnel_summary.csv")
    specialists = pd.read_csv(OUTPUTS / "volume_specialists_v1_labeled_wallets.csv")
    print(f"Created {PROJECT}")
    print(summary.to_string(index=False))
    print(f"Specialists: {len(specialists)}")
    print(f"Top specialist score: {specialists['volume_score'].max() if len(specialists) else 'n/a'}")


if __name__ == "__main__":
    main()
