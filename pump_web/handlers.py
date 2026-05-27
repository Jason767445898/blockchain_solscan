from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout

import gradio as gr


def _capture_output(fn, **kwargs) -> str:
    """Run a synchronous function and capture all stdout/stderr output."""
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        try:
            fn(**kwargs)
        except SystemExit as e:
            if e.code and e.code != 0:
                print(f"[错误] 进程退出，代码 {e.code}")
        except Exception as e:
            print(f"[错误] {e}")
    output = buf.getvalue()
    return output if output.strip() else "（无输出）"


def do_scan(wallet: str, rpc_url: str, data_dir: str, limit: int, refresh_seen: bool, verbose: bool) -> str:
    """Run wallet transaction scan."""
    from pump_monitor.monitor import cli_scan

    return _capture_output(
        cli_scan,
        rpc_url=rpc_url,
        wallet=wallet,
        limit=limit,
        verbose=verbose,
        refresh_seen=refresh_seen,
        pump_program_ids=None,
        data_dir=data_dir,
    )


def do_dedupe(wallet: str, data_dir: str) -> str:
    """Deduplicate wallet output by signature."""
    from pump_monitor.monitor import cli_dedupe

    return _capture_output(cli_dedupe, wallet=wallet, data_dir=data_dir)


def do_tokens(wallet: str, data_dir: str) -> str:
    """Summarize meme tokens for the wallet."""
    from pump_monitor.monitor import cli_tokens

    return _capture_output(cli_tokens, wallet=wallet, data_dir=data_dir)


def do_market(wallet: str, data_dir: str, helius_api_key: str) -> str:
    """Fetch market trades via Helius enhanced API."""
    from pump_monitor.monitor import cli_market

    return _capture_output(
        cli_market,
        wallet=wallet,
        data_dir=data_dir,
        helius_api_key=helius_api_key,
        market_dir=None,
    )


def do_inspect(rpc_url: str, signature: str, verbose: bool) -> str:
    """Inspect a single transaction signature."""
    from pump_monitor.monitor import cli_inspect

    return _capture_output(
        cli_inspect,
        rpc_url=rpc_url,
        signature=signature.strip(),
        pump_program_ids=None,
        verbose=verbose,
    )


def do_analyze(wallet: str, data_dir: str, min_effective_sol: float = 0.005) -> str:
    """Generate entry/exit behavior analysis reports."""
    from pump_analyst.analyze import main as analyze_main

    argv = [
        "--wallet",
        wallet,
        "--data-dir",
        data_dir,
        "--min-effective-sol",
        str(min_effective_sol),
    ]
    return _capture_output(analyze_main, argv=argv)


def do_pipeline(
    wallet: str,
    rpc_url: str,
    helius_api_key: str,
    data_dir: str,
    limit: int,
    refresh_seen: bool,
    verbose: bool,
    skip_scan: bool,
    skip_market: bool,
    min_effective_sol: float,
    progress: gr.Progress = gr.Progress(),
) -> str:
    """Run the complete pipeline: scan → dedupe → tokens → market → analyze."""
    results: list[str] = []

    if not skip_scan:
        progress(0.15, desc="步骤 1/5：正在扫描钱包交易...")
        results.append(f"=== SCAN ===\n{do_scan(wallet, rpc_url, data_dir, limit, refresh_seen, verbose)}")

    progress(0.30, desc="步骤 2/5：正在去重...")
    results.append(f"=== DEDUPE ===\n{do_dedupe(wallet, data_dir)}")

    progress(0.45, desc="步骤 3/5：正在汇总 Meme 代币...")
    results.append(f"=== TOKENS ===\n{do_tokens(wallet, data_dir)}")

    if not skip_market and helius_api_key:
        progress(0.65, desc="步骤 4/5：正在获取市场交易（可能需要一段时间）...")
        results.append(f"=== MARKET ===\n{do_market(wallet, data_dir, helius_api_key)}")
    elif not skip_market:
        results.append("=== MARKET ===\n（已跳过 — 未提供 Helius API 密钥）")

    progress(0.85, desc="步骤 5/5：正在生成分析报告...")
    results.append(f"=== ANALYZE ===\n{do_analyze(wallet, data_dir, min_effective_sol)}")

    progress(1.0, desc="流水线完成！")
    return "\n\n".join(results)
