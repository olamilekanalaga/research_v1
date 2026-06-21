from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuleResult:
    passed: bool
    failed_reason: str
    entry_reason: str
    required_consecutive_passes: int = 2


def cautious_a_type_rule(snapshot: dict) -> RuleResult:
    failures: list[str] = []
    age = snapshot.get("age_seconds")
    market_cap = snapshot.get("market_cap")
    buy_volume_1m = snapshot.get("buy_volume_1m") or 0
    sell_volume_1m = snapshot.get("sell_volume_1m") or 0
    unique_buyers_1m = snapshot.get("unique_buyers_1m") or 0
    risk_score = snapshot.get("risk_score")
    top_10 = snapshot.get("top_10_holder_pct")
    dev_sold = snapshot.get("dev_wallet_sold") or 0
    rugged = snapshot.get("rugged") or 0

    if age is None or age > 300:
        failures.append("age_over_5m")
    if market_cap is None or not (5_000 <= market_cap <= 20_000):
        failures.append("mc_not_5k_20k")
    if buy_volume_1m < 2_500:
        failures.append("buy_volume_1m_low")
    if unique_buyers_1m < 5:
        failures.append("unique_buyers_1m_low")
    if sell_volume_1m > buy_volume_1m:
        failures.append("sell_volume_gt_buy_volume")
    if dev_sold:
        failures.append("dev_sold")
    if rugged:
        failures.append("rugged")
    if risk_score is not None and risk_score >= 8:
        failures.append("risk_score_high")
    if top_10 is not None and top_10 >= 85:
        failures.append("top10_concentration_high")

    reason = (
        f"buy1m=${buy_volume_1m:,.0f}; sellers<=buyers; "
        f"unique_buyers_1m={unique_buyers_1m}; mc=${market_cap or 0:,.0f}"
    )
    return RuleResult(
        passed=not failures,
        failed_reason=",".join(failures),
        entry_reason=reason,
        required_consecutive_passes=2,
    )


def fast_breakout_rule(snapshot: dict) -> RuleResult:
    failures: list[str] = []
    age = snapshot.get("age_seconds")
    market_cap = snapshot.get("market_cap")
    buy_volume_1m = snapshot.get("buy_volume_1m") or 0
    sell_volume_1m = snapshot.get("sell_volume_1m") or 0
    unique_buyers_1m = snapshot.get("unique_buyers_1m") or 0
    trade_count_1m = snapshot.get("trade_count_1m") or 0
    top_10 = snapshot.get("top_10_holder_pct")
    rugged = snapshot.get("rugged") or 0

    if age is None or age > 300:
        failures.append("age_over_5m")
    if market_cap is None or not (5_000 <= market_cap <= 50_000):
        failures.append("mc_not_5k_50k")
    if buy_volume_1m < 1_000:
        failures.append("buy_volume_1m_low")
    if unique_buyers_1m < 10:
        failures.append("unique_buyers_1m_low")
    if trade_count_1m < 20:
        failures.append("trade_count_1m_low")
    if sell_volume_1m > buy_volume_1m * 0.85:
        failures.append("sell_pressure_high")
    if rugged:
        failures.append("rugged")
    if top_10 is not None and top_10 >= 85:
        failures.append("top10_concentration_high")

    reason = (
        f"FAST_BREAKOUT; mc=${market_cap or 0:,.0f}; "
        f"buy1m=${buy_volume_1m:,.0f}; sell1m=${sell_volume_1m:,.0f}; "
        f"buyers1m={unique_buyers_1m}; trades1m={trade_count_1m}"
    )
    return RuleResult(
        passed=not failures,
        failed_reason=",".join(failures),
        entry_reason=reason,
        required_consecutive_passes=1,
    )


def fast_breakout_sell_pressure_rule(snapshot: dict) -> RuleResult:
    failures: list[str] = []
    age = snapshot.get("age_seconds")
    market_cap = snapshot.get("market_cap")
    buy_volume_1m = snapshot.get("buy_volume_1m") or 0
    sell_volume_1m = snapshot.get("sell_volume_1m") or 0
    unique_buyers_1m = snapshot.get("unique_buyers_1m") or 0
    trade_count_1m = snapshot.get("trade_count_1m") or 0
    top_10 = snapshot.get("top_10_holder_pct")
    rugged = snapshot.get("rugged") or 0
    sell_ratio = sell_volume_1m / buy_volume_1m if buy_volume_1m else 999

    if age is None or age > 300:
        failures.append("age_over_5m")
    if market_cap is None or not (5_000 <= market_cap <= 50_000):
        failures.append("mc_not_5k_50k")
    if buy_volume_1m < 1_500:
        failures.append("buy_volume_1m_low")
    if unique_buyers_1m < 20:
        failures.append("unique_buyers_1m_low")
    if trade_count_1m < 30:
        failures.append("trade_count_1m_low")
    if sell_ratio > 0.50:
        failures.append("sell_pressure_over_50pct")
    if rugged:
        failures.append("rugged")
    if top_10 is not None and top_10 >= 35:
        failures.append("top10_concentration_high")

    reason = (
        f"FAST_BREAKOUT_V4; mc=${market_cap or 0:,.0f}; "
        f"buy1m=${buy_volume_1m:,.0f}; sell1m=${sell_volume_1m:,.0f}; "
        f"sell_ratio={sell_ratio:.2f}; buyers1m={unique_buyers_1m}; "
        f"trades1m={trade_count_1m}; top10={top_10 if top_10 is not None else 'n/a'}"
    )
    return RuleResult(
        passed=not failures,
        failed_reason=",".join(failures),
        entry_reason=reason,
        required_consecutive_passes=1,
    )


def entry_rule(snapshot: dict, rule_version: str = "") -> RuleResult:
    if "sell_pressure" in rule_version:
        return fast_breakout_sell_pressure_rule(snapshot)
    if "fast_breakout" in rule_version:
        return fast_breakout_rule(snapshot)
    return cautious_a_type_rule(snapshot)
