from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ._utils import int_or_none

TRADE_CATEGORIES = {"pump_buy", "pump_sell"}


@dataclass
class MemeTokenSummary:
    mint: str
    symbol: str | None = None
    buy_tx: int = 0
    sell_tx: int = 0
    buy_sol: float = 0.0
    sell_sol: float = 0.0
    buy_tokens: float = 0.0
    sell_tokens: float = 0.0
    net_tokens: float = 0.0
    first_block_time: int | None = None
    last_block_time: int | None = None

    @property
    def net_sol(self) -> float:
        return self.sell_sol - self.buy_sol

    @property
    def total_tx(self) -> int:
        return self.buy_tx + self.sell_tx

    def to_record(self) -> dict[str, Any]:
        return {
            "mint": self.mint,
            "symbol": self.symbol,
            "buy_tx": self.buy_tx,
            "sell_tx": self.sell_tx,
            "total_tx": self.total_tx,
            "buy_sol": self.buy_sol,
            "sell_sol": self.sell_sol,
            "net_sol": self.net_sol,
            "buy_tokens": self.buy_tokens,
            "sell_tokens": self.sell_tokens,
            "net_tokens": self.net_tokens,
            "first_block_time": self.first_block_time,
            "last_block_time": self.last_block_time,
            "first_time_utc": format_block_time(self.first_block_time),
            "last_time_utc": format_block_time(self.last_block_time),
        }


def summarize_meme_tokens(records: list[dict[str, Any]]) -> list[MemeTokenSummary]:
    summaries: dict[str, MemeTokenSummary] = {}

    for record in records:
        if record.get("status") not in {None, "Success", "success", "Succ", "succ", True}:
            continue
        category = record.get("category")
        if category not in TRADE_CATEGORIES:
            continue

        sol_change = _number(record.get("sol_change"))
        block_time = int_or_none(record.get("block_time"))
        for change in record.get("token_changes") or []:
            if not isinstance(change, dict):
                continue
            mint = change.get("mint")
            if not isinstance(mint, str) or not mint:
                continue

            summary = summaries.setdefault(mint, MemeTokenSummary(mint=mint))
            symbol = change.get("symbol")
            if summary.symbol is None and isinstance(symbol, str) and symbol:
                summary.symbol = symbol

            token_amount = token_amount_ui(change)
            if category == "pump_buy":
                summary.buy_tx += 1
                if sol_change is not None and sol_change < 0:
                    summary.buy_sol += abs(sol_change)
                if token_amount is not None:
                    summary.buy_tokens += max(token_amount, 0.0)
                    summary.net_tokens += token_amount
            elif category == "pump_sell":
                summary.sell_tx += 1
                if sol_change is not None and sol_change > 0:
                    summary.sell_sol += sol_change
                if token_amount is not None:
                    summary.sell_tokens += abs(min(token_amount, 0.0))
                    summary.net_tokens += token_amount

            if block_time is not None:
                if summary.first_block_time is None or block_time < summary.first_block_time:
                    summary.first_block_time = block_time
                if summary.last_block_time is None or block_time > summary.last_block_time:
                    summary.last_block_time = block_time

    return sorted(
        summaries.values(),
        key=lambda item: (item.first_block_time is None, item.first_block_time or 0, item.mint),
    )


def token_amount_ui(change: dict[str, Any]) -> float | None:
    amount = _number(change.get("amount"))
    if amount is None:
        return None
    decimals = int_or_none(change.get("decimals")) or 0
    return amount / (10**decimals)


def format_block_time(block_time: int | None) -> str:
    if block_time is None:
        return ""
    return datetime.fromtimestamp(block_time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None
