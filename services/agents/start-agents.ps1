# Starts the team's KAVACH agents locally, each in its own window, offline (no AI key needed).
# Ports come from environment variables (defaults in brackets), so a conflict never needs a code change:
#   INTELLIGENCE_PORT [8001]  Incident Intelligence   (shreyakaushik878-cloud)  mock mode
#   DUPLICATE_PORT    [8002]  Duplicate Detection     (Yash Dadlani)             SQLite store in _data/
#   SUPERVISOR_PORT   [8003]  Supervisor              (Karanveer Singh Malhotra) mock mode
#   SANITATION_PORT   [8004]  Sanitation Planning     (Namrata Digarse)          rule-based
# (Verification, by MrBadDrip, runs inside the Kavach server itself.)
# Agents listen on 127.0.0.1 only: they are never exposed outside this laptop.
# First time only:
#   py -3.13 -m venv .venv
#   .\.venv\Scripts\python -m pip install fastapi "uvicorn[standard]" pydantic pydantic-settings httpx python-multipart python-dotenv pillow tzdata google-genai scikit-learn numpy sqlalchemy alembic
# Normally run through run-kavach.ps1 in the repository root, which also checks the ports first.

$root = $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
function PortOf([string]$name, [int]$default) { $v = [Environment]::GetEnvironmentVariable($name); if ($v -match '^\d+$') { [int]$v } else { $default } }
$pIntel = PortOf "INTELLIGENCE_PORT" 8001; $pDup = PortOf "DUPLICATE_PORT" 8002; $pSup = PortOf "SUPERVISOR_PORT" 8003; $pSan = PortOf "SANITATION_PORT" 8004
New-Item -ItemType Directory -Force (Join-Path $root "_data") | Out-Null
$dupDb = "sqlite:///" + ((Join-Path $root "_data\duplicates.db") -replace '\\', '/')

# Opens a new PowerShell window running $command. Encoded, so quotes and spaces survive.
function Start-KavachWindow([string]$title, [string]$command) {
  $full = "`$host.UI.RawUI.WindowTitle = '$title'; $command"
  $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($full))
  Start-Process powershell -ArgumentList "-NoExit", "-EncodedCommand", $encoded | Out-Null
}

# Duplicate store schema (alembic prints INFO lines on stderr; only the exit code matters).
Push-Location (Join-Path $root "duplicate-detection")
$env:KAVACH_DATABASE_URL = $dupDb
$prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"   # alembic logs to stderr; only its exit code matters
& $py -m alembic upgrade head 2>&1 | Out-Null
$ErrorActionPreference = $prev
if ($LASTEXITCODE -ne 0) { Write-Host "Duplicate store migration failed." -ForegroundColor Red }
Pop-Location

$agents = @(
  @{ name = "Incident Intelligence :$pIntel"; dir = "incident-intelligence"; env = "`$env:KAVACH_LLM_MODE = 'mock'"; args = "-m uvicorn kavach.main:app --app-dir src --host 127.0.0.1 --port $pIntel" },
  @{ name = "Duplicate Detection :$pDup"; dir = "duplicate-detection"; env = "`$env:KAVACH_DATABASE_URL = '$dupDb'"; args = "-m uvicorn app.main:app --host 127.0.0.1 --port $pDup" },
  @{ name = "Supervisor :$pSup"; dir = "supervisor\supervisor"; env = "`$env:KAVACH_LLM_MODE = 'mock'"; args = "-m uvicorn kavach.main:app --app-dir src --host 127.0.0.1 --port $pSup" },
  @{ name = "Sanitation :$pSan"; dir = "sanitation"; env = ""; args = "-m uvicorn main:app --host 127.0.0.1 --port $pSan" }
)
foreach ($a in $agents) {
  Start-KavachWindow "KAVACH agent - $($a.name)" "Set-Location '$(Join-Path $root $a.dir)'; $($a.env); & '$py' $($a.args)"
}
Write-Host "Started 4 agents on ports $pIntel, $pDup, $pSup, $pSan."

