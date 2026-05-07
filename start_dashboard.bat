@echo off
setlocal
cd /d "%~dp0"
py -m streamlit run app\streamlit_app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
