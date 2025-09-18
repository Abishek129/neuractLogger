Here’s the production brief you can drop to your codex agent:

**Objective (prod ship):** Create a separate **Python system-tray app** (“**PLC Agent Tray**”) that **keeps the FastAPI backend running in the background** and lets the user **start/stop/restart the backend and launch the existing UI** (`plc-logger-tray.exe`) from the tray. **Do not modify the UI app.**

**Scope & constraints**

- Backend is the current FastAPI agent (same codebase). Port must be **5175** by default; honor `AGENT_PORT` if set; write `agent.lock.json` as today.
- Tray must be **session-based (no Windows service)** and auto-start on user login (toggle).
- No changes to `plc-logger-tray.exe`; only **optionally launch it** from a tray menu.
- Production-grade packaging: **PyInstaller (onedir)** + **NSIS/Inno Setup** installer. No dev servers/tools included.

**Repo layout (new)**

- `apps/agent-tray/` (new project)

  - `main.py` (entry; PySide6 `QSystemTrayIcon`)
  - `process_manager.py` (spawn/monitor backend with `subprocess.Popen`)
  - `health.py` (poll `http://127.0.0.1:<port>/health`)
  - `autostart.py` (HKCU Run key or Startup shortcut)
  - `logging_conf.py` (rotating logs under `%ProgramData%\PLCLogger\agent\logs`)
  - `assets/tray.ico`

- Keep backend source as is (`agent/run_agent.py`).

**Tray behavior (requirements)**

- Single instance (Win32 mutex or file lock).
- Menu: **Start Agent**, **Stop Agent**, **Restart Agent**, **Open UI**, **Open Logs Folder**, **Autostart (✓)**, **Exit**.
- Status: tray icon reflects health: **green** when `/health` is `ok`, **red** when down; tooltip shows port and uptime.
- Process mgmt:

  - Start: spawn the backend **as a child process**, passing env `AGENT_PORT=5175`, `AGENT_STRICT_PORT=1`.
  - Capture stdout/stderr to rotating file logs (`agent.log`, 1MB x5) in `%ProgramData%\PLCLogger\agent\logs`.
  - Auto-restart if the child dies (exponential backoff 1s→5s, max 30s).
  - On **Exit/Stop**, terminate gracefully; if the backend doesn’t exit in 5s, kill.

- Health polling: every **2s** call `/health`; flip status.
- Autostart toggle:

  - Preferred: **HKCU\Software\Microsoft\Windows\CurrentVersion\Run** value `PLCLoggerAgentTray` → `"C:\Program Files\PLCLogger\agent-tray\plc-agent-tray.exe"`.
  - Alternative: Startup shortcut under `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`.

- “Open UI” behavior (do not change the UI app):

  - Try these paths in order and launch the first that exists:

    1. `%LOCALAPPDATA%\PLC Logger\plc-logger-tray.exe` (user install)
    2. `C:\Program Files\PLCLogger\ui\plc-logger-tray.exe` (machine install)

  - If neither exists, show a notification “UI not installed”.

- Port conflict handling: If something already binds 5175, show a blocking notification and offer **Retry**; do **not** auto-pick a new port (prod consistency).

**Packaging & install**

- Build **two executables** via PyInstaller (onedir):

  - `plc-agent-core.exe` from `agent/run_agent.py` (the backend), OR keep backend as a **module spawned via pythonw\.exe** inside the tray bundle. **Pick one**:

    - **Simplest** (preferred): **spawn the backend in-process** by importing `agent.run_agent:main()` in a dedicated thread and manage lifecycle. (Accept that a crash may bring down the tray—mitigated by watchdog restart of whole tray via a “relauncher” stub.)
    - **Safer isolation**: ship **`plc-agent-core.exe`** and have the tray spawn it (better crash isolation; slightly larger footprint).

  - `plc-agent-tray.exe` from `apps/agent-tray/main.py`.

- PyInstaller flags (guidance): `--noconfirm --clean --onedir --icon assets/tray.ico --name plc-agent-tray`.
- Installer (NSIS or Inno Setup):

  - Install to: `C:\Program Files\PLCLogger\agent-tray\`
  - Create Start Menu shortcut **PLC Agent Tray**.
  - Optionally check **Start on login** (sets HKCU Run).
  - On install/uninstall: **don’t touch** the UI app.

- Ensure **Microsoft Visual C++ runtimes** not required (PyInstaller onedir embeds what it needs).
- Sign binaries if you have a code-signing cert (reduces AV friction).

**Coexistence**

- If legacy **PLCLoggerSvc** service is present, **do not start it** and **do not install a new service**. The tray is the only runner.
- On first run, if the service is running on 5175, prompt user to stop/disable it (and offer a one-click stop).

**Prod configuration**

- Default port: **5175** (env-overridable).
- Keep your updated CORS config (must allow `http://tauri.localhost`).
- Lockfile path unchanged so the UI continues to read it.

**Deliverables**

1. `apps/agent-tray/` code with the modules listed above.
2. PyInstaller spec(s) committed.
3. NSIS/Inno script committed.
4. Icons/assets.
5. `README_tray.md` with runbook.
6. **Output artifacts** under `dist/agent-tray/` (tray) and, if chosen, `dist/agent-core/` (backend).

**Acceptance tests**

- Fresh Windows machine without Python installed:

  - Install package; **tray auto-starts on login** (if checked).
  - Tray shows **red**, then flips to **green** as backend comes up; `/health` returns `ok`.
  - `agent.lock.json` is created/updated; logs written to `%ProgramData%\PLCLogger\agent\logs`.
  - “Open UI” launches existing `plc-logger-tray.exe` if present; otherwise shows a friendly message.
  - Stop/Start/Restart work cleanly; logs reflect transitions; port stays on 5175.
  - On uninstall, tray removed, autostart removed; logs left in place (or prompt to clean).

**Copy/paste build & smoke-test commands (to include in `output.md`)**

```powershell
# From repo root, in a clean venv with PySide6/pywin32/requests installed
$ErrorActionPreference = "Stop"

# 1) Build tray (and backend core if using split model)
pyinstaller --noconfirm --clean --onedir --name plc-agent-tray --icon apps/agent-tray/assets/tray.ico apps/agent-tray/main.py
# Optional, if using separate backend exe:
# pyinstaller --noconfirm --clean --onedir --name plc-agent-core agent/run_agent.py

# 2) Make installer (NSIS/Inno) — provide scripts in repo:
# NSIS example:
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
```

**Notes**

- Choose the **split process** model (tray spawns `plc-agent-core.exe`) if you want hard isolation; otherwise the **in-process** model is smaller and simpler. Either satisfies the requirement; pick one and document it.
- Keep **plc-logger-tray.exe** untouched; only add a launcher menu item that looks in `%LOCALAPPDATA%\PLC Logger\plc-logger-tray.exe` then `C:\Program Files\PLCLogger\ui\plc-logger-tray.exe`.
