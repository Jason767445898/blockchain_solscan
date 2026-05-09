from __future__ import annotations

from typing import Any

from .models import PumpClassification


# Pump.fun and PumpSwap program IDs that are commonly visible in Solana txs.
# Keep this list configurable in code so new Pump programs can be added quickly.
PUMP_FUN_PROGRAM_IDS = {
    "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P",
}

PUMP_SWAP_PROGRAM_IDS = {
    "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA",
}

KNOWN_PUMP_PROGRAM_IDS = PUMP_FUN_PROGRAM_IDS | PUMP_SWAP_PROGRAM_IDS


def parse_program_ids(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip() for item in value.replace(";", ",").split(",") if item.strip()}


def classify_transaction(
    summary: dict[str, Any],
    detail: dict[str, Any] | None,
    wallet: str,
    extra_pump_program_ids: set[str] | None = None,
) -> PumpClassification:
    program_ids = sorted(_collect_program_ids(summary, detail))
    reasons: list[str] = []
    confidence = 0.0
    known_pump_program_ids = KNOWN_PUMP_PROGRAM_IDS | (extra_pump_program_ids or set())

    pump_hits = sorted(set(program_ids) & known_pump_program_ids)
    if pump_hits:
        reasons.append(f"matched Pump program id: {', '.join(pump_hits)}")
        confidence += 0.7

    source = str(summary.get("source") or detail_get(detail, "source") or "").lower()
    if "pump" in source:
        reasons.append(f"source contains pump: {source}")
        confidence += 0.2

    status = str(summary.get("status") or detail_get(detail, "status") or "").lower()
    if status and status not in {"success", "succ", "true"}:
        reasons.append(f"transaction status is {status}")
        return PumpClassification(
            category="failed_pump_tx" if pump_hits else "failed_other_tx",
            confidence=min(confidence, 0.8),
            reasons=reasons,
            program_ids=program_ids,
        )

    sol_change = _wallet_sol_change(detail, wallet)
    token_changes = _wallet_token_changes(detail, wallet)

    if not pump_hits and confidence == 0.0:
        return PumpClassification(
            category="other_tx",
            confidence=0.0,
            reasons=reasons,
            program_ids=program_ids,
            sol_change=sol_change,
            token_changes=token_changes,
        )

    category = _infer_pump_category(summary, detail, sol_change, token_changes)
    if token_changes:
        reasons.append("wallet token balance changed")
        confidence += 0.1
    if sol_change is not None:
        reasons.append(f"wallet SOL change: {sol_change:.9f}")
        confidence += 0.05

    return PumpClassification(
        category=category,
        confidence=min(confidence, 0.95),
        reasons=reasons,
        program_ids=program_ids,
        sol_change=sol_change,
        token_changes=token_changes,
    )


def detail_get(detail: dict[str, Any] | None, key: str) -> Any:
    if not detail:
        return None
    return detail.get(key)


def _collect_program_ids(summary: dict[str, Any], detail: dict[str, Any] | None) -> set[str]:
    ids: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                normalized = key.lower()
                if normalized in {"program_id", "programid", "program"} and isinstance(item, str):
                    ids.add(item)
                else:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for container in (summary, detail or {}):
        for key in ("program_ids", "programIds"):
            values = container.get(key)
            if isinstance(values, list):
                ids.update(str(item) for item in values)

    walk(summary)
    if detail:
        walk(detail)
    return ids

def _wallet_sol_change(detail: dict[str, Any] | None, wallet: str) -> float | None:
    if not detail:
        return None

    for key in ("sol_bal_change", "sol_balance_change", "native_bal_change"):
        changes = detail.get(key)
        if isinstance(changes, list):
            lamports = 0
            found = False
            for change in changes:
                if not isinstance(change, dict):
                    continue
                owner = change.get("address") or change.get("account") or change.get("owner")
                if owner != wallet:
                    continue
                amount = change.get("change_amount") or change.get("changeAmount") or change.get("amount")
                if isinstance(amount, (int, float)):
                    lamports += int(amount)
                    found = True
            if found:
                return lamports / 1_000_000_000

    return None


def _wallet_token_changes(detail: dict[str, Any] | None, wallet: str) -> list[dict[str, Any]]:
    if not detail:
        return []

    changes: list[dict[str, Any]] = []
    for key in ("token_bal_change", "token_balance_change", "tokens_bal_change"):
        raw_changes = detail.get(key)
        if not isinstance(raw_changes, list):
            continue
        for item in raw_changes:
            if not isinstance(item, dict):
                continue
            owner = item.get("owner") or item.get("address") or item.get("account")
            if owner != wallet:
                continue
            changes.append(
                {
                    "mint": item.get("token_address") or item.get("mint") or item.get("tokenAddress"),
                    "symbol": item.get("symbol") or item.get("token_symbol"),
                    "amount": item.get("change_amount") or item.get("changeAmount") or item.get("amount"),
                    "decimals": item.get("decimals") or item.get("token_decimals"),
                }
            )
    return changes


def _infer_pump_category(
    summary: dict[str, Any],
    detail: dict[str, Any] | None,
    sol_change: float | None,
    token_changes: list[dict[str, Any]],
) -> str:
    text = " ".join(
        str(value).lower()
        for value in (
            summary.get("source"),
            summary.get("type"),
            summary.get("activity_type"),
            detail_get(detail, "type"),
        )
        if value is not None
    )
    if "create" in text:
        return "pump_create_token"
    if "sell" in text:
        return "pump_sell"
    if "buy" in text:
        return "pump_buy"

    token_delta = _net_token_delta(token_changes)
    if token_delta is not None and sol_change is not None:
        if token_delta > 0 and sol_change < 0:
            return "pump_buy"
        if token_delta < 0 and sol_change > 0:
            return "pump_sell"

    return "pump_related"


def _net_token_delta(token_changes: list[dict[str, Any]]) -> float | None:
    total = 0.0
    found = False
    for change in token_changes:
        amount = change.get("amount")
        if isinstance(amount, str):
            try:
                amount = float(amount)
            except ValueError:
                continue
        if isinstance(amount, (int, float)):
            total += float(amount)
            found = True
    return total if found else None
