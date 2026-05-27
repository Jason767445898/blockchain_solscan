from __future__ import annotations

import csv
import io
import os
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

import gradio as gr
import pandas as pd

# --- Constants ---
DEFAULT_WALLET = os.getenv("SOLSCAN_WALLET", "55PB376nxsrBLTZr1UdQSk6M89AxPif6oKmbmZmWq5dr")
DEFAULT_RPC = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
DEFAULT_DATA_DIR = os.getenv("SOLSCAN_OUTPUT_DIR", "data")
DEFAULT_WEBUI_PORT = int(os.getenv("PUMP_WEBUI_PORT", "7862"))
SCREENER_TABLE_TYPES = [
    "bool",
    "str",
    "number",
    "str",
    "number",
    "number",
    "number",
    "number",
    "number",
    "number",
    "number",
    "number",
]


# --- Output Capture ---


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


# --- Individual Command Handlers ---


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


# --- Realtime Screener Helpers ---


def _build_screener(
    helius_api_key: str,
    data_dir: str,
    min_effective_sol: float,
    max_age_s: int,
    min_trade_count: int,
    min_unique_buyers: int,
    min_buy_sol: float,
    min_last60_trade_count: int,
    min_last60_sol: float,
    min_buy_ratio: float,
    max_last_trade_gap_s: int,
    discovery_limit: int,
    market_limit: int,
    max_candidates: int,
    telegram_bot_token: str,
    telegram_chat_id: str,
    retention_hours: float,
) -> Any:
    from pump_monitor.screener import EntryRule, RealtimeScreener, ScreenerConfig

    rule = EntryRule(
        max_age_s=int(max_age_s),
        min_trade_count=int(min_trade_count),
        min_unique_buyers=int(min_unique_buyers),
        min_buy_sol=float(min_buy_sol),
        min_last60_trade_count=int(min_last60_trade_count),
        min_last60_sol=float(min_last60_sol),
        min_buy_ratio=float(min_buy_ratio),
        max_last_trade_gap_s=int(max_last_trade_gap_s),
        min_effective_sol=float(min_effective_sol),
    )
    config = ScreenerConfig(
        helius_api_key=(helius_api_key or "").strip(),
        data_dir=data_dir,
        discovery_limit=int(discovery_limit),
        market_limit=int(market_limit),
        max_candidates=int(max_candidates),
        candidate_max_age_s=max(int(max_age_s) + 60, 240),
        rule=rule,
        telegram_bot_token=(telegram_bot_token or "").strip(),
        telegram_chat_id=(telegram_chat_id or "").strip(),
        alert_retention_hours=retention_hours,
    )
    return RealtimeScreener(config)


def _screener_settings_key(
    helius_api_key: str,
    data_dir: str,
    min_effective_sol: float,
    max_age_s: int,
    min_trade_count: int,
    min_unique_buyers: int,
    min_buy_sol: float,
    min_last60_trade_count: int,
    min_last60_sol: float,
    min_buy_ratio: float,
    max_last_trade_gap_s: int,
    discovery_limit: int,
    market_limit: int,
    max_candidates: int,
    telegram_bot_token: str,
    telegram_chat_id: str,
) -> tuple[Any, ...]:
    return (
        (helius_api_key or "").strip(),
        data_dir,
        float(min_effective_sol),
        int(max_age_s),
        int(min_trade_count),
        int(min_unique_buyers),
        float(min_buy_sol),
        int(min_last60_trade_count),
        float(min_last60_sol),
        float(min_buy_ratio),
        int(max_last_trade_gap_s),
        int(discovery_limit),
        int(market_limit),
        int(max_candidates),
        bool((telegram_bot_token or "").strip()),
        (telegram_chat_id or "").strip(),
    )


def run_screener_once(
    helius_api_key: str,
    data_dir: str,
    min_effective_sol: float,
    max_age_s: int,
    min_trade_count: int,
    min_unique_buyers: int,
    min_buy_sol: float,
    min_last60_trade_count: int,
    min_last60_sol: float,
    min_buy_ratio: float,
    max_last_trade_gap_s: int,
    discovery_limit: int,
    market_limit: int,
    max_candidates: int,
    telegram_bot_token: str,
    telegram_chat_id: str,
    retention_hours: float,
    screener_state: Any,
) -> tuple[list[list[Any]], list[list[Any]], str, Any]:
    from pump_monitor.screener import load_alert_rows, rows_for_table, summarize_poll

    if not (helius_api_key or "").strip():
        return (
            [],
            rows_for_table(load_alert_rows(data_dir, retention_hours=retention_hours)),
            "需要 Helius API 密钥。",
            screener_state,
        )

    settings_key = _screener_settings_key(
        helius_api_key,
        data_dir,
        min_effective_sol,
        max_age_s,
        min_trade_count,
        min_unique_buyers,
        min_buy_sol,
        min_last60_trade_count,
        min_last60_sol,
        min_buy_ratio,
        max_last_trade_gap_s,
        discovery_limit,
        market_limit,
        max_candidates,
        telegram_bot_token,
        telegram_chat_id,
    )
    if screener_state is None or getattr(screener_state, "_webui_settings_key", None) != settings_key:
        screener_state = _build_screener(
            helius_api_key,
            data_dir,
            min_effective_sol,
            max_age_s,
            min_trade_count,
            min_unique_buyers,
            min_buy_sol,
            min_last60_trade_count,
            min_last60_sol,
            min_buy_ratio,
            max_last_trade_gap_s,
            discovery_limit,
            market_limit,
            max_candidates,
            telegram_bot_token,
            telegram_chat_id,
            retention_hours,
        )
        screener_state._webui_settings_key = settings_key

    try:
        result = screener_state.poll_once()
    except Exception as exc:
        return (
            [],
            rows_for_table(load_alert_rows(data_dir, retention_hours=retention_hours)),
            f"[错误] {exc}",
            screener_state,
        )

    return (
        rows_for_table(result["rows"]),
        rows_for_table(load_alert_rows(data_dir, retention_hours=retention_hours)),
        summarize_poll(result),
        screener_state,
    )


def run_screener_loop(
    helius_api_key: str,
    data_dir: str,
    min_effective_sol: float,
    max_age_s: int,
    min_trade_count: int,
    min_unique_buyers: int,
    min_buy_sol: float,
    min_last60_trade_count: int,
    min_last60_sol: float,
    min_buy_ratio: float,
    max_last_trade_gap_s: int,
    discovery_limit: int,
    market_limit: int,
    max_candidates: int,
    telegram_bot_token: str,
    telegram_chat_id: str,
    retention_hours: float,
    poll_seconds: int,
    cycles: int,
    screener_state: Any,
    progress: gr.Progress = gr.Progress(),
) -> tuple[list[list[Any]], list[list[Any]], str, Any]:
    latest_candidates: list[list[Any]] = []
    latest_alerts: list[list[Any]] = []
    latest_status = ""
    for index in range(max(1, int(cycles))):
        progress((index + 1) / max(1, int(cycles)), desc=f"轮询 {index + 1}/{int(cycles)}")
        latest_candidates, latest_alerts, latest_status, screener_state = run_screener_once(
            helius_api_key,
            data_dir,
            min_effective_sol,
            max_age_s,
            min_trade_count,
            min_unique_buyers,
            min_buy_sol,
            min_last60_trade_count,
            min_last60_sol,
            min_buy_ratio,
            max_last_trade_gap_s,
            discovery_limit,
            market_limit,
            max_candidates,
            telegram_bot_token,
            telegram_chat_id,
            retention_hours,
            screener_state,
        )
        if index < int(cycles) - 1:
            time.sleep(max(1, int(poll_seconds)))
    return latest_candidates, latest_alerts, latest_status, screener_state


def reset_screener_state(data_dir: str, retention_hours: float) -> tuple[list[list[Any]], list[list[Any]], str, None]:
    from pump_monitor.screener import load_alert_rows, rows_for_table

    return (
        [],
        rows_for_table(load_alert_rows(data_dir, retention_hours=retention_hours)),
        "实时筛选器状态已重置。",
        None,
    )


def on_alert_row_select(table_data: list[list[Any]], evt: gr.SelectData) -> str:
    """Populate mint copy textbox when user selects a row in the alert table."""
    # Gradio passes gr.Dataframe values as pandas DataFrames; convert to list[list] for consistent indexing
    if isinstance(table_data, pd.DataFrame):
        table_data = table_data.values.tolist()
    if not table_data or evt.index is None:
        return ""
    row_idx = evt.index[0]
    if not isinstance(row_idx, int) or row_idx < 0 or row_idx >= len(table_data):
        return ""
    row = table_data[row_idx]
    if len(row) < 4:
        return ""
    return str(row[3]) if row[3] else ""


def save_alert_read_status(table_data: list[list[Any]], data_dir: str) -> str:
    """Persist read/unread status from alert table checkboxes to read_mints.json."""
    from pump_monitor.screener import load_read_status, save_read_status

    # Gradio passes gr.Dataframe values as pandas DataFrames; convert to list[list] for consistent iteration
    if isinstance(table_data, pd.DataFrame):
        table_data = table_data.values.tolist()
    if not table_data:
        return "无数据可保存。"
    existing = load_read_status(data_dir)
    updated = 0
    for row in table_data:
        if not row or len(row) < 4:
            continue
        mint = str(row[3]) if row[3] else ""
        if not mint:
            continue
        is_read = bool(row[0]) if row else False
        if existing.get(mint) != is_read:
            existing[mint] = is_read
            updated += 1
    save_read_status(data_dir, existing)
    return f"已保存 {updated} 条已读状态变更。"


# --- Results Tab Helpers ---


def _list_output_files(wallet: str, data_dir: str) -> list[str]:
    """Return sorted list of output file paths for a wallet."""
    files: list[str] = []
    base = Path(data_dir)
    result_base = Path("pump_analyst/results") / wallet

    # Main data files
    for suffix in [".jsonl", ".csv", ".meme_tokens.csv"]:
        p = base / f"{wallet}{suffix}"
        if p.exists():
            files.append(str(p))

    # Market trades directory
    market_dir = base / f"{wallet}.market_trades"
    if market_dir.exists():
        for f in sorted(market_dir.iterdir()):
            if f.is_file():
                files.append(str(f))

    # Analysis results
    if result_base.exists():
        for f in sorted(result_base.iterdir()):
            if f.is_file():
                files.append(str(f))

    return files


def _read_file_content(file_path: str | None) -> tuple[list[list[str]], str, str]:
    """Read a file and return (csv_rows, markdown_text, raw_text)."""
    if not file_path:
        return [], "*未选择文件。*", ""

    path = Path(file_path)
    if not path.exists():
        return [], f"*文件未找到：`{file_path}`*", ""

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        return [], f"*读取文件出错：{e}*", ""

    suffix = path.suffix.lower()

    if suffix == ".csv":
        try:
            reader = csv.reader(io.StringIO(text))
            rows = list(reader)
            return rows, "", text
        except Exception:
            return [], "", text

    if suffix == ".md":
        return [], text, text

    # .jsonl or other — show as raw text only
    return [], "", text


def refresh_file_list(wallet: str, data_dir: str) -> gr.Dropdown:
    """Callback: repopulate the file dropdown with current output files."""
    files = _list_output_files(wallet, data_dir)
    return gr.Dropdown(choices=files, value=files[0] if files else None)


def update_file_view(file_path: str | None) -> tuple[list[list[str]], str, str]:
    """Callback: update table/markdown/raw views when a file is selected."""
    return _read_file_content(file_path)


# --- UI Construction ---


_UI_CSS = """
.output-log textarea {
    font-family: 'Menlo', 'Consolas', 'SF Mono', monospace;
    font-size: 12px;
    line-height: 1.4;
}
footer { display: none !important; }
"""
_UI_THEME = gr.themes.Soft(
    primary_hue="blue",
    secondary_hue="slate",
)


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Pump 钱包工具") as demo:
        # --- Header ---
        gr.Markdown(
            """# 🚀 Pump 钱包工具

            监控 Solana 钱包的 **Pump.fun / PumpSwap** Meme 代币活动。
            扫描交易 → 获取市场交易 → 生成开仓/平仓行为分析报告。
            """
        )

        # --- Settings Panel ---
        with gr.Accordion("⚙️ 设置", open=True):
            with gr.Row():
                wallet_input = gr.Textbox(
                    label="钱包地址",
                    value=DEFAULT_WALLET,
                    placeholder="Solana 钱包地址（base58）",
                    scale=3,
                )
                data_dir_input = gr.Textbox(
                    label="数据目录",
                    value=DEFAULT_DATA_DIR,
                    scale=1,
                )
            with gr.Row():
                rpc_input = gr.Textbox(
                    label="RPC 地址",
                    value=DEFAULT_RPC,
                    placeholder="https://api.mainnet-beta.solana.com",
                    scale=2,
                )
                helius_key_input = gr.Textbox(
                    label="Helius API 密钥",
                    type="password",
                    placeholder="获取市场交易时需要",
                    value="",
                    scale=1,
                )

        # --- Main Tabs ---
        with gr.Tabs():
            # ============================
            # Realtime Screener Tab
            # ============================
            with gr.TabItem("⏰实时筛选器"):
                gr.Markdown("使用报告中的入场画像对新 Pump 代币进行可视化实时筛选。")
                screener_state = gr.State(value=None)

                with gr.Row():
                    with gr.Column(scale=1):
                        with gr.Group():
                            min_effective_sol_rt = gr.Number(
                                label="最小有效 SOL",
                                value=0.005,
                                minimum=0.0,
                                step=0.001,
                            )
                            max_age_rt = gr.Number(label="最大存活秒数", value=180, minimum=1, precision=0)
                            min_trades_rt = gr.Number(label="最小交易数", value=15, minimum=0, precision=0)
                            min_buyers_rt = gr.Number(label="最小独立买家数", value=10, minimum=0, precision=0)
                            min_buy_sol_rt = gr.Number(label="最小买入 SOL", value=5.0, minimum=0.0, step=0.1)
                            min_last60_trades_rt = gr.Number(
                                label="最近 60 秒最小交易数",
                                value=5,
                                minimum=0,
                                precision=0,
                            )
                            min_last60_sol_rt = gr.Number(
                                label="最近 60 秒最小 SOL",
                                value=2.0,
                                minimum=0.0,
                                step=0.1,
                            )
                            min_buy_ratio_rt = gr.Slider(
                                label="最小买入比例",
                                value=0.55,
                                minimum=0.0,
                                maximum=1.0,
                                step=0.01,
                            )
                            max_gap_rt = gr.Number(label="最后交易最大间隔秒数", value=10, minimum=0, precision=0)
                        with gr.Group():
                            discovery_limit_rt = gr.Number(
                                label="发现页面限制",
                                value=30,
                                minimum=1,
                                maximum=100,
                                precision=0,
                            )
                            market_limit_rt = gr.Number(
                                label="市场页面限制",
                                value=100,
                                minimum=1,
                                maximum=100,
                                precision=0,
                            )
                            max_candidates_rt = gr.Number(
                                label="最多显示候选数",
                                value=20,
                                minimum=1,
                                maximum=100,
                                precision=0,
                            )
                            poll_seconds_rt = gr.Number(label="轮询间隔秒数", value=8, minimum=1, precision=0)
                            cycles_rt = gr.Number(label="循环次数", value=5, minimum=1, maximum=100, precision=0)
                            retention_hours_rt = gr.Number(label="告警保留小时数", value=24, minimum=1, precision=0)
                        with gr.Accordion("Telegram 通知", open=False):
                            telegram_token_rt = gr.Textbox(
                                label="机器人 Token",
                                type="password",
                                placeholder="可选",
                                value="",
                            )
                            telegram_chat_rt = gr.Textbox(
                                label="聊天 ID",
                                placeholder="可选",
                                value="",
                            )
                        with gr.Row():
                            run_screener_once_btn = gr.Button("单次轮询", variant="primary")
                            run_screener_loop_btn = gr.Button("循环运行")
                            reset_screener_btn = gr.Button("重置")

                    with gr.Column(scale=3):
                        screener_status = gr.Textbox(
                            label="状态",
                            lines=6,
                            max_lines=12,
                            elem_classes="output-log",
                        )
                        candidate_table = gr.Dataframe(
                            label="实时候选",
                            headers=[
                                "匹配",
                                "分数",
                                "代币",
                                "存活秒数",
                                "交易数",
                                "买家数",
                                "买入 SOL",
                                "近60秒交易",
                                "近60秒SOL",
                                "买入比例",
                                "间隔秒数",
                            ],
                            datatype=SCREENER_TABLE_TYPES,
                            row_count=(12, "dynamic"),
                            wrap=True,
                        )
                        alert_table = gr.Dataframe(
                            label="命中提醒",
                            headers=[
                                "已读",
                                "匹配",
                                "分数",
                                "代币",
                                "存活秒数",
                                "交易数",
                                "买家数",
                                "买入 SOL",
                                "近60秒交易",
                                "近60秒SOL",
                                "买入比例",
                                "间隔秒数",
                            ],
                            datatype=SCREENER_TABLE_TYPES,
                            row_count=(8, "dynamic"),
                            wrap=True,
                            interactive=True,
                        )

                        with gr.Row():
                            mint_copy_box = gr.Textbox(label="代币地址", elem_id="mint-copy-textbox", scale=3)
                            copy_btn = gr.Button("📋 复制", scale=1)
                        save_read_btn = gr.Button("保存已读状态", variant="secondary")
                        save_status = gr.Textbox(visible=False)

                screener_inputs = [
                    helius_key_input,
                    data_dir_input,
                    min_effective_sol_rt,
                    max_age_rt,
                    min_trades_rt,
                    min_buyers_rt,
                    min_buy_sol_rt,
                    min_last60_trades_rt,
                    min_last60_sol_rt,
                    min_buy_ratio_rt,
                    max_gap_rt,
                    discovery_limit_rt,
                    market_limit_rt,
                    max_candidates_rt,
                    telegram_token_rt,
                    telegram_chat_rt,
                    retention_hours_rt,
                ]
                run_screener_once_btn.click(
                    fn=run_screener_once,
                    inputs=[*screener_inputs, screener_state],
                    outputs=[candidate_table, alert_table, screener_status, screener_state],
                )
                run_screener_loop_btn.click(
                    fn=run_screener_loop,
                    inputs=[*screener_inputs, poll_seconds_rt, cycles_rt, screener_state],
                    outputs=[candidate_table, alert_table, screener_status, screener_state],
                )
                reset_screener_btn.click(
                    fn=reset_screener_state,
                    inputs=[data_dir_input, retention_hours_rt],
                    outputs=[candidate_table, alert_table, screener_status, screener_state],
                )
                alert_table.select(fn=on_alert_row_select, inputs=[alert_table], outputs=[mint_copy_box])
                save_read_btn.click(
                    fn=save_alert_read_status,
                    inputs=[alert_table, data_dir_input],
                    outputs=[save_status],
                )
                copy_btn.click(
                    fn=None,
                    inputs=None,
                    outputs=None,
                    js=(
                        "() => {"
                        " const el = document.querySelector('#mint-copy-textbox textarea');"
                        " if (el) { navigator.clipboard.writeText(el.value); }"
                        " }"
                    ),
                )

            # ============================
            # Pipeline Tab
            # ============================
            with gr.TabItem("🚀 流水线"):
                gr.Markdown("运行完整流水线：**扫描 → 去重 → 代币汇总 → 市场交易 → 分析报告**。")
                with gr.Row():
                    with gr.Column(scale=1):
                        with gr.Group():
                            limit_pl = gr.Number(
                                label="交易数量限制",
                                value=100,
                                minimum=1,
                                maximum=1000,
                                precision=0,
                            )
                            refresh_pl = gr.Checkbox(label="刷新已见签名", value=False)
                            verbose_pl = gr.Checkbox(label="详细输出", value=True)
                            skip_scan_pl = gr.Checkbox(
                                label="跳过扫描（使用已有本地数据）",
                                value=False,
                            )
                            skip_market_pl = gr.Checkbox(
                                label="跳过市场（使用已有市场数据）",
                                value=False,
                            )
                            min_sol_pl = gr.Number(
                                label="最小有效 SOL",
                                value=0.005,
                                minimum=0.0,
                                step=0.001,
                            )
                        run_pipeline_btn = gr.Button("▶ 运行流水线", variant="primary", size="lg")
                    with gr.Column(scale=2):
                        pipeline_output = gr.Textbox(
                            label="流水线日志",
                            lines=22,
                            max_lines=50,
                            elem_classes="output-log",
                            autoscroll=True,
                        )

                run_pipeline_btn.click(
                    fn=do_pipeline,
                    inputs=[
                        wallet_input,
                        rpc_input,
                        helius_key_input,
                        data_dir_input,
                        limit_pl,
                        refresh_pl,
                        verbose_pl,
                        skip_scan_pl,
                        skip_market_pl,
                        min_sol_pl,
                    ],
                    outputs=pipeline_output,
                )

            # ============================
            # Scan Tab
            # ============================
            with gr.TabItem("🔍 扫描"):
                gr.Markdown("获取钱包交易并分类 Pump.fun / PumpSwap 活动。")
                with gr.Row():
                    with gr.Column(scale=1):
                        with gr.Group():
                            limit_sc = gr.Number(
                                label="交易数量限制",
                                value=100,
                                minimum=1,
                                maximum=1000,
                                precision=0,
                            )
                            refresh_sc = gr.Checkbox(label="刷新已见签名", value=False)
                            verbose_sc = gr.Checkbox(label="详细输出", value=True)
                        run_scan_btn = gr.Button("▶ 运行扫描", variant="primary")
                    with gr.Column(scale=2):
                        scan_output = gr.Textbox(
                            label="扫描日志",
                            lines=18,
                            max_lines=40,
                            elem_classes="output-log",
                            autoscroll=True,
                        )

                run_scan_btn.click(
                    fn=do_scan,
                    inputs=[wallet_input, rpc_input, data_dir_input, limit_sc, refresh_sc, verbose_sc],
                    outputs=scan_output,
                )

            # ============================
            # Market Tab
            # ============================
            with gr.TabItem("📊 市场交易"):
                gr.Markdown("获取每个 Meme 代币的全市场 Helius 增强交易数据。需要在设置中提供有效的 Helius API 密钥。")
                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown(
                            """**注意：** 此步骤读取 `data/<钱包>.meme_tokens.csv`，
                            并获取每个代币在交易窗口内的所有市场交易。
                            根据代币数量，可能需要几分钟。"""
                        )
                        run_market_btn = gr.Button("▶ 获取市场交易", variant="primary")
                    with gr.Column(scale=2):
                        market_output = gr.Textbox(
                            label="市场日志",
                            lines=18,
                            max_lines=40,
                            elem_classes="output-log",
                            autoscroll=True,
                        )

                run_market_btn.click(
                    fn=do_market,
                    inputs=[wallet_input, data_dir_input, helius_key_input],
                    outputs=market_output,
                )

            # ============================
            # Inspect Tab
            # ============================
            with gr.TabItem("🔎 检查"):
                gr.Markdown("检查单笔交易并查看其 Pump 分类详情。")
                with gr.Row():
                    with gr.Column(scale=1):
                        sig_input = gr.Textbox(
                            label="交易签名",
                            placeholder="输入 Solana 交易签名（base58）...",
                            lines=2,
                        )
                        verbose_insp = gr.Checkbox(label="详细输出", value=True)
                        run_inspect_btn = gr.Button("▶ 检查", variant="primary")
                    with gr.Column(scale=2):
                        inspect_output = gr.Textbox(
                            label="检查结果",
                            lines=16,
                            max_lines=30,
                            elem_classes="output-log",
                        )

                run_inspect_btn.click(
                    fn=do_inspect,
                    inputs=[rpc_input, sig_input, verbose_insp],
                    outputs=inspect_output,
                )

            # ============================
            # Analyze Tab
            # ============================
            with gr.TabItem("📈 分析"):
                gr.Markdown("根据收集的数据生成开仓和平仓行为分析报告。")
                with gr.Row():
                    with gr.Column(scale=1):
                        with gr.Group():
                            min_sol_an = gr.Number(
                                label="最小有效 SOL",
                                value=0.005,
                                minimum=0.0,
                                step=0.001,
                                info="计算特征时忽略低于此 SOL 金额的交易。",
                            )
                        run_analyze_btn = gr.Button("▶ 生成分析", variant="primary")
                    with gr.Column(scale=2):
                        analyze_output = gr.Textbox(
                            label="分析日志",
                            lines=12,
                            max_lines=30,
                            elem_classes="output-log",
                            autoscroll=True,
                        )

                run_analyze_btn.click(
                    fn=do_analyze,
                    inputs=[wallet_input, data_dir_input, min_sol_an],
                    outputs=analyze_output,
                )

            # ============================
            # Results Tab
            # ============================
            with gr.TabItem("📁 结果"):
                gr.Markdown("浏览和查看生成的输出文件（CSV、JSONL、Markdown 报告）。")
                with gr.Row():
                    refresh_btn = gr.Button("🔄 刷新文件列表", scale=1)
                    file_dropdown = gr.Dropdown(
                        label="可用输出文件",
                        choices=[],
                        interactive=True,
                        allow_custom_value=True,
                        scale=3,
                    )

                refresh_btn.click(
                    fn=refresh_file_list,
                    inputs=[wallet_input, data_dir_input],
                    outputs=file_dropdown,
                )

                with gr.Tabs():
                    with gr.TabItem("📋 表格视图"):
                        csv_table = gr.Dataframe(
                            label="CSV 内容",
                            row_count=(30, "dynamic"),
                            wrap=True,
                        )
                    with gr.TabItem("📝 报告视图"):
                        md_view = gr.Markdown("*从上方下拉菜单中选择 `.md` 报告文件。*")
                    with gr.TabItem("📄 原始文本"):
                        raw_view = gr.Textbox(
                            label="原始文件内容",
                            lines=20,
                            max_lines=60,
                            elem_classes="output-log",
                        )

                file_dropdown.change(
                    fn=update_file_view,
                    inputs=file_dropdown,
                    outputs=[csv_table, md_view, raw_view],
                )

        # --- Footer ---
        gr.Markdown(
            """---
            *Pump 钱包工具 — 监控 | 分析 | 聪明交易*
            """
        )

    return demo


# --- Entry Point ---

demo = build_ui()

if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=DEFAULT_WEBUI_PORT,
        share=False,
        theme=_UI_THEME,
        css=_UI_CSS,
    )
