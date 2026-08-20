# Frontend (Vite dev-სერვერი) — http://localhost:5173/panel/
# გაშვება: .\start-frontend.ps1
Set-Location $PSScriptRoot\frontend
if (-not (Test-Path node_modules)) {
    Write-Host "node_modules ვერ მოიძებნა — ვაყენებ..." -ForegroundColor Yellow
    npm install
}
Write-Host "Frontend (Vite) ეშვება http://localhost:5173/panel/ ..." -ForegroundColor Cyan
npm run dev
