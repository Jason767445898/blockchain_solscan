from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any

from .classifier import classify_transaction, parse_program_ids
from .meme_tokens import MemeTokenSummary
from .models import MonitoredTransaction
from .storage import TransactionStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Monitor a Solana wallet's Pump.fun activity.",
    )
    parser.add_argument("--wallet", default=os.getenv("SOLSCAN_WALLET"), help="Solana wallet address")
    parser.add_argument(
        "--source",
        choices=["rpc", "solscan"],
        default=os.getenv("MONITOR_SOURCE", "rpc"),
        help="Data source. rpc is free and default; solscan requires a paid API key for these endpoints.",
    )
    parser.add_argument("--api-key", default=os.getenv("SOLSCAN_API_KEY"), help="Solscan Pro API key")
    parser.add_argument(
        "--rpc-url",
        default=os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"),
        help="Solana JSON-RPC URL used when --source rpc",
    )
    parser.add_argument(
        "--rpc-min-interval",
        type=float,
        default=float(os.getenv("RPC_MIN_INTERVAL", "1.0")),
        help="Minimum seconds between RPC requests. Increase this for public RPC endpoints.",
    )
    parser.add_argument(
        "--output-dir",
        default=os.getenv("SOLSCAN_OUTPUT_DIR", "data"),
        help="Directory for JSONL and CSV output",
    )
    parser.add_argument("--limit", type=int, default=10, help="Transactions to fetch each poll")
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=int(os.getenv("SOLSCAN_POLL_SECONDS", "30")),
        help="Polling interval when --once is not used",
    )
    parser.add_argument("--once", action="store_true", help="Run one scan and exit")
    parser.add_argument(
        "--include-other",
        action="store_true",
        help="Persist non-Pump transactions too",
    )
    parser.add_argument(
        "--category",
        action="append",
        default=[],
        help="Only persist matching categories, for example --category pump_sell. Can be passed multiple times.",
    )
    parser.add_argument(
        "--no-details",
        action="store_true",
        help="Only use account transaction summaries; faster but less precise",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print fetched transaction counts and skip reasons",
    )
    parser.add_argument(
        "--pump-program-id",
        action="append",
        default=[],
        help="Additional Pump-related program id. Can be passed multiple times.",
    )
    parser.add_argument(
        "--inspect-signature",
        help="Fetch one transaction signature, print its program ids/classification, then exit.",
    )
    parser.add_argument(
        "--refresh-seen",
        action="store_true",
        help="Ignore existing output files and reprocess fetched signatures in this run.",
    )
    parser.add_argument(
        "--dedupe",
        action="store_true",
        help="Deduplicate this wallet's output files by signature, then exit.",
    )
    parser.add_argument(
        "--meme-tokens",
        action="store_true",
        help="Summarize meme tokens traded by this wallet from the local JSONL output, then exit.",
    )
    parser.add_argument(
        "--meme-tokens-csv",
        action="store_true",
        help="With --meme-tokens, also write data/<wallet>.meme_tokens.csv.",
    )
    parser.add_argument(
        "--market-trades",
        action="store_true",
        help="Fetch market-wide Helius enhanced transactions for mints in data/<wallet>.meme_tokens.csv.",
    )
    parser.add_argument(
        "--helius-api-key",
        default=os.getenv("HELIUS_API_KEY"),
        help="Helius API key for --market-trades. Defaults to HELIUS_API_KEY.",
    )
    parser.add_argument(
        "--helius-base-url",
        default=os.getenv("HELIUS_BASE_URL", "https://api-mainnet.helius-rpc.com"),
        help="Helius enhanced API base URL used by --market-trades.",
    )
    parser.add_argument(
        "--helius-min-interval",
        type=float,
        default=float(os.getenv("HELIUS_MIN_INTERVAL", "0.25")),
        help="Minimum seconds between Helius enhanced API requests.",
    )
    parser.add_argument(
        "--market-window-buffer",
        type=int,
        default=300,
        help="Seconds to extend before wallet open time and after wallet close/last trade time.",
    )
    parser.add_argument(
        "--market-page-limit",
        type=int,
        default=100,
        help="Helius enhanced transaction page size for --market-trades, capped at 100.",
    )
    parser.add_argument(
        "--market-max-pages",
        type=int,
        default=20,
        help="Maximum Helius pages to fetch per mint.",
    )
    parser.add_argument(
        "--market-token-limit",
        type=int,
        help="Only process the first N meme token windows. Useful for testing.",
    )
    return parser


def cli_scan(
    rpc_url: str,
    wallet: str,
    limit: int,
    verbose: bool,
    refresh_seen: bool,
    pump_program_ids: list[str] | None,
    data_dir: str,
) -> None:
    """Public entry point for scan subcommand from pump_tool.py."""
    args = argparse.Namespace(
        rpc_url=rpc_url,
        wallet=wallet,
        limit=limit,
        verbose=verbose,
        refresh_seen=refresh_seen,
        pump_program_id=pump_program_ids or [],
        output_dir=data_dir,
        source="rpc",
        api_key=None,
        rpc_min_interval=1.0,
        include_other=False,
        no_details=False,
        category=[],
    )
    store = TransactionStore(data_dir)
    client, source_error = build_client(args)
    extra_pump_program_ids = parse_program_ids(os.getenv("PUMP_PROGRAM_IDS")) | set(args.pump_program_id)
    seen = set() if refresh_seen else store.seen_signatures(wallet)
    scan_once(
        client,
        store,
        wallet=wallet,
        seen=seen,
        limit=limit,
        include_other=args.include_other,
        categories=set(args.category),
        with_details=not args.no_details,
        verbose=verbose,
        extra_pump_program_ids=extra_pump_program_ids,
    )


def cli_dedupe(wallet: str, data_dir: str) -> None:
    """Public entry point for dedupe subcommand from pump_tool.py."""
    store = TransactionStore(data_dir)
    kept = store.dedupe(wallet)
    print(f"deduped output for {wallet}; kept {kept} unique records")


def cli_tokens(wallet: str, data_dir: str) -> None:
    """Public entry point for tokens subcommand from pump_tool.py."""
    store = TransactionStore(data_dir)
    summaries = store.meme_token_summaries(wallet)
    print_meme_token_summaries(summaries)
    path = store.write_meme_token_csv(wallet, summaries)
    print(f"wrote {path}")


def cli_market(
    wallet: str,
    data_dir: str,
    helius_api_key: str,
    market_dir: str | None,
) -> None:
    """Public entry point for market subcommand from pump_tool.py."""
    if not helius_api_key:
        raise SystemExit("--helius-api-key or HELIUS_API_KEY is required for market collection")
    args = argparse.Namespace(
        wallet=wallet,
        output_dir=data_dir,
        helius_api_key=helius_api_key,
        market_dir=market_dir,
        helius_base_url=os.getenv("HELIUS_BASE_URL", "https://api-mainnet.helius-rpc.com"),
        helius_min_interval=float(os.getenv("HELIUS_MIN_INTERVAL", "0.25")),
        market_window_buffer=300,
        market_page_limit=100,
        market_max_pages=20,
        market_token_limit=None,
    )
    fetch_market_trades(args, TransactionStore(data_dir))


def cli_inspect(
    rpc_url: str,
    signature: str,
    pump_program_ids: list[str] | None,
    verbose: bool,
) -> None:
    """Public entry point for inspect subcommand from pump_tool.py."""
    args = argparse.Namespace(
        rpc_url=rpc_url,
        signature=signature,
        pump_program_id=pump_program_ids or [],
        verbose=verbose,
        output_dir="data",
        source="rpc",
        rpc_min_interval=1.0,
    )
    from .rpc import SolanaRpcClient

    client = SolanaRpcClient(rpc_url, min_interval=1.0)
    extra_pump_program_ids = parse_program_ids(os.getenv("PUMP_PROGRAM_IDS")) | set(args.pump_program_id)
    inspect_signature(client, signature, "", extra_pump_program_ids)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.wallet:
        parser.error("--wallet or SOLSCAN_WALLET is required")
    if args.source == "solscan" and not args.api_key:
        parser.error("--api-key or SOLSCAN_API_KEY is required")

    store = TransactionStore(args.output_dir)
    if args.dedupe:
        kept = store.dedupe(args.wallet)
        print(f"deduped output for {args.wallet}; kept {kept} unique records")
        return 0
    if args.meme_tokens:
        summaries = store.meme_token_summaries(args.wallet)
        print_meme_token_summaries(summaries)
        if args.meme_tokens_csv:
            path = store.write_meme_token_csv(args.wallet, summaries)
            print(f"wrote {path}")
        return 0
    if args.market_trades:
        if not args.helius_api_key:
            parser.error("--helius-api-key or HELIUS_API_KEY is required with --market-trades")
        try:
            fetch_market_trades(args, store)
        except Exception as exc:
            print(f"market trades error: {exc}", file=sys.stderr)
            return 1
        return 0

    client, source_error = build_client(args)
    extra_pump_program_ids = parse_program_ids(os.getenv("PUMP_PROGRAM_IDS")) | set(args.pump_program_id)
    if args.inspect_signature:
        try:
            inspect_signature(client, args.inspect_signature, args.wallet, extra_pump_program_ids)
        except source_error as exc:
            print(f"{args.source} error: {exc}", file=sys.stderr)
            return 1
        return 0

    seen = set() if args.refresh_seen else store.seen_signatures(args.wallet)

    while True:
        try:
            new_records = scan_once(
                client,
                store,
                wallet=args.wallet,
                seen=seen,
                limit=args.limit,
                include_other=args.include_other,
                categories=set(args.category),
                with_details=not args.no_details,
                verbose=args.verbose,
                extra_pump_program_ids=extra_pump_program_ids,
            )
        except source_error as exc:
            print(f"{args.source} error: {exc}", file=sys.stderr)
            if args.once:
                return 1
        else:
            print(f"saved {new_records} new records; tracking {len(seen)} signatures")

        if args.once:
            return 0
        time.sleep(args.poll_seconds)


def build_client(args: argparse.Namespace) -> tuple[Any, type[Exception]]:
    if args.source == "solscan":
        from .solscan import SolscanClient, SolscanError

        return SolscanClient(args.api_key), SolscanError

    from .rpc import SolanaRpcClient, RpcError

    return SolanaRpcClient(args.rpc_url, min_interval=args.rpc_min_interval), RpcError


def scan_once(
    client: Any,
    store: TransactionStore,
    *,
    wallet: str,
    seen: set[str],
    limit: int,
    include_other: bool,
    categories: set[str],
    with_details: bool,
    verbose: bool,
    extra_pump_program_ids: set[str],
) -> int:
    summaries = client.account_transactions(wallet, limit=limit)
    if verbose:
        print(f"fetched {len(summaries)} transaction summaries for {wallet}")
    txs: list[MonitoredTransaction] = []
    skipped_seen = 0
    skipped_other = 0

    for summary in reversed(summaries):
        signature = _signature(summary)
        if not signature or signature in seen:
            if signature in seen:
                skipped_seen += 1
            continue

        detail: dict[str, Any] | None = None
        if with_details:
            detail = client.transaction_detail(signature)

        classification = classify_transaction(summary, detail, wallet, extra_pump_program_ids)
        keep_by_category = not categories or classification.category in categories
        keep_by_default = include_other or classification.category != "other_tx"
        if keep_by_category and keep_by_default:
            txs.append(
                MonitoredTransaction(
                    signature=signature,
                    block_time=_int_or_none(_first_value(summary, detail, "block_time", "blockTime")),
                    slot=_int_or_none(_first_value(summary, detail, "slot")),
                    status=_str_or_none(_first_value(summary, detail, "status")),
                    fee=_int_or_none(_first_value(summary, detail, "fee")),
                    signer=_list_of_str(_first_value(summary, detail, "signer", "signers")),
                    source=_str_or_none(_first_value(summary, detail, "source")),
                    raw={"summary": summary, "detail": detail},
                    classification=classification,
                )
            )
        elif classification.category == "other_tx":
            skipped_other += 1
        seen.add(signature)

    records = [tx.to_record(wallet) for tx in txs]
    store.append(wallet, records)
    if verbose:
        print(f"skipped {skipped_seen} already-seen txs and {skipped_other} non-Pump txs")
    return len(records)


def inspect_signature(client: Any, signature: str, wallet: str, extra_pump_program_ids: set[str]) -> None:
    detail = client.transaction_detail(signature)
    summary = {
        "signature": signature,
        "status": detail.get("status"),
        "source": detail.get("source"),
        "program_ids": detail.get("program_ids") or [],
    }
    classification = classify_transaction(summary, detail, wallet, extra_pump_program_ids)
    print(f"signature: {signature}")
    print(f"category: {classification.category}")
    print(f"confidence: {classification.confidence}")
    print("program_ids:")
    for program_id in classification.program_ids:
        print(f"  {program_id}")
    print("reasons:")
    for reason in classification.reasons:
        print(f"  {reason}")
    if classification.sol_change is not None:
        print(f"sol_change: {classification.sol_change:.9f}")
    if classification.token_changes:
        print("token_changes:")
        for change in classification.token_changes:
            print(f"  {change}")


def fetch_market_trades(args: argparse.Namespace, store: TransactionStore) -> None:
    from .market_trades import (
        HeliusEnhancedClient,
        fetch_market_transactions,
        format_block_time,
        read_meme_token_windows,
    )

    meme_tokens_path = store.meme_tokens_csv_path(args.wallet)
    if not meme_tokens_path.exists():
        summaries = store.meme_token_summaries(args.wallet)
        if not summaries:
            raise RuntimeError(f"{meme_tokens_path} does not exist and no local wallet trades were found to build it")
        store.write_meme_token_csv(args.wallet, summaries)

    windows = read_meme_token_windows(meme_tokens_path, buffer_seconds=args.market_window_buffer)
    if args.market_token_limit is not None:
        windows = windows[: max(0, args.market_token_limit)]
    if not windows:
        raise RuntimeError(f"No usable meme token windows found in {meme_tokens_path}")

    client = HeliusEnhancedClient(
        args.helius_api_key,
        base_url=args.helius_base_url,
        min_interval=args.helius_min_interval,
    )

    summary_rows: list[dict[str, Any]] = []
    all_records: list[dict[str, Any]] = []
    print(f"fetching market trades for {len(windows)} mint(s)")
    for index, window in enumerate(windows, start=1):
        print(
            f"[{index}/{len(windows)}] {window.mint} "
            f"{format_block_time(window.window_start)} -> {format_block_time(window.window_end)}"
        )
        raw_transactions, records = fetch_market_transactions(
            client,
            window,
            page_limit=args.market_page_limit,
            max_pages=args.market_max_pages,
        )
        store.write_market_trades(args.wallet, window.mint, raw_transactions, records)
        all_records.extend(records)
        summary_rows.append(market_trade_summary_row(window, raw_transactions, records, format_block_time))
        print(f"  wrote {len(records)} matched tx(s) from {len(raw_transactions)} raw tx(s)")

    summary_path = store.write_market_trade_summary(args.wallet, summary_rows)
    all_path = store.write_all_market_trades(args.wallet, all_records)
    print(f"wrote {summary_path}")
    print(f"wrote {all_path}")


def market_trade_summary_row(
    window: Any,
    raw_transactions: list[dict[str, Any]],
    records: list[dict[str, Any]],
    format_block_time_fn: Any,
) -> dict[str, Any]:
    timestamps = [_int_or_none(record.get("timestamp")) for record in records]
    timestamps = [item for item in timestamps if item is not None]
    first_trade = min(timestamps) if timestamps else None
    last_trade = max(timestamps) if timestamps else None
    row = window.to_record()
    row.update(
        {
            "raw_tx_count": len(raw_transactions),
            "matched_trade_count": len(records),
            "first_market_trade_time": format_block_time_fn(first_trade),
            "last_market_trade_time": format_block_time_fn(last_trade),
        }
    )
    return row


def print_meme_token_summaries(summaries: list[MemeTokenSummary]) -> None:
    if not summaries:
        print("No meme token trades found in local output.")
        return

    columns = [
        ("mint", 44),
        ("buy", 5),
        ("sell", 5),
        ("buy_sol", 10),
        ("sell_sol", 10),
        ("net_sol", 10),
        ("net_tokens", 14),
        ("first_time_utc", 23),
        ("last_time_utc", 23),
    ]
    print(f"found {len(summaries)} meme token mint(s)")
    print(" ".join(name.ljust(width) for name, width in columns))
    for summary in summaries:
        record = summary.to_record()
        row = {
            "mint": summary.mint,
            "buy": str(summary.buy_tx),
            "sell": str(summary.sell_tx),
            "buy_sol": _format_number(record["buy_sol"]),
            "sell_sol": _format_number(record["sell_sol"]),
            "net_sol": _format_number(record["net_sol"]),
            "net_tokens": _format_number(record["net_tokens"]),
            "first_time_utc": record["first_time_utc"],
            "last_time_utc": record["last_time_utc"],
        }
        print(" ".join(row[name].ljust(width)[:width] for name, width in columns))


def _format_number(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)


def _signature(tx: dict[str, Any]) -> str | None:
    for key in ("tx_hash", "txHash", "signature", "trans_id"):
        value = tx.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _first_value(summary: dict[str, Any], detail: dict[str, Any] | None, *keys: str) -> Any:
    for container in (summary, detail or {}):
        for key in keys:
            value = container.get(key)
            if value is not None:
                return value
    return None


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


def _str_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _list_of_str(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


if __name__ == "__main__":
    raise SystemExit(main())
