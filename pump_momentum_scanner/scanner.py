from __future__ import annotations

import argparse
import sqlite3
import time
from typing import Any

from .config import get_settings
from .db import connect, dumps, init_db
from .rules import entry_rule
from .solanatracker import ApiError, SolanaTrackerClient
from .telegram_alerts import TelegramAlerts, paper_buy_message, paper_sell_message


def now_ms() -> int:
    return int(time.time() * 1000)


def seconds_from_ms(ms: int | None) -> int | None:
    if ms is None:
        return None
    return int(ms / 1000) if ms > 10_000_000_000 else int(ms)


def first_pool(info: dict[str, Any]) -> dict[str, Any]:
    pools = info.get("pools") or []
    pump_pools = [p for p in pools if str(p.get("market", "")).lower().startswith("pump")]
    return (pump_pools or pools or [{}])[0]


def nested(data: dict[str, Any], *keys: str) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def log_api(conn: sqlite3.Connection, source: str, endpoint: str, status_code: int | None, latency_ms: int, error: str = "", token: str | None = None) -> None:
    conn.execute(
        "INSERT INTO api_logs(timestamp, source, endpoint, token_address, status_code, error_message, latency_ms) VALUES(?,?,?,?,?,?,?)",
        (int(time.time()), source, endpoint, token, status_code, error, latency_ms),
    )
    conn.commit()


def save_token(conn: sqlite3.Connection, info: dict[str, Any]) -> str | None:
    token = info.get("token") or {}
    pool = first_pool(info)
    address = token.get("mint") or pool.get("tokenAddress")
    if not address:
        return None

    launch_time = seconds_from_ms(nested(token, "creation", "created_time") or pool.get("createdAt"))
    conn.execute(
        """
        INSERT OR IGNORE INTO tokens(
            token_address, symbol, name, launch_time, initial_market_cap, initial_price,
            creator_wallet, created_tx, market, raw_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        (
            address,
            token.get("symbol"),
            token.get("name"),
            launch_time,
            nested(pool, "marketCap", "usd"),
            nested(pool, "price", "usd"),
            nested(token, "creation", "creator") or pool.get("deployer"),
            nested(token, "creation", "created_tx"),
            pool.get("market"),
            dumps(info),
        ),
    )
    conn.commit()
    return address


def trade_features(trades: list[dict[str, Any]], at_ms: int) -> dict[str, Any]:
    one_min = at_ms - 60_000
    five_min = at_ms - 300_000
    buy_1m = sell_1m = buy_5m = sell_5m = 0.0
    buyers_1m: set[str] = set()
    buyers_5m: set[str] = set()
    count_1m = count_5m = 0

    for trade in trades:
        t = int(trade.get("time") or 0)
        side = str(trade.get("type") or "").lower()
        volume = float(trade.get("volume") or 0)
        wallet = trade.get("wallet")
        if t >= five_min:
            count_5m += 1
            if side == "buy":
                buy_5m += volume
                if wallet:
                    buyers_5m.add(wallet)
            elif side == "sell":
                sell_5m += volume
        if t >= one_min:
            count_1m += 1
            if side == "buy":
                buy_1m += volume
                if wallet:
                    buyers_1m.add(wallet)
            elif side == "sell":
                sell_1m += volume

    return {
        "buy_volume_1m": buy_1m,
        "buy_volume_5m": buy_5m,
        "sell_volume_1m": sell_1m,
        "sell_volume_5m": sell_5m,
        "unique_buyers_1m": len(buyers_1m),
        "unique_buyers_5m": len(buyers_5m),
        "trade_count_1m": count_1m,
        "trade_count_5m": count_5m,
    }


def save_trades(conn: sqlite3.Connection, token_address: str, trades: list[dict[str, Any]]) -> None:
    for trade in trades:
        tx = trade.get("tx")
        if not tx:
            continue
        conn.execute(
            """
            INSERT OR IGNORE INTO trades(
                tx_signature, token_address, timestamp, wallet, side, amount_token,
                amount_sol, amount_usd, price_usd, program, raw_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                tx,
                token_address,
                int((trade.get("time") or 0) / 1000),
                trade.get("wallet"),
                trade.get("type"),
                trade.get("amount"),
                trade.get("volumeSol"),
                trade.get("volume"),
                trade.get("priceUsd"),
                trade.get("program"),
                dumps(trade),
            ),
        )
    conn.commit()


def save_snapshot(conn: sqlite3.Connection, token_address: str, info: dict[str, Any], trades: list[dict[str, Any]]) -> tuple[int, dict[str, Any]]:
    token = info.get("token") or {}
    pool = first_pool(info)
    risk = info.get("risk") or {}
    at_ms = now_ms()
    launch_time = seconds_from_ms(nested(token, "creation", "created_time") or pool.get("createdAt"))
    age_seconds = int(time.time()) - launch_time if launch_time else None
    market_cap = nested(pool, "marketCap", "usd")
    initial = conn.execute("SELECT initial_market_cap FROM tokens WHERE token_address=?", (token_address,)).fetchone()
    initial_mc = initial["initial_market_cap"] if initial else None
    change_pct = ((market_cap - initial_mc) / initial_mc * 100) if market_cap and initial_mc else None
    features = trade_features(trades, at_ms)
    dev_pct = nested(risk, "dev", "percentage")

    snapshot = {
        **features,
        "token_address": token_address,
        "timestamp": int(time.time()),
        "age_seconds": age_seconds,
        "market_cap": market_cap,
        "price": nested(pool, "price", "usd"),
        "liquidity_usd": nested(pool, "liquidity", "usd"),
        "buys_total": info.get("buys"),
        "sells_total": info.get("sells"),
        "holders": info.get("holders"),
        "top_10_holder_pct": risk.get("top10"),
        "bundle_or_cluster_risk": nested(risk, "bundlers", "totalPercentage"),
        "risk_score": risk.get("score"),
        "creator_current_balance_pct": dev_pct,
        "dev_wallet_sold": 0,
        "market_cap_change_pct": change_pct,
        "curve_percentage": pool.get("curvePercentage"),
        "rugged": 1 if risk.get("rugged") else 0,
    }
    cursor = conn.execute(
        """
        INSERT INTO snapshots(
            token_address, timestamp, age_seconds, market_cap, price, liquidity_usd,
            buy_volume_1m, buy_volume_5m, sell_volume_1m, sell_volume_5m,
            unique_buyers_1m, unique_buyers_5m, trade_count_1m, trade_count_5m,
            buys_total, sells_total, holders, top_10_holder_pct, bundle_or_cluster_risk,
            risk_score, dev_wallet_sold, creator_current_balance_pct, market_cap_change_pct,
            curve_percentage, rugged, raw_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            token_address,
            snapshot["timestamp"],
            age_seconds,
            market_cap,
            snapshot["price"],
            snapshot["liquidity_usd"],
            features["buy_volume_1m"],
            features["buy_volume_5m"],
            features["sell_volume_1m"],
            features["sell_volume_5m"],
            features["unique_buyers_1m"],
            features["unique_buyers_5m"],
            features["trade_count_1m"],
            features["trade_count_5m"],
            snapshot["buys_total"],
            snapshot["sells_total"],
            snapshot["holders"],
            snapshot["top_10_holder_pct"],
            snapshot["bundle_or_cluster_risk"],
            snapshot["risk_score"],
            snapshot["dev_wallet_sold"],
            snapshot["creator_current_balance_pct"],
            snapshot["market_cap_change_pct"],
            snapshot["curve_percentage"],
            snapshot["rugged"],
            dumps(info),
        ),
    )
    conn.commit()
    return int(cursor.lastrowid), snapshot


def has_paper_trade(conn: sqlite3.Connection, token_address: str, rule_version: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM paper_trades WHERE token_address=? AND rule_version=?",
        (token_address, rule_version),
    ).fetchone()
    return row is not None


def record_decision(conn: sqlite3.Connection, token_address: str, rule_version: str, snapshot_id: int, snapshot: dict[str, Any]) -> tuple[bool, str, str, int, int]:
    result = entry_rule(snapshot, rule_version)
    row = conn.execute(
        """
        SELECT consecutive_passes FROM scanner_decisions
        WHERE token_address=? AND rule_version=?
        ORDER BY id DESC LIMIT 1
        """,
        (token_address, rule_version),
    ).fetchone()
    consecutive = (row["consecutive_passes"] if row else 0) + 1 if result.passed else 0
    conn.execute(
        """
        INSERT INTO scanner_decisions(
            token_address, timestamp, passed_filter, failed_reason, rule_version,
            snapshot_id, consecutive_passes, features_json
        ) VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            token_address,
            int(time.time()),
            1 if result.passed else 0,
            result.failed_reason,
            rule_version,
            snapshot_id,
            consecutive,
            dumps(snapshot),
        ),
    )
    conn.commit()
    return result.passed, result.failed_reason, result.entry_reason, consecutive, result.required_consecutive_passes


def open_paper_trade(conn: sqlite3.Connection, token_address: str, snapshot_id: int, snapshot: dict[str, Any], reason: str, rule_version: str, notional_usd: float) -> None:
    price = snapshot.get("price")
    units = (notional_usd / price) if price and price > 0 else None
    conn.execute(
        """
        INSERT OR IGNORE INTO paper_trades(
            token_address, entry_time, entry_age_seconds, entry_market_cap, entry_price,
            entry_notional_usd, paper_token_units, entry_reason, rule_version, status, snapshot_id
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            token_address,
            int(time.time()),
            snapshot.get("age_seconds"),
            snapshot["market_cap"],
            price,
            notional_usd,
            units,
            reason,
            rule_version,
            "open",
            snapshot_id,
        ),
    )
    conn.commit()


def update_paper_trades(
    conn: sqlite3.Connection,
    token_address: str,
    snapshot: dict[str, Any],
    alerts: TelegramAlerts,
    symbol: str,
    take_profit_pct: float,
    stop_loss_pct: float,
) -> None:
    row = conn.execute(
        "SELECT * FROM paper_trades WHERE token_address=? AND status='open'",
        (token_address,),
    ).fetchone()
    if not row or not snapshot.get("market_cap"):
        return

    entry_mc = row["entry_market_cap"]
    pnl_pct = (snapshot["market_cap"] - entry_mc) / entry_mc * 100
    max_runup = max(row["max_runup_pct"] or 0, pnl_pct)
    max_drawdown = min(row["max_drawdown_pct"] or 0, pnl_pct)
    hold_seconds = int(time.time()) - row["entry_time"]
    exit_reason = None

    if pnl_pct >= take_profit_pct:
        exit_reason = "take profit"
    elif pnl_pct <= -stop_loss_pct:
        exit_reason = "stop loss"
    elif snapshot.get("rugged") or pnl_pct <= -50:
        exit_reason = "rug"
    elif hold_seconds >= 600:
        exit_reason = "max hold"

    if exit_reason:
        exit_value = row["entry_notional_usd"] * (1 + pnl_pct / 100) if row["entry_notional_usd"] is not None else None
        paper_pnl = exit_value - row["entry_notional_usd"] if exit_value is not None else None
        conn.execute(
            """
            UPDATE paper_trades
            SET status='closed', exit_time=?, exit_market_cap=?, exit_price=?, exit_reason=?,
                pnl_pct=?, paper_pnl_usd=?, exit_value_usd=?, max_runup_pct=?, max_drawdown_pct=?
            WHERE id=?
            """,
            (
                int(time.time()),
                snapshot["market_cap"],
                snapshot.get("price"),
                exit_reason,
                pnl_pct,
                paper_pnl,
                exit_value,
                max_runup,
                max_drawdown,
                row["id"],
            ),
        )
        conn.commit()
        alerts.send(paper_sell_message(symbol, token_address, pnl_pct, exit_reason, hold_seconds))
    else:
        conn.execute(
            "UPDATE paper_trades SET max_runup_pct=?, max_drawdown_pct=? WHERE id=?",
            (max_runup, max_drawdown, row["id"]),
        )
        conn.commit()


def status_message(conn: sqlite3.Connection) -> str:
    counts = {}
    for table in ["tokens", "snapshots", "trades", "scanner_decisions", "paper_trades"]:
        counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    passed = conn.execute("SELECT COUNT(*) FROM scanner_decisions WHERE passed_filter=1").fetchone()[0]
    open_trades = conn.execute("SELECT COUNT(*) FROM paper_trades WHERE status='open'").fetchone()[0]
    last_reason = conn.execute(
        """
        SELECT failed_reason, COUNT(*) AS c
        FROM scanner_decisions
        WHERE passed_filter=0
        GROUP BY failed_reason
        ORDER BY c DESC
        LIMIT 1
        """
    ).fetchone()
    reason = last_reason["failed_reason"] if last_reason else "none"
    return (
        "SCANNER STATUS\n\n"
        f"Tokens: {counts['tokens']}\n"
        f"Snapshots: {counts['snapshots']}\n"
        f"Trades stored: {counts['trades']}\n"
        f"Decisions: {counts['scanner_decisions']}\n"
        f"Passed filters: {passed}\n"
        f"Paper trades: {counts['paper_trades']}\n"
        f"Open trades: {open_trades}\n"
        f"Top reject: {reason}"
    )


def scalar(conn: sqlite3.Connection, query: str, params: tuple = ()) -> int | float | str | None:
    row = conn.execute(query, params).fetchone()
    return row[0] if row else None


def command_reply(conn: sqlite3.Connection, command: str) -> str:
    cmd = command.strip().split()[0].lower()
    if cmd in {"summary", "/summary", "status", "/status"}:
        return status_message(conn)

    if cmd in {"trades", "/trades"}:
        row = conn.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN status='open' THEN 1 ELSE 0 END) AS open_trades,
                   SUM(CASE WHEN status='closed' AND pnl_pct >= 0 THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN status='closed' AND pnl_pct < 0 THEN 1 ELSE 0 END) AS losses,
                   COALESCE(SUM(CASE WHEN status='closed' THEN paper_pnl_usd ELSE 0 END), 0) AS pnl
            FROM paper_trades
            """
        ).fetchone()
        return (
            "PAPER TRADES\n\n"
            f"Total: {row['total'] or 0}\n"
            f"Open: {row['open_trades'] or 0}\n"
            f"Wins: {row['wins'] or 0}\n"
            f"Losses: {row['losses'] or 0}\n"
            f"Realized PnL: ${row['pnl'] or 0:.2f}"
        )

    if cmd in {"winners", "/winners"}:
        row = conn.execute(
            """
            WITH runs AS (
                SELECT t.token_address, t.initial_market_cap, MAX(s.market_cap) AS max_mc
                FROM tokens t JOIN snapshots s ON s.token_address=t.token_address
                WHERE t.initial_market_cap > 0
                GROUP BY t.token_address
            )
            SELECT COUNT(*) AS tokens,
                   SUM(CASE WHEN max_mc >= initial_market_cap * 1.2 THEN 1 ELSE 0 END) AS hit20,
                   SUM(CASE WHEN max_mc >= initial_market_cap * 1.5 THEN 1 ELSE 0 END) AS hit50,
                   SUM(CASE WHEN max_mc >= initial_market_cap * 2 THEN 1 ELSE 0 END) AS hit100
            FROM runs
            """
        ).fetchone()
        return (
            "WINNERS\n\n"
            f"Tokens analyzed: {row['tokens'] or 0}\n"
            f"Hit +20%: {row['hit20'] or 0}\n"
            f"Hit +50%: {row['hit50'] or 0}\n"
            f"Hit +100%: {row['hit100'] or 0}"
        )

    if cmd in {"why_no_trade", "/why_no_trade", "why", "/why"}:
        rows = conn.execute(
            """
            SELECT failed_reason, COUNT(*) AS c
            FROM scanner_decisions
            WHERE rule_version=(SELECT value FROM bot_state WHERE key='active_rule_version')
               OR rule_version=(SELECT rule_version FROM rule_versions ORDER BY created_at DESC LIMIT 1)
            GROUP BY failed_reason
            ORDER BY c DESC
            LIMIT 5
            """
        ).fetchall()
        if not rows:
            rows = conn.execute(
                "SELECT failed_reason, COUNT(*) AS c FROM scanner_decisions GROUP BY failed_reason ORDER BY c DESC LIMIT 5"
            ).fetchall()
        lines = ["WHY NO TRADE\n"]
        lines.extend(f"{row['c']}x: {row['failed_reason'] or 'passed'}" for row in rows)
        return "\n".join(lines)

    if cmd in {"rule", "/rule"}:
        version = scalar(conn, "SELECT value FROM bot_state WHERE key='active_rule_version'") or "unknown"
        return (
            "ACTIVE RULE\n\n"
            f"{version}\n"
            "Paper entry: $20\n"
            "Target: +50%\n"
            "Stop: -20%\n"
            "Focus: fast breakout momentum"
        )

    if cmd in {"database", "/database", "db", "/db"}:
        tables = ["tokens", "snapshots", "trades", "scanner_decisions", "paper_trades", "api_logs"]
        lines = ["DATABASE\n"]
        for table in tables:
            lines.append(f"{table}: {scalar(conn, 'SELECT COUNT(*) FROM ' + table) or 0}")
        return "\n".join(lines)

    if cmd in {"ml", "/ml", "model", "/model"}:
        row = conn.execute(
            "SELECT model_name, target, metrics_json, trained_rows, positive_rows, created_at FROM ml_models ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            return "No ML model trained yet."
        import json

        metrics = json.loads(row["metrics_json"])
        test = metrics.get("test", {})
        return (
            "ML MODEL\n\n"
            f"Model: {row['model_name']}\n"
            f"Target: +50%\n"
            f"Train rows: {row['trained_rows']}\n"
            f"Train positives: {row['positive_rows']}\n"
            f"Test base rate: {test.get('base_rate', 0) * 100:.1f}%\n"
            f"Top 5% precision: {test.get('top_5_pct_precision', 0) * 100:.1f}%\n"
            f"Top 10% precision: {test.get('top_10_pct_precision', 0) * 100:.1f}%\n"
            f"Top 20% precision: {test.get('top_20_pct_precision', 0) * 100:.1f}%"
        )

    return (
        "Commands:\n"
        "/summary\n"
        "/trades\n"
        "/winners\n"
        "/why_no_trade\n"
        "/rule\n"
        "/database\n"
        "/ml"
    )


def handle_telegram_commands(conn: sqlite3.Connection, alerts: TelegramAlerts) -> None:
    if not alerts.enabled:
        return
    raw_offset = scalar(conn, "SELECT value FROM bot_state WHERE key='telegram_update_offset'")
    offset = int(raw_offset) if raw_offset else None
    try:
        updates = alerts.get_updates(offset)
    except Exception as exc:
        log_api(conn, "telegram", "getUpdates", None, 0, str(exc))
        return

    max_update_id = None
    for update in updates:
        max_update_id = max(max_update_id or update["update_id"], update["update_id"])
        message = update.get("message") or update.get("edited_message") or {}
        text = (message.get("text") or "").strip()
        chat = message.get("chat") or {}
        if not text or str(chat.get("id")) != str(alerts.chat_id):
            continue
        alerts.send(command_reply(conn, text))

    if max_update_id is not None:
        conn.execute(
            "INSERT OR REPLACE INTO bot_state(key, value) VALUES('telegram_update_offset', ?)",
            (str(max_update_id + 1),),
        )
        conn.commit()


def active_tokens(conn: sqlite3.Connection, max_track_seconds: int) -> list[str]:
    cutoff = int(time.time()) - max_track_seconds
    rows = conn.execute(
        "SELECT token_address FROM tokens WHERE launch_time IS NULL OR launch_time >= ?",
        (cutoff,),
    ).fetchall()
    return [row["token_address"] for row in rows]


def run_once(
    conn: sqlite3.Connection,
    client: SolanaTrackerClient,
    alerts: TelegramAlerts,
    rule_version: str,
    max_track_seconds: int,
    paper_trade_size_usd: float,
    take_profit_pct: float,
    stop_loss_pct: float,
) -> None:
    latest = client.latest_tokens(page=1)
    log_api(conn, "solanatracker", latest.endpoint, latest.status_code, latest.latency_ms)
    for info in latest.data or []:
        pool = first_pool(info)
        if str(pool.get("market", "")).lower().startswith("pump"):
            save_token(conn, info)

    for token_address in active_tokens(conn, max_track_seconds):
        try:
            info_result = client.token_info(token_address)
            log_api(conn, "solanatracker", info_result.endpoint, info_result.status_code, info_result.latency_ms, token=token_address)
            trades_result = client.token_trades(token_address)
            log_api(conn, "solanatracker", trades_result.endpoint, trades_result.status_code, trades_result.latency_ms, token=token_address)
        except ApiError as exc:
            log_api(conn, "solanatracker", exc.endpoint, exc.status_code, exc.latency_ms, exc.args[0], token_address)
            continue

        trades = (trades_result.data or {}).get("trades") or []
        save_trades(conn, token_address, trades)
        snapshot_id, snapshot = save_snapshot(conn, token_address, info_result.data or {}, trades)
        token_meta = (info_result.data or {}).get("token") or {}
        symbol = token_meta.get("symbol") or token_address[:6]
        passed, _failed, reason, consecutive, required_passes = record_decision(conn, token_address, rule_version, snapshot_id, snapshot)

        if passed and consecutive >= required_passes and not has_paper_trade(conn, token_address, rule_version):
            open_paper_trade(conn, token_address, snapshot_id, snapshot, reason, rule_version, paper_trade_size_usd)
            alerts.send(
                paper_buy_message(
                    symbol,
                    token_address,
                    snapshot["market_cap"],
                    snapshot.get("age_seconds"),
                    reason,
                    take_profit_pct,
                    stop_loss_pct,
                )
            )

        update_paper_trades(conn, token_address, snapshot, alerts, symbol, take_profit_pct, stop_loss_pct)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pump.fun paper-trade micro-momentum scanner")
    parser.add_argument("--once", action="store_true", help="Run one scan cycle and exit")
    parser.add_argument("--subscription", action="store_true", help="Print SolanaTracker subscription plan without secrets")
    args = parser.parse_args()

    settings = get_settings()
    conn = connect(settings.database_path)
    init_db(conn)
    conn.execute(
        "INSERT OR REPLACE INTO bot_state(key, value) VALUES('active_rule_version', ?)",
        (settings.rule_version,),
    )
    conn.execute(
            "INSERT OR IGNORE INTO rule_versions(rule_version, description, config_json) VALUES(?,?,?)",
        (
            settings.rule_version,
            "Fast breakout paper rule: aims to catch $5k-$50k momentum tokens that can hit +20% before -20%.",
            dumps(
                {
                    "snapshot_seconds": settings.snapshot_seconds,
                    "max_track_minutes": settings.max_track_minutes,
                    "paper_start_balance_usd": settings.paper_start_balance_usd,
                    "paper_trade_size_usd": settings.paper_trade_size_usd,
                    "take_profit_pct": settings.take_profit_pct,
                    "stop_loss_pct": settings.stop_loss_pct,
                }
            ),
        ),
    )
    conn.commit()
    client = SolanaTrackerClient(settings.solana_tracker_api_key)
    alerts = TelegramAlerts(settings.telegram_bot_token, settings.telegram_chat_id)

    if args.subscription:
        result = client.subscription()
        log_api(conn, "solanatracker", result.endpoint, result.status_code, result.latency_ms)
        data = result.data or {}
        print(f"plan={data.get('plan')} status={data.get('status')} credits={data.get('credits')}")
        return

    if not args.once:
        alerts.send("SCANNER STARTED\n\nPaper trading only. I will DM paper buys, sells, and status heartbeats.")
    last_heartbeat = 0.0

    while True:
        try:
            handle_telegram_commands(conn, alerts)
            run_once(
                conn,
                client,
                alerts,
                settings.rule_version,
                settings.max_track_seconds,
                settings.paper_trade_size_usd,
                settings.take_profit_pct,
                settings.stop_loss_pct,
            )
        except ApiError as exc:
            log_api(conn, "solanatracker", exc.endpoint, exc.status_code, exc.latency_ms, exc.args[0])
        if args.once:
            return
        if settings.heartbeat_minutes > 0 and time.time() - last_heartbeat >= settings.heartbeat_minutes * 60:
            alerts.send(status_message(conn))
            last_heartbeat = time.time()
        time.sleep(settings.snapshot_seconds)


if __name__ == "__main__":
    main()
