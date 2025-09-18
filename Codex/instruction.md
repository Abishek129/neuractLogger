
# Production Build and Packaging Guide (Windows)

This guide produces a single MSI that installs the PLC Logger backend Agent (Python/FastAPI), registers it as a Windows service, and bundles the Desktop UI (Tauri). It reflects the current repo scripts and system details in `system.md` and `console.md`.

Audience: Windows 11, PowerShell users with admin rights for install.

---

## 0) Prerequisites (one‑time)

- Python 3.12+ on PATH (same interpreter used to package the Agent)
- Node.js 18+ and npm
- Rust toolchain + Tauri CLI
  - `npm i -g @tauri-apps/cli`
- WiX Toolset 3.14 (candle.exe, light.exe, heat.exe on PATH)
  - If installed to the default path, our script adds it to PATH automatically
- PowerShell with ExecutionPolicy allowing local scripts (we pass `-ExecutionPolicy Bypass` where needed)

Optional but recommended: Visual Studio C++ Build Tools for Rust/Tauri.

---

## 1) Prep Python environment

From repo root (open PowerShell):

PS> python -m pip install --upgrade pip
PS> python -m pip install -r requirements.txt

This installs FastAPI/Uvicorn plus optional modules used by diagnostics and connectors (icmplib, opcua, pymodbus, psutil, apscheduler, cryptography).

---

## 2) Build the Agent (PyInstaller)

Run the packaging script. It installs PyInstaller if missing, stops conflicting processes, cleans previous outputs, and produces a folderized build under `dist/plclogger-agent`.

PS> powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_agent.ps1

Expected outputs:
- `dist\plclogger-agent\plclogger-agent.exe` (Agent runner)
- `dist\plclogger-agent\agent_service.exe` (pywin32 service wrapper)

Hidden‑imports shipped: icmplib, opcua (+subpackages), psutil, pymodbus, apscheduler, sqlmodel/sqlalchemy, cryptography.

---

## 3) Build the Desktop UI (Tauri)

PS> Push-Location apps\desktop
PS> if (Test-Path package-lock.json) { npm ci } else { npm install }
PS> npm run build
PS> npm run tauri:build
PS> Pop-Location

Expected outputs:
- `apps\desktop\dist\` (web assets consumed by Tauri)
- `apps\desktop\src-tauri\target\release\...` (Desktop UI exe and bundles)

---

## 4) Build the MSI (WiX)

Harvest `dist\plclogger-agent` and the Tauri UI release folder, inject a Windows service for the Agent, and produce `installer\PLCLogger.msi`.

PS> powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_wix.ps1 -AgentDir 'dist\plclogger-agent' -Out 'installer\PLCLogger.msi'

Notes:
- The script auto‑detects the UI dir from `apps\desktop\src-tauri\target\release`. If detection fails, pass `-UiDir '<absolute\path\to\ui\folder>'`.
- Service wired: `PLCLoggerAgent` (pywin32 service using `agent_service.exe`).
- Install directories created by the MSI:
  - `C:\Program Files\PLCLogger\agent\` (Agent files)
  - `C:\Program Files\PLCLogger\ui\`    (UI files if harvested)
  - `C:\ProgramData\PLCLogger\agent\`   (lockfile + logs at runtime)

---

## 5) Install the MSI (Admin)

PS (Admin)> msiexec /i installer\PLCLogger.msi

The service `PLCLoggerAgent` is installed and set to Automatic start.

Start/Stop/Query service:
- Query: `sc query PLCLoggerAgent`
- Stop:  `sc stop PLCLoggerAgent`
- Start: `sc start PLCLoggerAgent`

Logs:
- Service/stdout: `C:\ProgramData\PLCLogger\agent\logs\service.out.log`
- Agent app:      `C:\ProgramData\PLCLogger\agent\logs\agent.log`

---

## 6) Post‑install verification

Fetch the token/port, then probe the API:

PS> $lf = "C:\\ProgramData\\PLCLogger\\agent\\agent.lock.json"
PS> $m  = Get-Content $lf -Raw | ConvertFrom-Json
PS> $p  = [int]$m.port; $t = $m.token
PS> $h  = @{ 'Authorization' = "Bearer $t"; 'X-Agent-Token' = $t }
PS> Invoke-RestMethod "http://127.0.0.1:$p/health"
PS> Invoke-RestMethod -Headers $h "http://127.0.0.1:$p/devices"
PS> Invoke-RestMethod -Headers $h -Method Post -ContentType 'application/json' -Body '{"target":"127.0.0.1","count":1,"timeoutMs":800}' "http://127.0.0.1:$p/networking/ping"
PS> Invoke-RestMethod -Headers $h -Method Post -ContentType 'application/json' -Body '{"endpoint":"opc.tcp://127.0.0.1:4840"}' "http://127.0.0.1:$p/networking/opcua/test"

Or run the helper:

PS> powershell -NoProfile -ExecutionPolicy Bypass -File scripts/verify_agent.ps1

Success criteria:
- `/health` returns ok
- `/networking/ping` does not return a missing‑module error (ICMP policy/timeout is acceptable)
- `/networking/opcua/test` does not return `OPCUA_PKG_MISSING` (connection errors without a server are acceptable)

---

## 7) Shipping

Distribute `installer\PLCLogger.msi`. Running it installs the Agent service and the Desktop UI. The Agent listens on `http://127.0.0.1:5175` and writes its lockfile + logs under ProgramData.

If you prefer the WinSW service flavor (`PLCLoggerSvc`) instead of the bundled pywin32 service (`PLCLoggerAgent`), reuse your existing WinSW EXE + XML and WiX wiring from your prior flow; the rest of this pipeline (Agent exe and UI build) remains the same.

---

## Troubleshooting

- Build fails at UI “Could not resolve entry module”: ensure `apps\desktop\index.html` exists and run `npm run build` before `npm run tauri:build`.
- MSI build errors: confirm WiX 3.x tools (heat/candle/light) on PATH.
- Service installed but API unreachable:
  - Check logs in `C:\ProgramData\PLCLogger\agent\logs\`
  - Verify Windows Firewall allows loopback; ensure `127.0.0.1:5175` is listening: `Get-NetTCPConnection -LocalPort 5175`
  - Restart service: `sc stop PLCLoggerAgent; sc start PLCLoggerAgent`
