# Frontend (static პანელი) — http://localhost:5500
# გაშვება: .\start-frontend.ps1
Set-Location $PSScriptRoot\frontend
Write-Host "Frontend ეშვება http://localhost:5500 (no-cache) ..." -ForegroundColor Cyan
python serve.py
