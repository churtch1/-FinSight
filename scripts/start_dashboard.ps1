param(
    [int]$Port = 8501,
    [switch]$DemoMode
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if ($DemoMode) {
    $env:SUPABASE_URL = ""
    $env:SUPABASE_ANON_KEY = ""
    $env:SUPABASE_SERVICE_ROLE_KEY = ""
    Write-Host ""
    Write-Host "Starting FinSight in demo mode..." -ForegroundColor Cyan
    Write-Host "Local URL: http://127.0.0.1:$Port" -ForegroundColor Green
    Write-Host "This session will use sample data instead of your real portfolio." -ForegroundColor DarkGray
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "Starting FinSight with local environment data..." -ForegroundColor Cyan
    Write-Host "Local URL: http://127.0.0.1:$Port" -ForegroundColor Green
    Write-Host ""
}

py -m streamlit run app/streamlit_app.py `
    --server.address 127.0.0.1 `
    --server.port $Port `
    --browser.gatherUsageStats false
