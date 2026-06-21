# v1 + Vlak Formation Notes (Persisted)

This repo is the lightweight v1 research baseline and migration-tracking area.
Keep secrets out of git (`.env`) and keep this file as the strategy record.

## Scope (what is included)
- Signal-level alert rows and token-level outcomes.
- No dependency on `.env` for this documentation.
- Formation logic in this repo is preserved as text only.

## Core surviving/formation assumptions
- Early-life filtering must be evaluated at alert-time snapshots we already have.
- Main useful signal families:
  1. `volume_10m_usd`
  2. `buys_10m`
  3. `holders_10m` and `holder growth` from holders snapshots
  4. `market_cap_at_signal`
  5. `liquidity_at_signal`
  6. `bundle_pct`, `sniper_pct`, `top10_holder_pct` (null-safe)

## Persisted filter shortlist (current)
- `market_cap_at_signal in [100k,250k]`
  - Very strong rate uplift, but low sample (n=35)
- `liquidity_at_signal >= 30,000`
  - Better sample (n=1,604), strong 5x/10x uplift in lightweight study
- `liquidity_at_signal >= 20,000`
  - Largest sample (n=2,531)
- `market_cap_at_signal in [25k,50k)`
  - Strong middle-sample alternative

## Important note
- If a rule has excellent lift but tiny sample, treat as **pilot only** until we collect a minimum sample size.
- For reliable production routing, combine this with outcome windows and raw journey checks.
