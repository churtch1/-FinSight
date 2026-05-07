# Streamlit 云端部署说明

这份项目适合做成下面这种结构：

- 本地电脑负责：
  - `IBKR` 同步
  - 汇丰 PDF 导入
  - 汇率导入
- `Supabase` 负责：
  - 存储持仓、导入记录、汇率、错误日志
- `Streamlit Community Cloud` 负责：
  - 只读展示看板
  - 通过浏览器和手机访问

这样做的好处是：云端不需要直接连接你的 `IBKR Gateway/TWS`，也不需要上传原始 PDF。

## 1. 部署前准备

确保这几个文件已经在仓库中：

- `app/streamlit_app.py`
- `requirements.txt`
- `.streamlit/config.toml`

不要提交下面这些本地私密文件：

- `.env`
- `.streamlit/secrets.toml`
- `HSBC/` 下的 PDF 或原始资料

## 2. 你需要准备的云端密钥

在 Streamlit Community Cloud 的应用 Secrets 中填写：

```toml
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_ANON_KEY = "your-anon-key"
STREAMLIT_PASSWORD = "your-dashboard-password"
FX_API_URL = "https://open.er-api.com/v6/latest/USD"
```

说明：

- `SUPABASE_URL`：你的 Supabase 项目地址
- `SUPABASE_ANON_KEY`：只读展示用，适合放在云端看板
- `STREAMLIT_PASSWORD`：看板访问密码
- `FX_API_URL`：可选，默认可保留

不要把 `SUPABASE_SERVICE_ROLE_KEY` 放到公开的云端看板里。

## 3. Streamlit Community Cloud 上线参数

创建应用时建议这样填写：

- Repository: 你的 GitHub 仓库
- Branch: 你要发布的分支
- Main file path: `app/streamlit_app.py`

如果平台让你选择 Python 版本，优先选择 `3.12`。

## 4. 上线后的使用方式

云端看板只负责读取 `Supabase` 中已经存在的数据。

因此日常更新流程是：

1. 在你自己的电脑上同步 `IBKR`
2. 在你自己的电脑上导入汇丰 PDF
3. 数据写入 `Supabase`
4. 手机或其他设备打开 Streamlit 云端链接查看最新看板

常用本地更新命令：

```powershell
python scripts/load_fx_rates.py sample_data/fx_rates.csv
python scripts/import_hsbc_pdf.py HSBC/资产配置报告.pdf
python scripts/sync_ibkr.py --account all
```

## 5. 当前项目的实际部署边界

当前这个项目已经适合“远程看板”部署，但不适合把下面这些动作搬到 Streamlit 云端：

- 直接连接本地 `IBKR Gateway/TWS`
- 上传和解析本地银行 PDF
- 用 service role key 在公开前端执行写入

如果后面你想进一步自动化，可以再加一个定时同步层，例如：

- 本地定时任务
- 云函数 / 私有后端
- 受保护的导入接口

## 6. 你真正发布时只差什么

真正上线时，只差两步：

1. 把当前可部署代码推到 GitHub
2. 在 Streamlit Community Cloud 里选分支、填入口文件、粘贴 Secrets

完成后，你就会拿到一个公网链接，手机端可直接访问。
