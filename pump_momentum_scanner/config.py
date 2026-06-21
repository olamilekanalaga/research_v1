from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_dotenv(path: Path | None = None) -> None:
    env_path = path or ROOT / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class Settings:
    solana_tracker_api_key: str
    helius_api_key: str
    helius_ws_url: str
    helius_rpc_url: str
    telegram_bot_token: str
    telegram_chat_id: str
    database_path: Path
    snapshot_seconds: int = 10
    max_track_minutes: int = 30
    rule_version: str = "v1_a_type_20_before_minus_20"
    heartbeat_minutes: int = 15
    paper_start_balance_usd: float = 100.0
    paper_trade_size_usd: float = 20.0
    take_profit_pct: float = 50.0
    stop_loss_pct: float = 20.0

    @property
    def max_track_seconds(self) -> int:
        return self.max_track_minutes * 60


def get_settings() -> Settings:
    load_dotenv()
    db_path = Path(os.getenv("DATABASE_PATH", "pump_momentum_scanner/data/paper_trades.sqlite"))
    if not db_path.is_absolute():
        db_path = ROOT / db_path

    return Settings(
        solana_tracker_api_key=os.getenv("SOLANA_TRACKER_API_KEY", "").strip(),
        helius_api_key=os.getenv("HELIUS_API_KEY", "").strip(),
        helius_ws_url=os.getenv("HELIUS_WS_URL", "").strip(),
        helius_rpc_url=os.getenv("HELIUS_RPC_URL", "").strip(),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
        database_path=db_path,
        snapshot_seconds=int(os.getenv("SNAPSHOT_SECONDS", "10")),
        max_track_minutes=int(os.getenv("MAX_TRACK_MINUTES", "30")),
        rule_version=os.getenv("RULE_VERSION", "v1_a_type_20_before_minus_20").strip(),
        heartbeat_minutes=int(os.getenv("HEARTBEAT_MINUTES", "15")),
        paper_start_balance_usd=float(os.getenv("PAPER_START_BALANCE_USD", "100")),
        paper_trade_size_usd=float(os.getenv("PAPER_TRADE_SIZE_USD", "20")),
        take_profit_pct=float(os.getenv("TAKE_PROFIT_PCT", "50")),
        stop_loss_pct=float(os.getenv("STOP_LOSS_PCT", "20")),
    )
