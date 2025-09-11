param(
  [int]$Port = 5175,
  [int]$UiPort = 5173
)

$ErrorActionPreference = 'Stop'

function Ensure-Port-Free([int]$p) {
  try { $conns = Get-NetTCPConnection -LocalPort $p -ErrorAction SilentlyContinue } catch { $conns = @() }
  if (-not $conns) { return }
  $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique | Where-Object { $_ -ne $null -and $_ -ne $PID }
  foreach ($id in $pids) {
    try {
      Write-Warning "Killing process $id holding port $p"
      Stop-Process -Id $id -Force -ErrorAction Stop
    } catch {
      try {
        $cmd = "Stop-Process -Id $id -Force"
        Start-Process -Verb runAs powershell -ArgumentList "-NoProfile","-Command", $cmd | Out-Null
      } catch {}
    }
  }
}

function Try-Stop-AgentService() {
  try {
    $svc = sc.exe query PLCLoggerSvc 2>$null | Out-String
    if ($svc -and $svc -match "STATE") {
      Write-Host "Stopping PLCLoggerSvc service (if running)..."
      try { Start-Process sc.exe -Verb runAs -ArgumentList 'stop PLCLoggerSvc' | Out-Null } catch {}
      Start-Sleep -Seconds 2
    }
  } catch {}
}

function Wait-Port-Free([int]$p, [int]$timeoutSec = 10) {
  $deadline = (Get-Date).AddSeconds($timeoutSec)
  while ((Get-Date) -lt $deadline) {
    try { $c = Get-NetTCPConnection -LocalPort $p -ErrorAction SilentlyContinue } catch { $c = @() }
    if (-not $c) { return $true }
    Start-Sleep -Milliseconds 250
  }
  return $false
}

# Free and wait
Try-Stop-AgentService
Ensure-Port-Free -p $Port
Ensure-Port-Free -p $UiPort
if (-not (Wait-Port-Free -p $Port -timeoutSec 10)) { Write-Warning "Port $Port still busy after waits" }
if (-not (Wait-Port-Free -p $UiPort -timeoutSec 5)) { Write-Warning "UI Port $UiPort still busy after waits" }

Write-Host "Starting agent on port $Port..."
$env:AGENT_PORT = $Port
$env:AGENT_STRICT_PORT = "1"

# Do not set VITE_AGENT_BASE_URL in dev; UI will use /api via Vite proxy

$agent = Start-Process -PassThru -NoNewWindow python -ArgumentList "agent/run_agent.py" -WorkingDirectory "$PSScriptRoot\.."

# Wait for lockfile and read port+token, prefer LocalAppData (dev agent) over ProgramData (service)
$pdLock   = Join-Path $env:ProgramData   "PLCLogger\agent\agent.lock.json"
$laLock   = if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA "PLCLogger\agent\agent.lock.json" } else { $null }
$cwdLock  = Join-Path "$PSScriptRoot\.." "agent.dev.lock.json"

for ($i=0; $i -lt 80; $i++) {
  if ($laLock -and (Test-Path $laLock)) { break }
  if (Test-Path $pdLock) { break }
  if (Test-Path $cwdLock) { break }
  Start-Sleep -Milliseconds 250
}

function _tryReadJson([string]$path) { try { if (Test-Path $path) { return Get-Content $path -Raw | ConvertFrom-Json } } catch {}; return $null }

$data = $null
if ($laLock) { $data = _tryReadJson $laLock }
if (-not $data) { $data = _tryReadJson $cwdLock }
if (-not $data) { $data = _tryReadJson $pdLock }

if ($data) {
  $uiBase = "http://127.0.0.1:" + $data.port
  if ($data.token) { $env:VITE_AGENT_TOKEN = $data.token }
  Write-Host "Agent: $uiBase"
} else {
  Write-Warning "Could not read agent lockfile; checking agent process"
  try {
    if ($agent -and $agent.HasExited) {
      Write-Warning "Agent process exited (code $($agent.ExitCode)). Ensuring port free and retrying once."
      Try-Stop-AgentService
      Ensure-Port-Free -p $Port
      if (-not (Wait-Port-Free -p $Port -timeoutSec 10)) { Write-Warning "Port $Port remained busy" }
      $env:AGENT_PORT = $Port
      $env:AGENT_STRICT_PORT = "1"
      $agent = Start-Process -PassThru -NoNewWindow python -ArgumentList "agent/run_agent.py" -WorkingDirectory "$PSScriptRoot\.."
      Start-Sleep -Milliseconds 750
      if ($laLock) { $data = _tryReadJson $laLock }
      if (-not $data) { $data = _tryReadJson $cwdLock }
      if (-not $data) { $data = _tryReadJson $pdLock }
      if ($data) {
        $uiBase = "http://127.0.0.1:" + $data.port
        if ($data.token) { $env:VITE_AGENT_TOKEN = $data.token }
        Write-Host "Agent: $uiBase"
      }
    }
  } catch {}
}

# If agent fell back to a random port (shouldn't in strict), retry once
if ($data -and $data.port -ne $Port) {
  Write-Warning "Agent bound to $($data.port) instead of $Port. Retrying after ensuring port is free."
  try { if ($agent -ne $null) { Stop-Process -Id $agent.Id -Force -ErrorAction SilentlyContinue } } catch {}
  Try-Stop-AgentService
  Ensure-Port-Free -p $Port
  if (-not (Wait-Port-Free -p $Port -timeoutSec 10)) { Write-Warning "Port $Port remained busy" }
  $env:AGENT_PORT = $Port
  $env:AGENT_STRICT_PORT = "1"
  $agent = Start-Process -PassThru -NoNewWindow powershell -ArgumentList "-NoProfile","-Command","python","agent/run_agent.py" -WorkingDirectory "$PSScriptRoot\.."
  Start-Sleep -Milliseconds 750
  $data = $null
  if ($laLock) { $data = _tryReadJson $laLock }
  if (-not $data) { $data = _tryReadJson $cwdLock }
  if (-not $data) { $data = _tryReadJson $pdLock }
  if ($data) {
    $uiBase = "http://127.0.0.1:" + $data.port
    if ($data.token) { $env:VITE_AGENT_TOKEN = $data.token }
    Write-Host "Agent: $uiBase"
  }
}

Write-Host "Starting UI dev server..."
Push-Location "$PSScriptRoot\..\apps\desktop"
npm run dev -- --port $UiPort --strictPort
Pop-Location

if ($agent -ne $null) { try { Stop-Process -Id $agent.Id -Force } catch {} }
