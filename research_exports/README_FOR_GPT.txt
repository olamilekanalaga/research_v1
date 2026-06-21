Pump Momentum Scanner research export

Use these CSVs instead of uploading the full SQLite database.

Recommended prompt:
I am researching Pump.fun short-term scalp behavior. One row in token_outcomes.csv is one token. One row in paper_trades_enriched.csv is one paper trade. The target is finding setups that can hit +50% while avoiding heavy stop losses. Please analyze the CSVs and suggest better rule conditions and ML features. Avoid data leakage from future snapshots.

Key files:
- paper_trades_enriched.csv: actual paper entries/exits with entry features
- token_outcomes.csv: one row per token with max runup and early features
- market_cap_band_summary.csv: outcome rates by initial market cap
- winner_vs_dead_feature_summary.csv: feature averages by outcome group
- scanner_rejection_summary.csv: why scanner rejected tokens
- schema_tables_columns.csv: database schema
- ml_models_summary.csv: saved ML metrics JSON
