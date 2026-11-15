# KAVACH live demo: starts the team agents, the Kavach server and a Cloudflare
# HTTPS tunnel, each in its own window. Run from PowerShell:
#   powershell -ExecutionPolicy Bypass -File D:\Desktop\Kavach-epam-team\start-kavach-demo.ps1
# The access code you type is kept only in memory for this run (never saved to a file).
# Stop everything: close the KAVACH windows.

$root = $PSScriptRoot
$geo = Join-Path $root "services\geosatya"
$agents = Join-Path $root "services\agents"
$py = "D:\Desktop\Kavach-epam\.venv\Scripts\python.exe"

function Start-KavachWindow([string]$title, [string]$command) {
  $full = "`$host.UI.RawUI.WindowTitle = '$title'; $command"
  $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($full))
  Start-Process powershell -ArgumentList "-NoExit", "-EncodedCommand", $encoded | Out-Null
}

# 1. Nothing may already be using the ports.
$busy = 8000..8004 | Where-Object { Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue }
if ($busy) { Write-Host "Ports already in use: $($busy -join ', '). Close the old KAVACH windows first." -ForegroundColor Red; exit 1 }
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) { Write-Host "cloudflared is not installed: winget install --id Cloudflare.cloudflared" -ForegroundColor Red; exit 1 }

# 2. Access code for phones (6+ characters). Share it with your team by message, not in the repo.
do {
  $secure = Read-Host "Choose a demo access code (6+ characters)" -AsSecureString
  $code = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
} while ($code.Length -lt 6)

# 3. Team agents (Intelligence 8001, Duplicate 8002, Supervisor 8003, Sanitation 8004).
& (Join-Path $agents "start-agents.ps1")
Start-Sleep -Seconds 6

# 4. Kavach server. The code goes to that window through its environment, not its command line.
$env:ACCESS_CODE = $code
$env:ACCESS_COOKIE_HOURS = "12"
Start-KavachWindow "KAVACH server :8000" "Set-Location '$geo'; & '$py' -m uvicorn geosatya.main:create_app --factory --host 127.0.0.1 --port 8000"
Start-Sleep -Seconds 2
Remove-Item Env:ACCESS_CODE
$code = $null
Start-Sleep -Seconds 4

# 5. Temporary HTTPS link for phones.
Start-KavachWindow "KAVACH tunnel" "cloudflared tunnel --url http://localhost:8000"

Write-Host ""
Write-Host "Laptop:  http://localhost:8000" -ForegroundColor Green
Write-Host "Phones:  in the 'KAVACH tunnel' window, look for  https://....trycloudflare.com" -ForegroundColor Green
Write-Host "Share that link + your access code with the team (WhatsApp)."
