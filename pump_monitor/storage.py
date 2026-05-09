from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .meme_tokens import MemeTokenSummary, summarize_meme_tokens


CSV_COLUMNS = [
    "wallet",
    "signature",
    "block_time",
    "slot",
    "status",
    "category",
    "confidence",
    "sol_change",
    "source",
    "fee",
    "reasons",
    "program_ids",
    "token_changes",
]

MEME_TOKEN_COLUMNS = [
    "mint",
    "symbol",
    "buy_tx",
    "sell_tx",
    "total_tx",
    "buy_sol",
    "sell_sol",
    "net_sol",
    "buy_tokens",
    "sell_tokens",
    "net_tokens",
    "first_block_time",
    "last_block_time",
    "first_time_utc",
    "last_time_utc",
]

MARKET_TRADE_COLUMNS = [
    "mint",
    "symbol",
    "signature",
    "timestamp",
    "time_utc",
    "slot",
    "type",
    "source",
    "fee",
    "fee_payer",
    "description",
    "trade_side",
    "token_amount",
    "sol_amount",
    "price_sol",
    "token_input_amount",
    "token_output_amount",
    "native_input_sol",
    "native_output_sol",
    "token_transfer_count",
    "native_transfer_count",
    "window_start",
    "window_end",
    "window_basis",
    "is_closed_position",
]

MARKET_SUMMARY_COLUMNS = [
    "mint",
    "symbol",
    "window_start",
    "window_end",
    "window_start_utc",
    "window_end_utc",
    "is_closed_position",
    "window_basis",
    "raw_tx_count",
    "matched_trade_count",
    "first_market_trade_time",
    "last_market_trade_time",
]


class TransactionStore:
    def __init__(self, output_dir: str | Path) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def seen_signatures(self, wallet: str) -> set[str]:
        path = self._jsonl_path(wallet)
        if not path.exists():
            return set()

        seen: set[str] = set()
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                signature = record.get("signature")
                if isinstance(signature, str):
                    seen.add(signature)
        return seen

    def records(self, wallet: str) -> list[dict[str, Any]]:
        path = self._jsonl_path(wallet)
        if not path.exists():
            return []

        records: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    records.append(record)
        return records

    def meme_token_summaries(self, wallet: str) -> list[MemeTokenSummary]:
        return summarize_meme_tokens(self.records(wallet))

    def write_meme_token_csv(self, wallet: str, summaries: list[MemeTokenSummary] | None = None) -> Path:
        path = self._meme_tokens_csv_path(wallet)
        rows = summaries if summaries is not None else self.meme_token_summaries(wallet)
        with path.open("w", encoding="utf-8", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=MEME_TOKEN_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for summary in rows:
                writer.writerow(summary.to_record())
        return path

    def write_market_trades(
        self,
        wallet: str,
        mint: str,
        raw_transactions: list[dict[str, Any]],
        records: list[dict[str, Any]],
    ) -> tuple[Path, Path]:
        market_dir = self._market_trades_dir(wallet)
        market_dir.mkdir(parents=True, exist_ok=True)
        jsonl_path = market_dir / f"{mint}.jsonl"
        csv_path = market_dir / f"{mint}.csv"

        with jsonl_path.open("w", encoding="utf-8") as jsonl:
            for tx in raw_transactions:
                jsonl.write(json.dumps(tx, ensure_ascii=False, sort_keys=True) + "\n")

        with csv_path.open("w", encoding="utf-8", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=MARKET_TRADE_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for record in records:
                writer.writerow(record)

        return jsonl_path, csv_path

    def write_market_trade_summary(self, wallet: str, rows: list[dict[str, Any]]) -> Path:
        path = self._market_trades_dir(wallet) / "summary.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=MARKET_SUMMARY_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        return path

    def write_all_market_trades(self, wallet: str, records: list[dict[str, Any]]) -> Path:
        path = self._market_trades_dir(wallet) / "all_market_trades.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=MARKET_TRADE_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for record in records:
                writer.writerow(record)
        return path

    def append(self, wallet: str, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        jsonl_path = self._jsonl_path(wallet)
        csv_path = self._csv_path(wallet)

        with jsonl_path.open("a", encoding="utf-8") as jsonl:
            for record in records:
                jsonl.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

        needs_header = not csv_path.exists()
        with csv_path.open("a", encoding="utf-8", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS, extrasaction="ignore")
            if needs_header:
                writer.writeheader()
            for record in records:
                row = dict(record)
                row["reasons"] = " | ".join(record.get("reasons") or [])
                row["program_ids"] = " | ".join(record.get("program_ids") or [])
                row["token_changes"] = json.dumps(record.get("token_changes") or [], ensure_ascii=False)
                writer.writerow(row)

    def dedupe(self, wallet: str) -> int:
        path = self._jsonl_path(wallet)
        if not path.exists():
            return 0

        by_signature: dict[str, dict[str, Any]] = {}
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                signature = record.get("signature")
                if isinstance(signature, str) and signature:
                    by_signature[signature] = record

        csv_path = self._csv_path(wallet)
        with path.open("w", encoding="utf-8") as jsonl:
            for record in by_signature.values():
                jsonl.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

        with csv_path.open("w", encoding="utf-8", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for record in by_signature.values():
                row = dict(record)
                row["reasons"] = " | ".join(record.get("reasons") or [])
                row["program_ids"] = " | ".join(record.get("program_ids") or [])
                row["token_changes"] = json.dumps(record.get("token_changes") or [], ensure_ascii=False)
                writer.writerow(row)

        return len(by_signature)

    def _jsonl_path(self, wallet: str) -> Path:
        return self.output_dir / f"{wallet}.jsonl"

    def _csv_path(self, wallet: str) -> Path:
        return self.output_dir / f"{wallet}.csv"

    def _meme_tokens_csv_path(self, wallet: str) -> Path:
        return self.output_dir / f"{wallet}.meme_tokens.csv"

    def meme_tokens_csv_path(self, wallet: str) -> Path:
        return self._meme_tokens_csv_path(wallet)

    def _market_trades_dir(self, wallet: str) -> Path:
        return self.output_dir / f"{wallet}.market_trades"
