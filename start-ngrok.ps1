# ngrok ტუნელი — https საჯარო მისამართი backend-ისთვის (პორტი 8000)
# გაშვება: .\start-ngrok.ps1
# შენიშვნა: უფასო ngrok-ის მისამართი ყოველ გაშვებაზე იცვლება — მაშინ განაახლე
#   .env-ში FB_REDIRECT_URI და Meta-ში webhook callback + OAuth redirect URI.
$ng = (Get-Command ngrok -ErrorAction SilentlyContinue).Source
if (-not $ng) {
    $ng = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet" -Filter ngrok.exe -Recurse -ErrorAction SilentlyContinue |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $ng) {
    Write-Host "ngrok ვერ მოიძებნა. დააყენე: winget install --id Ngrok.Ngrok -e --source winget" -ForegroundColor Red
    exit 1
}
Write-Host "ngrok ეშვება -> http://localhost:8000" -ForegroundColor Cyan
Write-Host "დააკოპირე 'Forwarding https://....ngrok-free.dev' მისამართი." -ForegroundColor Yellow
& $ng http 8000
