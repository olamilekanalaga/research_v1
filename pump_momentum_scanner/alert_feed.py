from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path


MONEY_RE = re.compile(r"\$([0-9]+(?:\.[0-9]+)?)([KMB]?)", re.IGNORECASE)
PCT_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?)%")


@dataclass(frozen=True)
class FeedAlert:
    source: str = ""
    timestamp_label: str = ""
    token_address: str = ""
    name: str = ""
    symbol: str = ""
    label: str = ""
    alert_sol: float | None = None
    alert_buys: int | None = None
    market_cap_usd: float | None = None
    liquidity_usd: float | None = None
    volume_usd: float | None = None
    total_fees_sol: float | None = None
    age_minutes: float | None = None
    socials: tuple[str, ...] = field(default_factory=tuple)
    holders: int | None = None
    top_10_pct: float | None = None
    dex_paid: bool | None = None
    bundle_pct: float | None = None
    snipers_pct: float | None = None
    dev_sold_all: bool | None = None
    dev_current_pct: float | None = None
    holder_distribution: tuple[float, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class FeedOutcome:
    source: str = ""
    timestamp_label: str = ""
    symbol: str = ""
    multiple_x: float | None = None
    start_market_cap_usd: float | None = None
    peak_market_cap_usd: float | None = None
    within_minutes: float | None = None


@dataclass(frozen=True)
class AlertScore:
    score: int
    tier: str
    reasons: tuple[str, ...]
    penalties: tuple[str, ...]


def parse_money(value: str) -> float | None:
    match = MONEY_RE.search(value)
    if not match:
        return None
    amount = float(match.group(1))
    suffix = match.group(2).upper()
    scale = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[suffix]
    return amount * scale


def parse_pct(value: str) -> float | None:
    match = PCT_RE.search(value)
    return float(match.group(1)) if match else None


def parse_age_minutes(value: str) -> float | None:
    text = value.lower()
    total = 0.0
    matched = False
    for amount, unit in re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*([hm])", text):
        matched = True
        total += float(amount) * (60 if unit == "h" else 1)
    return total if matched else None


def parse_source_header(line: str) -> tuple[str, str] | None:
    match = re.match(r"\s*(.*?),\s*\[(.*?)\]\s*$", line)
    if not match:
        return None
    return match.group(1).strip(), match.group(2).strip()


def split_messages(raw_text: str) -> list[str]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in raw_text.splitlines():
        if parse_source_header(line) and current:
            blocks.append(current)
            current = [line]
        elif line.strip() or current:
            current.append(line)
    if current:
        blocks.append(current)
    return ["\n".join(block).strip() for block in blocks if "\n".join(block).strip()]


def parse_holder_distribution(line: str) -> tuple[float, ...]:
    if "|" not in line and "｜" not in line:
        return ()
    values = re.findall(r"([0-9]+(?:\.[0-9]+)?)", line)
    return tuple(float(value) for value in values)


def parse_alert(block: str) -> FeedAlert | None:
    if "NEW ALERT:" not in block or "CA:" not in block:
        return None

    source = ""
    timestamp_label = ""
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    header = parse_source_header(lines[0]) if lines else None
    if header:
        source, timestamp_label = header

    text = "\n".join(lines)
    sol_match = re.search(r"NEW ALERT:\s*([0-9]+(?:\.[0-9]+)?)\s*SOL\s+in\s+([0-9]+)\s+buys", text, re.IGNORECASE)
    ca_match = re.search(r"CA:\s*([1-9A-HJ-NP-Za-km-z]{32,60})", text)
    title_match = re.search(r"┌\s*(.*?)\s*\|\s*#([^\s]+)", text)

    kwargs: dict[str, object] = {
        "source": source,
        "timestamp_label": timestamp_label,
        "token_address": ca_match.group(1) if ca_match else "",
        "alert_sol": float(sol_match.group(1)) if sol_match else None,
        "alert_buys": int(sol_match.group(2)) if sol_match else None,
        "name": title_match.group(1).strip() if title_match else "",
        "symbol": title_match.group(2).strip() if title_match else "",
    }

    for line in lines:
        if "Label:" in line:
            kwargs["label"] = line.split("Label:", 1)[1].strip()
        elif "MC:" in line:
            kwargs["market_cap_usd"] = parse_money(line)
        elif "Liq:" in line:
            kwargs["liquidity_usd"] = parse_money(line)
        elif "Vol:" in line:
            kwargs["volume_usd"] = parse_money(line)
            fee_match = re.search(r"Total Fees:\s*([0-9]+(?:\.[0-9]+)?)\s*SOL", line, re.IGNORECASE)
            if fee_match:
                kwargs["total_fees_sol"] = float(fee_match.group(1))
        elif "Age:" in line:
            kwargs["age_minutes"] = parse_age_minutes(line)
        elif "Social:" in line:
            social_text = line.split("Social:", 1)[1].strip()
            kwargs["socials"] = tuple(part.strip() for part in re.split(r"[|｜]", social_text) if part.strip())
        elif "Holder:" in line:
            holder_match = re.search(r"Holder:\s*([0-9]+)", line)
            kwargs["holders"] = int(holder_match.group(1)) if holder_match else None
            kwargs["top_10_pct"] = parse_pct(line)
        elif "DEX Paid:" in line:
            kwargs["dex_paid"] = "✅" in line
        elif "Bundle:" in line:
            kwargs["bundle_pct"] = parse_pct(line)
        elif "Snipers:" in line:
            kwargs["snipers_pct"] = parse_pct(line)
        elif "Dev:" in line:
            kwargs["dev_sold_all"] = "Sold All" in line
            kwargs["dev_current_pct"] = parse_pct(line)
        elif line.startswith("└"):
            distribution = parse_holder_distribution(line)
            if distribution:
                kwargs["holder_distribution"] = distribution

    return FeedAlert(**kwargs)


def parse_outcome(block: str) -> FeedOutcome | None:
    if "🔥" not in block and "x" not in block:
        return None
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    text = "\n".join(lines)
    multiple_match = re.search(r"([0-9]+(?:\.[0-9]+)?)x", text, re.IGNORECASE)
    detail_match = re.search(
        r"#([^\s]+)\s+\$[0-9.]+[KMB]?\s*.*?\s*(\$[0-9.]+[KMB]?)\s+within\s+(.+)$",
        text,
        re.IGNORECASE,
    )
    start_match = re.search(r"#\S+\s+(\$[0-9.]+[KMB]?)", text, re.IGNORECASE)
    header = parse_source_header(lines[0]) if lines else None

    if not multiple_match or not detail_match:
        return None
    return FeedOutcome(
        source=header[0] if header else "",
        timestamp_label=header[1] if header else "",
        symbol=detail_match.group(1).strip(),
        multiple_x=float(multiple_match.group(1)),
        start_market_cap_usd=parse_money(start_match.group(1)) if start_match else None,
        peak_market_cap_usd=parse_money(detail_match.group(2)),
        within_minutes=parse_age_minutes(detail_match.group(3)),
    )


def parse_feed(raw_text: str) -> tuple[list[FeedAlert], list[FeedOutcome]]:
    alerts: list[FeedAlert] = []
    outcomes: list[FeedOutcome] = []
    for block in split_messages(raw_text):
        alert = parse_alert(block)
        if alert:
            alerts.append(alert)
            continue
        outcome = parse_outcome(block)
        if outcome:
            outcomes.append(outcome)
    return alerts, outcomes


def score_alert(alert: FeedAlert) -> AlertScore:
    score = 0
    reasons: list[str] = []
    penalties: list[str] = []

    if alert.alert_sol is not None and alert.alert_sol >= 30:
        score += 18
        reasons.append("strong_sol_burst")
    if alert.alert_buys is not None and alert.alert_buys >= 25:
        score += 14
        reasons.append("many_buys")
    if alert.market_cap_usd is not None and 12_000 <= alert.market_cap_usd <= 30_000:
        score += 14
        reasons.append("early_mc_window")
    if alert.age_minutes is not None and alert.age_minutes <= 5:
        score += 12
        reasons.append("very_fresh")
    elif alert.age_minutes is not None and alert.age_minutes <= 60:
        score += 6
        reasons.append("still_young")
    if alert.holders is not None and alert.holders >= 80:
        score += 8
        reasons.append("holder_base_forming")
    if alert.top_10_pct is not None and alert.top_10_pct <= 22:
        score += 8
        reasons.append("top10_not_extreme")
    if alert.dev_sold_all:
        score += 8
        reasons.append("dev_sold_all")
    if alert.dex_paid:
        score += 5
        reasons.append("dex_paid")
    if alert.socials:
        score += 4
        reasons.append("has_social")
    if alert.total_fees_sol is not None and alert.total_fees_sol >= 0.4:
        score += 4
        reasons.append("fees_show_activity")

    if alert.bundle_pct is not None and alert.bundle_pct >= 20:
        score -= 14
        penalties.append("bundle_high")
    if alert.snipers_pct is not None and alert.snipers_pct >= 5:
        score -= 10
        penalties.append("snipers_high")
    if alert.top_10_pct is not None and alert.top_10_pct >= 30:
        score -= 8
        penalties.append("top10_high")
    if alert.dev_current_pct is not None and alert.dev_current_pct > 0:
        score -= 8
        penalties.append("dev_still_holds")
    if alert.liquidity_usd is not None and alert.market_cap_usd is not None:
        if alert.liquidity_usd < alert.market_cap_usd * 0.35:
            score -= 6
            penalties.append("liquidity_thin")

    score = max(0, min(100, score))
    if score >= 70:
        tier = "A"
    elif score >= 55:
        tier = "B"
    elif score >= 40:
        tier = "C"
    else:
        tier = "watch_only"
    return AlertScore(score=score, tier=tier, reasons=tuple(reasons), penalties=tuple(penalties))


def match_outcomes(alerts: list[FeedAlert], outcomes: list[FeedOutcome]) -> list[dict]:
    rows: list[dict] = []
    for alert in alerts:
        candidates = [
            outcome
            for outcome in outcomes
            if outcome.symbol.lower() == alert.symbol.lower()
            or (
                outcome.start_market_cap_usd
                and alert.market_cap_usd
                and abs(outcome.start_market_cap_usd - alert.market_cap_usd) / alert.market_cap_usd <= 0.03
            )
        ]
        best = max(candidates, key=lambda row: row.multiple_x or 0, default=None)
        score = score_alert(alert)
        row = asdict(alert)
        row.update(
            {
                "score": score.score,
                "tier": score.tier,
                "score_reasons": ",".join(score.reasons),
                "score_penalties": ",".join(score.penalties),
                "outcome_multiple_x": best.multiple_x if best else None,
                "outcome_peak_market_cap_usd": best.peak_market_cap_usd if best else None,
                "outcome_within_minutes": best.within_minutes if best else None,
            }
        )
        rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse BIG VOLUME ALERT text into scored JSON rows.")
    parser.add_argument("path", type=Path, help="Text file containing pasted Telegram alert/export text")
    parser.add_argument("--jsonl", action="store_true", help="Print one JSON object per alert")
    args = parser.parse_args()

    raw_text = args.path.read_text(encoding="utf-8")
    alerts, outcomes = parse_feed(raw_text)
    rows = match_outcomes(alerts, outcomes)
    if args.jsonl:
        for row in rows:
            print(json.dumps(row, ensure_ascii=False, sort_keys=True))
    else:
        print(json.dumps({"alerts": rows, "outcomes": [asdict(row) for row in outcomes]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
