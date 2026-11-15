# Starts the team's KAVACH agents locally, each in its own window, offline (no AI key needed).
#   8001 Incident Intelligence   (shreyakaushik878-cloud)  mock mode
#   8002 Duplicate Detection     (Yash Dadlani)            SQLite store in _data/
#   8003 Supervisor              (Karanveer Singh Malhotra) mock mode
#   8004 Sanitation Planning     (Namrata Digarse)          rule-based
# (Verification, by MrBadDrip, runs inside the Kavach server itself.)
# First time only:
#   py -3.13 -m venv .venv
#   .\.venv\Scripts\python -m pip install fastapi "uvicorn[standard]" pydantic pydantic-settings httpx python-multipart python-dotenv pillow tzdata google-genai scikit-learn numpy sqlalchemy alembic
# GeoSatya finds them through services/geosatya/.env (git-ignored):
#   INTELLIGENCE_URL=http://127.0.0.1:8001
#   DUPLICATE_DETECTION_URL=http://127.0.0.1:8002
#   SUPERVISOR_AGENT_URL=http://127.0.0.1:8003
#   SANITATION_AGENT_URL=http://127.0.0.1:8004

$root = $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
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
& $py -m alembic upgrade head 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host "Duplicate store migration failed." -ForegroundColor Red }
Pop-Location

$agents = @(
  @{ name = "Incident Intelligence :8001"; dir = "incident-intelligence"; env = "`$env:KAVACH_LLM_MODE = 'mock'"; args = "-m uvicorn kavach.main:app --app-dir src --host 127.0.0.1 --port 8001" },
  @{ name = "Duplicate Detection :8002"; dir = "duplicate-detection"; env = "`$env:KAVACH_DATABASE_URL = '$dupDb'"; args = "-m uvicorn app.main:app --host 127.0.0.1 --port 8002" },
  @{ name = "Supervisor :8003"; dir = "supervisor\supervisor"; env = "`$env:KAVACH_LLM_MODE = 'mock'"; args = "-m uvicorn kavach.main:app --app-dir src --host 127.0.0.1 --port 8003" },
  @{ name = "Sanitation :8004"; dir = "sanitation"; env = ""; args = "-m uvicorn main:app --host 127.0.0.1 --port 8004" }
)
foreach ($a in $agents) {
  Start-KavachWindow "KAVACH agent - $($a.name)" "Set-Location '$(Join-Path $root $a.dir)'; $($a.env); & '$py' $($a.args)"
}
Write-Host "Started 4 agents. Check: http://127.0.0.1:8001/health  :8002/docs  :8003/health  :8004/health"
