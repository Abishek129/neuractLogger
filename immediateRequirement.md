# ImmediateRequirements.md

**Purpose**
Tell the Codex agent exactly what’s working, what isn’t, and what to fix **first**. The full raw logs will be in `console.md`. This doc is the ground truth summary and acceptance criteria.

---

## TL;DR

- The **Windows service** (`PLCLoggerSvc` via WinSW) starts and **/health** is OK on **`http://127.0.0.1:5175`**.
- The **API is reachable** and the lockfile is present at **`C:\ProgramData\PLCLogger\agent\agent.lock.json`** (contains `pid`, `port`, `token`).
- Two feature endpoints are **not functional** because the packaged EXE is missing runtime modules:

  - `POST /networking/ping` → returns `PING_ICMP_BLOCKED` with message `No module named 'icmplib'`.
  - `POST /networking/opcua/test` → returns `OPCUA_PKG_MISSING`.

- Earlier attempts to run the service with venv Python failed due to pointing Python at the **repo folder** (which has **no `__main__`**), not at the **actual entry module/script**. That’s why you saw repeated `python.exe: can't find '__main__' module` in the service logs.
- Front-end dev server (Vite) previously had 404/entry-resolution warnings; those are secondary now. **Priority is fixing backend packaging/runtime so the API endpoints work.**

---

## Environment (for context)

- OS: Windows 11 (elevated PowerShell used).
- Service wrapper: **WinSW** (PLCLoggerSvc.exe).
- Agent lockfile: **`C:\ProgramData\PLCLogger\agent\agent.lock.json`**.
- Service logs: `C:\Program Files\PLCLogger\agent\PLCLoggerSvc.out.log` and `.err.log`.
- Agent app logs: `C:\ProgramData\PLCLogger\agent\logs\agent.log`.
- Dev UI (when used): Vite on **5173**.
- Agent: FastAPI/Uvicorn on **5175** (pinned / stable in our runs).

---

## What **works now**

1. **Service starts and binds the port**

   - Port **5175** shows as **LISTENING**.
   - `/health` returns:

     ```
     status: ok
     agent: plc-agent
     version: 0.1.0
     ```

2. **Auth & lockfile flow**

   - Lockfile is created at **`C:\ProgramData\PLCLogger\agent\agent.lock.json`**.
   - Reads `port` and `token` successfully.
   - Unauthorized requests to protected routes return proper 401 (when tested without token).

3. **Base API routes**

   - `/health` is responsive.
   - `/devices` with headers returns a valid (empty) payload.

---

## What’s **not** working

1. **Networking ping endpoint**

   - `POST /networking/ping` responds with:

     - `ok: false`
     - `code: PING_ICMP_BLOCKED`
     - `message: No module named 'icmplib'`

   - This is **not** a firewall/permission issue—it’s a **packaging** issue (module missing inside the EXE).

2. **OPC UA probe endpoint**

   - `POST /networking/opcua/test` responds with:

     - `ok: false`
     - `protocol: opcua`
     - `message: OPCUA_PKG_MISSING`

   - Again a **packaging** problem (the `opcua` module isn’t in the EXE).

3. **Earlier service run via venv Python**

   - Attempts to run WinSW with `python.exe` pointing at the repo root failed:

     - Repeated `python.exe: can't find '__main__' module in 'D:\Apps\plc_logger_app\plc_logger'`.

   - Root cause: no entry; you must target the **actual entry module/script** that runs the agent (e.g., `python -m <package.path.to.main>` or a specific `main.py`).

4. **Front-end**

   - Previously saw Vite warnings and occasional 404 at `/`. These are **secondary** and should be re-checked **after** the agent’s feature endpoints are fixed. (Front-end will still struggle if those endpoints fail.)

---

## Evidence (see `console.md`)

- Lockfile shows **pid** and **port 5175**.
- `Get-NetTCPConnection` shows **127.0.0.1:5175 Listen**.
- `/health` returns OK.
- `POST /networking/ping` → `No module named 'icmplib'`.
- `POST /networking/opcua/test` → `OPCUA_PKG_MISSING`.
- WinSW logs contain prior `python.exe: can't find '__main__' module` messages when misconfigured.

---

## Likely root causes

1. **PyInstaller packaging omitted optional imports**

   - `icmplib` and `opcua` are imported conditionally in code; PyInstaller won’t include them unless told to (hidden imports).

2. **Wrong service entry when attempting venv-run**

   - WinSW XML pointed `python.exe` to the repo path, not to the real **entry module/script** that starts Uvicorn.

---

## Non-issues (already clarified)

- **Ports are stable** (5175 agent, 5173 Vite).
- **CORS** has not been identified as the cause of the current backend failures.
- **Auth** works; 401 is expected without token. With token, endpoints respond (and reveal the missing-module errors).

---

## Immediate requirements (Dev first, then Production)

### A) Development (get feature endpoints working locally)

1. **Confirm the agent entry module/script**

   - Identify the **exact** Python entry that launches Uvicorn (e.g., `plc_agent/api/main.py` or `apps/agent/__main__.py`).
   - Document it (Codex must use it consistently).

2. **Run agent from venv to validate imports**

   - Ensure venv has: `icmplib`, `opcua`, `apscheduler`, `cryptography`.
   - Start the agent **from venv** using the correct entry and `--port 5175`.
   - Verify:

     - `/health` → OK
     - `POST /networking/ping` → result without “No module named 'icmplib'”

       - Note: If ICMP is blocked by OS/policy, expect a different error (timeout/permission), **not** a missing-module message.

     - `POST /networking/opcua/test` → result without `OPCUA_PKG_MISSING`

       - With no OPC UA server running, a timeout or connection error is acceptable.

3. **Front-end quick sanity (once 2 passes)**

   - Point the UI dev server at `http://127.0.0.1:5175`.
   - Ensure the UI can read the lockfile token (from **ProgramData**) and make successful authorized calls to the above two endpoints.
   - Watch `agent.log` while exercising the UI to confirm calls arrive.

### B) Production (package and deploy)

1. **PyInstaller rebuild with hidden imports**

   - Include at minimum:

     - `icmplib`
     - `opcua`, `opcua.ua`, `opcua.common`, `opcua.crypto`
     - (and keep existing `apscheduler` hidden imports if present)

   - Build the EXE using the **real agent entry**.

2. **Deploy updated EXE**

   - Copy to `C:\Program Files\PLCLogger\agent\plclogger-agent.exe`
   - Ensure WinSW XML:

     - Uses the **EXE** (or venv python + actual entry, if you choose that route).
     - Exposes `ProgramData` env var so lockfile/logs are under `C:\ProgramData\PLCLogger\agent\...`.
     - Start mode = Automatic; onfailure restart.

3. **Service restart and validation**

   - Restart `PLCLoggerSvc`.
   - Validate:

     - Lockfile present and fresh.
     - Port 5175 listening.
     - `/health` OK.
     - `POST /networking/ping` has **no** “No module named 'icmplib'”.
     - `POST /networking/opcua/test` has **no** `OPCUA_PKG_MISSING`.

---

## Constraints & notes

- ICMP on Windows may require admin privileges or can be blocked by policy; success criteria here is **absence of the missing-module error**, not necessarily a successful ping reply from the OS/network.
- OPC UA test without a real server at `opc.tcp://127.0.0.1:4840` will likely **timeout**—that’s acceptable. The key is **module present** and **call handled**.
- Keep the **lockfile** authoritative source for `port` and `token`.
- Ensure the **UI reads lockfile from ProgramData**; do **not** require copying the lockfile to `Program Files`.

---

## Definition of Done

- **Dev**: Running from venv, both endpoints respond **without** missing-module errors. UI dev server can add a device and perform network tests successfully; related calls appear in `agent.log`.
- **Prod**: Service starts from the packaged EXE; `/health` OK; both endpoints return no missing-module errors; UI talks to the service without manual lockfile copying; logs clean of `No module named 'icmplib'` and `OPCUA_PKG_MISSING`.

---

## Deliverables for this pass

1. The **confirmed entry module/script** for the agent.
2. A **working dev run** (venv) demonstrating both endpoints without missing-module errors.
3. A **rebuilt EXE** with the required hidden imports and a short note of the exact PyInstaller command/spec used.
4. A short verification note with the four checks: `/health`, `ping`, `opcua/test`, and a UI action hitting the API (with timestamps that match `agent.log`).
