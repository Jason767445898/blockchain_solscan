# PROJECT KNOWLEDGE BASE

**Generated:** 2026-05-22
**Commit:** 8ea85ec
**Branch:** main

## OVERVIEW
Python 3.9+ CLI pipeline that monitors Solana wallets for Pump.fun/PumpSwap meme-coin activity, fetches market-trade windows via Helius API, and generates entry/exit behavior analysis reports. Also includes a Gradio web UI for browser-based operation.

## STRUCTURE
```
./
├── pump_tool.py          # Unified CLI — all commands funnel through here
├── webui.py              # Thin Gradio entry point (~16 lines) — delegates to pump_web/
├── pump_web/             # Gradio Web UI package (split from monolithic webui.py)
│   ├── __init__.py       #   Re-exports build_ui
│   ├── ui.py             #   build_ui(), CSS, theme, constants
│   ├── handlers.py       #   do_scan, do_market, do_inspect, do_analyze, do_pipeline
│   ├── screener.py       #   Screener UI functions (build, run, reset, refresh, alerts)
│   └── results.py        #   File listing, content viewing for Results tab
├── pyproject.toml        # Project metadata, deps (requests, urllib3<2, gradio), ruff config
├── pump_monitor/         # Data collection: RPC, classification, storage
│   ├── _base_client.py   #   BaseApiClient — shared rate-limit, retry, timeout
│   ├── _utils.py         #   int_or_none(), str_or_none(), float_or_none(), as_list()
│   ├── _cli_bridges.py   #   cli_scan(), cli_dedupe(), cli_tokens(), cli_market(), cli_inspect()
│   ├── monitor.py        #   Orchestration logic (scan, inspect, market fetch, CLI argparser)
│   ├── rpc.py            #   Solana JSON-RPC client (requests, BaseApiClient)
│   ├── solscan.py        #   Solscan Pro API client (requests, BaseApiClient)
│   ├── classifier.py     #   Pump.fun/PumpSwap TX classification
│   ├── storage.py        #   TransactionStore — hierarchical JSONL/CSV paths (data/<wallet>/)
│   ├── market_trades.py  #   Helius enhanced TX fetch + standardization
│   ├── meme_tokens.py    #   Mint-level buy/sell aggregation
│   └── models.py         #   PumpClassification, MonitoredTransaction dataclasses
├── pump_analyst/         # Entry/exit behavior analysis + report generation
│   ├── _conditions.py    #   Core entry/exit feature computation
│   ├── _reports.py       #   Report writing: CSV, JSON, Markdown
│   ├── cli.py            #   Argparse entry point for analyze subcommand
│   ├── analyze.py        #   Thin wrapper around cli.main() for module invocation
│   └── README.md         #   Analyst usage and methodology documentation
├── data/                 # Wallet output (hierarchical: data/<wallet>/transactions.jsonl, ...)
├── docs/                 # PROJECT_FLOW.md (architecture + data flow)
└── .gitignore            # Ignores data/, .ruff_cache/
```
```
Note: setup.cfg and setup.py have been removed — pyproject.toml is the single source of truth.

## WHERE TO LOOK
| Task | Location | Notes |
|------|----------|-------|
| Add a CLI subcommand | `pump_tool.py` → `build_parser()` | Map subcommand to `run_*()` function |
| Add a data source | `pump_monitor/rpc.py` or `solscan.py` | Subclass `BaseApiClient` for rate-limit/retry |
| Change TX classification | `pump_monitor/classifier.py` ⇒ `classify_transaction()` | Use `inspect` command for diagnosis |
| Add analysis features | `pump_analyst/_conditions.py` | Feature constants at top of file |
| Change analysis output | `pump_analyst/_reports.py` | `write_csv()`, `write_json()`, `write_report()` |
| Change storage format | `pump_monitor/storage.py` ⇒ `TransactionStore` | JSONL is source of truth |
| Add Pump program IDs | `classifier.py` ⇒ `PUMP_FUN_PROGRAM_IDS` / `PUMP_SWAP_PROGRAM_IDS` | Or via `--pump-program-id` / `PUMP_PROGRAM_IDS` env var |
| Diagnostic single TX | `pump_tool.py inspect <SIGNATURE>` | Prints program IDs, classification, SOL/token changes |
| Pipeline orchestration | `pump_tool.py` ⇒ `run_pipeline()` | scan → dedupe → tokens → market → analyze |
| Launch web UI | `webui.py` ⇒ `pump_web/ui.py:build_ui()` | Gradio Blocks app with 7 tabs (Screener, Pipeline, Scan, Market, Inspect, Analyze, Results) |
| Change web UI layout | `pump_web/ui.py` ⇒ `build_ui()` | Tab-based: Screener, Pipeline, Scan, Market, Inspect, Analyze, Results |

## CODE MAP
| Symbol | Type | Location | Role |
|--------|------|----------|------|
| `pump_tool.main()` | function | `pump_tool.py:206` | Unifying CLI dispatching |
| `BaseApiClient` | class | `pump_monitor/_base_client.py:6` | Shared rate-limit, retry, timeout for all API clients |
| `SolanaRpcClient` | class | `pump_monitor/rpc.py:20` | Solana JSON-RPC via `requests` + `BaseApiClient` |
| `SolscanClient` | class | `pump_monitor/solscan.py:15` | Solscan Pro API via `requests` + `BaseApiClient` (with retry) |
| `HeliusEnhancedClient` | class | `pump_monitor/market_trades.py` | Helius market trades via `requests` + `BaseApiClient` |
| `classify_transaction()` | function | `pump_monitor/classifier.py:27` | Pump classification core |
| `TransactionStore` | class | `pump_monitor/storage.py` | JSONL + CSV dual persistence |
| `MemeTokenSummary` | dataclass | `pump_monitor/meme_tokens.py` | Per-mint aggregated wallet activity |
| `MonitoredTransaction` | dataclass | `pump_monitor/models.py:18` | Normalized TX with classification |
| `PumpClassification` | dataclass | `pump_monitor/models.py:8` | Category, confidence, SOL/token changes |
| `build_entry_samples()` | function | `pump_analyst/_conditions.py:15` | Entry feature computation from pre-buy market window |
| `build_exit_samples()` | function | `pump_analyst/_conditions.py` | Exit feature computation from pre-sell market window |
| `cli.main()` | function | `pump_analyst/cli.py:30` | Standalone argparser + analysis orchestration |
| `analyze.main()` | function | `pump_analyst/analyze.py:9` | Module-invocation wrapper → delegates to `cli.main()` |
| `monitor.cli_*()` | function group | `pump_monitor/_cli_bridges.py` | Bridge functions: `cli_scan()`, `cli_dedupe()`, `cli_tokens()`, `cli_market()`, `cli_inspect()`; re-exported from `monitor.py` |
| `webui.build_ui()` | function | `pump_web/ui.py` | Gradio Blocks UI construction — all 7 tabs, settings panel, event wiring |
| `webui.do_pipeline()` | function | `pump_web/handlers.py` | Pipeline wrapper with progress bar — orchestrates scan→dedupe→tokens→market→analyze |

## CONVENTIONS
- `from __future__ import annotations` in EVERY .py file — deferred evaluation, enables `|` union syntax
- Full type annotations on all functions: `list[str]`, `dict[str, Any]`, `set[str]`, `int | None`
- `typing.Any` for raw API response dicts; dataclasses for structured models
- Custom exceptions per module: `RpcError(RuntimeError)`, `SolscanError(RuntimeError)`, `HeliusError(RuntimeError)`
- SOL amounts: `f"{sol:.9f}"` (9 decimal), lamports: `amount / 1_000_000_000`
- Timestamps: Unix int in records, display as `"%Y-%m-%d %H:%M:%S UTC"` with `timezone.utc`
- JSONL: `ensure_ascii=False`, `sort_keys=True`, trailing `"\n"` per record
- CSV: `csv.DictWriter` with `extrasaction="ignore"`, `newline=""`, `encoding="utf-8"`
- Config: CLI arg > env var > hardcoded default (e.g., `os.getenv("SOLSCAN_WALLET") or DEFAULT_WALLET`)
- Rate limiting via `BaseApiClient`: call `_rate_limit()` before each request, `_mark_request()` after, `_retry_delay()` for backoff
- `raise SystemExit(main())` in `__main__` guard
- Private helpers prefixed `_`: `_collect_program_ids()`, `_sol_balance_changes()`
- Constants: `UPPER_SNAKE_CASE` (`LAMPORTS_PER_SOL`, `CSV_COLUMNS`)
- Ruff config in `pyproject.toml`: `line-length = 120`, `target-version = "py39"`, lint rules `E,F,W,I,N,UP`

## ANTI-PATTERNS (THIS PROJECT)
- **DO NOT hardcode Pump program IDs** outside `classifier.py` ⇒ `PUMP_FUN_PROGRAM_IDS`. Use `--pump-program-id` or `PUMP_PROGRAM_IDS` env for new ones.
- **DO NOT use public RPC endpoints** for production monitoring → rate limits will kill the pipeline. Use Helius/Alchemy/QuickNode.
- **DO NOT run `market` without `HELIUS_API_KEY`** → raises `SystemExit`.
- **DO NOT treat analysis results as profit signals** — no negative samples exist; the report is behavioral profiling, not backtested strategy.
- **DO NOT write a 4th API client from scratch** — subclass `BaseApiClient` to get rate-limit, retry, and timeout for free.
- **DO NOT add async/await without full conversion** — all HTTP is synchronous (`requests`). Mixing sync + async will deadlock on the rate-limiter.
- **DO NOT add `setup.cfg` or `setup.py` back** — `pyproject.toml` is the single, authoritative dependency and packaging source. These legacy files were removed during the v0.2.0 refactor.

## UNIQUE STYLES
- **cli_*() bridge pattern**: `pump_monitor/monitor.py` exposes `cli_scan()`, `cli_dedupe()`, `cli_tokens()`, `cli_market()`, `cli_inspect()` as keyword-argument functions. `pump_tool.py` calls them directly without building argv or re-parsing — no dual argparse.
- **Single argparser per module**: `monitor.py` retains its own argparser for `python -m pump_monitor.monitor` invocation. `pump_analyst/cli.py` has its own for `python -m pump_analyst.analyze`. `pump_tool.py` does not re-parse; it calls the bridge functions directly.
- **BaseApiClient inheritance**: All 3 API clients (`SolanaRpcClient`, `SolscanClient`, `HeliusEnhancedClient`) inherit rate-limit, retry, and timeout from `BaseApiClient`. No duplicate rate-limit logic.
- **`requests` for all HTTP**: `rpc.py` uses `requests` (same as `solscan.py` and `market_trades.py`). No `urllib.request` anywhere.
- **Flat package layout**: No `src/` directory. `pump_tool.py` lives at project root alongside `pump_monitor/` and `pump_analyst/`.
- **Helius API key in URL query parameter**: `?api-key=...` (per Helius spec, not header-based).

## COMMANDS
```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
pip install -e .                     # Optional: install pump-tool CLI

# Full pipeline (recommended)
export HELIUS_API_KEY="<key>"
python pump_tool.py --wallet <ADDR> --rpc-url "<RPC>" pipeline --limit 100 --refresh-seen

# Individual steps
python pump_tool.py --wallet <ADDR> --rpc-url "<RPC>" scan --limit 100 --verbose
python pump_tool.py --wallet <ADDR> dedupe
python pump_tool.py --wallet <ADDR> tokens
python pump_tool.py --wallet <ADDR> --helius-api-key "<key>" market
python pump_tool.py --wallet <ADDR> analyze
python pump_tool.py --wallet <ADDR> --rpc-url "<RPC>" inspect <SIGNATURE>

# Module-level invocation
python -m pump_monitor.monitor --wallet <ADDR> --once --limit 5
python -m pump_analyst.analyze --wallet <ADDR>

# Web UI (browser-based)
python webui.py                        # Opens at http://0.0.0.0:7862
```

## NOTES
- No tests exist. No CI.
- Ruff configured in `pyproject.toml` — `line-length=120`, `target-version="py39"`, lint rules `E,F,W,I,N,UP`, double quotes format.
- `pyproject.toml` is the single authoritative dependency source; `setup.cfg` and `setup.py` were removed in v0.2.0 refactor.
- Only 2 external deps (`requests`, `gradio`). Adding more needs justification in `pyproject.toml` and `requirements.txt`.
- Single `DEFAULT_WALLET` in `pump_tool.py:7`: `DEFAULT_WALLET = "55PB376nxsrBLTZr1UdQSk6M89AxPif6oKmbmZmWq5dr"` (was previously duplicated in the deleted legacy analyzer).
- `data/` is in `.gitignore` (covers all wallet subdirectories including analysis output). `pump_analyst/results/` line removed — analysis now writes to `data/<wallet>/analysis/`.
- Timestamp handling: all 3 API clients (`BaseApiClient` subclasses) now share identical rate-limiting via `_rate_limit()` + `_mark_request()`.
- Analysis feature thresholds (`MIN_EFFECTIVE_SOL = 0.005`) live at the top of `pump_analyst/_conditions.py`.
