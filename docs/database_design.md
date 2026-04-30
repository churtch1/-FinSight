# 数据库表设计

## 设计目标

数据库服务于三个目标：

1. 保存来自 IBKR、银行 PDF、CSV 的统一资产数据。
2. 保留每次导入的来源、状态和错误，便于排查。
3. 支持手机 Dashboard 快速读取当前资产、历史快照和收益分析。

## 枚举建议

### asset_type

```text
stock
fund
wealth_product
bond
cash
gold
crypto
other
```

### transaction_type

```text
buy
sell
subscribe
redeem
deposit
withdrawal
dividend
interest
coupon
fee
tax
cash_balance
position_snapshot
other
```

### import_status

```text
started
completed
partial
needs_review
failed
```

## 核心表

### accounts

账户表。

```text
id uuid primary key
provider text not null
account_name text not null
account_number_masked text
account_type text
base_currency text not null
status text not null default 'active'
created_at timestamptz
updated_at timestamptz
unique(provider, account_name)
```

### instruments

资产标的表。

```text
id uuid primary key
symbol text
name text not null
isin text
provider_code text
currency text
asset_type asset_type not null default 'other'
region text
mapping_status text not null default 'needs_review'
created_at timestamptz
updated_at timestamptz
```

建议索引：

```text
symbol + currency
isin
provider_code
asset_type
```

### instrument_aliases

不同来源对同一个标的的别名。

```text
id uuid primary key
instrument_id uuid references instruments(id)
provider text
alias text not null
alias_type text
created_at timestamptz
unique(provider, alias)
```

### statement_imports

导入审计表。

```text
id uuid primary key
source text not null
source_type text not null
file_name text
file_hash text
parser_name text
parser_version text
status import_status not null default 'started'
rows_imported integer not null default 0
error_summary text
imported_at timestamptz
created_at timestamptz
unique(source, file_hash)
```

source_type 示例：

```text
ibkr_api
hsbc_pdf
cmb_pdf
csv
manual
```

### import_errors

导入错误表。

```text
id uuid primary key
statement_import_id uuid references statement_imports(id)
row_number integer
raw_payload jsonb
error_message text not null
severity text not null default 'error'
created_at timestamptz
```

### positions_current

当前持仓表。

```text
id uuid primary key
account_id uuid references accounts(id)
instrument_id uuid references instruments(id)
quantity numeric(24, 8) not null default 0
price_original numeric(24, 8)
market_value_original numeric(24, 2) not null default 0
currency text not null
market_value_usd numeric(24, 2)
market_value_cny numeric(24, 2)
fx_rate_to_usd numeric(24, 10)
fx_rate_to_cny numeric(24, 10)
valuation_date date not null
source text
source_import_id uuid references statement_imports(id)
updated_at timestamptz
unique(account_id, instrument_id, valuation_date)
```

### transactions

交易流水表。

```text
id uuid primary key
account_id uuid references accounts(id)
instrument_id uuid references instruments(id)
source_import_id uuid references statement_imports(id)
transaction_date date not null
transaction_type transaction_type not null
quantity numeric(24, 8)
price_original numeric(24, 8)
amount_original numeric(24, 2) not null default 0
currency text not null
amount_usd numeric(24, 2)
amount_cny numeric(24, 2)
fee_original numeric(24, 2)
tax_original numeric(24, 2)
description text
created_at timestamptz
```

### cash_flows

现金流水表。

```text
id uuid primary key
account_id uuid references accounts(id)
source_import_id uuid references statement_imports(id)
flow_date date not null
flow_type text not null
amount_original numeric(24, 2) not null
currency text not null
amount_usd numeric(24, 2)
amount_cny numeric(24, 2)
description text
created_at timestamptz
```

### income_records

收益记录表。

```text
id uuid primary key
account_id uuid references accounts(id)
instrument_id uuid references instruments(id)
source_import_id uuid references statement_imports(id)
income_date date not null
income_type text not null
amount_original numeric(24, 2) not null
currency text not null
amount_usd numeric(24, 2)
amount_cny numeric(24, 2)
description text
created_at timestamptz
```

### fx_rates

汇率表。

```text
id uuid primary key
base_currency text not null
quote_currency text not null
rate numeric(24, 10) not null
rate_date date not null
source text not null
created_at timestamptz
unique(base_currency, quote_currency, rate_date, source)
```

## 历史快照表

### portfolio_snapshots

每日总资产快照。

```text
id uuid primary key
snapshot_date date not null unique
total_value_usd numeric(24, 2)
total_value_cny numeric(24, 2)
total_cost_usd numeric(24, 2)
total_pnl_usd numeric(24, 2)
total_pnl_pct numeric(12, 6)
net_deposit_usd numeric(24, 2)
created_at timestamptz
```

### portfolio_snapshot_breakdowns

快照维度拆分。

```text
id uuid primary key
snapshot_id uuid references portfolio_snapshots(id)
dimension text not null
key text not null
label text not null
value_usd numeric(24, 2)
value_cny numeric(24, 2)
weight numeric(12, 6)
created_at timestamptz
unique(snapshot_id, dimension, key)
```

dimension 示例：

```text
account
provider
asset_type
currency
```

## 后续增强表

### raw_import_files

可选。保存 PDF 文件元数据，不建议第一版直接把敏感 PDF 存入云端。

```text
id uuid primary key
statement_import_id uuid references statement_imports(id)
file_name text
file_hash text
local_path text
mime_type text
created_at timestamptz
```

### parser_reviews

可选。保存人工复核记录。

```text
id uuid primary key
statement_import_id uuid references statement_imports(id)
raw_payload jsonb
review_status text
review_note text
created_at timestamptz
updated_at timestamptz
```

## Dashboard 视图建议

后续可以建立这些 view，减少 Streamlit 侧复杂度：

```text
dashboard_positions
dashboard_allocation_by_account
dashboard_allocation_by_asset_type
dashboard_allocation_by_currency
dashboard_net_worth_history
dashboard_import_status
```

## 权限策略建议

第一版建议：

- 本地采集端使用 Supabase service role key，只放在 Windows 本地 `.env`。
- 手机 Dashboard 使用 anon key 或单独只读 key。
- Dashboard 所需表开放只读 policy。
- 写入权限只允许 service role。
- 不把 service role key 放进网页端。

