from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any


class TelegramAlerts:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send(self, text: str) -> None:
        if not self.enabled:
            return
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        data = urllib.parse.urlencode(
            {
                "chat_id": self.chat_id,
                "text": text,
                "disable_web_page_preview": "true",
            }
        ).encode("utf-8")
        request = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(request, timeout=15) as response:
            response.read()

    def get_updates(self, offset: int | None = None) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        params: dict[str, Any] = {"timeout": 0}
        if offset is not None:
            params["offset"] = offset
        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not payload.get("ok"):
            return []
        return payload.get("result") or []


def fmt_usd(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"${value:,.0f}"


def paper_buy_message(symbol: str, token: str, market_cap: float, age_seconds: int | None, reason: str, take_profit_pct: float = 50, stop_loss_pct: float = 20) -> str:
    age = f"{age_seconds // 60}m {age_seconds % 60}s" if age_seconds is not None else "n/a"
    return (
        "PAPER BUY\n\n"
        f"Token: {symbol or 'UNKNOWN'}\n"
        f"Address: {token}\n"
        f"Age: {age}\n"
        f"Entry MC: {fmt_usd(market_cap)}\n"
        f"Reason: {reason}\n\n"
        f"Target: +{take_profit_pct:g}%\n"
        f"Stop: -{stop_loss_pct:g}%\n"
        "Max hold: 10m"
    )


def paper_sell_message(symbol: str, token: str, pnl_pct: float | None, reason: str, hold_seconds: int | None) -> str:
    hold = f"{hold_seconds // 60}m {hold_seconds % 60}s" if hold_seconds is not None else "n/a"
    pnl = "n/a" if pnl_pct is None else f"{pnl_pct:+.1f}%"
    return (
        f"PAPER SELL - {reason.upper()}\n\n"
        f"Token: {symbol or 'UNKNOWN'}\n"
        f"Address: {token}\n"
        f"PnL: {pnl}\n"
        f"Hold time: {hold}"
    )
