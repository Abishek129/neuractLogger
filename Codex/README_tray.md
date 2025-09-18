PLC Agent Tray

Overview
- Windows system-tray app that manages the FastAPI backend (plc-agent-core), with start/stop/restart, health indicator, autostart toggle, and quick links.
- Default port 5175; honors AGENT_PORT if set; strict port enforced.
- Writes rotating logs to %ProgramData%\PLCLogger\agent\logs.

Repo Layout
- apps/agent-tray/main.py: PySide6 QSystemTrayIcon UI
- apps/agent-tray/process_manager.py: spawn/monitor backend process
- apps/agent-tray/health.py: HTTP polling of /health
- apps/agent-tray/autostart.py: HKCU Run key or Startup shortcut
- apps/agent-tray/logging_conf.py: rotating logging
- plc-agent-tray.spec / plc-agent-core.spec: PyInstaller specs
- installers/nsis/plc-agent-tray.nsi: NSIS installer script

Build (dev)
1) Create venv and install deps:
   - pip install -r requirements.txt
   - pip install -r apps/agent-tray/requirements.txt
2) Build executables:
   - pyinstaller --noconfirm --clean plc-agent-tray.spec
   - pyinstaller --noconfirm --clean plc-agent-core.spec
3) Make installer:
   - makensis installers\nsis\plc-agent-tray.nsi

Install & Run
- Install to C:\Program Files\PLCLogger\agent-tray (admin required)
- Launch plc-agent-tray.exe; tray icon turns green when healthy
- Use context menu to start/stop/restart, open UI, open logs, toggle autostart

Notes
- If port 5175 is busy, a dialog offers Retry or Cancel (no auto port switching in production).
- UI launcher looks for:
  1) %LOCALAPPDATA%\PLC Logger\plc-logger-tray.exe
  2) C:\Program Files\PLCLogger\ui\plc-logger-tray.exe
- Coexistence: If a legacy PLCLoggerSvc is running on 5175, stop/disable it before using the tray runner.

