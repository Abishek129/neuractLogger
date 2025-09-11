# instructions.py

# PLC Logger â€” Build & Install Guide (Production)

# Run: python instructions.py (prints the guide)

# Or: type instructions.py (to read inline)

INSTRUCTIONS = r"""
PLC Logger â€” Build and Install (Single MSI, Always-On Agent + Desktop UI)
===========================================================================

This guide produces a single MSI that installs:

- The **Agent** as an always-on Windows **Service** (jobs run even if UI is closed)
- The **Desktop UI** (Tauri) with Start Menu / Desktop shortcuts (optional)

It also covers the #1 post-install pitfall (UI canâ€™t reach Agent) and how to fix it
(CORS + making sure the Agent really runs in the background).

---

0. What you get

---

- Agent binaries under: %ProgramFiles%\PLCLogger\agent\
- ProgramData (state/logs): %ProgramData%\PLCLogger\agent\
  - app.db, logs\*, agent.lock.json { port, token, pid }
- Service: PLCLoggerAgent (Automatic start)
- UI (optional): %ProgramFiles%\PLCLogger\ui\ + shortcuts
- Loopback-only HTTP API: http://127.0.0.1:<port> (default 5175)

---

1. Prerequisites

---

Windows

- Windows 10/11 x64, PowerShell

Agent build

- Python 3.11+ on PATH (py -3.11 --version)
- (Your repoâ€™s) scripts\build_agent.ps1

UI build (Tauri)

- Node.js LTS + npm
- Rust toolchain + MSVC Build Tools
  Rust: https://rustup.rs
  VS Build Tools 2022: "Desktop development with C++" + Windows 10/11 SDK
- Tauri CLI: npm install -g @tauri-apps/cli
- WebView2 Runtime (required to run packaged UI):
  winget install -e Microsoft.EdgeWebView2Runtime

Installer tools (choose one path; v3 is recommended today)
A) WiX Toolset v3.14 (heat/candle/light) â† recommended - Chocolatey: choco install wixtoolset -y - After install, WiX v3 is usually at:
C:\Program Files (x86)\WiX Toolset v3.14\bin

B) WiX Toolset v4 (wix.exe) â† supported by scripts, but stick to v3 if unsure - winget install -e --id WiXToolset.WiXCLI - (Optional extras) winget install -e --id WiXToolset.WiXAdditionalTools

Optional (fast, robust service wrapper if your agent_service.exe is not a true
Windows service or you want to avoid service code issues):

- NSSM: choco install nssm -y

---

2. One-Time Agent Code Update (CORS for Packaged UI)

---

Packaged Tauri apps do NOT come from http://localhost:5173. Add this to your
FastAPI app setup so the Desktop UI can call the Agent:

from fastapi.middleware.cors import CORSMiddleware

ALLOW*ORIGIN_REGEX = r"(app://.*|tauri://.\_|http://localhost(:\d+)?|http://127\.0\.0\.1(:\d+)?)"

app.add_middleware(
CORSMiddleware,
allow_origin_regex=ALLOW_ORIGIN_REGEX,
allow_credentials=True,
allow_methods=["*"],
allow_headers=["*"],
)

Rebuild the Agent after adding the above (Section 3).

---

3. Quick Build (Agent + UI + MSI)

---

Open a non-admin PowerShell in repo root, e.g.: d:\Apps\plc_logger_app\plc_logger

Agent
powershell -ExecutionPolicy Bypass -File scripts\build_agent.ps1

# Produces dist\plclogger-agent\ (PyInstaller onedir + agent_service.exe if you have it)

UI (Tauri)
cd apps\desktop
npm install
npm run tauri:build

# The UI exe lands under apps\desktop\src-tauri\target\release\....

Back to repo root
cd d:\Apps\plc_logger_app\plc_logger

# Find the packaged UI folder automatically:

$ui = Get-ChildItem apps\desktop\src-tauri\target\release -Recurse -Filter *.exe | Select-Object -First 1
  if ($ui) {
$uiDir = $ui.DirectoryName
powershell -ExecutionPolicy Bypass -File scripts\build_wix.ps1 `      -AgentDir dist\plclogger-agent`
-UiDir $uiDir `      -Out     installer\PLCLogger.msi
  } else {
    powershell -ExecutionPolicy Bypass -File scripts\build_wix.ps1`
-AgentDir dist\plclogger-agent `
-Out installer\PLCLogger.msi
}

Result
installer\PLCLogger.msi

Notes

- scripts\build_wix.ps1 supports both WiX v3 and v4. With v3, it uses heat/candle/light.
- If WiX executables are not found, ensure WiX v3 bin is on PATH for this shell:
  $wix3 = 'C:\Program Files (x86)\WiX Toolset v3.14\bin'
    if (Test-Path $wix3) { $env:Path = "$wix3;$env:Path" }

---

4. Agent-Only MSI (no UI)

---

powershell -ExecutionPolicy Bypass -File scripts\build_agent.ps1
powershell -ExecutionPolicy Bypass -File scripts\build_wix.ps1 `    -AgentDir dist\plclogger-agent`
-Out installer\PLCLogger.msi

---

5. Install (Admin)

---

Double-click installer\PLCLogger.msi

- Installs to Program Files:
  PLCLogger\agent\ and (if provided) PLCLogger\ui\
- Creates ProgramData:
  %ProgramData%\PLCLogger\agent\ (logs, app.db, agent.lock.json)
- Registers Windows service:
  PLCLoggerAgent (StartType=Automatic)
- Starts the service
- Adds Start Menu & Desktop shortcuts (if UI included)

---

6. Verify After Install

---

Service
Get-Service PLCLoggerAgent | Format-Table Status,StartType,Name

Lockfile
type "%ProgramData%\PLCLogger\agent\agent.lock.json"

# Contains: { "port": 5175, "token": "...", "pid": ... }

Health
Invoke-RestMethod -Uri "http://127.0.0.1:5175/health"

# If port differs, use the one in agent.lock.json

UI
Start Menu "PLC Logger" (or Desktop shortcut).
The tray icon should appear; opening the window should now talk to the Agent.

---

7. Operations (Admin)

---

Start / Stop service
sc start PLCLoggerAgent
sc stop PLCLoggerAgent

Logs
%ProgramData%\PLCLogger\agent\logs\agent.log
%ProgramData%\PLCLogger\agent\logs\service.out.log (if your wrapper writes here)

Check listener
Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 5175 -State Listen

---

8. Post‑install checks and common pitfalls (and fixes)

---

This is almost always one of the following:

A) Agent not running as a real background service

- Quick fix without rebuild (recommended during bring-up): use NSSM to host the agent EXE

  choco install nssm -y
  $nssm = "$Env:ProgramData\chocolatey\bin\nssm.exe"
  $agentExe = "$Env:ProgramFiles\PLCLogger\agent\plclogger-agent.exe"
  $agentDir = "$Env:ProgramFiles\PLCLogger\agent"
  & $nssm install PLCLoggerAgent $agentExe
  & $nssm set PLCLoggerAgent AppDirectory $agentDir
  & $nssm set PLCLoggerAgent Start SERVICE_AUTO_START
  & $nssm start PLCLoggerAgent

- This pins the working directory and keeps the Agent alive reliably.
- Later you can replace NSSM with a native service (agent_service.exe) via WiX ServiceInstall.

B) CORS not allowing packaged UI

- Ensure you added the CORS regex shown in Section 2 and rebuilt the Agent.

C) Wrong base URL / token

- Packaged UI must call http://127.0.0.1:<port>. Default is 5175.
- The UI should use GET /auth/handshake to get a token, or read agent.lock.json.

D) Service working directory problem

- If the service starts and dies in ~2s, it likely tried to access relative paths.
- Use NSSMâ€™s AppDirectory (above) or make your service entry set os.chdir(exe_dir).

Debug quickly

# try calling the API from the same machine:

Invoke-RestMethod http://127.0.0.1:5175/health

# open UI devtools (Ctrl+Shift+I) and look for CORS/401/connection errors

---

9. What the MSI Does (expected behavior)

---

- Bundles Agent (PyInstaller onedir) and optional service host (agent_service.exe)
- Creates ProgramData folders for DB, lockfile, and logs
- Registers Service "PLCLoggerAgent" (automatic) and starts it
- Creates Start Menu / Desktop shortcuts for UI (if UI bundled)
- Restricts API to 127.0.0.1 (loopback); token handshake via /auth/handshake

---

10. Upgrade / Uninstall

---

Upgrade

- Build a new MSI with a higher ProductVersion and matching UpgradeCode.
- Installer stops the service, replaces binaries, runs DB migrations, restarts.

Uninstall

- Stops and removes the service
- Removes Program Files binaries
- Optionally keep %ProgramData%\PLCLogger\ (user data) if you prefer

---

## Appendix A â€” Manual WiX v3 compile (for CI or deep troubleshooting)

$wix = 'C:\Program Files (x86)\WiX Toolset v3.14\bin'

# 1) Harvest (+autoguid) Agent and UI

& "$wix\heat.exe"  dir "dist\plclogger-agent" -dr AGENTDIR -cg AgentGroup -ke -srd -sreg -scom -var var.AgentDir -ag -out installer\wix\AgentGroup.wxs
& "$wix\heat.exe" dir "installer\ui" -dr UIDIR -cg UiGroup -ke -srd -sreg -scom -var var.UiDir -ag -out installer\wix\UiGroup.wxs

# 2) Compile

& "$wix\candle.exe" -arch x64 -dAgentDir="dist\plclogger-agent" -dUiDir="installer\ui" -out installer\wix\Main.wixobj       installer\wix\Main.wxs
& "$wix\candle.exe" -arch x64 -dAgentDir="dist\plclogger-agent" -dUiDir="installer\ui" -out installer\wix\AgentGroup.wixobj installer\wix\AgentGroup.wxs
& "$wix\candle.exe" -arch x64 -dAgentDir="dist\plclogger-agent" -dUiDir="installer\ui" -out installer\wix\UiGroup.wixobj   installer\wix\UiGroup.wxs
& "$wix\candle.exe" -arch x64 -dAgentDir="dist\plclogger-agent" -dUiDir="installer\ui" -out installer\wix\Extras.wixobj installer\wix\Extras.wxs

# 3) Link

& "$wix\light.exe" -out installer\PLCLogger.msi `
installer\wix\Main.wixobj installer\wix\AgentGroup.wixobj installer\wix\UiGroup.wixobj installer\wix\Extras.wixobj

(Notes: our Extras.wxs is authored to avoid ICE38/ICE43/ICE57/ICE64 conflicts by using proper
per-machine components and directory handling.)

---

## Appendix B â€” Service via WiX (native, no NSSM)

If you have a true Windows service host (agent_service.exe) that starts uvicorn
and sets its working directory:

  <Component Id="AgentServiceComponent" Guid="*">
    <File Id="AgentServiceExe" Source="$(var.AgentDir)\agent_service.exe" KeyPath="yes"/>
    <ServiceInstall Id="AgentSvcInstall"
                    Name="PLCLoggerAgent"
                    DisplayName="PLC Logger Agent"
                    Description="Runs the PLC Logger Agent API and background jobs."
                    Start="auto"
                    Type="ownProcess"
                    ErrorControl="normal"
                    Arguments="--port 5175" />
    <ServiceControl Id="AgentSvcControl"
                    Name="PLCLoggerAgent"
                    Start="install" Stop="both" Remove="uninstall" Wait="yes"/>
  </Component>

Make sure your service code uses absolute paths or chdirâ€™s to its exe folder.
"""

if **name** == "**main**":
print(INSTRUCTIONS)
