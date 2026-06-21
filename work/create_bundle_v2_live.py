from __future__ import annotations

from pathlib import Path


PROJECT = Path(r"C:\Users\alaga\Desktop\My Script Library\Behaviour Labeling\bundle_specialist")
BOT_DIR = PROJECT / "telegram_bot"
OUT_DIR = PROJECT / "outputs" / "v2"


FILES = {
    "bundle_v2_config.py": r'''"""Configuration for Bundle Specialist V2 cautious live alerts."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BOT_DIR.parent
OUTPUT_DIR = PROJECT_DIR / "outputs" / "v2"
V1_SCORED_WALLETS_PATH = PROJECT_DIR / "outputs" / "v1" / "bundle_scored_wallets_v1.csv"
LOCAL_ENV_PATH = BOT_DIR / ".env"
MIGRATION_ENV_PATH = PROJECT_DIR.parent / "migration_specialist" / "telegram_bot" / ".env"


@dataclass(frozen=True)
class BundleV2Config:
    telegram_bot_token: str
    telegram_chat_id: str
    solana_tracker_api_key: str
    helius_api_key: str
    birdeye_api_key: str
    poll_interval_seconds: int = 60
    max_trade_age_seconds: int = 300
    min_score: float = 55.0
    min_buy_usd: float = 25.0
    max_entry_market_cap_usd: float = 50_000.0
    max_wallets_per_run: int = 75
    dry_run: bool = False

    @property
    def has_telegram(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def has_market_or_trade_api(self) -> bool:
        return bool(self.solana_tracker_api_key or self.helius_api_key or self.birdeye_api_key)

    @property
    def live_enabled(self) -> bool:
        return self.has_telegram and self.has_market_or_trade_api


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_config() -> BundleV2Config:
    load_dotenv(LOCAL_ENV_PATH)
    load_dotenv(MIGRATION_ENV_PATH)
    return BundleV2Config(
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
        solana_tracker_api_key=os.getenv("SOLANA_TRACKER_API_KEY", "").strip(),
        helius_api_key=os.getenv("HELIUS_API_KEY", "").strip(),
        birdeye_api_key=os.getenv("BIRDEYE_API_KEY", "").strip(),
        poll_interval_seconds=int(os.getenv("BUNDLE_V2_POLL_INTERVAL_SECONDS", "60")),
        max_trade_age_seconds=int(os.getenv("BUNDLE_V2_MAX_TRADE_AGE_SECONDS", "300")),
        min_score=float(os.getenv("BUNDLE_V2_MIN_SCORE", "55")),
        min_buy_usd=float(os.getenv("BUNDLE_V2_MIN_BUY_USD", "25")),
        max_entry_market_cap_usd=float(os.getenv("BUNDLE_V2_MAX_ENTRY_MARKET_CAP_USD", "50000")),
        max_wallets_per_run=int(os.getenv("BUNDLE_V2_MAX_WALLETS_PER_RUN", "75")),
        dry_run=os.getenv("BUNDLE_V2_DRY_RUN", "false").lower() == "true",
    )
''',
    "bundle_v2_storage.py": r'''"""CSV storage for Bundle Specialist V2 live alerts."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

ALERT_COLUMNS = [
    "alert_id", "alert_time", "wallet_address", "bundle_label_v1", "bundle_specialist_score",
    "bundled_token_count", "bundled_win_rate", "token_address", "token_symbol",
    "entry_market_cap", "entry_price", "entry_volume_usd", "live_bundler_count",
    "live_bundle_initial_pct", "live_bundle_current_pct", "migration_status_at_entry",
    "source_api", "tx_hash", "telegram_message_id", "status",
]
OUTCOME_COLUMNS = [
    "alert_id", "token_address", "alert_time", "last_checked_at", "entry_market_cap",
    "current_market_cap", "ath_market_cap_since_alert", "max_return_multiple",
    "migration_status_latest", "days_since_alert", "source_api", "status",
]
SKIPPED_COLUMNS = ["skipped_at", "wallet_address", "token_address", "tx_hash", "reason", "source_api"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BundleV2Storage:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.alerts_path = self.output_dir / "bundle_alerts_live.csv"
        self.outcomes_path = self.output_dir / "bundle_alert_outcomes.csv"
        self.skipped_path = self.output_dir / "bundle_skipped_trades.csv"

    @staticmethod
    def _read(path: Path, columns: list[str]) -> pd.DataFrame:
        if not path.exists():
            return pd.DataFrame(columns=columns)
        return pd.read_csv(path)

    @staticmethod
    def _ensure(path: Path, columns: list[str]) -> None:
        if not path.exists():
            pd.DataFrame(columns=columns).to_csv(path, index=False)

    @staticmethod
    def _append(path: Path, columns: list[str], row: dict) -> None:
        existing = BundleV2Storage._read(path, columns)
        new_row = pd.DataFrame([{col: row.get(col) for col in columns}])
        pd.concat([existing, new_row], ignore_index=True).drop_duplicates().to_csv(path, index=False)

    def initialize_files(self) -> None:
        self._ensure(self.alerts_path, ALERT_COLUMNS)
        self._ensure(self.outcomes_path, OUTCOME_COLUMNS)
        self._ensure(self.skipped_path, SKIPPED_COLUMNS)

    def read_alerts(self) -> pd.DataFrame:
        return self._read(self.alerts_path, ALERT_COLUMNS)

    def read_outcomes(self) -> pd.DataFrame:
        return self._read(self.outcomes_path, OUTCOME_COLUMNS)

    def token_already_alerted(self, token_address: str) -> bool:
        alerts = self.read_alerts()
        return False if alerts.empty else bool(alerts["token_address"].astype(str).eq(str(token_address)).any())

    def append_alert(self, row: dict) -> None:
        self._append(self.alerts_path, ALERT_COLUMNS, row)

    def append_skip(self, wallet_address: str, token_address: str, tx_hash: str, reason: str, source_api: str = "") -> None:
        skipped = self._read(self.skipped_path, SKIPPED_COLUMNS)
        if not skipped.empty:
            mask = (
                skipped["wallet_address"].astype(str).eq(str(wallet_address))
                & skipped["token_address"].astype(str).eq(str(token_address))
                & skipped["tx_hash"].astype(str).eq(str(tx_hash))
                & skipped["reason"].astype(str).eq(str(reason))
            )
            if mask.any():
                return
        self._append(self.skipped_path, SKIPPED_COLUMNS, {
            "skipped_at": utc_now_iso(), "wallet_address": wallet_address,
            "token_address": token_address, "tx_hash": tx_hash,
            "reason": reason, "source_api": source_api,
        })

    def upsert_outcome(self, row: dict) -> None:
        outcomes = self.read_outcomes()
        alert_id = str(row.get("alert_id", ""))
        if outcomes.empty or not outcomes["alert_id"].astype(str).eq(alert_id).any():
            self._append(self.outcomes_path, OUTCOME_COLUMNS, row)
            return
        for col in OUTCOME_COLUMNS:
            outcomes.loc[outcomes["alert_id"].astype(str).eq(alert_id), col] = row.get(col)
        outcomes.drop_duplicates().to_csv(self.outcomes_path, index=False)
''',
    "bundle_v2_telegram.py": r'''"""Telegram messages for Bundle Specialist V2."""

from __future__ import annotations

import html, json, os
from urllib import parse, request
from bundle_v2_config import BundleV2Config

DEFAULT_TROJAN_REF = "r-ola_crrypt"

def _money(value, decimals=0):
    try: return f"${float(value):,.{decimals}f}"
    except Exception: return "n/a"

def _score(value):
    try: return f"{float(value):.0f}/100"
    except Exception: return "n/a"

def dex_url(token): return f"https://dexscreener.com/solana/{parse.quote(str(token))}"
def trojan_url(token):
    ref = os.getenv("TROJAN_REF", DEFAULT_TROJAN_REF)
    return f"https://t.me/hector_trojanbot?start={parse.quote(ref + '-' + str(token))}"

def markup(alert):
    token = str(alert.get("token_address") or "")
    return {"inline_keyboard": [[{"text": "Trade on Trojan", "url": trojan_url(token)}], [{"text": "Open Dexscreener", "url": dex_url(token)}]]}

def format_alert(alert):
    token = str(alert.get("token_address") or "")
    symbol = alert.get("token_symbol") or token[:6]
    return (
        "<b>Bundle Specialist V2 Signal</b>\n\n"
        f"<b>Wallet:</b> <code>{html.escape(str(alert.get('wallet_address') or ''))}</code>\n"
        f"<b>Label:</b> {html.escape(str(alert.get('bundle_label_v1') or ''))}\n"
        f"<b>Score:</b> {_score(alert.get('bundle_specialist_score'))}\n"
        f"<b>Historical bundled tokens:</b> {html.escape(str(alert.get('bundled_token_count') or ''))}\n"
        f"<b>Historical win rate:</b> {html.escape(str(alert.get('bundled_win_rate') or ''))}\n\n"
        f"<b>Token:</b> <a href=\"{dex_url(token)}\">{html.escape(str(symbol))}</a>\n"
        f"<b>Entry MC:</b> {_money(alert.get('entry_market_cap'), 0)}\n"
        f"<b>Buy:</b> {_money(alert.get('entry_volume_usd'), 2)}\n"
        f"<b>Bundlers:</b> {html.escape(str(alert.get('live_bundler_count') or 'n/a'))}\n"
        f"<b>Initial bundle:</b> {html.escape(str(alert.get('live_bundle_initial_pct') or 'n/a'))}%"
    )

class TelegramClient:
    def __init__(self, config: BundleV2Config): self.config = config
    def enabled(self): return self.config.has_telegram and not self.config.dry_run
    def _send(self, text, reply_markup=None):
        if not self.enabled(): return ""
        payload = {"chat_id": self.config.telegram_chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        if reply_markup: payload["reply_markup"] = json.dumps(reply_markup)
        data = parse.urlencode(payload).encode("utf-8")
        with request.urlopen(f"https://api.telegram.org/bot{self.config.telegram_bot_token}/sendMessage", data=data, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
        if not result.get("ok"): raise RuntimeError(f"Telegram send failed: {result}")
        return str(result["result"]["message_id"])
    def send_status(self, text): return self._send(text)
    def send_alert(self, alert): return self._send(format_alert(alert), markup(alert))
''',
    "bundle_v2_live_bot.py": r'''"""Bundle Specialist V2 cautious live engine. No mock alerts."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib, os, sys, time
from pathlib import Path
import pandas as pd

from bundle_v2_config import OUTPUT_DIR, V1_SCORED_WALLETS_PATH, load_config
from bundle_v2_storage import BundleV2Storage, utc_now_iso
from bundle_v2_telegram import TelegramClient

MIGRATION_BOT_DIR = Path(__file__).resolve().parents[1].parent / "migration_specialist" / "telegram_bot"
if str(MIGRATION_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(MIGRATION_BOT_DIR))
from v4_market_data import MarketDataClient  # noqa: E402

LOCK_PATH = OUTPUT_DIR / "bundle_v2_live_bot.lock"

def acquire_lock():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    try: fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print(f"Bundle V2 already appears to be running: {LOCK_PATH}")
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as h: h.write(str(os.getpid()))
    return True

def release_lock():
    try: LOCK_PATH.unlink()
    except FileNotFoundError: pass

def load_watchlist(config):
    wallets = pd.read_csv(V1_SCORED_WALLETS_PATH)
    wl = wallets[
        (wallets["is_bundle_specialist_v1"] == True)
        & (wallets["bundle_specialist_score"] >= config.min_score)
        & (wallets["bundled_realized_pnl_usd"] > 0)
        & (wallets["bundled_token_count"] >= 10)
    ].sort_values("bundle_specialist_score", ascending=False)
    return wl.head(config.max_wallets_per_run).copy()

def parse_time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None

def is_fresh(trade, max_age):
    parsed = parse_time(trade.get("trade_time") or trade.get("time"))
    if parsed is None: return False, "missing_or_invalid_trade_time"
    age = (datetime.now(timezone.utc) - parsed).total_seconds()
    if age > max_age: return False, "trade_too_old"
    if age < -60: return False, "trade_time_in_future"
    return True, ""

def bundle_risk(market):
    raw = market.get("raw") or {}
    risk = raw.get("risk") or {}
    bundlers = risk.get("bundlers") or {}
    count = float(bundlers.get("count") or 0)
    initial = float(bundlers.get("totalInitialPercentage") or 0)
    current = float(bundlers.get("totalPercentage") or 0)
    return count, initial, current

def alert_id(wallet, token, tx):
    return hashlib.sha256(f"bundle-v2|{wallet}|{token}|{tx}".encode()).hexdigest()[:24]

def evaluate(trade, wallet, market, config):
    if str(trade.get("trade_type") or "").lower() != "buy": return None, "not_buy"
    token = str(trade.get("token_address") or "")
    tx = str(trade.get("tx_hash") or "")
    buy = float(trade.get("usd_volume") or 0)
    if not token or not tx: return None, "missing_token_or_tx"
    if buy < config.min_buy_usd: return None, "buy_below_min"
    mc = float(market.get("market_cap") or 0)
    if mc <= 0: return None, "missing_market_cap"
    if mc > config.max_entry_market_cap_usd: return None, "entry_market_cap_too_high"
    status = str(market.get("migration_status") or "unknown")
    if status not in {"pre_migration", "unknown"}: return None, "not_early_or_pre_migration"
    count, initial, current = bundle_risk(market)
    if count < 10 and initial < 20:
        return None, "insufficient_live_bundle_evidence"
    row = wallet.to_dict()
    return {
        "alert_id": alert_id(row["wallet_address"], token, tx),
        "alert_time": utc_now_iso(),
        "wallet_address": row["wallet_address"],
        "bundle_label_v1": row["bundle_label_v1"],
        "bundle_specialist_score": row["bundle_specialist_score"],
        "bundled_token_count": row["bundled_token_count"],
        "bundled_win_rate": row["bundled_win_rate"],
        "token_address": token,
        "token_symbol": market.get("symbol") or trade.get("token_symbol"),
        "entry_market_cap": mc,
        "entry_price": market.get("price") or trade.get("price_usd"),
        "entry_volume_usd": buy,
        "live_bundler_count": count,
        "live_bundle_initial_pct": initial,
        "live_bundle_current_pct": current,
        "migration_status_at_entry": status,
        "source_api": trade.get("source_api") or market.get("source_api"),
        "tx_hash": tx,
        "telegram_message_id": "",
        "status": "open",
    }, ""

def process(watchlist, storage, market_data, telegram, config):
    for _, wallet in watchlist.iterrows():
        addr = str(wallet["wallet_address"])
        try: trades = market_data.fetch_recent_wallet_trades(addr)
        except Exception as exc:
            print(f"wallet fetch failed {addr}: {exc}")
            continue
        for trade in trades:
            token = str(trade.get("token_address") or "")
            tx = str(trade.get("tx_hash") or "")
            fresh, reason = is_fresh(trade, config.max_trade_age_seconds)
            if not fresh:
                storage.append_skip(addr, token, tx, reason, trade.get("source_api", ""))
                continue
            if storage.token_already_alerted(token):
                storage.append_skip(addr, token, tx, "token_already_alerted", trade.get("source_api", ""))
                continue
            try: market = market_data.fetch_token_market(token)
            except Exception as exc:
                storage.append_skip(addr, token, tx, f"market_fetch_failed:{exc}", trade.get("source_api", ""))
                continue
            alert, skip = evaluate(trade, wallet, market, config)
            if skip:
                storage.append_skip(addr, token, tx, skip, trade.get("source_api", market.get("source_api", "")))
                continue
            if telegram.enabled(): alert["telegram_message_id"] = telegram.send_alert(alert)
            storage.append_alert(alert)
            storage.upsert_outcome({
                "alert_id": alert["alert_id"], "token_address": alert["token_address"],
                "alert_time": alert["alert_time"], "last_checked_at": utc_now_iso(),
                "entry_market_cap": alert["entry_market_cap"], "current_market_cap": alert["entry_market_cap"],
                "ath_market_cap_since_alert": alert["entry_market_cap"], "max_return_multiple": 1.0,
                "migration_status_latest": alert["migration_status_at_entry"], "days_since_alert": 0,
                "source_api": alert["source_api"], "status": "open",
            })

def track(storage, market_data):
    alerts = storage.read_alerts()
    outcomes = storage.read_outcomes()
    if alerts.empty: return
    for _, alert in alerts[alerts["status"].astype(str).eq("open")].iterrows():
        try: market = market_data.fetch_token_market(str(alert["token_address"]))
        except Exception: continue
        current = market.get("market_cap")
        if current is None: continue
        current = float(current)
        entry = float(alert.get("entry_market_cap") or 0)
        old = outcomes[outcomes["alert_id"].astype(str).eq(str(alert["alert_id"]))]
        prev = float(old["ath_market_cap_since_alert"].iloc[0]) if not old.empty else entry
        ath = max(prev, current)
        at = parse_time(alert.get("alert_time")) or datetime.now(timezone.utc)
        storage.upsert_outcome({
            "alert_id": alert["alert_id"], "token_address": alert["token_address"],
            "alert_time": alert["alert_time"], "last_checked_at": utc_now_iso(),
            "entry_market_cap": entry, "current_market_cap": current,
            "ath_market_cap_since_alert": ath, "max_return_multiple": ath / entry if entry else 0,
            "migration_status_latest": market.get("migration_status"),
            "days_since_alert": (datetime.now(timezone.utc) - at).total_seconds()/86400,
            "source_api": market.get("source_api"), "status": alert.get("status", "open"),
        })

def run_once():
    config = load_config()
    storage = BundleV2Storage(OUTPUT_DIR); storage.initialize_files()
    if not config.live_enabled:
        print("Bundle V2 live disabled: missing credentials"); return 0
    watchlist = load_watchlist(config)
    print(f"Tracking {len(watchlist)} Bundle V2 wallets this run.")
    md = MarketDataClient(config); tg = TelegramClient(config)
    process(watchlist, storage, md, tg, config); track(storage, md)
    return 0

def main():
    if not acquire_lock(): return 0
    try:
        config = load_config()
        storage = BundleV2Storage(OUTPUT_DIR); storage.initialize_files()
        if not config.live_enabled:
            print("Bundle V2 live disabled: missing credentials"); return 0
        watchlist = load_watchlist(config); tg = TelegramClient(config)
        tg.send_status("<b>Bundle Specialist V2 is live</b>\n\n" f"<b>Mode:</b> cautious\n<b>Wallets:</b> {len(watchlist)}\n<b>Min score:</b> {config.min_score:.0f}/100")
        while True:
            try: run_once()
            except KeyboardInterrupt: raise
            except Exception as exc: print(f"Bundle V2 loop error: {exc}")
            time.sleep(config.poll_interval_seconds)
    finally:
        release_lock()

if __name__ == "__main__":
    raise SystemExit(main())
''',
    ".env.example": """BUNDLE_V2_MIN_SCORE=55
BUNDLE_V2_MIN_BUY_USD=25
BUNDLE_V2_MAX_ENTRY_MARKET_CAP_USD=50000
BUNDLE_V2_MAX_TRADE_AGE_SECONDS=300
BUNDLE_V2_MAX_WALLETS_PER_RUN=75
BUNDLE_V2_POLL_INTERVAL_SECONDS=60
BUNDLE_V2_DRY_RUN=false
""",
    "README.md": """# Bundle Specialist V2 Live

Cautious live alert layer for Bundle Specialist.

Rules:

```text
strict Bundle Specialist V1+ wallet
bundle_specialist_score >= 55
historical bundled PnL > 0
bundled_token_count >= 10
recent buy only
buy >= $25
entry market cap <= $50k
live token has bundle evidence
same token alerts only once
```
""",
}


def main() -> None:
    BOT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in FILES.items():
        (BOT_DIR / name).write_text(content, encoding="utf-8")
    print(f"Created Bundle V2 live bot in {BOT_DIR}")


if __name__ == "__main__":
    main()
