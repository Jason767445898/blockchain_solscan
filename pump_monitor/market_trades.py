from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests


DEFAULT_HELIUS_BASE_URL = "https://api-mainnet.helius-rpc.com"
LAMPORTS_PER_SOL = 1_000_000_000


class HeliusError(RuntimeError):
    """Raised when Helius enhanced transactions cannot be fetched."""


@dataclass
class MemeTokenWindow:
    mint: str
    symbol: str | None
    first_block_time: int
    last_block_time: int
    window_start: int
    window_end: int
    is_closed_position: bool

    @property
    def window_basis(self) -> str:
        if self.is_closed_position:
            return "open_to_close_plus_buffer"
        return "first_to_last_known_plus_buffer"

    def to_record(self) -> dict[str, Any]:
        return {
            "mint": self.mint,
            "symbol": self.symbol,
            "first_block_time": self.first_block_time,
            "last_block_time": self.last_block_time,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "window_start_utc": format_block_time(self.window_start),
            "window_end_utc": format_block_time(self.window_end),
            "is_closed_position": self.is_closed_position,
            "window_basis": self.window_basis,
        }


class HeliusEnhancedClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_HELIUS_BASE_URL,
        timeout: int = 30,
        min_interval: float = 0.25,
        max_retries: int = 3,
        retry_sleep: float = 2.0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.retry_sleep = retry_sleep
        self._last_request_at = 0.0

    def address_transactions(
        self,
        address: str,
        *,
        gte_time: int,
        lte_time: int,
        limit: int = 100,
        after_signature: str | None = None,
        token_accounts: str = "none",
        sort_order: str = "asc",
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "api-key": self.api_key,
            "gte-time": gte_time,
            "lte-time": lte_time,
            "limit": max(1, min(limit, 100)),
            "sort-order": sort_order,
            "token-accounts": token_accounts,
        }
        if after_signature:
            params["after-signature"] = after_signature

        url = f"{self.base_url}/v0/addresses/{address}/transactions?{urlencode(params)}"
        return self._get(url)

    def _get(self, url: str) -> list[dict[str, Any]]:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)

        for attempt in range(self.max_retries + 1):
            try:
                response = requests.get(url, timeout=self.timeout)
                self._last_request_at = time.monotonic()
            except requests.RequestException as exc:
                if attempt < self.max_retries:
                    time.sleep(self.retry_sleep * (attempt + 1))
                    continue
                raise HeliusError(f"Cannot connect to Helius: {exc}") from exc

            if response.status_code == 429 and attempt < self.max_retries:
                time.sleep(self.retry_sleep * (attempt + 1))
                continue
            if not response.ok:
                raise HeliusError(f"Helius HTTP {response.status_code}: {response.text[:300]}")

            try:
                payload = response.json()
            except json.JSONDecodeError as exc:
                raise HeliusError("Helius returned invalid JSON") from exc
            if not isinstance(payload, list):
                raise HeliusError(f"Expected a list from Helius, got {type(payload).__name__}")
            return [item for item in payload if isinstance(item, dict)]

        raise HeliusError("Helius request failed after retries")


def read_meme_token_windows(path: str | Path, *, buffer_seconds: int = 300) -> list[MemeTokenWindow]:
    windows: list[MemeTokenWindow] = []
    with Path(path).open("r", encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        for row in reader:
            mint = (row.get("mint") or "").strip()
            first_block_time = _int_or_none(row.get("first_block_time"))
            last_block_time = _int_or_none(row.get("last_block_time"))
            if not mint or first_block_time is None or last_block_time is None:
                continue

            net_tokens = _float_or_none(row.get("net_tokens"))
            sell_tx = _int_or_none(row.get("sell_tx")) or 0
            is_closed = sell_tx > 0 and net_tokens is not None and abs(net_tokens) < 1e-9
            windows.append(
                MemeTokenWindow(
                    mint=mint,
                    symbol=(row.get("symbol") or "").strip() or None,
                    first_block_time=first_block_time,
                    last_block_time=last_block_time,
                    window_start=max(0, first_block_time - buffer_seconds),
                    window_end=last_block_time + buffer_seconds,
                    is_closed_position=is_closed,
                )
            )
    return windows


def fetch_market_transactions(
    client: HeliusEnhancedClient,
    window: MemeTokenWindow,
    *,
    page_limit: int = 100,
    max_pages: int = 20,
    token_accounts: str = "none",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_transactions: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    seen_signatures: set[str] = set()
    after_signature: str | None = None

    for _ in range(max_pages):
        page = client.address_transactions(
            window.mint,
            gte_time=window.window_start,
            lte_time=window.window_end,
            limit=page_limit,
            after_signature=after_signature,
            token_accounts=token_accounts,
        )
        if not page:
            break

        last_signature: str | None = None
        added_from_page = 0
        for tx in page:
            signature = _str_or_none(tx.get("signature"))
            if not signature or signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            last_signature = signature
            if not transaction_mentions_mint(tx, window.mint):
                continue
            raw_transactions.append(tx)
            records.append(normalize_market_transaction(tx, window))
            added_from_page += 1

        if not last_signature or len(page) < page_limit:
            break
        after_signature = last_signature
        if added_from_page == 0 and _latest_timestamp(page) and _latest_timestamp(page) > window.window_end:
            break

    records.sort(key=lambda item: (item.get("timestamp") or 0, item.get("signature") or ""))
    raw_transactions.sort(key=lambda item: (item.get("timestamp") or 0, item.get("signature") or ""))
    return raw_transactions, records


def transaction_mentions_mint(tx: dict[str, Any], mint: str) -> bool:
    return mint in _collect_mints(tx)


def normalize_market_transaction(tx: dict[str, Any], window: MemeTokenWindow) -> dict[str, Any]:
    token_flow = _token_flow(tx, window.mint)
    sol_flow = _sol_flow(tx)
    token_amount = abs(token_flow["net_amount"]) or token_flow["transfer_amount"]
    sol_amount = _best_sol_amount(token_flow, sol_flow)
    price_sol = sol_amount / token_amount if sol_amount and token_amount else None

    return {
        "mint": window.mint,
        "symbol": window.symbol,
        "signature": _str_or_none(tx.get("signature")),
        "timestamp": _int_or_none(tx.get("timestamp")),
        "time_utc": format_block_time(_int_or_none(tx.get("timestamp"))),
        "slot": _int_or_none(tx.get("slot")),
        "type": _str_or_none(tx.get("type")),
        "source": _str_or_none(tx.get("source")),
        "fee": _int_or_none(tx.get("fee")),
        "fee_payer": _str_or_none(tx.get("feePayer")),
        "description": _str_or_none(tx.get("description")),
        "trade_side": _trade_side(token_flow, sol_flow),
        "token_amount": token_amount or None,
        "sol_amount": sol_amount,
        "price_sol": price_sol,
        "token_input_amount": token_flow["input_amount"] or None,
        "token_output_amount": token_flow["output_amount"] or None,
        "native_input_sol": sol_flow["native_input_sol"] or None,
        "native_output_sol": sol_flow["native_output_sol"] or None,
        "token_transfer_count": token_flow["transfer_count"],
        "native_transfer_count": sol_flow["native_transfer_count"],
        "window_start": window.window_start,
        "window_end": window.window_end,
        "window_basis": window.window_basis,
        "is_closed_position": window.is_closed_position,
    }


def format_block_time(block_time: int | None) -> str:
    if block_time is None:
        return ""
    return datetime.fromtimestamp(block_time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _collect_mints(value: Any) -> set[str]:
    mints: set[str] = set()

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            mint = item.get("mint") or item.get("tokenAddress")
            if isinstance(mint, str):
                mints.add(mint)
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    return mints


def _token_flow(tx: dict[str, Any], mint: str) -> dict[str, Any]:
    input_amount = 0.0
    output_amount = 0.0
    transfer_amount = 0.0
    transfer_count = 0

    swap = _event_swap(tx)
    for item in _as_list(swap.get("tokenInputs")):
        if _str_or_none(item.get("mint")) == mint:
            amount = _token_amount(item)
            if amount is not None:
                input_amount += amount
    for item in _as_list(swap.get("tokenOutputs")):
        if _str_or_none(item.get("mint")) == mint:
            amount = _token_amount(item)
            if amount is not None:
                output_amount += amount

    for item in _as_list(tx.get("tokenTransfers")):
        if _str_or_none(item.get("mint")) != mint:
            continue
        amount = _token_amount(item)
        if amount is None:
            continue
        transfer_amount += abs(amount)
        transfer_count += 1

    return {
        "input_amount": input_amount,
        "output_amount": output_amount,
        "net_amount": output_amount - input_amount,
        "transfer_amount": transfer_amount,
        "transfer_count": transfer_count,
    }


def _sol_flow(tx: dict[str, Any]) -> dict[str, Any]:
    native_input_sol = 0.0
    native_output_sol = 0.0
    native_transfer_count = 0

    swap = _event_swap(tx)
    native_input = swap.get("nativeInput")
    native_output = swap.get("nativeOutput")
    if isinstance(native_input, dict):
        native_input_sol = _lamports_to_sol(native_input.get("amount")) or 0.0
    if isinstance(native_output, dict):
        native_output_sol = _lamports_to_sol(native_output.get("amount")) or 0.0

    native_transfer_sol = 0.0
    for item in _as_list(tx.get("nativeTransfers")):
        amount = _lamports_to_sol(item.get("amount")) if isinstance(item, dict) else None
        if amount is None:
            continue
        native_transfer_sol += abs(amount)
        native_transfer_count += 1

    return {
        "native_input_sol": native_input_sol,
        "native_output_sol": native_output_sol,
        "native_transfer_sol": native_transfer_sol,
        "native_transfer_count": native_transfer_count,
    }


def _best_sol_amount(token_flow: dict[str, Any], sol_flow: dict[str, Any]) -> float | None:
    if token_flow["output_amount"] > token_flow["input_amount"] and sol_flow["native_input_sol"]:
        return sol_flow["native_input_sol"]
    if token_flow["input_amount"] > token_flow["output_amount"] and sol_flow["native_output_sol"]:
        return sol_flow["native_output_sol"]
    if sol_flow["native_input_sol"] or sol_flow["native_output_sol"]:
        return max(sol_flow["native_input_sol"], sol_flow["native_output_sol"])
    return sol_flow["native_transfer_sol"] or None


def _trade_side(token_flow: dict[str, Any], sol_flow: dict[str, Any]) -> str:
    if token_flow["output_amount"] > token_flow["input_amount"] and sol_flow["native_input_sol"]:
        return "buy"
    if token_flow["input_amount"] > token_flow["output_amount"] and sol_flow["native_output_sol"]:
        return "sell"
    return ""


def _event_swap(tx: dict[str, Any]) -> dict[str, Any]:
    events = tx.get("events")
    if not isinstance(events, dict):
        return {}
    swap = events.get("swap")
    return swap if isinstance(swap, dict) else {}


def _token_amount(item: dict[str, Any]) -> float | None:
    for key in ("tokenAmount", "amount"):
        amount = _float_or_none(item.get(key))
        if amount is not None:
            return amount

    raw = item.get("rawTokenAmount")
    if isinstance(raw, dict):
        amount = _float_or_none(raw.get("tokenAmount"))
        decimals = _int_or_none(raw.get("decimals")) or 0
        if amount is not None:
            return amount / (10**decimals)
    return None


def _latest_timestamp(page: list[dict[str, Any]]) -> int | None:
    timestamps = [_int_or_none(item.get("timestamp")) for item in page]
    timestamps = [item for item in timestamps if item is not None]
    return max(timestamps) if timestamps else None


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _float_or_none(value: Any) -> float | None:
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


def _lamports_to_sol(value: Any) -> float | None:
    amount = _float_or_none(value)
    if amount is None:
        return None
    return amount / LAMPORTS_PER_SOL
