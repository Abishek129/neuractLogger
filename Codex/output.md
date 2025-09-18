# Build & Smoke-Test Commands

# From repo root, in a clean venv with PySide6/pywin32/requests installed
$ErrorActionPreference = "Stop"

# 1) Build tray (and backend core if using split model)
pyinstaller --noconfirm --clean --onedir --name plc-agent-tray --icon apps/desktop/src-tauri/icons/icon.ico apps/agent-tray/main.py
pyinstaller --noconfirm --clean --onedir --name plc-agent-core agent/run_agent.py

# 2) Make installer (NSIS)
makensis installers\nsis\plc-agent-tray.nsi

# 3) Install silently to Program Files, then launch
Start-Process "dist\installer\PLC_Agent_Tray_Setup.exe" -ArgumentList "/S" -Wait
Start-Process "C:\Program Files\PLCLogger\agent-tray\plc-agent-tray.exe"

# 4) Verify backend health (expect ok)
$Lock = "C:\ProgramData\PLCLogger\agent\agent.lock.json"
Start-Sleep -Seconds 2
$L = Get-Content $Lock -Raw | ConvertFrom-Json
$Base = "http://127.0.0.1:$($L.port)"
Invoke-RestMethod "$Base/health" -TimeoutSec 5

# 5) Verify CORS preflight (expect allow-origin = http://tauri.localhost)
try {
  $pre = Invoke-WebRequest -Method Options -Uri "$Base/networking/ping" -Headers @{
    Origin='http://tauri.localhost'
    'Access-Control-Request-Method'='POST'
    'Access-Control-Request-Headers'='authorization,content-type,x-agent-token'
  } -TimeoutSec 8
  "ALLOW-ORIGIN=" + $pre.Headers['access-control-allow-origin']
} catch { "Preflight ERR: $($_.Exception.Message)" }
