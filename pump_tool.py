from __future__ import annotations

import argparse
import os
from pathlib import Path

DEFAULT_WALLET = "55PB376nxsrBLTZr1UdQSk6M89AxPif6oKmbmZmWq5dr"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Unified Pump.fun wallet monitor, market collector, and behavior analyst.",
    )
    parser.add_argument(
        "--wallet",
        default=os.getenv("SOLSCAN_WALLET") or DEFAULT_WALLET,
        help="Target Solana wallet. Defaults to SOLSCAN_WALLET or the bundled sample wallet.",
    )
    parser.add_argument(
        "--data-dir",
        default=os.getenv("SOLSCAN_OUTPUT_DIR", "data"),
        help="Directory for wallet, meme-token, and market-trade data.",
    )
    parser.add_argument(
        "--rpc-url",
        default=os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"),
        help="Solana JSON-RPC URL for wallet scans.",
    )
    parser.add_argument(
        "--helius-api-key",
        default=os.getenv("HELIUS_API_KEY"),
        help="Helius API key for market-trade collection.",
    )
    parser.add_argument("--verbose", action="store_true", help="Print detailed progress from subcommands.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="Fetch wallet transactions and classify Pump activity.")
    add_scan_options(scan)

    dedupe = subparsers.add_parser("dedupe", help="Deduplicate local wallet JSONL/CSV output.")
    dedupe.set_defaults(func=run_dedupe)

    tokens = subparsers.add_parser("tokens", help="Build data/<wallet>/meme_tokens.csv from wallet output.")
    tokens.set_defaults(func=run_tokens)

    market = subparsers.add_parser("market", help="Fetch market-wide Helius transactions for traded mints.")
    add_market_options(market)

    inspect = subparsers.add_parser("inspect", help="Inspect one transaction signature and its Pump classification.")
    inspect.add_argument("signature", help="Transaction signature to inspect.")
    inspect.add_argument("--source", choices=["rpc", "solscan"], default=os.getenv("MONITOR_SOURCE", "rpc"))
    inspect.add_argument("--api-key", default=os.getenv("SOLSCAN_API_KEY"), help="Solscan Pro API key.")
    inspect.add_argument("--rpc-min-interval", type=float, default=float(os.getenv("RPC_MIN_INTERVAL", "1.0")))
    inspect.add_argument("--pump-program-id", action="append", default=[], help="Additional Pump-related program id.")

    analyze = subparsers.add_parser("analyze", help="Generate entry and exit behavior reports.")
    add_analyze_options(analyze)

    pipeline = subparsers.add_parser("pipeline", help="Run scan -> dedupe -> tokens -> market -> analyze.")
    add_scan_options(pipeline, include_watch=False)
    add_market_options(pipeline)
    add_analyze_options(pipeline)
    pipeline.add_argument(
        "--skip-scan",
        action="store_true",
        help="Use existing wallet output and start from dedupe/tokens.",
    )
    pipeline.add_argument(
        "--skip-market",
        action="store_true",
        help="Use existing market_trades data and go straight to analysis.",
    )
    pipeline.set_defaults(func=run_pipeline)

    scan.set_defaults(func=run_scan)
    market.set_defaults(func=run_market)
    inspect.set_defaults(func=run_inspect)
    analyze.set_defaults(func=run_analyze)
    return parser


def add_scan_options(parser: argparse.ArgumentParser, *, include_watch: bool = True) -> None:
    parser.add_argument("--source", choices=["rpc", "solscan"], default=os.getenv("MONITOR_SOURCE", "rpc"))
    parser.add_argument("--api-key", default=os.getenv("SOLSCAN_API_KEY"), help="Solscan Pro API key.")
    parser.add_argument("--limit", type=int, default=100, help="Transactions to fetch.")
    parser.add_argument("--rpc-min-interval", type=float, default=float(os.getenv("RPC_MIN_INTERVAL", "1.0")))
    parser.add_argument("--category", action="append", default=[], help="Only persist matching category.")
    parser.add_argument("--include-other", action="store_true", help="Persist non-Pump transactions too.")
    parser.add_argument("--no-details", action="store_true", help="Skip transaction details for faster scans.")
    parser.add_argument("--refresh-seen", action="store_true", help="Reprocess fetched signatures in this run.")
    if include_watch:
        parser.add_argument("--watch", action="store_true", help="Keep polling instead of running once.")
        parser.add_argument("--poll-seconds", type=int, default=int(os.getenv("SOLSCAN_POLL_SECONDS", "30")))


def add_market_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--helius-base-url", default=os.getenv("HELIUS_BASE_URL", "https://api-mainnet.helius-rpc.com"))
    parser.add_argument("--helius-min-interval", type=float, default=float(os.getenv("HELIUS_MIN_INTERVAL", "0.25")))
    parser.add_argument("--market-window-buffer", type=int, default=300)
    parser.add_argument("--market-page-limit", type=int, default=100)
    parser.add_argument("--market-max-pages", type=int, default=20)
    parser.add_argument("--market-token-limit", type=int, help="Only process the first N meme tokens.")


def add_analyze_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--analysis-output-dir", default="", help="Defaults to pump_analyst/results/<wallet>.")
    parser.add_argument("--min-effective-sol", type=float, default=0.005)


def run_scan(args: argparse.Namespace) -> int:
    from pump_monitor import monitor

    monitor.cli_scan(
        rpc_url=args.rpc_url,
        wallet=args.wallet,
        limit=args.limit,
        verbose=getattr(args, "verbose", False),
        refresh_seen=getattr(args, "refresh_seen", False),
        pump_program_ids=getattr(args, "pump_program_ids", None),
        data_dir=args.data_dir,
    )
    return 0


def run_dedupe(args: argparse.Namespace) -> int:
    from pump_monitor import monitor

    monitor.cli_dedupe(wallet=args.wallet, data_dir=args.data_dir)
    return 0


def run_tokens(args: argparse.Namespace) -> int:
    from pump_monitor import monitor

    monitor.cli_tokens(wallet=args.wallet, data_dir=args.data_dir)
    return 0


def run_market(args: argparse.Namespace) -> int:
    from pump_monitor import monitor

    monitor.cli_market(
        wallet=args.wallet,
        data_dir=args.data_dir,
        helius_api_key=args.helius_api_key,
        market_dir=getattr(args, "market_dir", None),
    )
    return 0


def run_inspect(args: argparse.Namespace) -> int:
    from pump_monitor import monitor

    monitor.cli_inspect(
        rpc_url=args.rpc_url,
        signature=args.signature,
        pump_program_ids=getattr(args, "pump_program_ids", None),
        verbose=getattr(args, "verbose", False),
    )
    return 0


def run_analyze(args: argparse.Namespace) -> int:
    from pump_analyst import analyze

    analysis_args = [
        "--wallet",
        args.wallet,
        "--data-dir",
        args.data_dir,
        "--min-effective-sol",
        str(args.min_effective_sol),
    ]
    if args.analysis_output_dir:
        analysis_args.extend(["--output-dir", args.analysis_output_dir])
    return analyze.main(analysis_args)


def run_pipeline(args: argparse.Namespace) -> int:
    from pump_monitor import monitor

    if not args.skip_scan:
        monitor.cli_scan(
            rpc_url=args.rpc_url,
            wallet=args.wallet,
            limit=args.limit,
            verbose=getattr(args, "verbose", False),
            refresh_seen=getattr(args, "refresh_seen", False),
            pump_program_ids=getattr(args, "pump_program_ids", None),
            data_dir=args.data_dir,
        )
    monitor.cli_dedupe(wallet=args.wallet, data_dir=args.data_dir)
    monitor.cli_tokens(wallet=args.wallet, data_dir=args.data_dir)

    if not args.skip_market and args.helius_api_key:
        monitor.cli_market(
            wallet=args.wallet,
            data_dir=args.data_dir,
            helius_api_key=args.helius_api_key,
            market_dir=getattr(args, "market_dir", None),
        )
    return run_analyze(args)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    Path(args.data_dir).mkdir(parents=True, exist_ok=True)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
