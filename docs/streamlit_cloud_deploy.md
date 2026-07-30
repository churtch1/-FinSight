# Streamlit 云端部署说明

这份项目适合做成下面这种结构：

- Streamlit Cloud 负责：
  - `IBKR Flex` 每日自动同步
  - 汇丰 PDF 导入
  - 汇率导入
- `Supabase` 负责：
  - 存储持仓、导入记录、汇率、错误日志
- `Streamlit Community Cloud` 负责：
  - 只读展示看板
  - 通过浏览器和手机访问

这样做的好处是：云端不需要连接本地 `IBKR Gateway/TWS`，也不需要电脑长期在线。

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
IBKR_FLEX_TOKEN = "your-flex-token"
IBKR_FLEX_QUERY_ID = "1587428"
```

说明：

- `SUPABASE_URL`：你的 Supabase 项目地址
- `SUPABASE_ANON_KEY`：只读展示用，适合放在云端看板
- `STREAMLIT_PASSWORD`：看板访问密码
- `FX_API_URL`：可选，默认可保留

不要把 `SUPABASE_SERVICE_ROLE_KEY` 放到公开的云端看板里。

如果你希望在云端看板里直接上传汇丰 PDF 并写回数据库，则需要额外在 Secrets 中配置：

```toml
SUPABASE_SERVICE_ROLE_KEY = "your-service-role-key"
```

这会让云端应用具备写库能力，所以更适合下面这种情况：

- 这个看板只有你自己使用
- 你已经设置了访问密码
- 你接受“上传 PDF 入口在云端服务器执行解析和写入”

如果你只想远程看数据、不想让云端具备写权限，那就不要配置这个 key。

## 3. Streamlit Community Cloud 上线参数

创建应用时建议这样填写：

- Repository: 你的 GitHub 仓库
- Branch: 你要发布的分支
- Main file path: `app/streamlit_app.py`

如果平台让你选择 Python 版本，优先选择 `3.12`。

## 4. 上线后的使用方式

云端看板每天首次打开时从 IBKR Flex 读取上一交易日的股票、ETF 和债券持仓，
并写入 `Supabase`。银行 PDF 可以继续从云端看板上传。

常用本地更新命令：

```powershell
python scripts/load_fx_rates.py sample_data/fx_rates.csv
python scripts/import_hsbc_pdf.py HSBC/资产配置报告.pdf
```

## 5. 当前项目的实际部署边界

当前这个项目已经适合“远程看板”部署，但不适合把下面这些动作搬到 Streamlit 云端：

- 盘中持续连接 `IBKR Gateway/TWS`
- 上传和解析本地银行 PDF
- 用 service role key 在公开前端执行写入

如果后面需要在无人打开看板时也定时运行，可以再加一个调度层，例如：

- 本地定时任务
- 云函数 / 私有后端
- 受保护的导入接口

## 6. 你真正发布时只差什么

真正上线时，只差两步：

1. 把当前可部署代码推到 GitHub
2. 在 Streamlit Community Cloud 里选分支、填入口文件、粘贴 Secrets

完成后，你就会拿到一个公网链接，手机端可直接访问。
