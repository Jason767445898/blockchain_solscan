from __future__ import annotations

import csv
import io
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import gradio as gr

# --- Constants ---
DEFAULT_WALLET = os.getenv("SOLSCAN_WALLET", "55PB376nxsrBLTZr1UdQSk6M89AxPif6oKmbmZmWq5dr")
DEFAULT_RPC = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
DEFAULT_DATA_DIR = os.getenv("SOLSCAN_OUTPUT_DIR", "data")


# --- Output Capture ---


def _capture_output(fn, **kwargs) -> str:
    """Run a synchronous function and capture all stdout/stderr output."""
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        try:
            fn(**kwargs)
        except SystemExit as e:
            if e.code and e.code != 0:
                print(f"[ERROR] Process exited with code {e.code}")
        except Exception as e:
            print(f"[ERROR] {e}")
    output = buf.getvalue()
    return output if output.strip() else "(no output)"


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
        "--wallet", wallet,
        "--data-dir", data_dir,
        "--min-effective-sol", str(min_effective_sol),
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
        progress(0.15, desc="Step 1/5: Scanning wallet transactions...")
        results.append(f"=== SCAN ===\n{do_scan(wallet, rpc_url, data_dir, limit, refresh_seen, verbose)}")

    progress(0.30, desc="Step 2/5: Deduplicating...")
    results.append(f"=== DEDUPE ===\n{do_dedupe(wallet, data_dir)}")

    progress(0.45, desc="Step 3/5: Summarizing meme tokens...")
    results.append(f"=== TOKENS ===\n{do_tokens(wallet, data_dir)}")

    if not skip_market and helius_api_key:
        progress(0.65, desc="Step 4/5: Fetching market trades (this may take a while)...")
        results.append(f"=== MARKET ===\n{do_market(wallet, data_dir, helius_api_key)}")
    elif not skip_market:
        results.append("=== MARKET ===\n(skipped — no Helius API key provided)")

    progress(0.85, desc="Step 5/5: Generating analysis reports...")
    results.append(f"=== ANALYZE ===\n{do_analyze(wallet, data_dir, min_effective_sol)}")

    progress(1.0, desc="Pipeline complete!")
    return "\n\n".join(results)


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
        return [], "*No file selected.*", ""

    path = Path(file_path)
    if not path.exists():
        return [], f"*File not found: `{file_path}`*", ""

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        return [], f"*Error reading file: {e}*", ""

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


def build_ui() -> gr.Blocks:
    css = """
    .output-log textarea {
        font-family: 'Menlo', 'Consolas', 'SF Mono', monospace;
        font-size: 12px;
        line-height: 1.4;
    }
    footer { display: none !important; }
    """
    theme = gr.themes.Soft(
        primary_hue="blue",
        secondary_hue="slate",
    )

    with gr.Blocks(title="Pump Wallet Tool", theme=theme, css=css) as demo:
        # --- Header ---
        gr.Markdown(
            """# 🚀 Pump Wallet Tool

            Monitor Solana wallets for **Pump.fun / PumpSwap** meme-coin activity.
            Scan transactions → fetch market trades → generate entry/exit behavior analysis reports.
            """
        )

        # --- Settings Panel ---
        with gr.Accordion("⚙️ Settings", open=True):
            with gr.Row():
                wallet_input = gr.Textbox(
                    label="Wallet Address",
                    value=DEFAULT_WALLET,
                    placeholder="Solana wallet address (base58)",
                    scale=3,
                )
                data_dir_input = gr.Textbox(
                    label="Data Directory",
                    value=DEFAULT_DATA_DIR,
                    scale=1,
                )
            with gr.Row():
                rpc_input = gr.Textbox(
                    label="RPC URL",
                    value=DEFAULT_RPC,
                    placeholder="https://api.mainnet-beta.solana.com",
                    scale=2,
                )
                helius_key_input = gr.Textbox(
                    label="Helius API Key",
                    type="password",
                    placeholder="Required for market trade fetching",
                    scale=1,
                )

        # --- Main Tabs ---
        with gr.Tabs():
            # ============================
            # Pipeline Tab
            # ============================
            with gr.TabItem("🚀 Pipeline"):
                gr.Markdown("Run the complete pipeline: **scan → dedupe → tokens → market → analyze**.")
                with gr.Row():
                    with gr.Column(scale=1):
                        with gr.Group():
                            limit_pl = gr.Number(
                                label="Transaction Limit",
                                value=100,
                                minimum=1,
                                maximum=1000,
                                precision=0,
                            )
                            refresh_pl = gr.Checkbox(label="Refresh Seen Signatures", value=False)
                            verbose_pl = gr.Checkbox(label="Verbose Output", value=True)
                            skip_scan_pl = gr.Checkbox(
                                label="Skip Scan (use existing local data)",
                                value=False,
                            )
                            skip_market_pl = gr.Checkbox(
                                label="Skip Market (use existing market data)",
                                value=False,
                            )
                            min_sol_pl = gr.Number(
                                label="Min Effective SOL",
                                value=0.005,
                                minimum=0.0,
                                step=0.001,
                            )
                        run_pipeline_btn = gr.Button("▶ Run Pipeline", variant="primary", size="lg")
                    with gr.Column(scale=2):
                        pipeline_output = gr.Textbox(
                            label="Pipeline Log",
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
            with gr.TabItem("🔍 Scan"):
                gr.Markdown("Fetch wallet transactions and classify Pump.fun / PumpSwap activity.")
                with gr.Row():
                    with gr.Column(scale=1):
                        with gr.Group():
                            limit_sc = gr.Number(
                                label="Transaction Limit",
                                value=100,
                                minimum=1,
                                maximum=1000,
                                precision=0,
                            )
                            refresh_sc = gr.Checkbox(label="Refresh Seen Signatures", value=False)
                            verbose_sc = gr.Checkbox(label="Verbose Output", value=True)
                        run_scan_btn = gr.Button("▶ Run Scan", variant="primary")
                    with gr.Column(scale=2):
                        scan_output = gr.Textbox(
                            label="Scan Log",
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
            with gr.TabItem("📊 Market Trades"):
                gr.Markdown(
                    "Fetch market-wide Helius enhanced transactions for each meme token mint. "
                    "Requires a valid Helius API key in Settings."
                )
                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown(
                            """**Note:** This step reads `data/<wallet>.meme_tokens.csv`
                            and fetches all market trades within each mint's trading window.
                            May take several minutes depending on token count."""
                        )
                        run_market_btn = gr.Button("▶ Fetch Market Trades", variant="primary")
                    with gr.Column(scale=2):
                        market_output = gr.Textbox(
                            label="Market Log",
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
            with gr.TabItem("🔎 Inspect"):
                gr.Markdown("Inspect a single transaction and see its Pump classification details.")
                with gr.Row():
                    with gr.Column(scale=1):
                        sig_input = gr.Textbox(
                            label="Transaction Signature",
                            placeholder="Enter a Solana transaction signature (base58)...",
                            lines=2,
                        )
                        verbose_insp = gr.Checkbox(label="Verbose Output", value=True)
                        run_inspect_btn = gr.Button("▶ Inspect", variant="primary")
                    with gr.Column(scale=2):
                        inspect_output = gr.Textbox(
                            label="Inspection Result",
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
            with gr.TabItem("📈 Analyze"):
                gr.Markdown("Generate entry and exit behavior analysis reports from collected data.")
                with gr.Row():
                    with gr.Column(scale=1):
                        with gr.Group():
                            min_sol_an = gr.Number(
                                label="Min Effective SOL",
                                value=0.005,
                                minimum=0.0,
                                step=0.001,
                                info="Ignore trades below this SOL amount in feature computation.",
                            )
                        run_analyze_btn = gr.Button("▶ Generate Analysis", variant="primary")
                    with gr.Column(scale=2):
                        analyze_output = gr.Textbox(
                            label="Analysis Log",
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
            with gr.TabItem("📁 Results"):
                gr.Markdown("Browse and view generated output files (CSV, JSONL, Markdown reports).")
                with gr.Row():
                    refresh_btn = gr.Button("🔄 Refresh File List", scale=1)
                    file_dropdown = gr.Dropdown(
                        label="Available Output Files",
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
                    with gr.TabItem("📋 Table View"):
                        csv_table = gr.Dataframe(
                            label="CSV Content",
                            row_count=(30, "dynamic"),
                            wrap=True,
                        )
                    with gr.TabItem("📝 Report View"):
                        md_view = gr.Markdown("*Select a `.md` report file from the dropdown above.*")
                    with gr.TabItem("📄 Raw Text"):
                        raw_view = gr.Textbox(
                            label="Raw File Content",
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
            *Pump Wallet Tool — Monitor | Analyze | Trade Smart*
            """
        )

    return demo


# --- Entry Point ---

demo = build_ui()

if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
    )
