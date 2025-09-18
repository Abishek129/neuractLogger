PowerShell copy/paste to rebuild, launch packaged app, and tail frontend logs

```powershell
$ErrorActionPreference = "Stop"

function Section($t){ Write-Host "`n=== $t ===" -ForegroundColor Cyan }
function OK($t){ Write-Host $t -ForegroundColor Green }
function WRN($t){ Write-Host $t -ForegroundColor Yellow }
function ERR($t){ Write-Host $t -ForegroundColor Red }

# Resolve paths
$Root     = (Get-Location).Path
$Desktop  = Join-Path $Root "apps\desktop"
$SrcTauri = Join-Path $Desktop "src-tauri"
$UiExe    = Join-Path $SrcTauri "target\release\plc-logger-tray.exe"
$NsisDir  = Join-Path $SrcTauri "target\release\bundle\nsis"
$FrontOut = Join-Path $Root "frontout.md"

Section "Kill running tray (avoid stale binary)"
Get-Process -Name "plc-logger-tray" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

Section "Prepare frontout.md"
if (!(Test-Path $FrontOut)) { New-Item -ItemType File -Path $FrontOut -Force | Out-Null }
Set-Content -LiteralPath $FrontOut -Value "" -Encoding UTF8
$env:PLC_FRONTOUT_PATH = $FrontOut  # ensure packaged app writes here
OK ("Frontout path: " + $FrontOut)

Section "Frontend build"
Set-Location $Desktop
"vite","node","esbuild" | % { Get-Process -Name $* -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue }
if (Test-Path ".\package-lock.json") { npm ci } else { npm install }
npm run build

Section "Tauri build (NSIS)"
npx --yes @tauri-apps/cli@2 build --bundles nsis

Section "Artifacts"
if (Test-Path $NsisDir) {
  $inst = Get-ChildItem $NsisDir -Filter *.exe -File | Sort-Object LastWriteTime -Desc | Select-Object -First 1
  if ($inst) { OK ("Installer: " + $inst.FullName) }
}
if (Test-Path $UiExe) { OK ("UI exe: " + $UiExe) } else { ERR "No compiled UI exe found."; exit 1 }

Section "Read agent lockfile (port/token)"
$Lock1 = "C:\\ProgramData\\PLCLogger\\agent\\agent.lock.json"
$Lock2 = Join-Path $env:LOCALAPPDATA "PLCLogger\\agent\\agent.lock.json"
$Lock = $null
if (Test-Path $Lock1) { $Lock = $Lock1 } elseif (Test-Path $Lock2) { $Lock = $Lock2 }
if ($null -eq $Lock) {
  WRN "No lockfile found. Start the agent, then re-run."
} else {
  try {
    $LObj = Get-Content $Lock -Raw | ConvertFrom-Json
    $Port = [int]$LObj.port; $Tok = [string]$LObj.token
    OK ("Lockfile: $Lock  (port=$Port, token prefix=" + $Tok.Substring(0,[Math]::Min(8,$Tok.Length)) + ")")
  } catch { WRN "Could not parse lockfile: $($_.Exception.Message)" }
}

Section "Launch packaged UI"
Start-Process -FilePath $UiExe
OK "Launched. Interact with the app now (click buttons/links)."

Section "Tail frontout.md (Ctrl+C to stop)"
Write-Host "Showing live frontend logs (clicks, requests, responses)..." -ForegroundColor Gray
Get-Content -Path $FrontOut -Wait -Tail 50 | ForEach-Object {
  $_ | ConvertFrom-Json -ErrorAction SilentlyContinue | ForEach-Object {
    # Compact view: time, kind, method/url or status
    $t = $_.t
    $k = $_.kind
    if ($k -eq 'request_start') { Write-Host ("[$t] request: " + $_.method + ' ' + $_.url) }
    elseif ($k -eq 'response') { Write-Host ("[$t] response: " + $_.status + ' ' + $_.url) }
    elseif ($k -eq 'request_error') { Write-Host ("[$t] error: " + $_.status + ' ' + $_.url + ' — ' + ($_.text)) -ForegroundColor Red }
    elseif ($k -eq 'click') { Write-Host ("[$t] click: " + ($_.target.name + $_.target.id + $_.target.cls)) -ForegroundColor Yellow }
    elseif ($k -eq 'lockfile') { Write-Host ("[$t] lockfile: port=" + $_.port + ", hasToken=" + $_.hasToken) -ForegroundColor Cyan }
    elseif ($k -eq 'handshake') { Write-Host ("[$t] handshake: port=" + $_.port + ", hasToken=" + $_.hasToken + ", base=" + $_.baseUrl) -ForegroundColor Cyan }
    elseif ($k -eq 'init') { Write-Host ("[$t] init: base=" + $_.baseUrl + ", pinned=" + $_.basePinned + ", force=" + $_.forcePinned) -ForegroundColor DarkCyan }
  }
}
```

What to look for in the tail output

- init: base is not pinned in prod; shows starting base.
- lockfile/handshake: confirms the discovered port and token presence.
- request_start/response: requests go to http://127.0.0.1:<port_from_lockfile>/... with auth headers attached (redacted in logs).
- request_error: if present, shows status and a snippet of the body to diagnose.

Tip: You can also filter just the request/response lines:

```powershell
Get-Content .\frontout.md -Tail 400 | Select-String -Pattern 'request_start|response|request_error'
```

Restart the Agent service (requires admin)

```powershell
# Run this in an elevated PowerShell (Run as Administrator)
sc.exe stop PLCLoggerSvc
sc.exe start PLCLoggerSvc

# Verify the new CORS behavior on the current port (preflight from http://tauri.localhost)
$Lock = 'C:\\ProgramData\\PLCLogger\\agent\\agent.lock.json'
$Port = (Get-Content $Lock -Raw | ConvertFrom-Json).port
$Base = "http://127.0.0.1:$Port"
try {
  $pre = Invoke-WebRequest -Method Options -Uri ($Base + '/networking/ping') -Headers @{
    Origin='http://tauri.localhost'
    'Access-Control-Request-Method'='POST'
    'Access-Control-Request-Headers'='authorization,content-type,x-agent-token'
  } -TimeoutSec 5
  'allow-origin: ' + $pre.Headers['access-control-allow-origin']
} catch { Write-Host ('Preflight error: ' + $_.Exception.Message) -ForegroundColor Red }
```

Clean uninstall + reinstall from scratch (removes old MSI/NSIS installs, cleans builds, rebuilds, installs fresh, launches, and tails logs)

```powershell
$ErrorActionPreference = "Stop"
function Section($t){ Write-Host "`n=== $t ===" -ForegroundColor Cyan }
function OK($t){ Write-Host $t -ForegroundColor Green }
function WRN($t){ Write-Host $t -ForegroundColor Yellow }
function ERR($t){ Write-Host $t -ForegroundColor Red }

$Root     = (Get-Location).Path
$Desktop  = Join-Path $Root "apps\desktop"
$SrcTauri = Join-Path $Desktop "src-tauri"
$NsisDir  = Join-Path $SrcTauri "target\release\bundle\nsis"
$FrontOut = Join-Path $Root "frontout.md"

Section "Kill running processes"
Get-Process -Name "plc-logger-tray","PLC Logger","PLCLogger" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

Section "Uninstall MSI + NSIS entries"
function Uninstall-MSIEntries {
  $entries = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*','HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue |
             Where-Object { $_.DisplayName -and ($_.DisplayName -match 'PLC\s*Logger') }
  foreach($e in $entries){
    if ($e.UninstallString -match '\{[0-9A-F-]+\}') {
      $guid = ($e.UninstallString | Select-String -Pattern '\\{[0-9A-F-]+\\}' -AllMatches).Matches[-1].Value
      WRN ("MSI uninstall: $guid")
      Start-Process -FilePath 'msiexec.exe' -ArgumentList "/x $guid /qn" -Wait -WindowStyle Hidden
    }
  }
}
function Uninstall-NSISEntry {
  $nsis = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue |
          Where-Object { $_.DisplayName -eq 'PLC Logger' -and $_.UninstallString -like '*uninstall.exe*' }
  if ($nsis) {
    WRN ("NSIS uninstall: " + $nsis.UninstallString)
    $exe = $nsis.UninstallString.Trim('"')
    if (Test-Path $exe) { Start-Process -FilePath $exe -ArgumentList '/S' -Wait }
  }
}
Uninstall-MSIEntries
Uninstall-NSISEntry

Section "Remove leftover install folders"
$lp = Join-Path $env:LOCALAPPDATA 'Programs'
@('PLC Logger','plc-logger-tray','PLCLogger') | ForEach-Object {
  $p = Join-Path $lp $_; if (Test-Path $p) { WRN ("Remove: " + $p); Remove-Item -Recurse -Force $p -ErrorAction SilentlyContinue }
}
if (Test-Path "$env:LOCALAPPDATA\PLC Logger") { WRN ("Remove: $env:LOCALAPPDATA\PLC Logger"); Remove-Item -Recurse -Force "$env:LOCALAPPDATA\PLC Logger" -ErrorAction SilentlyContinue }

Section "Clean repo build artifacts"
@(
  (Join-Path $Desktop 'dist'),
  (Join-Path $SrcTauri 'target'),
  (Join-Path $SrcTauri 'target\release\bundle'),
  (Join-Path $Root 'build'),
  (Join-Path $Root 'dist')
) | ForEach-Object { if (Test-Path $_) { WRN ("Remove: " + $_); Remove-Item -Recurse -Force $_ -ErrorAction SilentlyContinue } }

Section "Prepare frontout.md"
if (!(Test-Path $FrontOut)) { New-Item -ItemType File -Path $FrontOut -Force | Out-Null }
Set-Content -LiteralPath $FrontOut -Value "" -Encoding UTF8
$env:PLC_FRONTOUT_PATH = $FrontOut
OK ("Frontout path: " + $FrontOut)

Section "Rebuild UI + Tauri"
Set-Location $Desktop
if (Test-Path ".\package-lock.json") { npm ci } else { npm install }
npm run build
npx --yes @tauri-apps/cli@2 build --bundles nsis

Section "Install fresh + launch"
$inst = Get-ChildItem $NsisDir -Filter *.exe -File | Sort-Object LastWriteTime -Desc | Select-Object -First 1
if (-not $inst) { ERR "Installer not found"; exit 1 }
OK ("Installer: " + $inst.FullName)
Start-Process -FilePath $inst.FullName -ArgumentList '/S' -Wait

# Prefer user install location created by NSIS
$InstalledExe = Join-Path $env:LOCALAPPDATA 'PLC Logger\plc-logger-tray.exe'
if (!(Test-Path $InstalledExe)) {
  WRN "User install exe not found; scanning Local Programs"
  $InstalledExe = Get-ChildItem -Recurse -File (Join-Path $env:LOCALAPPDATA 'Programs') -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '(?i)logger.*\.exe|plc.*logger.*\.exe' } | Sort-Object LastWriteTime -Desc | Select-Object -First 1 | ForEach-Object { $_.FullName }
}
if ($InstalledExe) {
  OK ("Launching: " + $InstalledExe)
  Start-Process -FilePath $InstalledExe
} else { ERR "Installed exe not found"; exit 1 }

Section "Tail logs (Ctrl+C to stop)"
Get-Content -Path $FrontOut -Wait -Tail 10
```
