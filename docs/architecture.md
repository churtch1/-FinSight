# 资产整合系统架构设计

## 目标定位

本项目目标调整为“本地采集 + 云端数据库 + 手机网页看板”的个人资产整合系统。

系统不是纯本地应用，而是由 Windows 本地采集端、Supabase 云数据库、手机浏览器看板三部分组成：

```text
Windows 本地采集端
  -> IBKR Flex Web Service
  -> 银行与券商 PDF 资产报告
  -> Python 解析、清洗、标准化
  -> Supabase 云数据库
  -> 手机网页 Dashboard
```

第一版重点不是做漂亮界面，而是先把数据结构、采集链路、同步逻辑和审计记录设计清楚。

## 系统边界

### Windows 本地采集端

本地端负责接触敏感数据源和本地文件：

- 通过 IBKR Flex Web Service 获取每日官方持仓与结算估值。
- 获取 IBKR 持仓、现金、交易、账户摘要。
- 接收 HSBC 中国、招商银行、其他银行或券商资产配置 PDF。
- 提取 PDF 文本与表格。
- 将不同来源数据清洗成统一资产模型。
- 使用 service role key 写入 Supabase。

### Supabase 云数据库

Supabase 负责持久化统一后的资产数据：

- 账户。
- 标的。
- 当前持仓。
- 交易流水。
- 现金流水。
- 收益记录。
- 汇率。
- 导入记录。
- 导入错误。
- 历史快照。
- Dashboard 查询视图。

### 手机网页看板

看板只负责读取云端数据并展示，不直接连接 IBKR，也不处理 PDF 原始文件。

第一版可以继续使用 Streamlit。后续当数据链路稳定后，再升级为更漂亮的网页端。

## 总体数据流

```text
IBKR / PDF / CSV
  -> Collector / Parser
  -> Raw Import Record
  -> Normalizer
  -> Standard Models
  -> Supabase Writer
  -> Current Positions / Transactions / Cash Flows
  -> Snapshot Builder
  -> Portfolio Snapshots / Breakdowns
  -> Mobile Dashboard
```

## 核心设计原则

1. 所有数据来源必须先标准化，再入库。
2. IBKR、HSBC、招商银行等来源不能把各自的原始字段扩散到系统其他层。
3. 每次导入都要有可追踪记录，包括来源、文件、parser、状态和错误。
4. 资产展示使用统一估值字段，至少支持 USD 和 CNY。
5. Dashboard 使用只读权限，不暴露 service role key。
6. PDF parser 初期允许保守，不确定的数据进入复核与错误记录。
7. 历史快照由标准化后的当前持仓生成，不直接依赖某个来源。

## 目标模块划分

```text
src/portfolio_mvp/
  collectors/      本地采集器，例如 IBKR、文件扫描
  parsers/         PDF / CSV 解析器
  normalizers/     数据清洗、资产类型映射、币种归一
  repositories/    账户、标的、持仓、交易等数据库访问
  sync/            Supabase 写入、导入审计、快照生成
  analytics/       收益、净值、分布计算
  models.py        统一资产模型
  config.py        配置
  db.py            Supabase 连接
  fx.py            汇率
```

## 统一资产模型

### Account

账户表示资产归属位置。

字段：

- provider: IBKR / HSBC China / CMB / Other。
- account_name。
- account_number_masked。
- account_type: brokerage / bank / wealth / cash / other。
- base_currency。
- status。

### Instrument

标的表示股票、基金、理财、债券、现金、黄金等资产。

字段：

- symbol。
- name。
- isin。
- provider_code。
- asset_type。
- currency。
- region。
- mapping_status。

### Position

当前持仓表示某账户在某天对某标的的资产余额。

字段：

- account。
- instrument。
- quantity。
- price_original。
- market_value_original。
- currency。
- market_value_usd。
- market_value_cny。
- valuation_date。
- source_import_id。
- source。

### Transaction

交易表示买入、卖出、申购、赎回等资产变动。

字段：

- account。
- instrument。
- transaction_date。
- transaction_type。
- quantity。
- price_original。
- amount_original。
- currency。
- amount_usd。
- amount_cny。
- fee_original。
- tax_original。
- description。

### CashFlow

现金流水表示入金、出金、现金余额调整。

字段：

- account。
- flow_date。
- flow_type。
- amount_original。
- currency。
- amount_usd。
- amount_cny。
- description。

### IncomeRecord

收益记录表示分红、利息、债券票息、理财收益。

字段：

- account。
- instrument。
- income_date。
- income_type。
- amount_original。
- currency。
- amount_usd。
- amount_cny。
- description。

### PortfolioSnapshot

资产快照表示某一天的整体资产状态。

字段：

- snapshot_date。
- total_value_usd。
- total_value_cny。
- total_cost_usd。
- total_pnl_usd。
- total_pnl_pct。
- net_deposit_usd。

### PortfolioSnapshotBreakdown

快照拆分表示账户、资产类别、币种、机构维度上的分布。

字段：

- snapshot_id。
- dimension。
- key。
- label。
- value_usd。
- value_cny。
- weight。

## 来源适配策略

### IBKR

IBKR 数据来自 Flex Web Service 的每日 Open Positions 报告。

优先采集：

- managed accounts。
- portfolio positions。
- cash balances。
- account summary。
- executions。
- dividends / interest / fees，视 API 可用性逐步完善。

### 银行 PDF

银行 PDF 使用 parser 插件机制：

- HSBC 中国 parser。
- 招商银行 parser。
- 通用 PDF parser。

每个 parser 输出统一中间结果，不直接写入数据库。

### CSV

CSV 继续作为人工补录和调试入口。

## Dashboard 查询目标

手机看板至少需要以下数据：

- 当前总资产。
- 按账户分布。
- 按机构分布。
- 按资产类别分布。
- 按币种分布。
- 持仓明细。
- 收益情况。
- 历史净值变化。
- 最近导入记录。
- 待处理错误。

