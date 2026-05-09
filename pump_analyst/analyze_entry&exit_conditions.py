from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


DEFAULT_WALLET = "55PB376nxsrBLTZr1UdQSk6M89AxPif6oKmbmZmWq5dr"
MIN_EFFECTIVE_SOL = 0.005


def main() -> None:
    args = parse_args()
    wallet = args.wallet
    data_dir = Path(args.data_dir)
    market_dir = data_dir / f"{wallet}.market_trades"
    out_dir = Path(args.output_dir) if args.output_dir else Path(__file__).parent / "results" / wallet
    out_dir.mkdir(parents=True, exist_ok=True)

    entry_samples = build_entry_samples(
        wallet=wallet,
        wallet_csv=data_dir / f"{wallet}.csv",
        meme_tokens_csv=data_dir / f"{wallet}.meme_tokens.csv",
        market_dir=market_dir,
        min_effective_sol=args.min_effective_sol,
    )
    exit_samples = build_exit_samples(
        wallet=wallet,
        wallet_csv=data_dir / f"{wallet}.csv",
        meme_tokens_csv=data_dir / f"{wallet}.meme_tokens.csv",
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reverse-analyze meme coin entry conditions for a wallet.")
    parser.add_argument("--wallet", default=DEFAULT_WALLET, help="Target wallet address.")
    parser.add_argument("--data-dir", default="data", help="Directory containing wallet CSVs and market_trades.")
    parser.add_argument("--output-dir", default="", help="Output directory. Defaults to pump_analyst/results/<wallet>.")
    parser.add_argument(
        "--min-effective-sol",
        type=float,
        default=MIN_EFFECTIVE_SOL,
        help="Ignore tiny market trades below this SOL amount when computing entry features.",
    )
    return parser.parse_args()


def build_entry_samples(
    *,
    wallet: str,
    wallet_csv: Path,
    meme_tokens_csv: Path,
    market_dir: Path,
    min_effective_sol: float,
) -> list[dict[str, Any]]:
    wallet_trades = read_wallet_trades(wallet_csv)
    first_buys = read_first_wallet_buys(wallet_trades)
    token_summaries = read_token_summaries(meme_tokens_csv)
    market_csv_by_sig = read_market_csv_by_signature(market_dir / "all_market_trades.csv")

    samples: list[dict[str, Any]] = []
    for mint, entry in sorted(first_buys.items(), key=lambda item: (item[1]["ts"], item[1]["slot"])):
        txs = read_raw_market_txs(market_dir / f"{mint}.jsonl", mint, market_csv_by_sig)
        pre_txs = [
            tx
            for tx in txs
            if tx["ts"] is not None
            and (tx["ts"], tx["slot"] or 0, tx["sig"] or "") < (entry["ts"], entry["slot"] or 0, entry["sig"])
            and tx["fee_payer"] != wallet
            and tx["side"] in {"buy", "sell"}
            and tx["sol"] >= min_effective_sol
        ]

        sample = calculate_entry_features(mint, entry, txs, pre_txs, token_summaries.get(mint, {}))
        samples.append(sample)
    return samples


def build_exit_samples(
    *,
    wallet: str,
    wallet_csv: Path,
    meme_tokens_csv: Path,
    market_dir: Path,
    min_effective_sol: float,
) -> list[dict[str, Any]]:
    wallet_trades = read_wallet_trades(wallet_csv)
    token_summaries = read_token_summaries(meme_tokens_csv)
    market_csv_by_sig = read_market_csv_by_signature(market_dir / "all_market_trades.csv")

    samples: list[dict[str, Any]] = []
    for mint, trades in sorted(wallet_trades.items(), key=lambda item: (item[1][0]["ts"], item[1][0]["slot"])):
        sells = [trade for trade in trades if trade["side"] == "sell"]
        buys = [trade for trade in trades if trade["side"] == "buy"]
        if not sells or not buys:
            continue

        exit_trade = max(sells, key=lambda trade: (trade["ts"], trade["slot"] or 0, trade["sig"]))
        first_buy = min(buys, key=lambda trade: (trade["ts"], trade["slot"] or 0, trade["sig"]))
        txs = read_raw_market_txs(market_dir / f"{mint}.jsonl", mint, market_csv_by_sig)
        pre_txs = [
            tx
            for tx in txs
            if tx["ts"] is not None
            and (tx["ts"], tx["slot"] or 0, tx["sig"] or "") < (exit_trade["ts"], exit_trade["slot"] or 0, exit_trade["sig"])
            and tx["fee_payer"] != wallet
            and tx["side"] in {"buy", "sell"}
            and tx["sol"] >= min_effective_sol
        ]
        position_txs = [tx for tx in pre_txs if tx["ts"] >= first_buy["ts"]]

        sample = calculate_exit_features(
            mint,
            exit_trade,
            first_buy,
            trades,
            txs,
            pre_txs,
            position_txs,
            token_summaries.get(mint, {}),
        )
        samples.append(sample)
    return samples


def read_wallet_trades(wallet_csv: Path) -> dict[str, list[dict[str, Any]]]:
    trades_by_mint: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with wallet_csv.open("r", encoding="utf-8", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            if row.get("status") != "Success" or row.get("category") not in {"pump_buy", "pump_sell"}:
                continue
            ts = int_or_none(row.get("block_time"))
            slot = int_or_none(row.get("slot"))
            if ts is None or slot is None:
                continue
            side = "buy" if row.get("category") == "pump_buy" else "sell"
            for change in parse_json_list(row.get("token_changes")):
                if not isinstance(change, dict) or not change.get("mint"):
                    continue
                raw_amount = float_or_zero(change.get("amount"))
                decimals = int_or_none(change.get("decimals")) or 0
                token_delta = raw_amount / (10**decimals)
                mint = change["mint"]
                trades_by_mint[mint].append(
                    {
                        "mint": mint,
                        "ts": ts,
                        "slot": slot,
                        "sig": row.get("signature") or "",
                        "side": side,
                        "sol": abs(float_or_zero(row.get("sol_change"))),
                        "token_delta": token_delta,
                        "token": abs(token_delta),
                    }
                )

    for trades in trades_by_mint.values():
        trades.sort(key=lambda item: (item["ts"], item["slot"] or 0, item["sig"]))
    return trades_by_mint


def read_first_wallet_buys(wallet_trades: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    first_buys: dict[str, dict[str, Any]] = {}
    for mint, trades in wallet_trades.items():
        buys = [trade for trade in trades if trade["side"] == "buy"]
        if buys:
            first_buys[mint] = min(buys, key=lambda trade: (trade["ts"], trade["slot"] or 0, trade["sig"]))
    return first_buys


def read_token_summaries(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as csv_file:
        return {row["mint"]: row for row in csv.DictReader(csv_file) if row.get("mint")}


def read_market_csv_by_signature(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as csv_file:
        return {row["signature"]: row for row in csv.DictReader(csv_file) if row.get("signature")}


def read_raw_market_txs(path: Path, mint: str, csv_by_sig: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    txs: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as jsonl_file:
        for line in jsonl_file:
            tx = json.loads(line)
            sig = tx.get("signature") or ""
            csv_row = csv_by_sig.get(sig, {})
            fee_payer = tx.get("feePayer") or csv_row.get("fee_payer") or ""
            native_by_account: dict[str, float] = defaultdict(float)
            token_by_user: dict[str, float] = defaultdict(float)

            for account in tx.get("accountData") or []:
                account_id = account.get("account")
                if account_id:
                    native_by_account[account_id] += float_or_zero(account.get("nativeBalanceChange")) / 1_000_000_000
                for token_balance in account.get("tokenBalanceChanges") or []:
                    if token_balance.get("mint") != mint:
                        continue
                    user = token_balance.get("userAccount") or account_id
                    raw = token_balance.get("rawTokenAmount") or {}
                    decimals = int_or_none(raw.get("decimals")) or 0
                    amount = float_or_zero(raw.get("tokenAmount")) / (10**decimals)
                    if user:
                        token_by_user[user] += amount

            fee_token_delta = token_by_user[fee_payer]
            fee_native_delta = native_by_account[fee_payer]
            side = infer_side(fee_token_delta, fee_native_delta)
            sol_amount = abs(fee_native_delta)
            token_amount = abs(fee_token_delta)
            price = sol_amount / token_amount if sol_amount and token_amount else None

            txs.append(
                {
                    "sig": sig,
                    "ts": int_or_none(tx.get("timestamp")),
                    "slot": int_or_none(tx.get("slot")),
                    "type": tx.get("type") or csv_row.get("type") or "",
                    "source": tx.get("source") or csv_row.get("source") or "",
                    "fee_payer": fee_payer,
                    "side": side,
                    "sol": sol_amount,
                    "token": token_amount,
                    "price": price,
                }
            )
    return sorted(txs, key=lambda item: (item["ts"] or 0, item["slot"] or 0, item["sig"]))


def calculate_entry_features(
    mint: str,
    entry: dict[str, Any],
    all_txs: list[dict[str, Any]],
    pre_txs: list[dict[str, Any]],
    token_summary: dict[str, Any],
) -> dict[str, Any]:
    buys = [tx for tx in pre_txs if tx["side"] == "buy"]
    sells = [tx for tx in pre_txs if tx["side"] == "sell"]
    create_ts = min([tx["ts"] for tx in all_txs if tx["type"] == "CREATE" and tx["ts"] is not None], default=None)
    first_ts = min([tx["ts"] for tx in all_txs if tx["ts"] is not None], default=entry["ts"])
    start_ts = create_ts if create_ts is not None else first_ts
    prices = [tx["price"] for tx in pre_txs if tx["price"]]

    buy_sol = sum(tx["sol"] for tx in buys)
    sell_sol = sum(tx["sol"] for tx in sells)
    buy_total_sol = float_or_zero(token_summary.get("buy_sol"))
    roi = float_or_zero(token_summary.get("net_sol")) / buy_total_sol if buy_total_sol else None

    def recent(seconds: int) -> list[dict[str, Any]]:
        return [tx for tx in pre_txs if entry["ts"] - tx["ts"] <= seconds]

    last30 = recent(30)
    last60 = recent(60)

    return {
        "mint": mint,
        "entry_time_utc": utc(entry["ts"]),
        "entry_ts": entry["ts"],
        "entry_slot": entry["slot"],
        "entry_signature": entry["sig"],
        "entry_sol": entry["sol"],
        "age_s": entry["ts"] - start_ts,
        "pre_trade_count": len(pre_txs),
        "pre_buy_count": len(buys),
        "pre_sell_count": len(sells),
        "pre_buy_ratio": safe_div(len(buys), len(pre_txs)),
        "pre_unique_wallets": len({tx["fee_payer"] for tx in pre_txs}),
        "pre_unique_buyers": len({tx["fee_payer"] for tx in buys}),
        "pre_buy_sol": buy_sol,
        "pre_sell_sol": sell_sol,
        "pre_net_flow_sol": buy_sol - sell_sol,
        "last_trade_gap_s": entry["ts"] - max([tx["ts"] for tx in pre_txs], default=entry["ts"]),
        "last30_trade_count": len(last30),
        "last30_sol": sum(tx["sol"] for tx in last30),
        "last60_trade_count": len(last60),
        "last60_sol": sum(tx["sol"] for tx in last60),
        "price_return": prices[-1] / prices[0] - 1 if len(prices) >= 2 and prices[0] else None,
        "near_high": prices[-1] / max(prices) if prices else None,
        "wallet_position_buy_sol": buy_total_sol,
        "wallet_position_sell_sol": float_or_zero(token_summary.get("sell_sol")),
        "wallet_position_net_sol": float_or_zero(token_summary.get("net_sol")),
        "wallet_position_roi": roi,
    }


def calculate_exit_features(
    mint: str,
    exit_trade: dict[str, Any],
    first_buy: dict[str, Any],
    wallet_trades: list[dict[str, Any]],
    all_txs: list[dict[str, Any]],
    pre_txs: list[dict[str, Any]],
    position_txs: list[dict[str, Any]],
    token_summary: dict[str, Any],
) -> dict[str, Any]:
    buys = [tx for tx in pre_txs if tx["side"] == "buy"]
    sells = [tx for tx in pre_txs if tx["side"] == "sell"]
    pos_buys = [tx for tx in position_txs if tx["side"] == "buy"]
    pos_sells = [tx for tx in position_txs if tx["side"] == "sell"]
    create_ts = min([tx["ts"] for tx in all_txs if tx["type"] == "CREATE" and tx["ts"] is not None], default=None)
    first_ts = min([tx["ts"] for tx in all_txs if tx["ts"] is not None], default=first_buy["ts"])
    start_ts = create_ts if create_ts is not None else first_ts
    prices = [tx["price"] for tx in pre_txs if tx["price"]]
    position_prices = [tx["price"] for tx in position_txs if tx["price"]]
    current_price = prices[-1] if prices else None
    high_price = max(position_prices) if position_prices else None
    high_tx = max(
        [tx for tx in position_txs if tx["price"] is not None],
        key=lambda tx: tx["price"],
        default=None,
    )

    wallet_before_exit = [
        trade
        for trade in wallet_trades
        if (trade["ts"], trade["slot"] or 0, trade["sig"]) < (exit_trade["ts"], exit_trade["slot"] or 0, exit_trade["sig"])
    ]
    wallet_until_exit = [
        trade
        for trade in wallet_trades
        if (trade["ts"], trade["slot"] or 0, trade["sig"]) <= (exit_trade["ts"], exit_trade["slot"] or 0, exit_trade["sig"])
    ]
    bought_sol_until_exit = sum(trade["sol"] for trade in wallet_until_exit if trade["side"] == "buy")
    sold_sol_until_exit = sum(trade["sol"] for trade in wallet_until_exit if trade["side"] == "sell")
    tokens_before_exit = sum(trade["token_delta"] for trade in wallet_before_exit)
    tokens_after_exit = sum(trade["token_delta"] for trade in wallet_until_exit)
    exit_roi = safe_div(sold_sol_until_exit - bought_sol_until_exit, bought_sol_until_exit)
    full_exit_ratio = safe_div(exit_trade["token"], abs(tokens_before_exit))

    def recent(seconds: int) -> list[dict[str, Any]]:
        return [tx for tx in pre_txs if exit_trade["ts"] - tx["ts"] <= seconds]

    def window(prefix: str, txs: list[dict[str, Any]]) -> dict[str, Any]:
        window_buys = [tx for tx in txs if tx["side"] == "buy"]
        window_sells = [tx for tx in txs if tx["side"] == "sell"]
        buy_sol = sum(tx["sol"] for tx in window_buys)
        sell_sol = sum(tx["sol"] for tx in window_sells)
        return {
            f"{prefix}_trade_count": len(txs),
            f"{prefix}_buy_count": len(window_buys),
            f"{prefix}_sell_count": len(window_sells),
            f"{prefix}_sell_ratio": safe_div(len(window_sells), len(txs)),
            f"{prefix}_sol": buy_sol + sell_sol,
            f"{prefix}_buy_sol": buy_sol,
            f"{prefix}_sell_sol": sell_sol,
            f"{prefix}_net_flow_sol": buy_sol - sell_sol,
        }

    last30 = recent(30)
    last60 = recent(60)
    result = {
        "mint": mint,
        "exit_time_utc": utc(exit_trade["ts"]),
        "exit_ts": exit_trade["ts"],
        "exit_slot": exit_trade["slot"],
        "exit_signature": exit_trade["sig"],
        "exit_sol": exit_trade["sol"],
        "exit_token": exit_trade["token"],
        "first_entry_time_utc": utc(first_buy["ts"]),
        "first_entry_ts": first_buy["ts"],
        "hold_s": exit_trade["ts"] - first_buy["ts"],
        "age_s": exit_trade["ts"] - start_ts,
        "pre_trade_count": len(pre_txs),
        "pre_buy_count": len(buys),
        "pre_sell_count": len(sells),
        "pre_sell_ratio": safe_div(len(sells), len(pre_txs)),
        "pre_buy_sol": sum(tx["sol"] for tx in buys),
        "pre_sell_sol": sum(tx["sol"] for tx in sells),
        "pre_net_flow_sol": sum(tx["sol"] for tx in buys) - sum(tx["sol"] for tx in sells),
        "position_trade_count": len(position_txs),
        "position_buy_sol": sum(tx["sol"] for tx in pos_buys),
        "position_sell_sol": sum(tx["sol"] for tx in pos_sells),
        "position_net_flow_sol": sum(tx["sol"] for tx in pos_buys) - sum(tx["sol"] for tx in pos_sells),
        "last_trade_gap_s": exit_trade["ts"] - max([tx["ts"] for tx in pre_txs], default=exit_trade["ts"]),
        "price_return_since_entry": position_prices[-1] / position_prices[0] - 1
        if len(position_prices) >= 2 and position_prices[0]
        else None,
        "drawdown_from_high": current_price / high_price - 1 if current_price and high_price else None,
        "near_high": current_price / high_price if current_price and high_price else None,
        "seconds_from_high": exit_trade["ts"] - high_tx["ts"] if high_tx else None,
        "wallet_buy_sol_until_exit": bought_sol_until_exit,
        "wallet_sell_sol_until_exit": sold_sol_until_exit,
        "wallet_realized_pnl_until_exit": sold_sol_until_exit - bought_sol_until_exit,
        "wallet_realized_roi_until_exit": exit_roi,
        "wallet_tokens_before_exit": tokens_before_exit,
        "wallet_tokens_after_exit": tokens_after_exit,
        "exit_sold_token_ratio": full_exit_ratio,
        "is_full_exit": abs(tokens_after_exit) <= max(abs(tokens_before_exit), exit_trade["token"], 1.0) * 0.01,
        "wallet_position_buy_sol": float_or_zero(token_summary.get("buy_sol")),
        "wallet_position_sell_sol": float_or_zero(token_summary.get("sell_sol")),
        "wallet_position_net_sol": float_or_zero(token_summary.get("net_sol")),
    }
    result.update(window("last30", last30))
    result.update(window("last60", last60))
    return result


def summarize_entry_samples(samples: list[dict[str, Any]], min_effective_sol: float) -> dict[str, Any]:
    numeric_fields = [
        "entry_sol",
        "age_s",
        "pre_trade_count",
        "pre_unique_buyers",
        "pre_buy_sol",
        "pre_sell_sol",
        "pre_net_flow_sol",
        "last_trade_gap_s",
        "last60_trade_count",
        "last60_sol",
        "pre_buy_ratio",
        "near_high",
        "wallet_position_roi",
    ]
    stats = {field: describe([sample.get(field) for sample in samples]) for field in numeric_fields}

    rules: list[tuple[str, Callable[[dict[str, Any]], bool]]] = [
        ("age<=120", lambda s: s["age_s"] <= 120),
        ("age<=180", lambda s: s["age_s"] <= 180),
        ("trades>=15", lambda s: s["pre_trade_count"] >= 15),
        ("buyers>=10", lambda s: s["pre_unique_buyers"] >= 10),
        ("buy_sol>=5", lambda s: s["pre_buy_sol"] >= 5),
        ("net_flow>=3", lambda s: s["pre_net_flow_sol"] >= 3),
        ("last60_trades>=5", lambda s: s["last60_trade_count"] >= 5),
        ("last60_sol>=2", lambda s: s["last60_sol"] >= 2),
        ("last_trade_gap<=10", lambda s: s["last_trade_gap_s"] <= 10),
        ("buy_ratio>=0.55", lambda s: (s["pre_buy_ratio"] or 0) >= 0.55),
    ]
    coverage = {name: coverage_row(samples, fn) for name, fn in rules}

    combos: list[tuple[str, Callable[[dict[str, Any]], bool]]] = [
        (
            "loose: buyers>=10 & buy_sol>=5 & last60_trades>=5",
            lambda s: s["pre_unique_buyers"] >= 10 and s["pre_buy_sol"] >= 5 and s["last60_trade_count"] >= 5,
        ),
        (
            "main: age<=180 & buyers>=10 & buy_sol>=5 & last60_trades>=5",
            lambda s: s["age_s"] <= 180
            and s["pre_unique_buyers"] >= 10
            and s["pre_buy_sol"] >= 5
            and s["last60_trade_count"] >= 5,
        ),
        (
            "strict: age<=120 & trades>=15 & buyers>=10 & buy_sol>=5 & last60_sol>=2",
            lambda s: s["age_s"] <= 120
            and s["pre_trade_count"] >= 15
            and s["pre_unique_buyers"] >= 10
            and s["pre_buy_sol"] >= 5
            and s["last60_sol"] >= 2,
        ),
    ]
    combo_coverage = {name: coverage_row(samples, fn, include_roi=True) for name, fn in combos}

    return {
        "sample_count": len(samples),
        "generated_at_utc": utc(int(datetime.now(tz=timezone.utc).timestamp())),
        "min_effective_sol": min_effective_sol,
        "stats": stats,
        "coverage": coverage,
        "combo_coverage": combo_coverage,
    }


def summarize_exit_samples(samples: list[dict[str, Any]], min_effective_sol: float) -> dict[str, Any]:
    numeric_fields = [
        "exit_sol",
        "hold_s",
        "age_s",
        "pre_trade_count",
        "pre_sell_ratio",
        "pre_net_flow_sol",
        "position_net_flow_sol",
        "last_trade_gap_s",
        "last30_trade_count",
        "last30_sell_ratio",
        "last30_net_flow_sol",
        "last60_trade_count",
        "last60_sell_ratio",
        "last60_net_flow_sol",
        "price_return_since_entry",
        "drawdown_from_high",
        "near_high",
        "seconds_from_high",
        "wallet_realized_roi_until_exit",
        "exit_sold_token_ratio",
    ]
    stats = {field: describe([sample.get(field) for sample in samples]) for field in numeric_fields}

    rules: list[tuple[str, Callable[[dict[str, Any]], bool]]] = [
        ("hold<=60", lambda s: s["hold_s"] <= 60),
        ("hold<=300", lambda s: s["hold_s"] <= 300),
        ("roi>=0", lambda s: (s["wallet_realized_roi_until_exit"] or -999) >= 0),
        ("roi>=20%", lambda s: (s["wallet_realized_roi_until_exit"] or -999) >= 0.2),
        ("near_high>=0.8", lambda s: (s["near_high"] or 0) >= 0.8),
        ("drawdown<=-10%", lambda s: (s["drawdown_from_high"] or 0) <= -0.1),
        ("last60_sell_ratio>=30%", lambda s: (s["last60_sell_ratio"] or 0) >= 0.3),
        ("last60_net_flow<=0", lambda s: s["last60_net_flow_sol"] <= 0),
        ("last_trade_gap<=10", lambda s: s["last_trade_gap_s"] <= 10),
        ("sold_tokens>=90%", lambda s: (s["exit_sold_token_ratio"] or 0) >= 0.9),
        ("full_exit", lambda s: bool(s["is_full_exit"])),
    ]
    coverage = {name: coverage_row(samples, fn) for name, fn in rules}

    combos: list[tuple[str, Callable[[dict[str, Any]], bool]]] = [
        (
            "fast_clear: hold<=300 & sold_tokens>=90%",
            lambda s: s["hold_s"] <= 300 and (s["exit_sold_token_ratio"] or 0) >= 0.9,
        ),
        (
            "profit_clear: roi>=0 & near_high>=0.8 & sold_tokens>=90%",
            lambda s: (s["wallet_realized_roi_until_exit"] or -999) >= 0
            and (s["near_high"] or 0) >= 0.8
            and (s["exit_sold_token_ratio"] or 0) >= 0.9,
        ),
        (
            "pressure_clear: last60_sell_ratio>=30% & last60_net_flow<=0 & sold_tokens>=90%",
            lambda s: (s["last60_sell_ratio"] or 0) >= 0.3
            and s["last60_net_flow_sol"] <= 0
            and (s["exit_sold_token_ratio"] or 0) >= 0.9,
        ),
    ]
    combo_coverage = {name: coverage_row(samples, fn, include_roi=True) for name, fn in combos}

    return {
        "sample_count": len(samples),
        "generated_at_utc": utc(int(datetime.now(tz=timezone.utc).timestamp())),
        "min_effective_sol": min_effective_sol,
        "stats": stats,
        "coverage": coverage,
        "combo_coverage": combo_coverage,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_report(path: Path, wallet: str, samples: list[dict[str, Any]], summary: dict[str, Any], min_effective_sol: float) -> None:
    stats = summary["stats"]
    coverage = summary["coverage"]
    combos = summary["combo_coverage"]
    lines = [
        f"# 钱包开仓条件逆向分析",
        "",
        f"- 钱包：`{wallet}`",
        f"- 样本：`{len(samples)}` 个 mint 的首次 `pump_buy`",
        f"- 有效市场交易过滤：可推断买卖方向，且 fee payer SOL 变化 `>= {min_effective_sol}`",
        "",
        "## 关键画像",
        "",
        f"- 开仓金额中位数：`{fmt(stats['entry_sol']['p50'])} SOL`",
        f"- 买入前币龄中位数：`{fmt(stats['age_s']['p50'])} 秒`",
        f"- 买入前独立买家中位数：`{fmt(stats['pre_unique_buyers']['p50'])}`",
        f"- 买入前累计买入 SOL 中位数：`{fmt(stats['pre_buy_sol']['p50'])} SOL`",
        f"- 最近 60 秒交易数中位数：`{fmt(stats['last60_trade_count']['p50'])}`",
        f"- 最近 60 秒成交额中位数：`{fmt(stats['last60_sol']['p50'])} SOL`",
        f"- 买盘占比中位数：`{fmt(stats['pre_buy_ratio']['p50'])}`",
        "",
        "## 单条件覆盖",
        "",
    ]
    for name, row in coverage.items():
        lines.append(f"- `{name}`：`{row['hit']}/{row['total']}`，`{fmt(row['rate'] * 100)}%`")

    lines.extend(["", "## 组合规则覆盖", ""])
    for name, row in combos.items():
        lines.append(
            f"- `{name}`：`{row['hit']}/{row['total']}`，`{fmt(row['rate'] * 100)}%`，"
            f"命中样本 ROI 中位数 `{fmt(row.get('median_roi'))}`，正收益 `{row.get('positive_roi')}/{row.get('roi_count')}`"
        )

    lines.extend(
        [
            "",
            "## 推荐复刻规则",
            "",
            "```text",
            "候选池：Pump 新 mint",
            "",
            "硬条件：",
            "1. mint 创建/首笔市场交易后 <= 180 秒",
            "2. 买入前有效市场交易 >= 15 笔",
            "3. 买入前独立买家 >= 10",
            "4. 买入前累计买入 SOL >= 5",
            "5. 最近 60 秒有效交易 >= 5",
            "6. 最近 60 秒成交 SOL >= 2",
            "7. 买盘占比 >= 55%",
            "8. 最近一笔有效交易距离当前 <= 10 秒",
            "",
            "执行：默认 0.5 SOL 开仓；极早期轻仓样本可用 0.1 SOL。",
            "```",
            "",
            "## 注意",
            "",
            "当前数据只有目标钱包买过的币，没有完整负样本，因此这些规则是行为画像/高覆盖条件，不是充分盈利条件。",
            "若要筛掉假阳性，需要补同时间段未买入的新币作为负样本。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_exit_report(path: Path, wallet: str, samples: list[dict[str, Any]], summary: dict[str, Any], min_effective_sol: float) -> None:
    stats = summary["stats"]
    coverage = summary["coverage"]
    combos = summary["combo_coverage"]
    lines = [
        "# 钱包清仓条件逆向分析",
        "",
        f"- 钱包：`{wallet}`",
        f"- 样本：`{len(samples)}` 个发生过 `pump_sell` 的 mint，锚点为该 mint 最后一笔 `pump_sell`",
        f"- 有效市场交易过滤：可推断买卖方向，且 fee payer SOL 变化 `>= {min_effective_sol}`",
        "",
        "## 关键画像",
        "",
        f"- 清仓/最后卖出金额中位数：`{fmt(stats['exit_sol']['p50'])} SOL`",
        f"- 首次买入到最后卖出持仓时长中位数：`{fmt(stats['hold_s']['p50'])} 秒`",
        f"- 最后卖出前累计市场净流入中位数：`{fmt(stats['position_net_flow_sol']['p50'])} SOL`",
        f"- 最近 60 秒卖盘占比中位数：`{fmt(stats['last60_sell_ratio']['p50'])}`",
        f"- 最近 60 秒净流入中位数：`{fmt(stats['last60_net_flow_sol']['p50'])} SOL`",
        f"- 相对持仓期高点回撤中位数：`{fmt(stats['drawdown_from_high']['p50'])}`",
        f"- 接近高点比例中位数：`{fmt(stats['near_high']['p50'])}`",
        f"- 清仓时已实现 ROI 中位数：`{fmt(stats['wallet_realized_roi_until_exit']['p50'])}`",
        f"- 单次卖出占卖前持仓 token 比例中位数：`{fmt(stats['exit_sold_token_ratio']['p50'])}`",
        "",
        "## 单条件覆盖",
        "",
    ]
    for name, row in coverage.items():
        lines.append(f"- `{name}`：`{row['hit']}/{row['total']}`，`{fmt(row['rate'] * 100)}%`")

    lines.extend(["", "## 组合规则覆盖", ""])
    for name, row in combos.items():
        lines.append(
            f"- `{name}`：`{row['hit']}/{row['total']}`，`{fmt(row['rate'] * 100)}%`，"
            f"命中样本 ROI 中位数 `{fmt(row.get('median_roi'))}`，正收益 `{row.get('positive_roi')}/{row.get('roi_count')}`"
        )

    lines.extend(
        [
            "",
            "## 推荐复刻规则",
            "",
            "```text",
            "触发对象：已经按开仓规则持有的 Pump mint",
            "",
            "优先清仓条件：",
            "1. 单币持仓时间 <= 300 秒时，若已盈利且价格仍在持仓期高点的 80% 以上，倾向一次性卖出 90%+ token。",
            "2. 最近 60 秒卖盘占比 >= 30%，且最近 60 秒净流入 <= 0 SOL，视为动能转弱，倾向清仓。",
            "3. 距离上一笔有效市场交易 <= 10 秒，说明退出发生在市场仍活跃时，不等待完全冷却。",
            "",
            "执行：默认卖出全部或 90%+ 仓位；若需要复刻原钱包风格，优先用最后一笔 pump_sell 作为全清锚点。",
            "```",
            "",
            "## 注意",
            "",
            "当前清仓分析仍是正样本画像：只观察目标钱包卖出的时刻，没有观察它选择继续持有的全部中间时刻。",
            "要把画像变成可回测规则，需要在持仓期间按秒或按交易重放市场状态，构造“未卖出”的负样本。",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def infer_side(token_delta: float, native_delta: float) -> str:
    if token_delta > 1e-9 and native_delta < 0:
        return "buy"
    if token_delta < -1e-9 and native_delta > 0:
        return "sell"
    return ""


def describe(values: list[Any]) -> dict[str, Any]:
    clean = sorted(value for value in values if isinstance(value, (int, float)) and not isinstance(value, bool) and not math.isnan(value))
    if not clean:
        return {"n": 0}
    return {
        "n": len(clean),
        "min": clean[0],
        "p10": percentile(clean, 10),
        "p25": percentile(clean, 25),
        "p50": percentile(clean, 50),
        "p75": percentile(clean, 75),
        "p90": percentile(clean, 90),
        "max": clean[-1],
    }


def percentile(sorted_values: list[float], p: float) -> float:
    k = (len(sorted_values) - 1) * p / 100
    low = math.floor(k)
    high = math.ceil(k)
    if low == high:
        return sorted_values[low]
    return sorted_values[low] * (high - k) + sorted_values[high] * (k - low)


def coverage_row(samples: list[dict[str, Any]], predicate: Callable[[dict[str, Any]], bool], *, include_roi: bool = False) -> dict[str, Any]:
    hits = [sample for sample in samples if predicate(sample)]
    row: dict[str, Any] = {"hit": len(hits), "total": len(samples), "rate": safe_div(len(hits), len(samples)) or 0}
    if include_roi:
        rois = []
        for sample in hits:
            roi = sample.get("wallet_position_roi")
            if roi is None:
                roi = sample.get("wallet_realized_roi_until_exit")
            if roi is not None:
                rois.append(roi)
        row["roi_count"] = len(rois)
        row["median_roi"] = percentile(sorted(rois), 50) if rois else None
        row["positive_roi"] = sum(1 for roi in rois if roi > 0)
    return row


def parse_json_list(value: str | None) -> list[Any]:
    if not value:
        return []
    parsed = json.loads(value)
    return parsed if isinstance(parsed, list) else []


def float_or_zero(value: Any) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def int_or_none(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def safe_div(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def utc(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def fmt(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


if __name__ == "__main__":
    main()
