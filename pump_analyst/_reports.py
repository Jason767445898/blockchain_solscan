from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from ._conditions import fmt


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


def write_report(
    path: Path, wallet: str, samples: list[dict[str, Any]], summary: dict[str, Any], min_effective_sol: float
) -> None:
    stats = summary["stats"]
    coverage = summary["coverage"]
    combos = summary["combo_coverage"]
    lines = [
        "# 钱包开仓条件逆向分析",
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
            f"命中样本 ROI 中位数 `{fmt(row.get('median_roi'))}`，"
            f"正收益 `{row.get('positive_roi')}/{row.get('roi_count')}`"
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


def write_exit_report(
    path: Path, wallet: str, samples: list[dict[str, Any]], summary: dict[str, Any], min_effective_sol: float
) -> None:
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
            f"命中样本 ROI 中位数 `{fmt(row.get('median_roi'))}`，"
            f"正收益 `{row.get('positive_roi')}/{row.get('roi_count')}`"
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
