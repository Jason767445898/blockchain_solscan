# Pump Analyst

这个目录用于沉淀对目标钱包 meme 币开仓和清仓条件的逆向分析流程。

当前脚本会读取已有采集结果：

```text
data/<wallet>/transactions.csv
data/<wallet>/meme_tokens.csv
data/<wallet>/market_trades/all_market_trades.csv
data/<wallet>/market_trades/<mint>.jsonl
```

然后分两条线分析：

- 对每个 mint 取目标钱包的首次 `pump_buy` 作为“开仓点”，只分析该开仓点之前的市场交易特征。
- 对每个发生过卖出的 mint 取最后一次 `pump_sell` 作为“清仓点”，分析卖出前的持仓、价格回撤、卖压和最近成交变化。

## 分析口径

### 开仓

1. 目标样本：每个 mint 的首次 `pump_buy`。
2. 买入前窗口：`market_trades/<mint>.jsonl` 中时间和 slot 早于目标钱包首次买入的交易。
3. 有效市场交易：能从 fee payer 的 SOL/token 余额变化推断出买卖方向，且 SOL 变化不小于 `0.005 SOL`。
4. 买卖方向：
   - fee payer token 增加且 SOL 减少，记为 `buy`
   - fee payer token 减少且 SOL 增加，记为 `sell`
5. 过滤极小额交易的原因：采集结果里存在 `0.0003 SOL` 一类关联交易，容易污染价格和成交活跃度判断。

### 清仓

1. 目标样本：每个发生过 `pump_sell` 的 mint。
2. 清仓锚点：该 mint 最后一笔 `pump_sell`，通常对应全清或接近全清。
3. 卖出前窗口：`market_trades/<mint>.jsonl` 中早于清仓锚点的有效市场交易，排除目标钱包自己的交易。
4. 持仓期窗口：从该 mint 首次 `pump_buy` 到清仓锚点之前的有效市场交易。
5. 重点特征：持仓时长、最近 30/60 秒卖盘占比、最近 30/60 秒净流入、相对持仓期高点回撤、清仓时已实现 ROI、单次卖出占卖前 token 持仓比例。

## 运行

在项目根目录执行：

```bash
python -m pump_analyst.analyze
```

指定钱包：

```bash
python -m pump_analyst.analyze \
  --wallet 55PB376nxsrBLTZr1UdQSk6M89AxPif6oKmbmZmWq5dr
```

指定输出目录：

```bash
python -m pump_analyst.analyze \
  --output-dir custom/path/my_run
```

## 输出

默认输出到：

```text
data/<wallet>/analysis/
```

文件说明：

- `entry_features.csv`：每个 mint 的开仓前特征明细。
- `summary.json`：分位数、单条件覆盖、组合规则覆盖。
- `report.md`：中文分析报告和推荐复刻规则。
- `exit_features.csv`：每个发生过卖出的 mint 的清仓前特征明细。
- `exit_summary.json`：清仓条件的分位数、单条件覆盖、组合规则覆盖。
- `exit_report.md`：中文清仓分析报告和推荐复刻规则。

## 当前推荐复刻规则

```text
候选池：Pump 新 mint

硬条件：
1. mint 创建/首笔市场交易后 <= 180 秒
2. 买入前有效市场交易 >= 15 笔
3. 买入前独立买家 >= 10
4. 买入前累计买入 SOL >= 5
5. 最近 60 秒有效交易 >= 5
6. 最近 60 秒成交 SOL >= 2
7. 买盘占比 >= 55%
8. 最近一笔有效交易距离当前 <= 10 秒

执行：默认 0.5 SOL 开仓；极早期轻仓样本可用 0.1 SOL。
```

## 当前推荐清仓规则

```text
触发对象：已经按开仓规则持有的 Pump mint

优先清仓条件：
1. 单币持仓时间 <= 300 秒时，若已盈利且价格仍在持仓期高点的 80% 以上，倾向一次性卖出 90%+ token。
2. 最近 60 秒卖盘占比 >= 30%，且最近 60 秒净流入 <= 0 SOL，视为动能转弱，倾向清仓。
3. 距离上一笔有效市场交易 <= 10 秒，说明退出发生在市场仍活跃时，不等待完全冷却。

执行：默认卖出全部或 90%+ 仓位；若需要复刻原钱包风格，优先用最后一笔 pump_sell 作为全清锚点。
```

## 复用流程

1. 先用 `pump_monitor` 更新目标钱包交易。
2. 生成或更新 `data/<wallet>/meme_tokens.csv`。
3. 抓取 `data/<wallet>/market_trades/`。
4. 运行 `python -m pump_analyst.analyze`，或使用根目录统一入口 `python pump_tool.py --wallet <WALLET> analyze`。
5. 查看 `report.md` 得到开仓规则覆盖，查看 `entry_features.csv` 做逐币开仓复盘。
6. 查看 `exit_report.md` 得到清仓规则覆盖，查看 `exit_features.csv` 做逐币清仓复盘。

## 局限

当前数据只有目标钱包买过/卖过的币，没有完整的负样本。因此本分析得到的是行为画像和高覆盖条件，不能直接证明规则有盈利能力。

若要进一步提高可复刻性，下一步应补充负样本：

- 同时间段 Pump 新 mint；
- 目标钱包没有买入；
- 同样计算开盘后前 180 秒特征；
- 对比当前命中规则的假阳性比例。

清仓规则还需要补“持仓但未卖出”的时刻作为负样本：

- 对每个持仓 mint 按秒或按市场交易重放状态；
- 将目标钱包未卖出的中间状态标为负样本；
- 对比最后 `pump_sell` 前状态，回测止盈、止损、卖压和回撤阈值。
