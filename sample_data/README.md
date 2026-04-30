# Sample data

- `transactions_template.csv` is the normalized CSV import template.
- `fx_rates.csv` is the manual FX rate template. Rates are stored as `base_currency -> USD`.
- `positions_demo.csv` is used by Streamlit when Supabase is not configured, so the dashboard can be tested immediately.

For HSBC China PDF parsing, provide a脱敏真实资产报告 PDF. The current parser only performs conservative text extraction until the real layout is known.

