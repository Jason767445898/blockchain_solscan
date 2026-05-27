from __future__ import annotations

import csv
import io
from pathlib import Path

import gradio as gr


def _list_output_files(wallet: str, data_dir: str) -> list[str]:
    """Return sorted list of output file paths for a wallet (new and old paths)."""
    files: list[str] = []
    base = Path(data_dir)
    wallet_dir = base / wallet

    # New hierarchical paths
    for filename in ["transactions.jsonl", "transactions.csv", "meme_tokens.csv"]:
        p = wallet_dir / filename
        if p.exists():
            files.append(str(p))

    # Old flat paths (backward-compat: data/<wallet>.jsonl, data/<wallet>.csv, ...)
    for filename, old_name in [
        ("transactions.jsonl", f"{wallet}.jsonl"),
        ("transactions.csv", f"{wallet}.csv"),
        ("meme_tokens.csv", f"{wallet}.meme_tokens.csv"),
    ]:
        old_p = base / old_name
        if old_p.exists() and str(old_p) not in files:
            files.append(str(old_p))

    # Market trades directory
    market_dir = wallet_dir / "market_trades"
    if market_dir.exists():
        for f in sorted(market_dir.iterdir()):
            if f.is_file():
                files.append(str(f))
    # Old flat market trades dir (data/<wallet>.market_trades/)
    old_market = base / f"{wallet}.market_trades"
    if old_market.exists() and old_market.is_dir():
        for f in sorted(old_market.iterdir()):
            if f.is_file():
                files.append(str(f))

    # Analysis results
    result_base = wallet_dir / "analysis"
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
