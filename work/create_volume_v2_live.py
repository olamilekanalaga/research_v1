from __future__ import annotations

from pathlib import Path


PROJECT = Path(r"C:\Users\alaga\Desktop\My Script Library\Behaviour Labeling\volume_specialist")
BOT_DIR = PROJECT / "telegram_bot"
OUT_DIR = PROJECT / "outputs" / "v2"


FILES: dict[str, str] = {
    "volume_v2_config.py": r'''"""Live configuration for Volume Specialist V2.

Volume V2 is cautious live testing. It does not fabricate alerts. Credentials
are loaded from this folder first, then from the existing Migration Telegram
bot folder to avoid duplicating secrets.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


BOT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BOT_DIR.parent
OUTPUT_DIR = PROJECT_DIR / "outputs" / "v2"
V1_SCORED_WALLETS_PATH = PROJECT_DIR / "outputs" / "v1" / "volume_scored_wallets_v1.csv"
LOCAL_ENV_PATH = BOT_DIR / ".env"
MIGRATION_ENV_PATH = PROJECT_DIR.parent / "migration_specialist" / "telegram_bot" / ".env"


@dataclass(frozen=True)
class VolumeV2Config:
    telegram_bot_token: str
    telegram_chat_id: str
    solana_tracker_api_key: str
    birdeye_api_key: str
    helius_api_key: str
    poll_interval_seconds: int = 60
    max_trade_age_seconds: int = 300
    max_wallets_per_run: int = 118
    min_score: float = 70.0
    max_noise_penalty: float = 70.0
    min_buy_usd: float = 25.0
    max_entry_market_cap_usd: float = 50_000.0
    required_tier: str = "Strong Score Confidence"
    dry_run: bool = False

    @property
    def has_telegram(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)

    @property
    def has_market_or_trade_api(self) -> bool:
        return bool(self.solana_tracker_api_key or self.birdeye_api_key or self.helius_api_key)

    @property
    def live_enabled(self) -> bool:
        return self.has_telegram and self.has_market_or_trade_api

    @property
    def missing_live_requirements(self) -> list[str]:
        missing: list[str] = []
        if not self.telegram_bot_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.telegram_chat_id:
            missing.append("TELEGRAM_CHAT_ID")
        if not self.has_market_or_trade_api:
            missing.append("SOLANA_TRACKER_API_KEY or BIRDEYE_API_KEY or HELIUS_API_KEY")
        return missing


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_config() -> VolumeV2Config:
    load_dotenv(LOCAL_ENV_PATH)
    load_dotenv(MIGRATION_ENV_PATH)
    return VolumeV2Config(
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
        solana_tracker_api_key=os.getenv("SOLANA_TRACKER_API_KEY", "").strip(),
        birdeye_api_key=os.getenv("BIRDEYE_API_KEY", "").strip(),
        helius_api_key=os.getenv("HELIUS_API_KEY", "").strip(),
        poll_interval_seconds=int(os.getenv("VOLUME_V2_POLL_INTERVAL_SECONDS", "60")),
        max_trade_age_seconds=int(os.getenv("VOLUME_V2_MAX_TRADE_AGE_SECONDS", "300")),
        max_wallets_per_run=int(os.getenv("VOLUME_V2_MAX_WALLETS_PER_RUN", "118")),
        min_score=float(os.getenv("VOLUME_V2_MIN_SCORE", "70")),
        max_noise_penalty=float(os.getenv("VOLUME_V2_MAX_NOISE_PENALTY", "70")),
        min_buy_usd=float(os.getenv("VOLUME_V2_MIN_BUY_USD", "25")),
        max_entry_market_cap_usd=float(os.getenv("VOLUME_V2_MAX_ENTRY_MARKET_CAP_USD", "50000")),
        required_tier=os.getenv("VOLUME_V2_REQUIRED_TIER", "Strong Score Confidence"),
        dry_run=os.getenv("VOLUME_V2_DRY_RUN", "false").lower() == "true",
    )
''',
    "volume_v2_storage.py": r'''"""CSV persistence for Volume Specialist V2 live alerts."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


ALERT_COLUMNS = [
    "alert_id",
    "alert_time",
    "wallet_address",
    "volume_label_v1",
    "volume_score_confidence_tier",
    "volume_specialist_score",
    "noise_penalty_score",
    "token_address",
    "token_symbol",
    "entry_market_cap",
    "entry_price",
    "entry_volume_usd",
    "migration_status_at_entry",
    "source_api",
    "tx_hash",
    "telegram_message_id",
    "status",
]

OUTCOME_COLUMNS = [
    "alert_id",
    "token_address",
    "alert_time",
    "last_checked_at",
    "entry_market_cap",
    "current_market_cap",
    "ath_market_cap_since_alert",
    "max_return_multiple",
    "migration_status_latest",
    "days_since_alert",
    "source_api",
    "status",
]

SKIPPED_COLUMNS = [
    "skipped_at",
    "wallet_address",
    "token_address",
    "tx_hash",
    "reason",
    "source_api",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class VolumeV2Storage:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.alerts_path = self.output_dir / "volume_alerts_live.csv"
        self.outcomes_path = self.output_dir / "volume_alert_outcomes.csv"
        self.skipped_path = self.output_dir / "volume_skipped_trades.csv"

    @staticmethod
    def _ensure(path: Path, columns: list[str]) -> None:
        if not path.exists():
            pd.DataFrame(columns=columns).to_csv(path, index=False)

    @staticmethod
    def _read(path: Path, columns: list[str]) -> pd.DataFrame:
        if not path.exists():
            return pd.DataFrame(columns=columns)
        return pd.read_csv(path)

    @staticmethod
    def _append(path: Path, columns: list[str], row: dict) -> None:
        existing = VolumeV2Storage._read(path, columns)
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
        if alerts.empty:
            return False
        return bool(alerts["token_address"].astype(str).eq(str(token_address)).any())

    def wallet_token_tx_exists(self, wallet_address: str, token_address: str, tx_hash: str) -> bool:
        alerts = self.read_alerts()
        if alerts.empty:
            return False
        mask = (
            alerts["wallet_address"].astype(str).eq(str(wallet_address))
            & alerts["token_address"].astype(str).eq(str(token_address))
            & alerts["tx_hash"].astype(str).eq(str(tx_hash))
        )
        return bool(mask.any())

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
        self._append(
            self.skipped_path,
            SKIPPED_COLUMNS,
            {
                "skipped_at": utc_now_iso(),
                "wallet_address": wallet_address,
                "token_address": token_address,
                "tx_hash": tx_hash,
                "reason": reason,
                "source_api": source_api,
            },
        )

    def upsert_outcome(self, row: dict) -> None:
        outcomes = self.read_outcomes()
        alert_id = str(row.get("alert_id", ""))
        if outcomes.empty or not outcomes["alert_id"].astype(str).eq(alert_id).any():
            new_row = pd.DataFrame([{col: row.get(col) for col in OUTCOME_COLUMNS}])
            pd.concat([outcomes, new_row], ignore_index=True).to_csv(self.outcomes_path, index=False)
            return
        for col in OUTCOME_COLUMNS:
            outcomes.loc[outcomes["alert_id"].astype(str).eq(alert_id), col] = row.get(col)
        outcomes.drop_duplicates().to_csv(self.outcomes_path, index=False)
''',
    "volume_v2_telegram.py": r'''"""Telegram formatting for cautious Volume Specialist V2 alerts."""

from __future__ import annotations

import html
import json
import os
from urllib import parse, request

from volume_v2_config import VolumeV2Config


DEFAULT_TROJAN_REF = "r-ola_crrypt"


def _money(value, decimals: int = 0) -> str:
    try:
        return f"${float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return "n/a"


def _score(value) -> str:
    try:
        return f"{float(value):.0f}/100"
    except (TypeError, ValueError):
        return "n/a"


def dexscreener_url(token_address: str) -> str:
    return f"https://dexscreener.com/solana/{parse.quote(str(token_address))}"


def trojan_url(token_address: str) -> str:
    ref = os.getenv("TROJAN_REF", DEFAULT_TROJAN_REF)
    return f"https://t.me/hector_trojanbot?start={parse.quote(ref + '-' + str(token_address))}"


def reply_markup(alert: dict) -> dict:
    token_address = str(alert.get("token_address") or "")
    return {
        "inline_keyboard": [
            [{"text": "Trade on Trojan", "url": trojan_url(token_address)}],
            [{"text": "Open Dexscreener", "url": dexscreener_url(token_address)}],
        ]
    }


def format_alert(alert: dict) -> str:
    token_address = str(alert.get("token_address") or "")
    symbol = alert.get("token_symbol") or token_address[:6]
    return (
        "<b>Volume Specialist V2 Signal</b>\n\n"
        f"<b>Wallet:</b> <code>{html.escape(str(alert.get('wallet_address') or ''))}</code>\n"
        f"<b>Tier:</b> {html.escape(str(alert.get('volume_score_confidence_tier') or ''))}\n"
        f"<b>Score:</b> {_score(alert.get('volume_specialist_score'))}\n"
        f"<b>Noise:</b> {_score(alert.get('noise_penalty_score'))}\n\n"
        f"<b>Token:</b> <a href=\"{dexscreener_url(token_address)}\">{html.escape(str(symbol))}</a>\n"
        f"<b>Entry MC:</b> {_money(alert.get('entry_market_cap'), 0)}\n"
        f"<b>Buy:</b> {_money(alert.get('entry_volume_usd'), 2)}\n"
        f"<b>Status:</b> {html.escape(str(alert.get('migration_status_at_entry') or 'n/a'))}"
    )


class TelegramClient:
    def __init__(self, config: VolumeV2Config):
        self.config = config

    def enabled(self) -> bool:
        return self.config.has_telegram and not self.config.dry_run

    def send_alert(self, alert: dict) -> str:
        if not self.enabled():
            return ""
        url = f"https://api.telegram.org/bot{self.config.telegram_bot_token}/sendMessage"
        payload = {
            "chat_id": self.config.telegram_chat_id,
            "text": format_alert(alert),
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": json.dumps(reply_markup(alert)),
        }
        encoded = parse.urlencode(payload).encode("utf-8")
        with request.urlopen(url, data=encoded, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
        if not data.get("ok"):
            raise RuntimeError(f"Telegram send failed: {data}")
        return str(data["result"]["message_id"])

    def send_status(self, text: str) -> str:
        if not self.enabled():
            return ""
        url = f"https://api.telegram.org/bot{self.config.telegram_bot_token}/sendMessage"
        payload = {
            "chat_id": self.config.telegram_chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        encoded = parse.urlencode(payload).encode("utf-8")
        with request.urlopen(url, data=encoded, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
        if not data.get("ok"):
            raise RuntimeError(f"Telegram status send failed: {data}")
        return str(data["result"]["message_id"])
''',
    "volume_v2_live_bot.py": r'''"""Volume Specialist V2 cautious live alert engine.

Current purpose:

Strong score-confidence wallets
-> real recent wallet trades
-> early/pre-migration meaningful buys
-> Telegram alert
-> CSV alert and outcome tracking

No mock data is generated.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import sys
import time

import pandas as pd

from volume_v2_config import OUTPUT_DIR, V1_SCORED_WALLETS_PATH, load_config
from volume_v2_storage import VolumeV2Storage, utc_now_iso
from volume_v2_telegram import TelegramClient

MIGRATION_BOT_DIR = Path(__file__).resolve().parents[1].parent / "migration_specialist" / "telegram_bot"
if str(MIGRATION_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(MIGRATION_BOT_DIR))

from v4_market_data import MarketDataClient  # noqa: E402


LOCK_PATH = OUTPUT_DIR / "volume_v2_live_bot.lock"


def acquire_lock() -> bool:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(LOCK_PATH), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print(f"Volume V2 already appears to be running: {LOCK_PATH}")
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
    return True


def release_lock() -> None:
    try:
        LOCK_PATH.unlink()
    except FileNotFoundError:
        pass


def load_watchlist(config) -> pd.DataFrame:
    if not V1_SCORED_WALLETS_PATH.exists():
        raise FileNotFoundError(f"Volume scored wallets not found: {V1_SCORED_WALLETS_PATH}")
    wallets = pd.read_csv(V1_SCORED_WALLETS_PATH)
    required = {
        "wallet_address",
        "volume_label_v1",
        "volume_score_confidence_tier",
        "volume_specialist_score",
        "noise_penalty_score",
    }
    missing = required.difference(wallets.columns)
    if missing:
        raise ValueError(f"Volume scored wallet file missing columns: {sorted(missing)}")
    watchlist = wallets[
        (wallets["volume_score_confidence_tier"].astype(str).eq(config.required_tier))
        & (wallets["volume_specialist_score"] >= config.min_score)
        & (wallets["noise_penalty_score"] <= config.max_noise_penalty)
    ].copy()
    watchlist = watchlist.sort_values("volume_specialist_score", ascending=False)
    if config.max_wallets_per_run:
        watchlist = watchlist.head(config.max_wallets_per_run).copy()
    return watchlist


def parse_trade_time(value) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def is_fresh_trade(trade: dict, max_age_seconds: int) -> tuple[bool, str]:
    parsed = parse_trade_time(trade.get("trade_time") or trade.get("timestamp") or trade.get("time"))
    if parsed is None:
        return False, "missing_or_invalid_trade_time"
    age = (datetime.now(timezone.utc) - parsed).total_seconds()
    if age < -60:
        return False, "trade_time_in_future"
    if age > max_age_seconds:
        return False, "trade_too_old"
    return True, ""


def make_alert_id(wallet_address: str, token_address: str, tx_hash: str) -> str:
    payload = f"volume-v2|{wallet_address}|{token_address}|{tx_hash}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:24]


def evaluate_volume_signal(trade: dict, wallet_row: dict, market: dict, config) -> tuple[dict | None, str]:
    if str(trade.get("trade_type") or "").lower() != "buy":
        return None, "not_buy"
    token_address = str(trade.get("token_address") or "")
    tx_hash = str(trade.get("tx_hash") or "")
    if not token_address or not tx_hash:
        return None, "missing_token_or_tx"
    try:
        buy_usd = float(trade.get("usd_volume") or 0)
    except (TypeError, ValueError):
        buy_usd = 0.0
    if buy_usd < config.min_buy_usd:
        return None, "buy_below_min_volume"
    try:
        entry_mc = float(market.get("market_cap") or 0)
    except (TypeError, ValueError):
        entry_mc = 0.0
    if entry_mc <= 0:
        return None, "missing_entry_market_cap"
    if entry_mc > config.max_entry_market_cap_usd:
        return None, "entry_market_cap_too_high"
    migration_status = str(market.get("migration_status") or "unknown")
    if migration_status not in {"pre_migration", "unknown"}:
        return None, "not_early_or_pre_migration"
    alert = {
        "alert_id": make_alert_id(str(wallet_row["wallet_address"]), token_address, tx_hash),
        "alert_time": utc_now_iso(),
        "wallet_address": str(wallet_row["wallet_address"]),
        "volume_label_v1": wallet_row.get("volume_label_v1"),
        "volume_score_confidence_tier": wallet_row.get("volume_score_confidence_tier"),
        "volume_specialist_score": wallet_row.get("volume_specialist_score"),
        "noise_penalty_score": wallet_row.get("noise_penalty_score"),
        "token_address": token_address,
        "token_symbol": market.get("symbol") or trade.get("token_symbol"),
        "entry_market_cap": entry_mc,
        "entry_price": market.get("price") or trade.get("price_usd"),
        "entry_volume_usd": buy_usd,
        "migration_status_at_entry": migration_status,
        "source_api": trade.get("source_api") or market.get("source_api"),
        "tx_hash": tx_hash,
        "telegram_message_id": "",
        "status": "open",
    }
    return alert, ""


def process_recent_trades(watchlist: pd.DataFrame, storage: VolumeV2Storage, market_data: MarketDataClient, telegram: TelegramClient, config) -> None:
    for _, row in watchlist.iterrows():
        wallet_row = row.to_dict()
        wallet = str(wallet_row["wallet_address"])
        try:
            trades = market_data.fetch_recent_wallet_trades(wallet)
        except Exception as exc:
            print(f"wallet fetch failed {wallet}: {exc}")
            continue
        for trade in trades:
            token_address = str(trade.get("token_address") or "")
            tx_hash = str(trade.get("tx_hash") or "")
            fresh, reason = is_fresh_trade(trade, config.max_trade_age_seconds)
            if not fresh:
                storage.append_skip(wallet, token_address, tx_hash, reason, trade.get("source_api", ""))
                continue
            if storage.wallet_token_tx_exists(wallet, token_address, tx_hash):
                storage.append_skip(wallet, token_address, tx_hash, "duplicate_wallet_token_tx", trade.get("source_api", ""))
                continue
            if storage.token_already_alerted(token_address):
                storage.append_skip(wallet, token_address, tx_hash, "token_already_alerted", trade.get("source_api", ""))
                continue
            try:
                market = market_data.fetch_token_market(token_address)
            except Exception as exc:
                storage.append_skip(wallet, token_address, tx_hash, f"market_fetch_failed:{exc}", trade.get("source_api", ""))
                continue
            alert, skip_reason = evaluate_volume_signal(trade, wallet_row, market, config)
            if skip_reason:
                storage.append_skip(wallet, token_address, tx_hash, skip_reason, trade.get("source_api", market.get("source_api", "")))
                continue
            if telegram.enabled():
                alert["telegram_message_id"] = telegram.send_alert(alert)
            storage.append_alert(alert)
            storage.upsert_outcome(
                {
                    "alert_id": alert["alert_id"],
                    "token_address": alert["token_address"],
                    "alert_time": alert["alert_time"],
                    "last_checked_at": utc_now_iso(),
                    "entry_market_cap": alert["entry_market_cap"],
                    "current_market_cap": alert["entry_market_cap"],
                    "ath_market_cap_since_alert": alert["entry_market_cap"],
                    "max_return_multiple": 1.0,
                    "migration_status_latest": alert["migration_status_at_entry"],
                    "days_since_alert": 0,
                    "source_api": alert["source_api"],
                    "status": "open",
                }
            )


def track_outcomes(storage: VolumeV2Storage, market_data: MarketDataClient) -> None:
    alerts = storage.read_alerts()
    outcomes = storage.read_outcomes()
    if alerts.empty:
        return
    for _, alert_row in alerts[alerts["status"].astype(str).eq("open")].iterrows():
        alert = alert_row.to_dict()
        try:
            market = market_data.fetch_token_market(str(alert["token_address"]))
        except Exception as exc:
            print(f"outcome fetch failed {alert['token_address']}: {exc}")
            continue
        current_mc = market.get("market_cap")
        if current_mc is None:
            continue
        current_mc = float(current_mc)
        entry_mc = float(alert.get("entry_market_cap") or 0)
        existing = outcomes[outcomes["alert_id"].astype(str).eq(str(alert["alert_id"]))]
        previous_ath = float(existing["ath_market_cap_since_alert"].iloc[0]) if not existing.empty else entry_mc
        ath = max(previous_ath, current_mc)
        alert_time = parse_trade_time(alert.get("alert_time")) or datetime.now(timezone.utc)
        days_since = (datetime.now(timezone.utc) - alert_time).total_seconds() / 86400
        storage.upsert_outcome(
            {
                "alert_id": alert["alert_id"],
                "token_address": alert["token_address"],
                "alert_time": alert["alert_time"],
                "last_checked_at": utc_now_iso(),
                "entry_market_cap": entry_mc,
                "current_market_cap": current_mc,
                "ath_market_cap_since_alert": ath,
                "max_return_multiple": ath / entry_mc if entry_mc else 0,
                "migration_status_latest": market.get("migration_status"),
                "days_since_alert": days_since,
                "source_api": market.get("source_api"),
                "status": alert.get("status", "open"),
            }
        )


def run_once() -> int:
    config = load_config()
    storage = VolumeV2Storage(OUTPUT_DIR)
    storage.initialize_files()
    if not config.live_enabled:
        print("Volume V2 live disabled: missing API credentials.")
        print("Missing:", ", ".join(config.missing_live_requirements))
        return 0
    watchlist = load_watchlist(config)
    print(f"Tracking {len(watchlist)} Volume V2 wallets this run.")
    market_data = MarketDataClient(config)
    telegram = TelegramClient(config)
    process_recent_trades(watchlist, storage, market_data, telegram, config)
    track_outcomes(storage, market_data)
    return 0


def main() -> int:
    if not acquire_lock():
        return 0
    config = load_config()
    try:
        storage = VolumeV2Storage(OUTPUT_DIR)
        storage.initialize_files()
        if not config.live_enabled:
            print("Volume V2 live disabled: missing API credentials.")
            print("Missing:", ", ".join(config.missing_live_requirements))
            return 0
        telegram = TelegramClient(config)
        watchlist = load_watchlist(config)
        telegram.send_status(
            "<b>Volume Specialist V2 is live</b>\n\n"
            f"<b>Mode:</b> cautious\n"
            f"<b>Wallets:</b> {len(watchlist)}\n"
            f"<b>Tier:</b> {config.required_tier}\n"
            f"<b>Min score:</b> {config.min_score:.0f}/100\n"
            f"<b>Max noise:</b> {config.max_noise_penalty:.0f}/100"
        )
        while True:
            try:
                run_once()
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                print(f"Volume V2 loop error: {exc}")
            time.sleep(config.poll_interval_seconds)
    finally:
        release_lock()


if __name__ == "__main__":
    raise SystemExit(main())
''',
    ".env.example": """# Optional overrides for Volume V2. Real shared secrets are read from
# ../migration_specialist/telegram_bot/.env if this file is absent.

VOLUME_V2_REQUIRED_TIER=Strong Score Confidence
VOLUME_V2_MIN_SCORE=70
VOLUME_V2_MAX_NOISE_PENALTY=70
VOLUME_V2_MIN_BUY_USD=25
VOLUME_V2_MAX_ENTRY_MARKET_CAP_USD=50000
VOLUME_V2_MAX_TRADE_AGE_SECONDS=300
VOLUME_V2_MAX_WALLETS_PER_RUN=118
VOLUME_V2_POLL_INTERVAL_SECONDS=60
VOLUME_V2_DRY_RUN=false
""",
    "README.md": """# Volume Specialist V2 Live

Cautious live alert layer for Volume Specialist.

Rules:

```text
volume_score_confidence_tier == Strong Score Confidence
volume_specialist_score >= 70
noise_penalty_score <= 70
recent buy only
buy_usd >= 25
entry_market_cap <= 50k
pre-migration or unknown migration status only
same token alerts only once
```

Outputs:

```text
../outputs/v2/volume_alerts_live.csv
../outputs/v2/volume_alert_outcomes.csv
../outputs/v2/volume_skipped_trades.csv
```

No mock alerts are generated.
""",
}


def main() -> None:
    BOT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in FILES.items():
        (BOT_DIR / name).write_text(content, encoding="utf-8")
    print(f"Created Volume V2 live bot in {BOT_DIR}")


if __name__ == "__main__":
    main()
