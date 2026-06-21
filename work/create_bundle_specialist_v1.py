from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


MIGRATION_PROJECT = Path(r"C:\Users\alaga\Desktop\My Script Library\Behaviour Labeling\migration_specialist")
PROJECT = Path(r"C:\Users\alaga\Desktop\My Script Library\Behaviour Labeling\bundle_specialist")
RAW = MIGRATION_PROJECT / "data" / "raw"
NOTEBOOKS = PROJECT / "notebooks"
OUTPUTS = PROJECT / "outputs" / "v1"


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


def create_notebook(path: Path, cells: list[dict]) -> None:
    nb = {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "pygments_lexer": "ipython3"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    path.write_text(json.dumps(nb, indent=2), encoding="utf-8")


def safe_json(value) -> dict:
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def pct_rank(series: pd.Series) -> pd.Series:
    return series.rank(pct=True).fillna(0) * 100


def build_outputs() -> dict[str, pd.DataFrame]:
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
            "raw_json",
        ],
    )
    trades = pd.read_csv(
        RAW / "token_trades.csv",
        usecols=[
            "token_address",
            "wallet_address",
            "trade_time",
            "trade_type",
            "usd_volume",
            "market_cap_at_trade_usd",
            "migration_phase",
        ],
    )
    for col in ["token_address"]:
        tokens[col] = tokens[col].astype(str).str.strip()
        trades[col] = trades[col].astype(str).str.strip()
    trades["wallet_address"] = trades["wallet_address"].astype(str).str.strip()
    trades["trade_time"] = pd.to_datetime(trades["trade_time"], errors="coerce", utc=True)
    tokens["created_time"] = pd.to_datetime(tokens["created_time"], errors="coerce", utc=True)

    bundle_rows = []
    for _, row in tokens.iterrows():
        raw = safe_json(row.get("raw_json"))
        bundlers = ((raw.get("risk") or {}).get("bundlers") or {})
        bundle_wallets = bundlers.get("wallets") or []
        bundle_rows.append(
            {
                "token_address": row["token_address"],
                "symbol": row.get("symbol"),
                "name": row.get("name"),
                "created_time": row.get("created_time"),
                "migration_time": row.get("migration_time"),
                "ath_market_cap_usd": row.get("ath_market_cap_usd"),
                "ath_market_cap_bucket": row.get("ath_market_cap_bucket"),
                "current_market_cap_usd": row.get("current_market_cap_usd"),
                "bundler_count": float(bundlers.get("count") or 0),
                "bundle_total_percentage": float(bundlers.get("totalPercentage") or 0),
                "bundle_total_initial_percentage": float(bundlers.get("totalInitialPercentage") or 0),
                "bundle_wallets_listed": len(bundle_wallets),
            }
        )
    token_scores = pd.DataFrame(bundle_rows)
    token_scores["bundler_count_score"] = pct_rank(token_scores["bundler_count"])
    token_scores["bundle_initial_pct_score"] = pct_rank(token_scores["bundle_total_initial_percentage"])
    token_scores["bundle_current_pct_score"] = pct_rank(token_scores["bundle_total_percentage"])
    token_scores["bundle_score"] = (
        0.45 * token_scores["bundler_count_score"]
        + 0.35 * token_scores["bundle_initial_pct_score"]
        + 0.20 * token_scores["bundle_current_pct_score"]
    ).round(2)
    token_scores["bundle_token_tier"] = np.select(
        [
            token_scores["bundle_score"] >= 80,
            token_scores["bundle_score"] >= 60,
            token_scores["bundle_score"] >= 30,
        ],
        ["Strong Bundle Token", "Moderate Bundle Token", "Weak Bundle Token"],
        default="Low Bundle Token",
    )
    token_scores["is_bundled_v1"] = token_scores["bundle_score"] >= 60
    token_scores["is_strong_bundle_v1"] = token_scores["bundle_score"] >= 80
    token_scores["ath_over_500k"] = token_scores["ath_market_cap_usd"] >= 500_000
    token_scores["ath_over_1m"] = token_scores["ath_market_cap_usd"] >= 1_000_000

    early_buys = trades[
        (trades["trade_type"].str.lower() == "buy")
        & (
            (trades["migration_phase"] == "pre_migration")
            | (trades["market_cap_at_trade_usd"] <= 40_000)
        )
    ].copy()
    wallet_token = (
        early_buys.groupby(["wallet_address", "token_address"])
        .agg(
            early_buy_usd=("usd_volume", "sum"),
            early_trade_count=("usd_volume", "size"),
            first_buy_time=("trade_time", "min"),
            first_buy_market_cap_usd=("market_cap_at_trade_usd", "min"),
        )
        .reset_index()
        .merge(token_scores, on="token_address", how="left")
    )
    wallet_token["is_bundled_v1"] = wallet_token["is_bundled_v1"].fillna(False)
    wallet_token["is_strong_bundle_v1"] = wallet_token["is_strong_bundle_v1"].fillna(False)
    wallet_token["first_buy_under_20k"] = wallet_token["first_buy_market_cap_usd"] <= 20_000

    pnl = (
        trades.groupby(["wallet_address", "token_address", "trade_type"])["usd_volume"]
        .sum()
        .unstack(fill_value=0)
        .reset_index()
        .rename(columns={"buy": "total_buy_usd", "sell": "total_sell_usd"})
    )
    for col in ["total_buy_usd", "total_sell_usd"]:
        if col not in pnl.columns:
            pnl[col] = 0.0
    pnl["realized_pnl_usd"] = pnl["total_sell_usd"] - pnl["total_buy_usd"]
    pnl["roi_pct"] = (100 * pnl["realized_pnl_usd"] / pnl["total_buy_usd"].replace(0, np.nan)).fillna(0)
    pnl["profitable_token"] = pnl["realized_pnl_usd"] > 0
    wallet_token = wallet_token.merge(pnl, on=["wallet_address", "token_address"], how="left")
    wallet_token[["realized_pnl_usd", "roi_pct", "total_buy_usd", "total_sell_usd"]] = wallet_token[
        ["realized_pnl_usd", "roi_pct", "total_buy_usd", "total_sell_usd"]
    ].fillna(0)
    wallet_token["profitable_token"] = wallet_token["profitable_token"].fillna(False)

    wallet_token["bundle_profit"] = wallet_token["profitable_token"] & wallet_token["is_bundled_v1"]
    wallet_token["nonbundle_profit"] = wallet_token["profitable_token"] & ~wallet_token["is_bundled_v1"]
    wallet_token["bundle_realized_pnl_usd"] = np.where(
        wallet_token["is_bundled_v1"], wallet_token["realized_pnl_usd"], 0
    )
    wallet_token["nonbundle_realized_pnl_usd"] = np.where(
        ~wallet_token["is_bundled_v1"], wallet_token["realized_pnl_usd"], 0
    )

    wallet_features = (
        wallet_token.groupby("wallet_address")
        .agg(
            total_early_token_count=("token_address", "nunique"),
            bundled_token_count=("is_bundled_v1", "sum"),
            strong_bundle_token_count=("is_strong_bundle_v1", "sum"),
            nonbundled_token_count=("is_bundled_v1", lambda s: int((~s).sum())),
            early_bundle_entries=("first_buy_under_20k", lambda s: int(s[wallet_token.loc[s.index, "is_bundled_v1"]].sum())),
            avg_entry_market_cap_usd=("first_buy_market_cap_usd", "mean"),
            avg_bundle_score=("bundle_score", "mean"),
            max_bundle_score=("bundle_score", "max"),
            total_bundle_buy_usd=("early_buy_usd", lambda s: float(s[wallet_token.loc[s.index, "is_bundled_v1"]].sum())),
            total_nonbundle_buy_usd=("early_buy_usd", lambda s: float(s[~wallet_token.loc[s.index, "is_bundled_v1"]].sum())),
            bundled_tokens_profitable=("bundle_profit", "sum"),
            nonbundled_tokens_profitable=("nonbundle_profit", "sum"),
            bundled_realized_pnl_usd=("bundle_realized_pnl_usd", "sum"),
            nonbundled_realized_pnl_usd=("nonbundle_realized_pnl_usd", "sum"),
            bundled_median_roi_pct=("roi_pct", lambda s: float(s[wallet_token.loc[s.index, "is_bundled_v1"]].median()) if wallet_token.loc[s.index, "is_bundled_v1"].any() else 0),
            nonbundled_median_roi_pct=("roi_pct", lambda s: float(s[~wallet_token.loc[s.index, "is_bundled_v1"]].median()) if (~wallet_token.loc[s.index, "is_bundled_v1"]).any() else 0),
            ath_over_500k_bundle_count=("ath_over_500k", lambda s: int(s[wallet_token.loc[s.index, "is_bundled_v1"]].sum())),
            ath_over_1m_bundle_count=("ath_over_1m", lambda s: int(s[wallet_token.loc[s.index, "is_bundled_v1"]].sum())),
            total_early_buy_usd=("early_buy_usd", "sum"),
            early_trade_count=("early_trade_count", "sum"),
        )
        .reset_index()
    )
    wallet_features["bundle_affinity_score"] = (
        wallet_features["bundled_token_count"] / wallet_features["total_early_token_count"].replace(0, np.nan)
    ).fillna(0)
    wallet_features["bundled_win_rate"] = (
        wallet_features["bundled_tokens_profitable"] / wallet_features["bundled_token_count"].replace(0, np.nan)
    ).fillna(0)
    wallet_features["nonbundled_win_rate"] = (
        wallet_features["nonbundled_tokens_profitable"] / wallet_features["nonbundled_token_count"].replace(0, np.nan)
    ).fillna(0)
    wallet_features["bundle_quality_rate"] = (
        wallet_features["ath_over_500k_bundle_count"] / wallet_features["bundled_token_count"].replace(0, np.nan)
    ).fillna(0)
    wallet_features["early_bundle_entry_rate"] = (
        wallet_features["early_bundle_entries"] / wallet_features["bundled_token_count"].replace(0, np.nan)
    ).fillna(0)

    wallet_features["bundle_label_v1"] = "Not Bundle Specialist"
    label_rules = [
        (
            "Elite Bundle Specialist",
            (wallet_features["bundled_token_count"] >= 20)
            & (wallet_features["bundle_affinity_score"] >= 0.70)
            & (wallet_features["bundled_win_rate"] >= 0.60)
            & (wallet_features["bundled_realized_pnl_usd"] > 0),
        ),
        (
            "Strong Bundle Specialist",
            (wallet_features["bundled_token_count"] >= 15)
            & (wallet_features["bundle_affinity_score"] >= 0.65)
            & (wallet_features["bundled_win_rate"] >= 0.55)
            & (wallet_features["bundled_realized_pnl_usd"] > 0),
        ),
        (
            "Bundle Specialist V1",
            (wallet_features["bundled_token_count"] >= 10)
            & (wallet_features["bundle_affinity_score"] >= 0.60)
            & (wallet_features["bundled_win_rate"] >= 0.50)
            & (wallet_features["bundled_realized_pnl_usd"] > 0),
        ),
        (
            "Bundle Specialist Candidate",
            (wallet_features["bundled_token_count"] >= 5)
            & (wallet_features["bundle_affinity_score"] >= 0.50),
        ),
        (
            "Bundle Pattern Observed",
            (wallet_features["bundled_token_count"] >= 2)
            & (wallet_features["bundle_affinity_score"] >= 0.30),
        ),
    ]
    for label, mask in label_rules:
        wallet_features.loc[
            (wallet_features["bundle_label_v1"] == "Not Bundle Specialist") & mask,
            "bundle_label_v1",
        ] = label
    wallet_features["is_bundle_specialist_v1"] = wallet_features["bundle_label_v1"].isin(
        ["Bundle Specialist V1", "Strong Bundle Specialist", "Elite Bundle Specialist"]
    )

    wallet_features["bundle_repeatability_score"] = pct_rank(wallet_features["bundled_token_count"])
    wallet_features["bundle_affinity_component_score"] = pct_rank(wallet_features["bundle_affinity_score"])
    wallet_features["bundle_outcome_score"] = (
        0.45 * pct_rank(wallet_features["bundled_win_rate"])
        + 0.35 * pct_rank(wallet_features["bundled_realized_pnl_usd"])
        + 0.20 * pct_rank(wallet_features["bundle_quality_rate"])
    )
    wallet_features["bundle_entry_score"] = pct_rank(wallet_features["early_bundle_entry_rate"])
    wallet_features["bundle_noise_penalty_score"] = (
        0.55 * pct_rank(wallet_features["total_early_token_count"])
        + 0.45 * pct_rank(wallet_features["early_trade_count"])
    ).clip(0, 100)
    wallet_features["bundle_specialist_score"] = (
        0.30 * wallet_features["bundle_repeatability_score"]
        + 0.25 * wallet_features["bundle_affinity_component_score"]
        + 0.25 * wallet_features["bundle_outcome_score"]
        + 0.10 * wallet_features["bundle_entry_score"]
        - 0.10 * wallet_features["bundle_noise_penalty_score"]
    ).clip(0, 100).round(2)
    wallet_features["bundle_score_confidence_tier"] = np.select(
        [
            (wallet_features["bundle_specialist_score"] >= 85) & (wallet_features["bundled_token_count"] >= 15),
            (wallet_features["bundle_specialist_score"] >= 70) & (wallet_features["bundled_token_count"] >= 10),
            (wallet_features["bundle_specialist_score"] >= 55) & (wallet_features["bundled_token_count"] >= 5),
        ],
        ["Elite Score Confidence", "Strong Score Confidence", "Candidate Score Confidence"],
        default="Research Score Confidence",
    )

    label_order = [
        "Not Bundle Specialist",
        "Bundle Pattern Observed",
        "Bundle Specialist Candidate",
        "Bundle Specialist V1",
        "Strong Bundle Specialist",
        "Elite Bundle Specialist",
    ]
    label_summary = (
        wallet_features["bundle_label_v1"]
        .value_counts()
        .reindex(label_order, fill_value=0)
        .rename_axis("bundle_label_v1")
        .reset_index(name="wallet_count")
    )
    label_summary["wallet_pct"] = (100 * label_summary["wallet_count"] / len(wallet_features)).round(4)

    feature_cols = [
        "bundled_token_count",
        "strong_bundle_token_count",
        "bundle_affinity_score",
        "bundled_win_rate",
        "bundled_realized_pnl_usd",
        "bundled_median_roi_pct",
        "bundle_quality_rate",
        "early_bundle_entry_rate",
        "bundle_specialist_score",
    ]
    distributions = (
        wallet_features[feature_cols]
        .describe(percentiles=[0.5, 0.75, 0.9, 0.95, 0.975, 0.99])
        .T.reset_index()
        .rename(columns={"index": "feature"})
    )

    sensitivity = []
    for count in [2, 5, 10, 15, 20]:
        for affinity in [0.3, 0.5, 0.6, 0.7]:
            wallet_count = int(
                ((wallet_features["bundled_token_count"] >= count) & (wallet_features["bundle_affinity_score"] >= affinity)).sum()
            )
            sensitivity.append(
                {
                    "bundled_token_count_threshold": count,
                    "bundle_affinity_threshold": affinity,
                    "wallet_count": wallet_count,
                    "wallet_pct": round(100 * wallet_count / len(wallet_features), 4),
                }
            )
    sensitivity_df = pd.DataFrame(sensitivity)

    validation_rows = []
    for cohort_name, cohort in [
        ("Bundle Specialist V1+", wallet_features[wallet_features["is_bundle_specialist_v1"]]),
        ("Non Specialist", wallet_features[~wallet_features["is_bundle_specialist_v1"]]),
        ("All Wallets", wallet_features),
    ]:
        validation_rows.append(
            {
                "cohort": cohort_name,
                "wallet_count": len(cohort),
                "median_bundled_token_count": cohort["bundled_token_count"].median(),
                "median_bundle_affinity_score": cohort["bundle_affinity_score"].median(),
                "median_bundled_win_rate": cohort["bundled_win_rate"].median(),
                "median_bundled_realized_pnl_usd": cohort["bundled_realized_pnl_usd"].median(),
                "median_bundle_quality_rate": cohort["bundle_quality_rate"].median(),
                "median_bundle_specialist_score": cohort["bundle_specialist_score"].median(),
            }
        )
    validation_summary = pd.DataFrame(validation_rows)

    tier_metric_rows = []
    tier_metrics = [
        "bundled_token_count",
        "bundle_affinity_score",
        "bundled_win_rate",
        "bundled_realized_pnl_usd",
        "bundled_median_roi_pct",
        "bundle_quality_rate",
        "early_bundle_entry_rate",
        "bundle_noise_penalty_score",
        "bundle_specialist_score",
    ]
    for tier, cohort in wallet_features.groupby("bundle_score_confidence_tier"):
        for metric in tier_metrics:
            values = cohort[metric].dropna()
            tier_metric_rows.append(
                {
                    "bundle_score_confidence_tier": tier,
                    "metric": metric,
                    "wallet_count": len(cohort),
                    "p25": values.quantile(0.25),
                    "median": values.median(),
                    "p75": values.quantile(0.75),
                    "mean": values.mean(),
                }
            )
    tier_metric_distribution = pd.DataFrame(tier_metric_rows)

    label_vs_confidence = pd.crosstab(
        wallet_features["bundle_label_v1"],
        wallet_features["bundle_score_confidence_tier"],
    ).reset_index()

    def aggregate_wallet_features(source: pd.DataFrame) -> pd.DataFrame:
        if source.empty:
            return pd.DataFrame()
        features = (
            source.groupby("wallet_address")
            .agg(
                total_early_token_count=("token_address", "nunique"),
                bundled_token_count=("is_bundled_v1", "sum"),
                strong_bundle_token_count=("is_strong_bundle_v1", "sum"),
                early_bundle_entries=("first_buy_under_20k", lambda s: int(s[source.loc[s.index, "is_bundled_v1"]].sum())),
                avg_bundle_score=("bundle_score", "mean"),
                total_bundle_buy_usd=("early_buy_usd", lambda s: float(s[source.loc[s.index, "is_bundled_v1"]].sum())),
                bundled_tokens_profitable=("bundle_profit", "sum"),
                bundled_realized_pnl_usd=("bundle_realized_pnl_usd", "sum"),
                bundled_median_roi_pct=("roi_pct", lambda s: float(s[source.loc[s.index, "is_bundled_v1"]].median()) if source.loc[s.index, "is_bundled_v1"].any() else 0),
                ath_over_500k_bundle_count=("ath_over_500k", lambda s: int(s[source.loc[s.index, "is_bundled_v1"]].sum())),
                ath_over_1m_bundle_count=("ath_over_1m", lambda s: int(s[source.loc[s.index, "is_bundled_v1"]].sum())),
                total_early_buy_usd=("early_buy_usd", "sum"),
                early_trade_count=("early_trade_count", "sum"),
            )
            .reset_index()
        )
        features["nonbundled_token_count"] = features["total_early_token_count"] - features["bundled_token_count"]
        features["bundle_affinity_score"] = (
            features["bundled_token_count"] / features["total_early_token_count"].replace(0, np.nan)
        ).fillna(0)
        features["bundled_win_rate"] = (
            features["bundled_tokens_profitable"] / features["bundled_token_count"].replace(0, np.nan)
        ).fillna(0)
        features["bundle_quality_rate"] = (
            features["ath_over_500k_bundle_count"] / features["bundled_token_count"].replace(0, np.nan)
        ).fillna(0)
        features["early_bundle_entry_rate"] = (
            features["early_bundle_entries"] / features["bundled_token_count"].replace(0, np.nan)
        ).fillna(0)
        features["bundle_repeatability_score"] = pct_rank(features["bundled_token_count"])
        features["bundle_affinity_component_score"] = pct_rank(features["bundle_affinity_score"])
        features["bundle_outcome_score"] = (
            0.45 * pct_rank(features["bundled_win_rate"])
            + 0.35 * pct_rank(features["bundled_realized_pnl_usd"])
            + 0.20 * pct_rank(features["bundle_quality_rate"])
        )
        features["bundle_entry_score"] = pct_rank(features["early_bundle_entry_rate"])
        features["bundle_noise_penalty_score"] = (
            0.55 * pct_rank(features["total_early_token_count"])
            + 0.45 * pct_rank(features["early_trade_count"])
        ).clip(0, 100)
        features["bundle_specialist_score"] = (
            0.30 * features["bundle_repeatability_score"]
            + 0.25 * features["bundle_affinity_component_score"]
            + 0.25 * features["bundle_outcome_score"]
            + 0.10 * features["bundle_entry_score"]
            - 0.10 * features["bundle_noise_penalty_score"]
        ).clip(0, 100).round(2)
        features["bundle_score_confidence_tier"] = np.select(
            [
                (features["bundle_specialist_score"] >= 85) & (features["bundled_token_count"] >= 15),
                (features["bundle_specialist_score"] >= 70) & (features["bundled_token_count"] >= 10),
                (features["bundle_specialist_score"] >= 55) & (features["bundled_token_count"] >= 5),
            ],
            ["Elite Score Confidence", "Strong Score Confidence", "Candidate Score Confidence"],
            default="Research Score Confidence",
        )
        return features

    split_cutoff = token_scores["created_time"].dropna().quantile(0.70)
    train_tokens = set(token_scores.loc[token_scores["created_time"] <= split_cutoff, "token_address"])
    validation_tokens = set(token_scores.loc[token_scores["created_time"] > split_cutoff, "token_address"])
    train_wallet_token = wallet_token[wallet_token["token_address"].isin(train_tokens)].copy()
    validation_wallet_token = wallet_token[wallet_token["token_address"].isin(validation_tokens)].copy()
    train_features = aggregate_wallet_features(train_wallet_token)
    validation_features = aggregate_wallet_features(validation_wallet_token)
    if not train_features.empty and not validation_features.empty:
        time_join = train_features[
            [
                "wallet_address",
                "bundle_score_confidence_tier",
                "bundle_specialist_score",
                "bundled_token_count",
            ]
        ].merge(
            validation_features[
                [
                    "wallet_address",
                    "bundled_token_count",
                    "bundle_affinity_score",
                    "bundled_win_rate",
                    "bundled_realized_pnl_usd",
                    "bundled_median_roi_pct",
                    "bundle_quality_rate",
                    "early_bundle_entry_rate",
                ]
            ],
            on="wallet_address",
            how="inner",
            suffixes=("_train", "_validation"),
        )
        rows = []
        for tier, cohort in time_join.groupby("bundle_score_confidence_tier"):
            rows.append(
                {
                    "train_bundle_score_confidence_tier": tier,
                    "wallets_with_later_bundle_trades": len(cohort),
                    "median_later_bundled_token_count": cohort["bundled_token_count_validation"].median(),
                    "median_later_bundle_affinity_score": cohort["bundle_affinity_score"].median(),
                    "median_later_bundled_win_rate": cohort["bundled_win_rate"].median(),
                    "median_later_bundled_realized_pnl_usd": cohort["bundled_realized_pnl_usd"].median(),
                    "median_later_bundle_roi_pct": cohort["bundled_median_roi_pct"].median(),
                    "median_later_bundle_quality_rate": cohort["bundle_quality_rate"].median(),
                    "median_train_score": cohort["bundle_specialist_score"].median(),
                }
            )
        time_split_validation = pd.DataFrame(rows).sort_values("median_train_score", ascending=False)
    else:
        time_split_validation = pd.DataFrame()
    time_split_metadata = pd.DataFrame(
        [
            {
                "split_method": "token_created_time_70_30",
                "split_cutoff_utc": split_cutoff.isoformat() if pd.notna(split_cutoff) else "",
                "train_token_count": len(train_tokens),
                "validation_token_count": len(validation_tokens),
                "train_wallet_count": len(train_features),
                "validation_wallet_count": validation_wallet_token["wallet_address"].nunique(),
            }
        ]
    )

    rule_summary = pd.DataFrame(
        [
            {"label": label, "rule": "See notebook 04_wallet_scoring.ipynb", "purpose": "Wallet-level repeated bundled-launch behavior."}
            for label, _ in label_rules[::-1]
        ]
    )

    return {
        "bundle_token_scores.csv": token_scores.sort_values("bundle_score", ascending=False),
        "bundle_wallet_token_features.csv": wallet_token.sort_values(["wallet_address", "bundle_score"], ascending=[True, False]),
        "bundle_wallet_features_v1.csv": wallet_features.sort_values("bundle_specialist_score", ascending=False),
        "bundle_scored_wallets_v1.csv": wallet_features.sort_values("bundle_specialist_score", ascending=False),
        "bundle_specialists_v1_labeled_wallets.csv": wallet_features[wallet_features["is_bundle_specialist_v1"]].sort_values("bundle_specialist_score", ascending=False),
        "bundle_label_funnel_summary.csv": label_summary,
        "bundle_feature_distributions.csv": distributions,
        "bundle_threshold_sensitivity.csv": sensitivity_df,
        "bundle_v1_validation_summary.csv": validation_summary,
        "bundle_v11_tier_metric_distribution.csv": tier_metric_distribution,
        "bundle_v11_time_split_validation.csv": time_split_validation,
        "bundle_v11_time_split_metadata.csv": time_split_metadata,
        "bundle_v1_label_vs_v11_confidence.csv": label_vs_confidence,
        "bundle_specialist_v1_rule_summary.csv": rule_summary,
        "top_bundle_wallets_for_review.csv": wallet_features.sort_values("bundle_specialist_score", ascending=False).head(100),
    }


def write_notebooks() -> None:
    setup = r"""from pathlib import Path
import pandas as pd
import numpy as np

PROJECT = Path(r"C:\Users\alaga\Desktop\My Script Library\Behaviour Labeling\bundle_specialist")
MIGRATION_PROJECT = Path(r"C:\Users\alaga\Desktop\My Script Library\Behaviour Labeling\migration_specialist")
RAW = MIGRATION_PROJECT / "data" / "raw"
OUT = PROJECT / "outputs" / "v1"
OUT.mkdir(parents=True, exist_ok=True)
"""
    notebooks = {
        "01_data_prep.ipynb": [
            md("# Bundle Specialist V1 - Data Prep\n\nPurpose: prepare token bundle scores and early wallet participation from real historical data."),
            code(setup),
            code("""tokens = pd.read_csv(RAW / "tokens.csv")
trades = pd.read_csv(RAW / "token_trades.csv")
tokens.shape, trades.shape"""),
            md("Bundle V1 uses `tokens.raw_json.risk.bundlers` for token-level bundle evidence and `token_trades.csv` for wallet participation."),
        ],
        "02_token_bundle_scoring.ipynb": [
            md("# Token Bundle Scoring\n\nPurpose: define the bundle event before labeling wallets."),
            code(setup),
            code("""token_scores = pd.read_csv(OUT / "bundle_token_scores.csv")
token_scores[["bundler_count", "bundle_total_percentage", "bundle_total_initial_percentage", "bundle_score"]].describe(percentiles=[.5,.75,.9,.95,.975,.99]).T"""),
            code("""token_scores["bundle_token_tier"].value_counts()"""),
            code("""token_scores.head(25)"""),
        ],
        "03_wallet_bundle_behavior.ipynb": [
            md("# Wallet Bundle Behavior\n\nPurpose: move from bundled tokens to repeat wallet behavior."),
            code(setup),
            code("""wallet_token = pd.read_csv(OUT / "bundle_wallet_token_features.csv")
wallets = pd.read_csv(OUT / "bundle_wallet_features_v1.csv")
wallet_token.shape, wallets.shape"""),
            code("""wallets[["bundled_token_count", "bundle_affinity_score", "bundled_win_rate", "bundled_realized_pnl_usd"]].describe(percentiles=[.5,.75,.9,.95,.975,.99]).T"""),
        ],
        "04_wallet_scoring.ipynb": [
            md("# Bundle Specialist V1 - Wallet Scoring\n\nPurpose: create wallet-level labels and confidence scores.\n\nImportant: this is Bundle Specialist, not Bundle Insider."),
            code(setup),
            code("""pd.read_csv(OUT / "bundle_label_funnel_summary.csv")"""),
            code("""pd.read_csv(OUT / "bundle_threshold_sensitivity.csv").head(25)"""),
            code("""wallets = pd.read_csv(OUT / "bundle_scored_wallets_v1.csv")
wallets.head(50)"""),
        ],
        "05_validation.ipynb": [
            md("# Bundle Specialist V1 Validation\n\nQuestion: do strict Bundle Specialists differ from non-specialists?"),
            code(setup),
            code("""pd.read_csv(OUT / "bundle_v1_validation_summary.csv")"""),
            code("""wallets = pd.read_csv(OUT / "bundle_scored_wallets_v1.csv")
metrics = ["bundled_token_count", "bundle_affinity_score", "bundled_win_rate", "bundled_realized_pnl_usd", "bundle_quality_rate", "bundle_specialist_score"]
wallets.groupby("bundle_score_confidence_tier")[metrics].median().sort_values("bundle_specialist_score", ascending=False)"""),
        ],
    }
    for name, cells in notebooks.items():
        create_notebook(NOTEBOOKS / name, cells)


def write_readme() -> None:
    readme = """# Bundle Specialist

Bundle Specialist is a wallet behavior label.

It is not a Bundle Insider label.

```text
Token bundle evidence
    -> early wallet participation
    -> repeatability
    -> profitability/outcome
    -> wallet label
```

V1 uses:

```text
tokens.csv raw_json.risk.bundlers
token_trades.csv
```

Outputs live in:

```text
outputs/v1/
```
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
    print(f"Created {PROJECT}")
    print(outputs["bundle_label_funnel_summary.csv"].to_string(index=False))
    print("Specialists:", len(outputs["bundle_specialists_v1_labeled_wallets.csv"]))


if __name__ == "__main__":
    main()
