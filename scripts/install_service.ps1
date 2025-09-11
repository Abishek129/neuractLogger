param(
  [ValidateSet('install','remove','start','stop')]
  [string]$Action = 'install'
)

$ErrorActionPreference = 'Stop'

# Check admin (required for install/remove)
try {
  $isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
} catch { $isAdmin = $false }
if (($Action -in @('install','remove')) -and -not $isAdmin) {
  Write-Warning 'Please run PowerShell as Administrator to install/remove the service.'
}

# Ensure pywin32 is available for service wrapper
try {
  $null = & python -c "import importlib; importlib.import_module('win32serviceutil'); print('ok')" 2>$null
} catch {
  try { & python -m pip install --quiet pywin32 } catch { Write-Warning 'Failed to install pywin32'; }
}

$svcScript = Join-Path $PSScriptRoot '..\agent\agent_service.py'

switch ($Action) {
  'install' {
    & python $svcScript install
    & python $svcScript start
    # Configure recovery: restart on failure after 5s, reset counter after 60s
    & sc.exe failure PLCLoggerAgent reset= 60 actions= restart/5000
    Write-Host 'Service installed and started.'
  }
  'remove' {
    try { & python $svcScript stop } catch {}
    & python $svcScript remove
    Write-Host 'Service removed.'
  }
  'start' { & python $svcScript start }
  'stop'  { & python $svcScript stop }
}
param(
  [ValidateSet('install','remove','start','stop')]
  [string]$Action = 'install'
)

$ErrorActionPreference = 'Stop'

# Check admin (required for install/remove)
try {
  $isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
} catch { $isAdmin = $false }
if (($Action -in @('install','remove')) -and -not $isAdmin) {
  Write-Warning 'Please run PowerShell as Administrator to install/remove the service.'
}

# Ensure pywin32 is available for service wrapper (only for install/remove)
if ($Action -in @('install','remove')) {
  try {
    $null = & python -c "import importlib; importlib.import_module('win32serviceutil'); print('ok')" 2>$null
  } catch {
    try { & python -m pip install --quiet pywin32 } catch { Write-Warning 'Failed to install pywin32'; }
  }
}

$svcScript = Join-Path $PSScriptRoot '..\agent\agent_service.py'

switch ($Action) {
  'install' {
    & python $svcScript install
    & python $svcScript start
    # Ensure start type is Automatic
    & sc.exe config PLCLoggerAgent start= auto
    # Configure recovery: restart on failure after 5s, reset counter after 60s
    & sc.exe failure PLCLoggerAgent reset= 60 actions= restart/5000
    Write-Host 'Service installed and started.'
  }
  'remove' {
    try { & python $svcScript stop } catch {}
    & python $svcScript remove
    Write-Host 'Service removed.'
  }
  'start' { & python $svcScript start }
  'stop'  { & python $svcScript stop }
}
