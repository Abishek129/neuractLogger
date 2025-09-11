# Build Agent (PyInstaller)
# Usage: powershell -ExecutionPolicy Bypass -File scripts/build_agent.ps1

$ErrorActionPreference = 'Stop'

$ROOT = Split-Path $PSScriptRoot -Parent
Push-Location $ROOT

# Ensure pyinstaller
try { & python -m PyInstaller --version | Out-Null } catch { & python -m pip install pyinstaller }

# Install runtime deps
$req = Join-Path $ROOT 'requirements.txt'
if (Test-Path $req) {
  try { & python -m pip install -r $req } catch { Write-Warning 'requirements install failed'; }
} else {
  Write-Warning "requirements.txt not found at $req"
}

# Ensure pywin32 for building service wrapper
try { & python -c "import win32serviceutil" 2>$null } catch { try { & python -m pip install pywin32 } catch { Write-Warning 'pywin32 install failed'; } }

# Best-effort: stop any running agent processes that could lock files
try {
  foreach ($n in @('plclogger-agent','agent_service')) {
    Get-Process -Name $n -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  }
  Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" 2>$null |
    Where-Object { $_.CommandLine -match 'agent\\run_agent.py' } |
    ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue } catch {} }
} catch {}

# Clean dist/build (tolerate locks; rename on failure)
if (Test-Path 'dist') {
  try { Remove-Item -Recurse -Force 'dist' -ErrorAction Stop }
  catch {
    Write-Warning ("Could not remove 'dist': " + $_.Exception.Message)
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    try { Rename-Item 'dist' ("dist_old_" + $stamp) -ErrorAction Stop; Write-Host "Renamed locked 'dist' -> dist_old_$stamp" }
    catch { Write-Warning "Could not rename 'dist' either; continuing." }
  }
}
if (Test-Path 'build') {
  try { Remove-Item -Recurse -Force 'build' -ErrorAction Stop }
  catch {
    Write-Warning ("Could not remove 'build': " + $_.Exception.Message)
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    try { Rename-Item 'build' ("build_old_" + $stamp) -ErrorAction Stop; Write-Host "Renamed locked 'build' -> build_old_$stamp" }
    catch { Write-Warning "Could not rename 'build' either; continuing." }
  }
}

# Clean old outputs for service exe as well
if (Test-Path 'dist\\agent_service.exe') { Remove-Item -Force 'dist\\agent_service.exe' -ErrorAction SilentlyContinue }

# Bundle agent runner
$opts = @(
  '--noconfirm',
  '--onedir',
  '--name', 'plclogger-agent',
  # Core stack
  '--hidden-import', 'fastapi',
  '--hidden-import', 'uvicorn',
  '--hidden-import', 'sqlalchemy',
  '--hidden-import', 'sqlmodel',
  '--hidden-import', 'apscheduler',
  # Optional diagnostics/connectors expected by endpoints
  '--hidden-import', 'icmplib',
  '--hidden-import', 'psutil',
  '--hidden-import', 'pymodbus',
  '--hidden-import', 'opcua',
  '--hidden-import', 'opcua.ua',
  '--hidden-import', 'opcua.common',
  '--hidden-import', 'opcua.crypto',
  '--hidden-import', 'cryptography',
  'agent/run_agent.py'
)
& python -m PyInstaller @opts

# Build Windows Service executable (onefile) and place into agent folder
$svcOpts = @(
  '--noconfirm',
  '--onefile',
  '--name', 'agent_service',
  '--hidden-import', 'win32serviceutil',
  '--hidden-import', 'win32service',
  '--hidden-import', 'win32event',
  '--hidden-import', 'servicemanager',
  'agent/agent_service.py'
)
& python -m PyInstaller @svcOpts

# Copy service exe into agent dist folder so a single folder contains all bits
if (Test-Path 'dist\\agent_service.exe') {
  Copy-Item -Force 'dist\\agent_service.exe' 'dist\\plclogger-agent\\agent_service.exe'
}

Pop-Location

Write-Host 'Agent build complete. Output under dist/plclogger-agent/'
