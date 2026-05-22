from __future__ import annotations

import itertools
import json
import time
from typing import Any

import requests

from ._base_client import BaseApiClient


DEFAULT_RPC_URL = "https://api.mainnet-beta.solana.com"


class RpcError(RuntimeError):
    """Raised when the Solana RPC endpoint returns an error."""


class SolanaRpcClient(BaseApiClient):
    def __init__(
        self,
        rpc_url: str = DEFAULT_RPC_URL,
        timeout: int = 20,
        min_interval: float = 1.0,
        max_retries: int = 3,
        retry_sleep: float = 3.0,
    ) -> None:
        super().__init__(
            min_interval=min_interval,
            max_retries=max_retries,
            retry_sleep=retry_sleep,
            timeout=timeout,
        )
        self.rpc_url = rpc_url
        self._ids = itertools.count(1)
        self._session = requests.Session()

    def account_transactions(
        self,
        address: str,
        *,
        before: str | None = None,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        config: dict[str, Any] = {"limit": limit}
        if before:
            config["before"] = before
        result = self._call("getSignaturesForAddress", [address, config])
        if not isinstance(result, list):
            raise RpcError("Expected a list from getSignaturesForAddress")
        return [_normalize_signature_summary(item) for item in result if isinstance(item, dict)]

    def transaction_detail(self, signature: str) -> dict[str, Any]:
        result = self._call(
            "getTransaction",
            [
                signature,
                {
                    "encoding": "jsonParsed",
                    "maxSupportedTransactionVersion": 0,
                },
            ],
        )
        if result is None:
            return {}
        if not isinstance(result, dict):
            raise RpcError("Expected an object from getTransaction")
        return _normalize_transaction_detail(signature, result)

    def _call(self, method: str, params: list[Any]) -> Any:
        payload = {
            "jsonrpc": "2.0",
            "id": next(self._ids),
            "method": method,
            "params": params,
        }

        for attempt in range(self.max_retries + 1):
            try:
                self._rate_limit()
                response = self._session.post(self.rpc_url, json=payload, timeout=self.timeout)
                self._mark_request()
                response.raise_for_status()
                body = response.json()
                break
            except requests.HTTPError as exc:
                self._mark_request()
                if exc.response is not None and exc.response.status_code == 429 and attempt < self.max_retries:
                    time.sleep(self._retry_delay(attempt))
                    continue
                if exc.response is not None and exc.response.status_code == 429:
                    raise RpcError(
                        "RPC rate limit reached after retries; use --limit 3, increase "
                        "--rpc-min-interval, or use another RPC URL"
                    ) from exc
                if exc.response is not None:
                    raise RpcError(f"RPC HTTP {exc.response.status_code}: {exc.response.text[:300]}") from exc
                raise RpcError(f"RPC HTTP error: {exc}") from exc
            except (requests.ConnectionError, requests.Timeout) as exc:
                self._mark_request()
                if attempt < self.max_retries:
                    time.sleep(self._retry_delay(attempt))
                    continue
                raise RpcError(f"Cannot connect to RPC endpoint: {exc}") from exc
            except json.JSONDecodeError as exc:
                self._mark_request()
                raise RpcError("RPC returned invalid JSON") from exc

        if "error" in body:
            error = body["error"]
            if isinstance(error, dict) and error.get("code") == 429:
                raise RpcError(
                    "RPC rate limit reached; use --limit 3, increase --rpc-min-interval, or use another RPC URL"
                )
            raise RpcError(f"RPC error from {method}: {body['error']}")
        return body.get("result")


def _normalize_signature_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "signature": item.get("signature"),
        "block_time": item.get("blockTime"),
        "slot": item.get("slot"),
        "status": "Success" if item.get("err") is None else "Fail",
        "err": item.get("err"),
        "source": "solana_rpc",
    }


def _normalize_transaction_detail(signature: str, tx: dict[str, Any]) -> dict[str, Any]:
    meta = tx.get("meta") if isinstance(tx.get("meta"), dict) else {}
    transaction = tx.get("transaction") if isinstance(tx.get("transaction"), dict) else {}
    message = transaction.get("message") if isinstance(transaction.get("message"), dict) else {}
    account_keys = message.get("accountKeys") if isinstance(message.get("accountKeys"), list) else []

    account_addresses = [_account_address(item) for item in account_keys]
    signer = [
        _account_address(item)
        for item in account_keys
        if isinstance(item, dict) and item.get("signer") is True and _account_address(item)
    ]

    return {
        "signature": signature,
        "block_time": tx.get("blockTime"),
        "slot": tx.get("slot"),
        "status": "Success" if meta.get("err") is None else "Fail",
        "fee": meta.get("fee"),
        "signer": signer,
        "program_ids": sorted(_collect_rpc_program_ids(tx)),
        "sol_bal_change": _sol_balance_changes(account_addresses, meta),
        "token_bal_change": _token_balance_changes(meta),
        "source": "solana_rpc",
        "raw_rpc": tx,
    }


def _account_address(item: Any) -> str | None:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        pubkey = item.get("pubkey")
        return pubkey if isinstance(pubkey, str) else None
    return None


def _collect_rpc_program_ids(tx: dict[str, Any]) -> set[str]:
    ids: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            program_id = value.get("programId")
            if isinstance(program_id, str):
                ids.add(program_id)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(tx)
    return ids


def _sol_balance_changes(account_addresses: list[str | None], meta: dict[str, Any]) -> list[dict[str, Any]]:
    pre = meta.get("preBalances")
    post = meta.get("postBalances")
    if not isinstance(pre, list) or not isinstance(post, list):
        return []

    changes: list[dict[str, Any]] = []
    for index, (before, after) in enumerate(zip(pre, post)):
        if not isinstance(before, int) or not isinstance(after, int):
            continue
        address = account_addresses[index] if index < len(account_addresses) else None
        if not address:
            continue
        delta = after - before
        if delta:
            changes.append({"address": address, "change_amount": delta})
    return changes


def _token_balance_changes(meta: dict[str, Any]) -> list[dict[str, Any]]:
    pre = _token_balances_by_key(meta.get("preTokenBalances"))
    post = _token_balances_by_key(meta.get("postTokenBalances"))
    keys = sorted(set(pre) | set(post))

    changes: list[dict[str, Any]] = []
    for key in keys:
        before = pre.get(key, {})
        after = post.get(key, {})
        before_amount = before.get("amount", 0)
        after_amount = after.get("amount", 0)
        delta = after_amount - before_amount
        if delta == 0:
            continue
        owner = after.get("owner") or before.get("owner")
        mint = after.get("mint") or before.get("mint")
        changes.append(
            {
                "owner": owner,
                "mint": mint,
                "token_address": mint,
                "change_amount": delta,
                "decimals": after.get("decimals") if "decimals" in after else before.get("decimals"),
            }
        )
    return changes


def _token_balances_by_key(value: Any) -> dict[tuple[int, str], dict[str, Any]]:
    if not isinstance(value, list):
        return {}

    balances: dict[tuple[int, str], dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        account_index = item.get("accountIndex")
        mint = item.get("mint")
        if not isinstance(account_index, int) or not isinstance(mint, str):
            continue

        ui_token_amount = item.get("uiTokenAmount")
        if not isinstance(ui_token_amount, dict):
            ui_token_amount = {}
        raw_amount = ui_token_amount.get("amount", "0")
        try:
            amount = int(raw_amount)
        except (TypeError, ValueError):
            amount = 0

        balances[(account_index, mint)] = {
            "owner": item.get("owner"),
            "mint": mint,
            "amount": amount,
            "decimals": ui_token_amount.get("decimals"),
        }
    return balances
