# RUN KAVACH: starts the team agents, the KAVACH server and a Cloudflare HTTPS tunnel, verifies each one,
# and prints the link only once it has been checked from the outside.
#
#   powershell -ExecutionPolicy Bypass -File D:\Desktop\Kavach-epam-team\run-kavach.ps1
#
# Options:  -NoTunnel          laptop only (no Cloudflare link)
#           -StopOldKavach     stop leftover KAVACH processes on the ports (only ones whose command line is a KAVACH one)
#           -AccessCode abc123 use this code instead of a random one (6+ characters)
#           -WorkerCode / -SupervisorCode / -AdminCode   sign-in access codes (6+ characters; random if not given)
#           -RealLogin         real sign-in only (JWT). Without it the server runs in development access mode:
#                              no login, a role switcher picks a test identity (refused when APP_ENV=production).
#           -Demo              kept for old habits; development access is now the default
#           -TeamDemo          team live demo: its own database (data\kavach_team_demo.db) with only the ten team members,
#                              and a sign-in screen that accepts any password. Your normal database is not touched.
# Sign-in: citizens register themselves; workers need the worker code; supervisors need an account created with
# services\geosatya\scripts\kavach_accounts.py plus the supervisor code (platform admins: the admin code).
# Ports (environment variables, defaults in brackets):
#   KAVACH_PORT [8000]  INTELLIGENCE_PORT [8001]  DUPLICATE_PORT [8002]  SUPERVISOR_PORT [8003]  SANITATION_PORT [8004]
# Optional:  KAVACH_PYTHON (python used for the server), CORS_ORIGINS (only if the frontend is hosted elsewhere).
# Nothing is written to a file: the access code lives only in the server's environment and in this window's output.
# A process that is not a KAVACH one is never stopped; you are told what it is and which free port to use instead.

param([switch]$NoTunnel, [switch]$StopOldKavach, [string]$AccessCode = "", [string]$WorkerCode = "", [string]$SupervisorCode = "",
      [string]$AdminCode = "", [switch]$Demo, [switch]$RealLogin, [switch]$TeamDemo)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$geo = Join-Path $root "services\geosatya"
$agentsDir = Join-Path $root "services\agents"
$logDir = Join-Path $agentsDir "_data"
New-Item -ItemType Directory -Force $logDir | Out-Null

function PortOf([string]$name, [int]$default) { $v = [Environment]::GetEnvironmentVariable($name); if ($v -match '^\d+$') { [int]$v } else { $default } }
$ports = [ordered]@{ KAVACH_PORT = PortOf "KAVACH_PORT" 8000; INTELLIGENCE_PORT = PortOf "INTELLIGENCE_PORT" 8001; DUPLICATE_PORT = PortOf "DUPLICATE_PORT" 8002
                     SUPERVISOR_PORT = PortOf "SUPERVISOR_PORT" 8003; SANITATION_PORT = PortOf "SANITATION_PORT" 8004 }
$py = $env:KAVACH_PYTHON
if (-not $py) { foreach ($c in @("D:\Desktop\Kavach-epam\.venv\Scripts\python.exe", (Join-Path $geo ".venv\Scripts\python.exe"))) { if (Test-Path $c) { $py = $c; break } } }
if (-not $py -or -not (Test-Path $py)) { Write-Host "Python for the KAVACH server was not found. Set KAVACH_PYTHON to its python.exe." -ForegroundColor Red; exit 1 }
if (-not $NoTunnel -and -not (Get-Command cloudflared -ErrorAction SilentlyContinue)) { Write-Host "cloudflared is not installed (winget install --id Cloudflare.cloudflared). Use -NoTunnel for laptop only." -ForegroundColor Red; exit 1 }

function Get-PortOwner([int]$port) {
  $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $c) { return $null }
  $p = Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)" -ErrorAction SilentlyContinue
  $cmd = [string]$p.CommandLine
  [pscustomobject]@{ Port = $port; ProcessId = $c.OwningProcess; Name = [string]$p.Name; Command = $cmd; IsKavach = ($cmd -match 'Kavach-epam-team|geosatya\.main') }
}
function Next-FreePort([int]$from) { for ($p = $from + 10; $p -lt $from + 200; $p++) { if (-not (Get-PortOwner $p)) { return $p } } return $null }

# 1. Ports. Never stop anything that is not a KAVACH process.
$blocked = @()
foreach ($kv in $ports.GetEnumerator()) {
  $owner = Get-PortOwner $kv.Value
  if (-not $owner) { continue }
  if ($owner.IsKavach -and $StopOldKavach) { Write-Host "Stopping old KAVACH process on port $($kv.Value) (pid $($owner.ProcessId))" -ForegroundColor Yellow; Stop-Process -Id $owner.ProcessId -Force; Start-Sleep -Milliseconds 800; continue }
  $blocked += [pscustomobject]@{ Var = $kv.Key; Owner = $owner; Suggest = (Next-FreePort $kv.Value) }
}
if ($blocked) {
  Write-Host "`nSome ports are already in use. Nothing was started." -ForegroundColor Red
  foreach ($b in $blocked) {
    $o = $b.Owner
    Write-Host ("  port {0} is used by {1} (pid {2}) {3}" -f $o.Port, $o.Name, $o.ProcessId, $(if ($o.IsKavach) { "- looks like an old KAVACH process: run again with -StopOldKavach" } else { "- NOT a KAVACH process, so it was left alone" }))
    Write-Host ("      its command: {0}" -f $o.Command.Substring(0, [Math]::Min(120, $o.Command.Length)))
    if (-not $o.IsKavach) { Write-Host ("      safe alternative: set `$env:{0} = {1} and run again" -f $b.Var, $b.Suggest) }
  }
  exit 2
}

# 2. Access code (6+ characters). Random unless you give one.
if ($AccessCode.Length -ge 1 -and $AccessCode.Length -lt 6) { Write-Host "-AccessCode must be at least 6 characters." -ForegroundColor Red; exit 1 }
if (-not $AccessCode) { $AccessCode = ((Get-Random -InputObject @("tiger", "maple", "river", "comet", "lotus", "amber", "cedar", "pearl")) + (Get-Random -Minimum 1000 -Maximum 9999)) }
# Sign-in codes and the token secret: random for this run unless given. Held only in the server's environment.
function New-Code([string]$prefix) { "$prefix-" + (Get-Random -Minimum 100000 -Maximum 999999) }
foreach ($c in @($WorkerCode, $SupervisorCode, $AdminCode)) { if ($c.Length -ge 1 -and $c.Length -lt 6) { Write-Host "Access codes must be at least 6 characters." -ForegroundColor Red; exit 1 } }
if (-not $WorkerCode) { $WorkerCode = New-Code "worker" }
if (-not $SupervisorCode) { $SupervisorCode = New-Code "super" }
if (-not $AdminCode) { $AdminCode = New-Code "admin" }
$bytes = New-Object byte[] 48; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$JwtSecret = [Convert]::ToBase64String($bytes)
# Development phase: open the app without logging in (demo identities + role switcher). -RealLogin restores JWT-only.
$Demo = -not $RealLogin
$AuthMode = if ($Demo) { "demo" } else { "jwt" }

function Start-KavachWindow([string]$title, [string]$command) {
  $full = "`$host.UI.RawUI.WindowTitle = '$title'; $command"
  $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($full))
  Start-Process powershell -ArgumentList "-NoExit", "-EncodedCommand", $encoded | Out-Null
}
function Wait-Http([string]$url, [int]$seconds) {
  $until = (Get-Date).AddSeconds($seconds)
  while ((Get-Date) -lt $until) { try { if ((Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 4).StatusCode -lt 500) { return $true } } catch { Start-Sleep -Milliseconds 800 } }
  return $false
}

# 3. Agents, then the server (agent addresses go to the server through its environment).
foreach ($kv in $ports.GetEnumerator()) { [Environment]::SetEnvironmentVariable($kv.Key, [string]$kv.Value, "Process") }
Write-Host "Starting the team agents..."
& (Join-Path $agentsDir "start-agents.ps1") | Out-Null
$p = $ports
$serverEnv = "`$env:ACCESS_CODE = '$AccessCode'; `$env:ACCESS_COOKIE_HOURS = '12'; `$env:AUTH_MODE = '$AuthMode'; `$env:JWT_SECRET = '$JwtSecret'; " +
             "`$env:WORKER_ACCESS_CODE = '$WorkerCode'; `$env:SUPERVISOR_ACCESS_CODE = '$SupervisorCode'; `$env:ADMIN_ACCESS_CODE = '$AdminCode'; " +
             "`$env:INTELLIGENCE_URL = 'http://127.0.0.1:$($p.INTELLIGENCE_PORT)'; " +
             "`$env:DUPLICATE_DETECTION_URL = 'http://127.0.0.1:$($p.DUPLICATE_PORT)'; `$env:SUPERVISOR_AGENT_URL = 'http://127.0.0.1:$($p.SUPERVISOR_PORT)'; " +
             "`$env:SANITATION_AGENT_URL = 'http://127.0.0.1:$($p.SANITATION_PORT)'"
if ($TeamDemo) {
  if ($RealLogin) { Write-Host "-TeamDemo and -RealLogin can't be used together." -ForegroundColor Red; exit 2 }
  $teamDb = (Join-Path $geo "data\kavach_team_demo.db").Replace('\', '/')
  $teamFiles = Join-Path $geo "private_uploads_team"
  $serverEnv += "; `$env:TEAM_DEMO = '1'; `$env:SEED_DEMO_DATA = 'false'; `$env:DATABASE_URL = 'sqlite:///$teamDb'; `$env:STORAGE_DIR = '$teamFiles'"
}
Write-Host "Starting the KAVACH server..."
Start-KavachWindow "KAVACH server :$($p.KAVACH_PORT)" "$serverEnv; Set-Location '$geo'; & '$py' -m uvicorn geosatya.main:create_app --factory --host 127.0.0.1 --port $($p.KAVACH_PORT)"

# 4. Verify locally: every service must answer, and the server must reach every agent.
$checks = [ordered]@{
  "KAVACH server" = "http://127.0.0.1:$($p.KAVACH_PORT)/health"; "Incident Intelligence" = "http://127.0.0.1:$($p.INTELLIGENCE_PORT)/health"
  "Duplicate Detection" = "http://127.0.0.1:$($p.DUPLICATE_PORT)/docs"; "Supervisor" = "http://127.0.0.1:$($p.SUPERVISOR_PORT)/health"
  "Sanitation" = "http://127.0.0.1:$($p.SANITATION_PORT)/health" }
$failed = @()
foreach ($c in $checks.GetEnumerator()) {
  $ok = Wait-Http $c.Value 90
  Write-Host ("  {0,-22} {1}" -f $c.Key, $(if ($ok) { "OK" } else { "NOT RESPONDING" })) -ForegroundColor $(if ($ok) { "Green" } else { "Red" })
  if (-not $ok) { $failed += $c.Key }
}
$base = "http://127.0.0.1:$($p.KAVACH_PORT)"
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
try { Invoke-WebRequest "$base/access" -Method Post -Body @{ code = $AccessCode } -WebSession $session -UseBasicParsing -MaximumRedirection 0 -ErrorAction Stop | Out-Null } catch { }
try {
  $st = (Invoke-RestMethod "$base/api/v1/kavach/agents/status" -WebSession $session -TimeoutSec 10).agents
  foreach ($a in $st) { Write-Host ("  server -> {0,-22} configured={1} reachable={2}" -f $a.agent, $a.configured, $a.reachable) -ForegroundColor $(if ($a.reachable) { "Green" } else { "Yellow" }) }
} catch { Write-Host "  could not read the agent status through the server: $($_.Exception.Message)" -ForegroundColor Yellow; $failed += "agent status" }
try {
  $opt = Invoke-RestMethod "$base/api/v1/auth/options" -WebSession $session -TimeoutSec 10
  $authOk = ($opt.auth_mode -eq $AuthMode -and $opt.worker_registration -and $opt.supervisor_login -and $opt.admin_login)
  Write-Host ("  sign-in                {0} (mode {1}, worker registration {2}, supervisor sign-in {3})" -f $(if ($authOk) { "OK" } else { "NOT READY" }), $opt.auth_mode, $opt.worker_registration, $opt.supervisor_login) -ForegroundColor $(if ($authOk) { "Green" } else { "Red" })
  if (-not $authOk) { $failed += "sign-in" }
} catch { Write-Host "  could not read the sign-in options: $($_.Exception.Message)" -ForegroundColor Yellow; $failed += "sign-in" }
if ($failed) { Write-Host "`nSome services are not healthy: $($failed -join ', '). No link was created." -ForegroundColor Red; exit 3 }

Write-Host "`nKAVACH is running on this laptop:  $base" -ForegroundColor Green
Write-Host "Access code (needed on every device): $AccessCode"
function Show-SignInCodes {
  Write-Host "Worker access code (to register a field worker):   $WorkerCode"
  Write-Host "Supervisor access code (with a supervisor account): $SupervisorCode"
  Write-Host "Admin access code (platform admin accounts only):   $AdminCode"
  Write-Host "Supervisor accounts: cd $geo ; & '$py' scripts\kavach_accounts.py list   (create-supervisor / set-login, password typed hidden)"
  if ($TeamDemo) { Write-Host "Team live demo: only the 10 team members; tap your name on the sign-in screen, password kavach123 (any password works)." -ForegroundColor Yellow }
  elseif ($Demo) { Write-Host "Development access is ON: no login needed; switch roles from the bar at the top (anyone with the link and the access code can). Use -RealLogin for real sign-in." -ForegroundColor Yellow }
  Write-Host "Codes and the token secret are new for each run; people sign in again after a restart."
}
Show-SignInCodes
if ($NoTunnel) { exit 0 }

# 5. Cloudflare tunnel. The link is only printed after it has been tested from outside.
# A new log file each run: an old tunnel window can keep the previous one open (and its old link must never be read).
$log = Join-Path $logDir ("tunnel-{0:yyyyMMdd-HHmmss}.log" -f (Get-Date))
Get-ChildItem $logDir -Filter "tunnel*.log" -ErrorAction SilentlyContinue | Where-Object { $_.FullName -ne $log } | Remove-Item -ErrorAction SilentlyContinue
Write-Host "Starting the Cloudflare tunnel..."
Start-KavachWindow "KAVACH tunnel" "cloudflared tunnel --url http://localhost:$($p.KAVACH_PORT) 2>&1 | Tee-Object -FilePath '$log'"
$link = $null
for ($i = 0; $i -lt 45 -and -not $link; $i++) { Start-Sleep -Seconds 2; if (Test-Path $log) { $m = Select-String -Path $log -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" | Select-Object -First 1; if ($m) { $link = $m.Matches[0].Value } } }
if (-not $link) { Write-Host "The tunnel did not give a link. Look at the 'KAVACH tunnel' window." -ForegroundColor Red; exit 4 }
# A new quick-tunnel address can take a little while to resolve; retry for up to 90 seconds.
$verified = $false; $detail = ""
for ($try = 0; $try -lt 18 -and -not $verified; $try++) {
  Start-Sleep -Seconds 5
  try {
    $h = (Invoke-WebRequest "$link/health" -UseBasicParsing -TimeoutSec 15).StatusCode
    $gated = $false; try { Invoke-WebRequest "$link/api/v1/config" -UseBasicParsing -TimeoutSec 15 | Out-Null } catch { $gated = ([int]$_.Exception.Response.StatusCode -eq 401) }
    $s2 = New-Object Microsoft.PowerShell.Commands.WebRequestSession; $accepted = $false
    try { $r2 = Invoke-WebRequest "$link/access" -Method Post -Body @{ code = $AccessCode } -WebSession $s2 -UseBasicParsing -MaximumRedirection 0 -TimeoutSec 40 -ErrorAction Stop; $accepted = ([int]$r2.StatusCode -in 301, 302, 303, 307) } catch { if ($_.Exception.Response) { $accepted = ([int]$_.Exception.Response.StatusCode -in 301, 302, 303, 307) } }   # a redirect arrives as a response or as an error, depending on the PowerShell version
    $verified = ($h -eq 200 -and $gated -and $accepted); $detail = "health=$h locked-without-code=$gated code-accepted=$accepted"
  } catch { $detail = $_.Exception.Message }
}
if (-not $verified) { Write-Host "The tunnel started but did not pass the check ($detail). Link NOT confirmed: $link" -ForegroundColor Red; exit 5 }

Write-Host "`n==================== READY ====================" -ForegroundColor Green
Write-Host "Link (open on any phone or laptop): $link"
Write-Host "Access code:                        $AccessCode"
Show-SignInCodes
Write-Host "Checked from outside: $detail"
Write-Host "This is a temporary development link, not a production deployment. Keep this laptop on; close the KAVACH windows (or run stop-kavach.ps1) to stop everything."


