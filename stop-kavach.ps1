# Stops KAVACH: the server, the team agents, the Cloudflare tunnel and their windows.
#   powershell -ExecutionPolicy Bypass -File D:\Desktop\Kavach-epam-team\stop-kavach.ps1
# Only processes that are clearly KAVACH ones are stopped. Anything else on those ports is reported and left alone.
$names = "KAVACH_PORT", "INTELLIGENCE_PORT", "DUPLICATE_PORT", "SUPERVISOR_PORT", "SANITATION_PORT"
$defaults = @(8000, 8001, 8002, 8003, 8004)
for ($i = 0; $i -lt $names.Count; $i++) {
  $v = [Environment]::GetEnvironmentVariable($names[$i]); $port = if ($v -match '^\d+$') { [int]$v } else { $defaults[$i] }
  $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $c) { Write-Host "port $port : free"; continue }
  $p = Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)" -ErrorAction SilentlyContinue
  if ([string]$p.CommandLine -match 'Kavach-epam-team|geosatya\.main') { Stop-Process -Id $c.OwningProcess -Force; Write-Host "port $port : stopped KAVACH process $($c.OwningProcess)" }
  else { Write-Host "port $port : used by $($p.Name) (pid $($c.OwningProcess)), not a KAVACH process, left alone" -ForegroundColor Yellow }
}
Get-Process cloudflared -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.Id -Force; Write-Host "stopped cloudflared $($_.Id)" }
# Close the windows the run script opened (their command contains KAVACH).
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object { $_.CommandLine -like "*-EncodedCommand*" } | ForEach-Object {
  $enc = ($_.CommandLine -split "-EncodedCommand\s+")[1].Trim().Split(" ")[0]
  try { $text = [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String($enc)) } catch { return }
  if ($text -match "KAVACH (server|tunnel|agent)") { Stop-Process -Id $_.ProcessId -Force }
}
Write-Host "Done."
