from __future__ import annotations

import argparse
import os

from .classifier import parse_program_ids
from .rpc import SolanaRpcClient
from .storage import TransactionStore


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
    from .monitor import build_client, scan_once

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
    from .monitor import print_meme_token_summaries

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
    from .monitor import fetch_market_trades

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
    from .monitor import inspect_signature

    args = argparse.Namespace(
        rpc_url=rpc_url,
        signature=signature,
        pump_program_id=pump_program_ids or [],
        verbose=verbose,
        output_dir="data",
        source="rpc",
        rpc_min_interval=1.0,
    )

    client = SolanaRpcClient(rpc_url, min_interval=1.0)
    extra_pump_program_ids = parse_program_ids(os.getenv("PUMP_PROGRAM_IDS")) | set(args.pump_program_id)
    inspect_signature(client, signature, "", extra_pump_program_ids)
