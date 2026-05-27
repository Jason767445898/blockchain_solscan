from __future__ import annotations

import time as _time
from pathlib import Path
from typing import Any

import gradio as gr
import pandas as pd

SCREENER_TABLE_TYPES = [
    "bool",
    "str",
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


def _build_screener(
    helius_api_key: str,
    wallet: str,
    base_data_dir: str,
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

    data_dir = str(Path(base_data_dir) / wallet)
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
    wallet: str,
    base_data_dir: str,
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
    data_dir = str(Path(base_data_dir) / wallet)
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
    wallet: str,
    base_data_dir: str,
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

    data_dir = str(Path(base_data_dir) / wallet)

    if not (helius_api_key or "").strip():
        return (
            [],
            rows_for_table(load_alert_rows(data_dir, retention_hours=retention_hours)),
            "需要 Helius API 密钥。",
            screener_state,
        )

    settings_key = _screener_settings_key(
        helius_api_key,
        wallet,
        base_data_dir,
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
            wallet,
            base_data_dir,
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
    wallet: str,
    base_data_dir: str,
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
            wallet,
            base_data_dir,
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
            _time.sleep(max(1, int(poll_seconds)))
    return latest_candidates, latest_alerts, latest_status, screener_state


def reset_screener_state(
    wallet: str, base_data_dir: str, retention_hours: float
) -> tuple[list[list[Any]], list[list[Any]], str, None]:
    from pump_monitor.screener import load_alert_rows, rows_for_table

    data_dir = str(Path(base_data_dir) / wallet)

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
    if len(row) < 5:
        return ""
    return str(row[4]) if row[4] else ""


def save_alert_read_status(table_data: list[list[Any]], wallet: str, base_data_dir: str) -> str:
    """Persist read/unread status from alert table checkboxes to read_mints.json."""
    from datetime import datetime, timedelta
    from datetime import timezone as _tz

    from pump_monitor.screener import load_read_status, save_read_status

    data_dir = str(Path(base_data_dir) / wallet)

    if isinstance(table_data, pd.DataFrame):
        table_data = table_data.values.tolist()
    if not table_data:
        return "无数据可保存。"
    existing = load_read_status(data_dir)
    updated = 0
    for row in table_data:
        if not row or len(row) < 5:
            continue
        mint = str(row[4]) if row[4] else ""
        if not mint:
            continue
        is_read = bool(row[0]) if row else False
        old_entry = existing.get(mint, {})
        old_read = bool(old_entry.get("read", False)) if isinstance(old_entry, dict) else bool(old_entry)
        if old_read != is_read:
            if is_read:
                existing[mint] = {
                    "read": True,
                    "marked_at": datetime.now(_tz(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S UTC+8"),
                }
            else:
                existing[mint] = {"read": False, "marked_at": None}
            updated += 1
    save_read_status(data_dir, existing)
    return f"已保存 {updated} 条已读状态变更。"


def refresh_alert_table(wallet: str, base_data_dir: str, retention_hours: float) -> list[list[Any]]:
    """Reload alert table from alerts.jsonl on disk without re-running the screener poll."""
    from pump_monitor.screener import load_alert_rows, rows_for_table

    data_dir = str(Path(base_data_dir) / wallet)

    return rows_for_table(load_alert_rows(data_dir, retention_hours=retention_hours))
