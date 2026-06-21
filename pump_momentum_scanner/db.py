from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS rule_versions (
    rule_version TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    config_json TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tokens (
    token_address TEXT PRIMARY KEY,
    symbol TEXT,
    name TEXT,
    launch_time INTEGER,
    initial_market_cap REAL,
    initial_price REAL,
    creator_wallet TEXT,
    created_tx TEXT,
    market TEXT,
    first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_address TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    age_seconds INTEGER,
    market_cap REAL,
    price REAL,
    liquidity_usd REAL,
    buy_volume_1m REAL DEFAULT 0,
    buy_volume_5m REAL DEFAULT 0,
    sell_volume_1m REAL DEFAULT 0,
    sell_volume_5m REAL DEFAULT 0,
    unique_buyers_1m INTEGER DEFAULT 0,
    unique_buyers_5m INTEGER DEFAULT 0,
    trade_count_1m INTEGER DEFAULT 0,
    trade_count_5m INTEGER DEFAULT 0,
    buys_total INTEGER,
    sells_total INTEGER,
    holders INTEGER,
    top_1_holder_pct REAL,
    top_5_holder_pct REAL,
    top_10_holder_pct REAL,
    bundle_or_cluster_risk REAL,
    risk_score INTEGER,
    dev_wallet_sold INTEGER DEFAULT 0,
    creator_current_balance_pct REAL,
    market_cap_change_pct REAL,
    curve_percentage REAL,
    rugged INTEGER DEFAULT 0,
    raw_json TEXT,
    FOREIGN KEY(token_address) REFERENCES tokens(token_address)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_token_time ON snapshots(token_address, timestamp);

CREATE TABLE IF NOT EXISTS trades (
    tx_signature TEXT PRIMARY KEY,
    token_address TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    wallet TEXT,
    side TEXT,
    amount_token REAL,
    amount_sol REAL,
    amount_usd REAL,
    price_usd REAL,
    market_cap_at_trade REAL,
    program TEXT,
    raw_json TEXT,
    FOREIGN KEY(token_address) REFERENCES tokens(token_address)
);

CREATE INDEX IF NOT EXISTS idx_trades_token_time ON trades(token_address, timestamp);

CREATE TABLE IF NOT EXISTS scanner_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_address TEXT NOT NULL,
    timestamp INTEGER NOT NULL,
    passed_filter INTEGER NOT NULL,
    failed_reason TEXT,
    rule_version TEXT NOT NULL,
    snapshot_id INTEGER,
    consecutive_passes INTEGER DEFAULT 0,
    features_json TEXT,
    FOREIGN KEY(token_address) REFERENCES tokens(token_address),
    FOREIGN KEY(snapshot_id) REFERENCES snapshots(id)
);

CREATE INDEX IF NOT EXISTS idx_decisions_token_time ON scanner_decisions(token_address, timestamp);

CREATE TABLE IF NOT EXISTS paper_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_address TEXT NOT NULL,
    entry_time INTEGER NOT NULL,
    entry_age_seconds INTEGER,
    entry_market_cap REAL NOT NULL,
    entry_price REAL,
    entry_notional_usd REAL DEFAULT 20,
    paper_token_units REAL,
    entry_reason TEXT,
    rule_version TEXT NOT NULL,
    status TEXT NOT NULL,
    exit_time INTEGER,
    exit_market_cap REAL,
    exit_price REAL,
    exit_value_usd REAL,
    exit_reason TEXT,
    pnl_pct REAL,
    paper_pnl_usd REAL,
    max_drawdown_pct REAL DEFAULT 0,
    max_runup_pct REAL DEFAULT 0,
    ambiguous INTEGER DEFAULT 0,
    snapshot_id INTEGER,
    FOREIGN KEY(token_address) REFERENCES tokens(token_address)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_one_open_or_done_trade_per_rule
ON paper_trades(token_address, rule_version);

CREATE TABLE IF NOT EXISTS outcomes (
    token_address TEXT PRIMARY KEY,
    rule_version TEXT NOT NULL,
    max_market_cap_5m REAL,
    max_market_cap_10m REAL,
    max_market_cap_30m REAL,
    hit_20pct INTEGER DEFAULT 0,
    hit_50pct INTEGER DEFAULT 0,
    hit_100pct INTEGER DEFAULT 0,
    hit_20k_mc INTEGER DEFAULT 0,
    hit_50k_mc INTEGER DEFAULT 0,
    rugged INTEGER DEFAULT 0,
    label TEXT,
    time_to_20pct_seconds INTEGER,
    time_to_50pct_seconds INTEGER,
    time_to_20k_seconds INTEGER,
    time_to_50k_seconds INTEGER,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(token_address) REFERENCES tokens(token_address)
);

CREATE TABLE IF NOT EXISTS missed_winners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_address TEXT NOT NULL,
    reason_not_entered TEXT,
    max_runup_pct REAL,
    time_to_20pct INTEGER,
    rule_version TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(token_address, rule_version)
);

CREATE TABLE IF NOT EXISTS api_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp INTEGER NOT NULL,
    source TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    token_address TEXT,
    status_code INTEGER,
    error_message TEXT,
    latency_ms INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bot_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ml_models (
    model_name TEXT PRIMARY KEY,
    target TEXT NOT NULL,
    feature_names TEXT NOT NULL,
    weights_json TEXT NOT NULL,
    means_json TEXT NOT NULL,
    scales_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    trained_rows INTEGER NOT NULL,
    positive_rows INTEGER NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

MIGRATIONS = [
    "ALTER TABLE paper_trades ADD COLUMN entry_notional_usd REAL DEFAULT 20",
    "ALTER TABLE paper_trades ADD COLUMN paper_token_units REAL",
    "ALTER TABLE paper_trades ADD COLUMN exit_value_usd REAL",
    "ALTER TABLE paper_trades ADD COLUMN paper_pnl_usd REAL",
]


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for statement in MIGRATIONS:
        try:
            conn.execute(statement)
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise
    conn.commit()


def dumps(data: Any) -> str:
    return json.dumps(data, separators=(",", ":"), ensure_ascii=True, default=str)
