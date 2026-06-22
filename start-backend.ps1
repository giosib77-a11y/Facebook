# Backend (FastAPI) — http://localhost:8000
# გაშვება: მარჯვენა კლიკი -> Run with PowerShell,  ან ტერმინალში: .\start-backend.ps1
Set-Location $PSScriptRoot\backend
$env:PYTHONUTF8 = '1'
Write-Host "Backend ეშვება http://localhost:8000 ..." -ForegroundColor Cyan
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
