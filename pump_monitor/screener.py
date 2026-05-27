from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from pump_analyst._conditions import normalize_raw_market_tx, safe_div

from ._utils import as_list, int_or_none, str_or_none
from .classifier import PUMP_FUN_PROGRAM_IDS, PUMP_SWAP_PROGRAM_IDS
from .market_trades import HeliusEnhancedClient

DEFAULT_PUMP_PROGRAM_IDS = sorted(PUMP_FUN_PROGRAM_IDS | PUMP_SWAP_PROGRAM_IDS)


@dataclass
class EntryRule:
    max_age_s: int = 180
    min_trade_count: int = 15
    min_unique_buyers: int = 10
    min_buy_sol: float = 5.0
    min_last60_trade_count: int = 5
    min_last60_sol: float = 2.0
    min_buy_ratio: float = 0.55
    max_last_trade_gap_s: int = 10
    min_effective_sol: float = 0.005

    def checks(self, features: dict[str, Any]) -> dict[str, bool]:
        return {
            "age": features["age_s"] <= self.max_age_s,
            "trades": features["pre_trade_count"] >= self.min_trade_count,
            "buyers": features["pre_unique_buyers"] >= self.min_unique_buyers,
            "buy_sol": features["pre_buy_sol"] >= self.min_buy_sol,
            "last60_trades": features["last60_trade_count"] >= self.min_last60_trade_count,
            "last60_sol": features["last60_sol"] >= self.min_last60_sol,
            "buy_ratio": (features["pre_buy_ratio"] or 0) >= self.min_buy_ratio,
            "gap": features["last_trade_gap_s"] <= self.max_last_trade_gap_s,
        }

    def passed(self, features: dict[str, Any]) -> bool:
        return all(self.checks(features).values())


@dataclass
class ScreenerConfig:
    helius_api_key: str
    data_dir: str = "data"
    base_url: str = "https://api-mainnet.helius-rpc.com"
    min_interval: float = 0.25
    discovery_limit: int = 30
    market_limit: int = 100
    candidate_max_age_s: int = 240
    watch_seconds: int = 8
    max_candidates: int = 20
    pump_program_ids: list[str] | None = None
    rule: EntryRule | None = None
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    alert_retention_hours: float = 24.0


class RealtimeScreener:
    def __init__(self, config: ScreenerConfig) -> None:
        self.config = config
        self.rule = config.rule or EntryRule()
        self.client = HeliusEnhancedClient(
            config.helius_api_key,
            base_url=config.base_url,
            min_interval=config.min_interval,
        )
        self.program_ids = config.pump_program_ids or DEFAULT_PUMP_PROGRAM_IDS
        self.candidates: dict[str, dict[str, Any]] = {}
        self.seen_signatures: set[str] = set()
        self.alerted_mints: set[str] = set()
        self.retention_hours = config.alert_retention_hours
        self.alert_path = Path(config.data_dir) / "realtime_screener" / "alerts.jsonl"
        self.alert_path.parent.mkdir(parents=True, exist_ok=True)
        cleanup_expired_alerts(config.data_dir, self.retention_hours)

    def poll_once(self) -> dict[str, Any]:
        now = int(time.time())
        errors: list[str] = []
        discovered = 0

        for program_id in self.program_ids:
            try:
                transactions = self.client.address_transactions(
                    program_id,
                    gte_time=max(0, now - self.config.candidate_max_age_s),
                    lte_time=now,
                    limit=self.config.discovery_limit,
                    sort_order="desc",
                )
            except Exception as exc:
                errors.append(f"{program_id}: {exc}")
                continue

            for tx in transactions:
                signature = str_or_none(tx.get("signature"))
                if not signature or signature in self.seen_signatures:
                    continue
                self.seen_signatures.add(signature)
                for mint in candidate_mints(tx):
                    if not is_pump_mint(mint):
                        continue
                    candidate = self.candidates.setdefault(
                        mint,
                        {
                            "mint": mint,
                            "symbol": token_symbol(tx, mint),
                            "first_seen_ts": int_or_none(tx.get("timestamp")) or now,
                            "source_signature": signature,
                            "program_id": program_id,
                        },
                    )
                    if not candidate.get("symbol"):
                        candidate["symbol"] = token_symbol(tx, mint)
                    discovered += 1

        rows: list[dict[str, Any]] = []
        alerts: list[dict[str, Any]] = []
        stale_mints: list[str] = []
        for mint, candidate in sorted(self.candidates.items(), key=lambda item: item[1]["first_seen_ts"], reverse=True):
            age = now - int(candidate["first_seen_ts"])
            if age > self.config.candidate_max_age_s:
                stale_mints.append(mint)
                continue
            try:
                raw_txs = self.client.address_transactions(
                    mint,
                    gte_time=max(0, int(candidate["first_seen_ts"]) - 5),
                    lte_time=now,
                    limit=self.config.market_limit,
                    sort_order="asc",
                )
            except Exception as exc:
                errors.append(f"{mint}: {exc}")
                continue

            features = calculate_live_entry_features(
                mint=mint,
                now_ts=now,
                raw_transactions=raw_txs,
                min_effective_sol=self.rule.min_effective_sol,
            )
            features["symbol"] = candidate.get("symbol") or ""
            features["first_seen_utc"] = utc(int(candidate["first_seen_ts"]))
            features["source_signature"] = candidate.get("source_signature") or ""
            features["score"] = score_features(features, self.rule)
            features["passed"] = self.rule.passed(features)
            rows.append(features)

            if features["passed"] and mint not in self.alerted_mints:
                self.alerted_mints.add(mint)
                features["alerted_at_ts"] = int(time.time())
                alerts.append(features)
                append_jsonl(self.alert_path, features)
                send_telegram_alert(self.config, features)

        for mint in stale_mints:
            self.candidates.pop(mint, None)

        rows.sort(key=lambda item: (item["passed"], item["score"], item["last60_sol"]), reverse=True)
        return {
            "generated_at_utc": utc(now),
            "candidate_count": len(self.candidates),
            "discovered_count": discovered,
            "alert_count": len(alerts),
            "errors": errors,
            "rows": rows[: self.config.max_candidates],
            "alerts": alerts,
        }


def candidate_mints(tx: dict[str, Any]) -> set[str]:
    mints: set[str] = set()
    for transfer in as_list(tx.get("tokenTransfers")):
        mint = str_or_none(transfer.get("mint")) if isinstance(transfer, dict) else None
        if mint:
            mints.add(mint)

    for account in as_list(tx.get("accountData")):
        if not isinstance(account, dict):
            continue
        for change in as_list(account.get("tokenBalanceChanges")):
            mint = str_or_none(change.get("mint")) if isinstance(change, dict) else None
            if mint:
                mints.add(mint)

    swap = tx.get("events", {}).get("swap") if isinstance(tx.get("events"), dict) else None
    if isinstance(swap, dict):
        for key in ("tokenInputs", "tokenOutputs"):
            for item in as_list(swap.get(key)):
                mint = str_or_none(item.get("mint")) if isinstance(item, dict) else None
                if mint:
                    mints.add(mint)
    return mints


def is_pump_mint(mint: str) -> bool:
    return mint.endswith("pump")


def token_symbol(tx: dict[str, Any], mint: str) -> str:
    for transfer in as_list(tx.get("tokenTransfers")):
        if not isinstance(transfer, dict) or transfer.get("mint") != mint:
            continue
        symbol = str_or_none(transfer.get("tokenStandard")) or str_or_none(transfer.get("symbol"))
        if symbol:
            return symbol
    return ""


def calculate_live_entry_features(
    *,
    mint: str,
    now_ts: int,
    raw_transactions: list[dict[str, Any]],
    min_effective_sol: float,
) -> dict[str, Any]:
    all_txs = [normalize_raw_market_tx(tx, mint) for tx in raw_transactions]
    pre_txs = [
        tx
        for tx in all_txs
        if tx["ts"] is not None and tx["side"] in {"buy", "sell"} and tx["sol"] >= min_effective_sol
    ]
    buys = [tx for tx in pre_txs if tx["side"] == "buy"]
    sells = [tx for tx in pre_txs if tx["side"] == "sell"]
    create_ts = min([tx["ts"] for tx in all_txs if tx["type"] == "CREATE" and tx["ts"] is not None], default=None)
    first_ts = min([tx["ts"] for tx in all_txs if tx["ts"] is not None], default=now_ts)
    start_ts = create_ts if create_ts is not None else first_ts
    prices = [tx["price"] for tx in pre_txs if tx["price"]]

    def recent(seconds: int) -> list[dict[str, Any]]:
        return [tx for tx in pre_txs if now_ts - tx["ts"] <= seconds]

    last60 = recent(60)
    buy_sol = sum(tx["sol"] for tx in buys)
    sell_sol = sum(tx["sol"] for tx in sells)
    return {
        "mint": mint,
        "age_s": max(0, now_ts - start_ts),
        "pre_trade_count": len(pre_txs),
        "pre_buy_count": len(buys),
        "pre_sell_count": len(sells),
        "pre_buy_ratio": safe_div(len(buys), len(pre_txs)),
        "pre_unique_wallets": len({tx["fee_payer"] for tx in pre_txs if tx["fee_payer"]}),
        "pre_unique_buyers": len({tx["fee_payer"] for tx in buys if tx["fee_payer"]}),
        "pre_buy_sol": buy_sol,
        "pre_sell_sol": sell_sol,
        "pre_net_flow_sol": buy_sol - sell_sol,
        "last_trade_gap_s": now_ts - max([tx["ts"] for tx in pre_txs], default=now_ts),
        "last60_trade_count": len(last60),
        "last60_sol": sum(tx["sol"] for tx in last60),
        "price_return": prices[-1] / prices[0] - 1 if len(prices) >= 2 and prices[0] else None,
        "near_high": prices[-1] / max(prices) if prices else None,
    }


def score_features(features: dict[str, Any], rule: EntryRule) -> int:
    checks = rule.checks(features)
    return sum(1 for passed in checks.values() if passed)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def cleanup_expired_alerts(data_dir: str, retention_hours: float) -> tuple[int, int]:
    """Remove alerts older than retention_hours from alerts.jsonl. Returns (kept, removed)."""
    path = Path(data_dir) / "realtime_screener" / "alerts.jsonl"
    if not path.exists():
        return (0, 0)
    # retention_hours <= 0 means "keep everything"
    if retention_hours <= 0:
        with path.open("r", encoding="utf-8") as handle:
            count = sum(1 for _ in handle)
        return (count, 0)
    now_ts = int(time.time())
    cutoff_ts = now_ts - int(retention_hours * 3600)
    kept_rows: list[dict[str, Any]] = []
    removed = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            alerted_at = int(row.get("alerted_at_ts") or 0)
            if alerted_at > 0 and alerted_at < cutoff_ts:
                removed += 1
                continue
            kept_rows.append(row)
    if removed:
        with path.open("w", encoding="utf-8") as handle:
            for row in kept_rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return (len(kept_rows), removed)


def _read_mints_path(data_dir: str) -> Path:
    return Path(data_dir) / "realtime_screener" / "read_mints.json"


def load_read_status(data_dir: str) -> dict[str, bool]:
    """Load the read/unread status of alert mints. Returns {} if file missing."""
    path = _read_mints_path(data_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_read_status(data_dir: str, read_mints: dict[str, bool]) -> None:
    """Persist read/unread status for alert mints."""
    path = _read_mints_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(read_mints, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def load_alert_rows(data_dir: str, limit: int = 100, retention_hours: float = 24.0) -> list[dict[str, Any]]:
    """Load recent alerts, cleaning expired ones and merging read status."""
    path = Path(data_dir) / "realtime_screener" / "alerts.jsonl"
    cleanup_expired_alerts(data_dir, retention_hours)
    if not path.exists():
        return []
    read_status = load_read_status(data_dir)
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                mint = row.get("mint", "")
                row["_read"] = read_status.get(mint, False)
                rows.append(row)
    return rows[-limit:]


def send_telegram_alert(config: ScreenerConfig, features: dict[str, Any]) -> None:
    if not config.telegram_bot_token or not config.telegram_chat_id:
        return

    text = (
        "Pump realtime match\n"
        f"Mint: {features['mint']}\n"
        f"Score: {features['score']}/8\n"
        f"Age: {features['age_s']}s\n"
        f"Buyers: {features['pre_unique_buyers']}\n"
        f"Buy SOL: {features['pre_buy_sol']:.4f}\n"
        f"Last60 SOL: {features['last60_sol']:.4f}\n"
        f"https://pump.fun/{features['mint']}"
    )
    url = f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage"
    try:
        requests.post(
            url,
            json={"chat_id": config.telegram_chat_id, "text": text, "disable_web_page_preview": True},
            timeout=10,
        )
    except requests.RequestException:
        return


def rows_for_table(rows: list[dict[str, Any]]) -> list[list[Any]]:
    table_rows: list[list[Any]] = []
    for row in rows:
        columns = [
            "YES" if row.get("passed") else "",
            row.get("score"),
            row.get("mint"),
            row.get("age_s"),
            row.get("pre_trade_count"),
            row.get("pre_unique_buyers"),
            round(float(row.get("pre_buy_sol") or 0), 4),
            row.get("last60_trade_count"),
            round(float(row.get("last60_sol") or 0), 4),
            round(float(row.get("pre_buy_ratio") or 0), 4),
            row.get("last_trade_gap_s"),
        ]
        if "_read" in row:
            columns.insert(0, bool(row["_read"]))
        table_rows.append(columns)
    return table_rows


def summarize_poll(result: dict[str, Any]) -> str:
    lines = [
        f"updated_at: {result['generated_at_utc']}",
        f"candidates: {result['candidate_count']}",
        f"new_candidate_events: {result['discovered_count']}",
        f"new_alerts: {result['alert_count']}",
    ]
    errors = result.get("errors") or []
    if errors:
        lines.append("errors:")
        lines.extend(f"- {error}" for error in errors[:5])
    return "\n".join(lines)


def utc(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
