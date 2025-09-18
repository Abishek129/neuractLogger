param(
  [int]$Port = 5175
)

$ErrorActionPreference = 'Stop'

function Ensure-Port-Free([int]$p) {
  try { $conns = Get-NetTCPConnection -LocalPort $p -ErrorAction SilentlyContinue } catch { $conns = @() }
  if (-not $conns) { return }
  $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique | Where-Object { $_ -ne $null -and $_ -ne $PID }
  foreach ($id in $pids) {
    try { Stop-Process -Id $id -Force -ErrorAction Stop } catch {}
  }
}

# Free the agent port
Ensure-Port-Free -p $Port

Write-Host "Starting backend agent on port $Port..."
$env:AGENT_PORT = $Port
$env:AGENT_STRICT_PORT = "1"

# Run the backend only
python agent/run_agent.py
