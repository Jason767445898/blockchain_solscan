from __future__ import annotations

import argparse
from pathlib import Path

from ._conditions import (
    MIN_EFFECTIVE_SOL,
    build_entry_samples,
    build_exit_samples,
    summarize_entry_samples,
    summarize_exit_samples,
)
from ._reports import write_csv, write_exit_report, write_json, write_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reverse-analyze meme coin entry conditions for a wallet.")
    parser.add_argument("--wallet", required=True, help="Target wallet address.")
    parser.add_argument("--data-dir", default="data", help="Directory containing wallet CSVs and market_trades.")
    parser.add_argument("--output-dir", default="", help="Output directory. Defaults to data/<wallet>/analysis/.")
    parser.add_argument(
        "--min-effective-sol",
        type=float,
        default=MIN_EFFECTIVE_SOL,
        help="Ignore tiny market trades below this SOL amount when computing entry features.",
    )
    return parser.parse_args()


def _existing_path(new_path: Path, old_path: Path) -> Path:
    """Return new_path if it exists, else old_path if it exists, else new_path."""
    if new_path.exists():
        return new_path
    if old_path.exists():
        return old_path
    return new_path


def main() -> None:
    args = parse_args()
    wallet = args.wallet
    data_dir = Path(args.data_dir)
    market_dir = _existing_path(
        data_dir / wallet / "market_trades",
        data_dir / f"{wallet}.market_trades",
    )
    out_dir = Path(args.output_dir) if args.output_dir else data_dir / wallet / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)

    wallet_csv = _existing_path(
        data_dir / wallet / "transactions.csv",
        data_dir / f"{wallet}.csv",
    )
    meme_tokens_csv = _existing_path(
        data_dir / wallet / "meme_tokens.csv",
        data_dir / f"{wallet}.meme_tokens.csv",
    )

    entry_samples = build_entry_samples(
        wallet=wallet,
        wallet_csv=wallet_csv,
        meme_tokens_csv=meme_tokens_csv,
        market_dir=market_dir,
        min_effective_sol=args.min_effective_sol,
    )
    exit_samples = build_exit_samples(
        wallet=wallet,
        wallet_csv=wallet_csv,
        meme_tokens_csv=meme_tokens_csv,
        market_dir=market_dir,
        min_effective_sol=args.min_effective_sol,
    )

    entry_summary = summarize_entry_samples(entry_samples, args.min_effective_sol)
    exit_summary = summarize_exit_samples(exit_samples, args.min_effective_sol)
    write_csv(out_dir / "entry_features.csv", entry_samples)
    write_json(out_dir / "summary.json", entry_summary)
    write_report(out_dir / "report.md", wallet, entry_samples, entry_summary, args.min_effective_sol)
    write_csv(out_dir / "exit_features.csv", exit_samples)
    write_json(out_dir / "exit_summary.json", exit_summary)
    write_exit_report(out_dir / "exit_report.md", wallet, exit_samples, exit_summary, args.min_effective_sol)

    print(f"Saved {len(entry_samples)} entry samples")
    print(f"- {out_dir / 'entry_features.csv'}")
    print(f"- {out_dir / 'summary.json'}")
    print(f"- {out_dir / 'report.md'}")
    print(f"Saved {len(exit_samples)} exit samples")
    print(f"- {out_dir / 'exit_features.csv'}")
    print(f"- {out_dir / 'exit_summary.json'}")
    print(f"- {out_dir / 'exit_report.md'}")


if __name__ == "__main__":
    main()
