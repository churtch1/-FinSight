# 个人资产管理系统 MVP

这是一个最小可运行的个人资产管理系统骨架，使用 Python、Supabase 和 Streamlit。第一版支持：

- IBKR 本地 Gateway/TWS 同步入口。
- 汇丰中国 PDF 解析入口。
- 标准 CSV 导入入口。
- 多账户、多币种、多资产类型。
- 按股票、基金、理财、黄金、现金等资产类型展示占比饼图。
- 分页查看各资产类型下的具体持仓。
- 在线汇率 API 优先，失败后在 Streamlit 中手动输入汇率。

第一版不实现银行与券商之间的内部转账识别。

## 1. 安装

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
```

复制环境变量模板：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`：

```text
SUPABASE_URL=你的 Supabase Project URL
SUPABASE_ANON_KEY=你的 anon key
SUPABASE_SERVICE_ROLE_KEY=你的 service role key
STREAMLIT_PASSWORD=你的仪表盘密码
FX_API_URL=https://open.er-api.com/v6/latest/USD
IBKR_HOST=127.0.0.1
IBKR_PORT=7497
IBKR_CLIENT_ID=11
```

如果暂时不配置 Supabase，也可以直接运行 Streamlit，它会使用 `sample_data/positions_demo.csv` 展示本地样例页面。

## 2. 配置 Supabase

1. 在 Supabase 创建一个新项目。
2. 打开 SQL Editor。
3. 执行 `sql/schema.sql`。
4. 把 Project URL、anon key、service role key 填入 `.env`。

权限设计：

- Streamlit dashboard 使用 anon key，只读数据。
- 本地导入脚本使用 service role key，负责写入数据库。
- 不要把 service role key 放进公开部署的前端环境。

## 3. 导入手动汇率

汇率格式见 `sample_data/fx_rates.csv`，`rate` 表示 `base_currency -> USD`。

```powershell
python scripts/load_fx_rates.py sample_data/fx_rates.csv
```

测试方式：

- 在 Supabase 的 `fx_rates` 表中确认出现 USD、CNY、HKD。
- 临时把 `FX_API_URL` 改成错误地址，运行 dashboard，应看到手动汇率输入框。

## 4. 导入标准 CSV

模板见 `sample_data/transactions_template.csv`。

```powershell
python scripts/import_csv.py sample_data/transactions_template.csv
```

支持字段：

```text
account_name, provider, date, type, instrument_code, instrument_name, isin,
asset_type, quantity, price, amount, currency, fee, tax, description
```

`type` 支持：

```text
buy, sell, deposit, withdrawal, dividend, interest, fee, tax, cash_balance, position_snapshot
```

`asset_type` 支持：

```text
stock, fund, wealth_product, gold, cash, crypto, bond, other
```

测试方式：

- 导入模板后查看 `positions_current`，应出现股票、基金、现金、理财、黄金。
- 打开 Streamlit，饼图金额合计应等于总资产 USD。
- 持仓列表筛选“股票”“基金”“理财”等，应只显示对应资产。

## 5. 导入汇丰中国 PDF

```powershell
python scripts/import_hsbc_pdf.py path\to\hsbc_cn_statement.pdf
```

当前 parser 是保守版本：在没有脱敏真实样例前，只尝试从文本中提取明显的人民币总资产、账户余额或存款余额。你提供脱敏样例 PDF 后，可以在 `src/portfolio_mvp/parsers/hsbc_cn_pdf.py` 中补精确规则。

测试方式：

- 能识别时，`positions_current` 会出现 CNY Cash。
- 不能识别时，`statement_imports.status` 会标记为 `needs_review`，并在 `import_errors` 中记录原因。

## 6. 同步 IBKR

先启动本地 IB Gateway 或 TWS，并确认：

- API 连接已启用。
- Paper TWS 常用端口是 `7497`。
- Live TWS 常用端口是 `7496`。
- Gateway 端口常见为 `4002` 或 `4001`。

运行：

```powershell
python scripts/sync_ibkr.py --account all
```

第一版同步：

- 当前持仓。
- 多币种现金余额。
- 账户摘要中的基础币种等关键字段。
- TWS/Gateway 当前可返回的成交流水。
- 同步失败时写入 `statement_imports` 和 `import_errors`，方便复核。

测试方式：

- 未启动 Gateway/TWS 时，脚本应清楚提示无法连接。
- 启动 Gateway/TWS 后，`positions_current` 应出现 IBKR 持仓和各币种 Cash。

## 7. 运行 Streamlit Dashboard

```powershell
streamlit run app/streamlit_app.py
```

打开浏览器中的本地地址，手机也可以在同一网络下访问该地址。

Dashboard 包含：

- 总资产 USD。
- IBKR USD 资产。
- 人民币资产。
- 按资产类型分类的饼图。
- 按账户与币种汇总。
- 可筛选、可分页的持仓列表。
- 最近导入记录。
- 待处理导入错误。

测试方式：

- 未配置 Supabase 时，应显示本地样例数据。
- 配置 Supabase 后，应显示云端数据。
- 窄屏或手机浏览器下，饼图和分页表格应可读。

## 8. 下一版预留

- 招行截图 + AI 识别。
- Binance parser。
- 其他银行/券商 parser 插件。
- 更完整的汇丰中国 PDF 样例驱动解析。
- Supabase Auth。
- 更完整的收益率、分红、税费分析。

