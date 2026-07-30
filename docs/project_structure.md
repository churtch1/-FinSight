# 项目目录结构规划

## 当前状态

当前项目已经有原型结构：

```text
app/
src/portfolio_mvp/
scripts/
sql/
sample_data/
tests/
```

这个结构可以保留，但需要在后续阶段逐步拆清楚职责。

## 目标结构

```text
portfolio-mvp/
  app/
    streamlit_app.py
    components/

  src/portfolio_mvp/
    config.py
    db.py
    fx.py
    models.py

    collectors/
      ibkr.py
      local_files.py

    parsers/
      base.py
      csv_normalized.py
      hsbc_cn_pdf.py
      cmb_cn_pdf.py
      generic_pdf.py

    normalizers/
      accounts.py
      instruments.py
      positions.py
      transactions.py
      asset_types.py
      currencies.py

    repositories/
      accounts.py
      instruments.py
      positions.py
      transactions.py
      cash_flows.py
      income.py
      snapshots.py

    sync/
      supabase_writer.py
      import_audit.py
      snapshot_builder.py

    analytics/
      allocation.py
      portfolio_value.py
      performance.py

  scripts/
    import_pdf.py
    import_csv.py
    load_fx_rates.py
    build_snapshot.py

  sql/
    schema.sql
    views.sql
    policies.sql

  sample_data/
    transactions_template.csv
    positions_demo.csv
    fx_rates.csv
    redacted_pdfs/

  tests/
    test_models.py
    test_ibkr_normalizer.py
    test_hsbc_parser.py
    test_cmb_parser.py
    test_snapshot_builder.py
```

## 模块职责

### collectors

负责接触外部数据源。

- `ibkr_flex.py`: 连接 IBKR Flex Web Service。
- `local_files.py`: 扫描或接收本地 PDF / CSV 文件。

collector 不直接写数据库，只输出原始数据或标准化前的中间数据。

### parsers

负责把文件内容解析成结构化记录。

- `base.py`: parser 接口。
- `hsbc_cn_pdf.py`: HSBC 中国 parser。
- `cmb_cn_pdf.py`: 招商银行 parser。
- `generic_pdf.py`: 通用保守 parser。
- `csv_normalized.py`: 标准 CSV parser。

parser 不做复杂业务判断，不直接写 Supabase。

### normalizers

负责将不同来源的数据转成统一资产模型。

- 资产类型映射。
- 币种归一。
- 标的识别。
- 账户识别。
- 金额与数量清洗。

### repositories

负责具体表的读写。

每个 repository 对应一组表，避免所有数据库逻辑集中在一个大文件中。

### sync

负责一次同步任务的编排。

- 创建导入记录。
- 调用 repository 写入数据。
- 记录错误。
- 同步完成后触发快照生成。

### analytics

负责 Dashboard 与历史分析需要的计算。

- 总资产。
- 分布。
- 历史净值。
- 收益率。
- 入金出金影响。

### app

第一版继续使用 Streamlit。

目标是手机浏览器优先：

- 信息密度适中。
- 图表不拥挤。
- 持仓表可筛选、可分页。
- 关键指标优先展示。

