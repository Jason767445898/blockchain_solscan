from __future__ import annotations

import os

import gradio as gr

from pump_web.handlers import do_analyze, do_inspect, do_market, do_pipeline, do_scan
from pump_web.results import refresh_file_list, update_file_view
from pump_web.screener import (
    SCREENER_TABLE_TYPES,
    on_alert_row_select,
    refresh_alert_table,
    reset_screener_state,
    run_screener_loop,
    run_screener_once,
    save_alert_read_status,
)

DEFAULT_WALLET = os.getenv("SOLSCAN_WALLET", "55PB376nxsrBLTZr1UdQSk6M89AxPif6oKmbmZmWq5dr")
DEFAULT_RPC = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
DEFAULT_DATA_DIR = os.getenv("SOLSCAN_OUTPUT_DIR", "data")
DEFAULT_WEBUI_PORT = int(os.getenv("PUMP_WEBUI_PORT", "7862"))

_UI_CSS = """
.output-log textarea {
    font-family: 'Menlo', 'Consolas', 'SF Mono', monospace;
    font-size: 12px;
    line-height: 1.4;
}
.screener-filters {
    max-height: calc(100vh - 200px);
    overflow-y: auto;
    overflow-x: hidden;
    padding-right: 6px;
}
.screener-filters::-webkit-scrollbar {
    width: 6px;
}
.screener-filters::-webkit-scrollbar-thumb {
    background: #c1c1c1;
    border-radius: 3px;
}
.screener-filters::-webkit-scrollbar-track {
    background: transparent;
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
                        with gr.Column(elem_classes="screener-filters"):
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
                                "标记时间",
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
                        with gr.Row():
                            save_read_btn = gr.Button("保存已读状态", variant="secondary", scale=1)
                            refresh_alert_btn = gr.Button("🔄 刷新提醒", variant="secondary", scale=1)
                        save_status = gr.Textbox(visible=False)

                screener_inputs = [
                    helius_key_input,
                    wallet_input,
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
                    inputs=[wallet_input, data_dir_input, retention_hours_rt],
                    outputs=[candidate_table, alert_table, screener_status, screener_state],
                )
                alert_table.select(fn=on_alert_row_select, inputs=[alert_table], outputs=[mint_copy_box])
                save_read_btn.click(
                    fn=save_alert_read_status,
                    inputs=[alert_table, wallet_input, data_dir_input],
                    outputs=[save_status],
                )
                refresh_alert_btn.click(
                    fn=refresh_alert_table,
                    inputs=[wallet_input, data_dir_input, retention_hours_rt],
                    outputs=[alert_table],
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
                            """**注意：** 此步骤读取 `data/<钱包>/meme_tokens.csv`，
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
