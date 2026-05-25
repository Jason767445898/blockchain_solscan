# Pump Wallet Tool

这是一个完整的钱包行为分析工具：通过免费 Solana JSON-RPC 监控指定钱包在 Pump.fun / PumpSwap 上的交易，汇总该钱包交易过的 meme token，再用 Helius Enhanced API 拉取这些 token 的市场交易窗口，最后生成开仓/清仓条件逆向分析报告。

核心入口是：

```bash
python pump_tool.py <command>
```

也支持 Web UI 在浏览器中操作：

```bash
python webui.py                      # 浏览器打开 http://0.0.0.0:7860
```

完整流程说明见 [docs/PROJECT_FLOW.md](/Users/lijason/Desktop/blockchain_solscan/docs/PROJECT_FLOW.md)。

## 功能

- 默认使用免费 RPC：
  - `getSignaturesForAddress`
  - `getTransaction`
- 仍保留 Solscan Pro API 作为可选数据源
- 识别 Pump.fun 和 PumpSwap 相关 program id
- 初步分类：`pump_buy`、`pump_sell`、`pump_create_token`、`pump_related`、失败交易、其他交易
- 输出：
  - `data/<wallet>.jsonl`：完整结构化记录，保留原始交易数据
  - `data/<wallet>.csv`：便于表格查看的摘要
  - `data/<wallet>.meme_tokens.csv`：目标钱包交易过的 meme token 汇总
  - `data/<wallet>.market_trades/`：每个 token 的市场交易窗口
  - `pump_analyst/results/<wallet>/`：开仓/清仓画像、CSV 特征和 Markdown 报告
- **Web UI**：Gradio 浏览器界面，6 个标签页覆盖所有功能：
  - 🚀 Pipeline — 一键运行完整流程，含进度条
  - 🔍 Scan — 抓取并分类钱包交易
  - 📊 Market — 拉取市场交易窗口
  - 🔎 Inspect — 诊断单笔交易分类
  - 📈 Analyze — 生成开仓/清仓报告
  - 📁 Results — 浏览 CSV 表格和 Markdown 报告

## 快速开始

下面以钱包 `55PB376nxsrBLTZr1UdQSk6M89AxPif6oKmbmZmWq5dr` 为例。

1. 创建环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

如果希望安装成命令行工具：

```bash
pip install -e .
pump-tool --help
```

如果只想用 Web UI，到这里就可以直接启动了：

```bash
python webui.py
# 浏览器打开 http://0.0.0.0:7860
# 在界面里填好钱包地址、RPC URL、Helius API Key 即可使用全部功能
```

2. 申请一个 Helius 免费 RPC URL。

推荐 Helius，因为它是 Solana 专用，免费额度对钱包监控足够友好。注册后在 Helius Dashboard 创建 API key，然后拼成：

```text
https://mainnet.helius-rpc.com/?api-key=你的API_KEY
```

3. 测试 RPC 是否可用：

```bash
curl "https://mainnet.helius-rpc.com/?api-key=你的API_KEY" \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"getHealth"}'
```

正常会返回 `result: ok`。如果返回 `Invalid API key`，说明 API key 复制错了、URL 没替换完整，或 key 已失效。

4. 扫描最近 100 条交易：

```bash
python pump_tool.py \
  --wallet 55PB376nxsrBLTZr1UdQSk6M89AxPif6oKmbmZmWq5dr \
  --rpc-url "https://mainnet.helius-rpc.com/?api-key=你的API_KEY" \
  scan \
  --limit 100 \
  --rpc-min-interval 0.5 \
  --refresh-seen \
  --verbose
```

5. 一键跑完整流程：

该命令会按顺序执行：钱包扫描、去重、meme token 汇总、市场交易抓取、开仓/清仓报告生成。

```bash
export HELIUS_API_KEY="你的Helius API key"
python pump_tool.py \
  --wallet 55PB376nxsrBLTZr1UdQSk6M89AxPif6oKmbmZmWq5dr \
  --rpc-url "https://mainnet.helius-rpc.com/?api-key=你的API_KEY" \
  pipeline \
  --limit 100 \
  --rpc-min-interval 0.5 \
  --refresh-seen \
  --market-page-limit 100 \
  --market-max-pages 20
```

如果本地已有钱包和市场数据，只想重新生成分析报告：

```bash
python pump_tool.py \
  --wallet 55PB376nxsrBLTZr1UdQSk6M89AxPif6oKmbmZmWq5dr \
  analyze
```

6. 只获取卖出交易：

```bash
python pump_tool.py \
  --wallet 55PB376nxsrBLTZr1UdQSk6M89AxPif6oKmbmZmWq5dr \
  --rpc-url "https://mainnet.helius-rpc.com/?api-key=你的API_KEY" \
  scan \
  --limit 100 \
  --category pump_sell \
  --refresh-seen \
  --verbose
```

7. 去重：

```bash
python pump_tool.py \
  --wallet 55PB376nxsrBLTZr1UdQSk6M89AxPif6oKmbmZmWq5dr \
  dedupe
```

8. 定位这个钱包交易过哪些 meme 币：

```bash
python pump_tool.py \
  --wallet 55PB376nxsrBLTZr1UdQSk6M89AxPif6oKmbmZmWq5dr \
  tokens
```

该命令会读取本地 `data/<wallet>.jsonl`，按 token mint 汇总成功的 `pump_buy` / `pump_sell` 记录，输出买入次数、卖出次数、投入 SOL、回收 SOL、净 SOL、净 token 和首次/最后交易时间。加上 `--meme-tokens-csv` 会额外生成：

```text
data/<wallet>.meme_tokens.csv
```

如果数据里没有 token 名称或 ticker，结果会以 mint 地址为准；Pump.fun 新币通常能看到以 `pump` 结尾的 mint。

9. 抓取每个 meme 币在目标钱包交易窗口内的市场交易：

这个命令会读取：

```text
data/<wallet>.meme_tokens.csv
```

对每个 mint 取 `first_block_time - 5分钟` 到 `last_block_time + 5分钟`，再调用 Helius Enhanced Transactions 按 mint 地址抓取窗口内交易，并二次过滤出确实包含该 mint 的记录。

```bash
export HELIUS_API_KEY="你的Helius API key"
python pump_tool.py \
  --wallet 55PB376nxsrBLTZr1UdQSk6M89AxPif6oKmbmZmWq5dr \
  market \
  --market-window-buffer 300 \
  --market-page-limit 100 \
  --market-max-pages 20
```

先小规模测试可以加：

```bash
python pump_tool.py \
  --wallet 55PB376nxsrBLTZr1UdQSk6M89AxPif6oKmbmZmWq5dr \
  --helius-api-key "你的Helius API key" \
  market \
  --market-token-limit 3
```

输出目录：

```text
data/<wallet>.market_trades/<mint>.jsonl
data/<wallet>.market_trades/<mint>.csv
data/<wallet>.market_trades/all_market_trades.csv
data/<wallet>.market_trades/summary.csv
```

`summary.csv` 会列出每个 mint 的窗口、是否看起来已清仓、抓到多少条交易。注意：这里抓的是 Helius 地址交易历史里能通过 mint 地址捕获到的市场交易；如果币迁移到 PumpSwap / Raydium 等池子，后续可以把 bonding curve / pool 地址也纳入查询来提高覆盖率。

10. 查看结果：

```text
data/55PB376nxsrBLTZr1UdQSk6M89AxPif6oKmbmZmWq5dr.csv
data/55PB376nxsrBLTZr1UdQSk6M89AxPif6oKmbmZmWq5dr.jsonl
data/55PB376nxsrBLTZr1UdQSk6M89AxPif6oKmbmZmWq5dr.market_trades/
pump_analyst/results/55PB376nxsrBLTZr1UdQSk6M89AxPif6oKmbmZmWq5dr/
```

## 统一命令

```bash
python pump_tool.py scan      # 抓取钱包交易并分类
python pump_tool.py dedupe    # 按 signature 去重
python pump_tool.py tokens    # 生成 meme token 汇总
python pump_tool.py market    # 抓取每个 mint 的市场交易窗口
python pump_tool.py inspect   # 诊断单笔交易分类
python pump_tool.py analyze   # 生成开仓/清仓报告
python pump_tool.py pipeline  # 串起完整流程
```

所有命令都支持全局参数：

```bash
python pump_tool.py \
  --wallet <WALLET> \
  --data-dir data \
  --rpc-url "你的RPC地址" \
  --helius-api-key "你的Helius API key" \
  pipeline
```

## 准备

使用默认免费 RPC 时可以不安装第三方依赖。建议仍然创建虚拟环境，方便以后切换 Solscan 或加通知模块：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

可选配置环境变量：

```bash
cp .env.example .env
export SOLSCAN_WALLET="要监控的钱包地址"
export SOLANA_RPC_URL="https://api.mainnet-beta.solana.com"
```

公共 RPC 免费但可能限频。如果你要长期稳定监控，建议换成 Helius、Alchemy、QuickNode 等服务的免费 RPC URL。

## 使用

只扫描一次：

```bash
python -m pump_monitor.monitor --wallet <WALLET> --once --limit 5 --rpc-min-interval 2
```

持续监控：

```bash
python -m pump_monitor.monitor --wallet <WALLET> --poll-seconds 60 --limit 5 --rpc-min-interval 2
```

扫描最近 100 条并重新处理已见过的签名：

```bash
python -m pump_monitor.monitor \
  --wallet <WALLET> \
  --rpc-url "你的免费RPC地址" \
  --once \
  --limit 100 \
  --rpc-min-interval 0.5 \
  --refresh-seen \
  --verbose
```

只保存卖出交易：

```bash
python -m pump_monitor.monitor \
  --wallet <WALLET> \
  --rpc-url "你的免费RPC地址" \
  --once \
  --limit 100 \
  --category pump_sell \
  --refresh-seen \
  --verbose
```

默认只保存 Pump 相关交易。如果你想把所有交易都落盘，方便调试分类规则：

```bash
python -m pump_monitor.monitor --wallet <WALLET> --once --include-other
```

如果公共 RPC 报限频，把请求降到更保守：

```bash
python -m pump_monitor.monitor --wallet <WALLET> --once --limit 3 --rpc-min-interval 3 --verbose
```

如果仍然限频，换一个免费 RPC URL：

```bash
python -m pump_monitor.monitor --wallet <WALLET> --once --rpc-url "你的免费RPC地址"
```

如果需要少打 RPC 请求，可以关闭交易详情，但买卖分类会更粗：

```bash
python -m pump_monitor.monitor --wallet <WALLET> --no-details
```

如果你之后升级了 Solscan API key，也可以切回 Solscan：

```bash
export SOLSCAN_API_KEY="你的 Solscan Pro API key"
python -m pump_monitor.monitor --source solscan --wallet <WALLET> --once
```

## 常见情况

`Solscan HTTP 401: Please upgrade your api key level`：

Solscan 免费 Level 1 key 不能调用当前需要的 Pro API。最省钱方案是改用 Helius / Alchemy / QuickNode 的免费 Solana RPC。

`RPC HTTP 401: Invalid API key`：

RPC URL 里的 API key 不对。检查是否完整替换了 `api-key=你的API_KEY`，URL 是否用英文双引号包住，key 里是否多了空格或换行。

`RPC rate limit reached`：

免费公共 RPC 或免费 RPC key 被限频。降低 `--limit`，增大 `--rpc-min-interval`，或者换 Helius 这类专用 RPC。

`fetched 0 transaction summaries`：

RPC 没返回这个钱包的交易。可能是公共 RPC 不稳定、钱包地址写错，或这个地址没有历史交易。建议先在 Solscan 上确认钱包地址有交易，再换 Helius RPC 重试。

`skipped ... non-Pump txs`：

交易拉到了，但没有匹配到 Pump program id。可以用 `--inspect-signature` 检查具体签名。如果 Solscan 页面显示 Pump.fun，而脚本没识别，通常需要补充新的 program id 或检查分类规则。

## 诊断漏识别的 Pump 交易

Solscan 页面会把一些路由交易标成 Pump.fun，但免费 RPC 返回的是原始 program id，不包含 Solscan 的平台标签。遇到页面显示 Pump.fun、脚本却说 non-Pump 的交易，先检查这笔交易实际出现了哪些 program id：

```bash
python -m pump_monitor.monitor \
  --wallet <WALLET> \
  --rpc-url "你的免费RPC地址" \
  --inspect-signature <SIGNATURE>
```

如果输出里的某个 program id 确认是 Pump 相关路由，可以临时追加：

```bash
python -m pump_monitor.monitor \
  --wallet <WALLET> \
  --rpc-url "你的免费RPC地址" \
  --pump-program-id <PROGRAM_ID> \
  --once \
  --limit 10 \
  --verbose
```

也可以长期配置：

```bash
export PUMP_PROGRAM_IDS="<PROGRAM_ID_1>,<PROGRAM_ID_2>"
```

## 分类逻辑

当前规则优先匹配以下 program id：

- Pump.fun：`6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`
- PumpSwap：`pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA`

如果交易详情中包含钱包的 SOL 变化和 token 变化，则进一步推断：

- token 增加且 SOL 减少：`pump_buy`
- token 减少且 SOL 增加：`pump_sell`
- Solscan 类型或来源包含 create：`pump_create_token`
- RPC / Solscan 交易中包含 Pump program id：`pump_related`

例如这笔交易：

```text
628BkTmrEhPzcsLMJBKMxBt4cnP3xVB4pcDp7LdnTEUnTckhVTX3Rk54Cen6mmCNGfPKZT4xJ5xqKr1Naq77suFU
```

诊断结果显示：

```text
category: pump_sell
sol_change: 0.553991661
token_changes: amount 为负数
```

因此它是卖出：钱包 SOL 增加，Pump token 数量减少。

## Web UI

除了命令行，本项目还提供了基于 [Gradio](https://www.gradio.app/) 的 Web 界面，可在浏览器中操作所有功能。

**启动：**

```bash
source .venv/bin/activate
python webui.py
```

浏览器打开 `http://0.0.0.0:7860` 后，你会看到 6 个标签页：

| 标签 | 对应命令 | 说明 |
|------|---------|------|
| 🚀 Pipeline | `pipeline` | 一键运行完整流程，顶部 Settings 面板填入钱包/RPC/Helius Key 后点击按钮即可。支持跳过已有数据的步骤。 |
| 🔍 Scan | `scan` | 从 RPC 抓取钱包交易并分类。可设置抓取数量、是否刷新已见过的签名。 |
| 📊 Market | `market` | 基于 `meme_tokens.csv` 拉取每个 mint 的市场交易窗口。**需要 Helius API Key。** |
| 🔎 Inspect | `inspect` | 粘贴一笔交易签名，查看其 program IDs、分类结果、SOL/token 变化。适合调试分类漏识别。 |
| 📈 Analyze | `analyze` | 基于本地已有数据生成开仓/清仓行为画像报告。可调整最小有效 SOL 阈值。 |
| 📁 Results | — | 浏览已生成的文件：CSV 以表格展示、Markdown 以渲染文本展示、JSONL 以原始文本展示。 |

界面顶部有一个 **⚙️ Settings** 面板，钱包地址、RPC URL、Helius API Key 和 Data Directory 在所有标签页中共享。

## 后续可扩展

- 增加 Telegram / Discord 通知
- 对接 SQLite 或 Postgres
- 加入钱包标签，如聪明钱、开发者钱包、狙击钱包
- 增加收益、持仓、买入均价、卖出胜率统计
- 接入 Pump.fun bonding curve / migration 状态
