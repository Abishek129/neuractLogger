Windows PowerShell
Copyright (C) Microsoft Corporation. All rights reserved.

Install the latest PowerShell for new features and improvements! https://aka.ms/PSWindows

PS C:\WINDOWS\system32> cd D:\Apps\plc_logger_app\plc_logger
PS D:\Apps\plc_logger_app\plc_logger> # Open PowerShell as Administrator in D:\Apps\plc_logger_app\plc_logger, then paste this:
PS D:\Apps\plc_logger_app\plc_logger>
PS D:\Apps\plc_logger_app\plc_logger> $ErrorActionPreference = "Stop"
PS D:\Apps\plc_logger_app\plc_logger> function Section($t){ Write-Host "`n=== $t ===" -ForegroundColor Cyan }
PS D:\Apps\plc_logger_app\plc_logger> function OK($t){ Write-Host $t -ForegroundColor Green }
PS D:\Apps\plc_logger_app\plc_logger> function WRN($t){ Write-Host $t -ForegroundColor Yellow }
PS D:\Apps\plc_logger_app\plc_logger> function ERR($t){ Write-Host $t -ForegroundColor Red }
PS D:\Apps\plc_logger_app\plc_logger>
PS D:\Apps\plc_logger_app\plc_logger> # Sanity: elevation
PS D:\Apps\plc_logger_app\plc_logger> if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()

> > ).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) { ERR "Not elevated. Re-open PowerShell as Administrator."; exit 1 }
> > PS D:\Apps\plc_logger_app\plc_logger>
> > PS D:\Apps\plc_logger_app\plc_logger> $Root = (Get-Location).Path
> > PS D:\Apps\plc_logger_app\plc_logger> $Dist = Join-Path $Root "dist"
> > PS D:\Apps\plc_logger_app\plc_logger>
> > PS D:\Apps\plc_logger_app\plc_logger> Section "Find service + newest build"

=== Find service + newest build ===
PS D:\Apps\plc_logger_app\plc_logger> $svc = Get-CimInstance Win32_Service -Filter "Name='PLCLoggerSvc'" -ErrorAction SilentlyContinue
PS D:\Apps\plc_logger_app\plc_logger> if (-not $svc) { ERR "Service PLCLoggerSvc not found."; exit 1 }
PS D:\Apps\plc_logger_app\plc_logger> $raw = $svc.PathName
PS D:\Apps\plc_logger_app\plc_logger> $SvcExe = $null
PS D:\Apps\plc_logger_app\plc_logger> if ($raw -match '^"([^"]+)"') { $SvcExe = $Matches[1] } else { $SvcExe = ($raw -split ' ')[0] }
PS D:\Apps\plc_logger_app\plc_logger> if (-not (Test-Path $SvcExe)) { ERR "Service EXE not found: $SvcExe"; exit 1 }
PS D:\Apps\plc_logger_app\plc_logger> if (-not (Test-Path $Dist)) { ERR "dist\ not found at $Dist"; exit 1 }
PS D:\Apps\plc_logger_app\plc_logger> $NewExe = Get-ChildItem $Dist -Recurse -File -Include "agent_service.exe","plclogger-agent.exe" |

> >           Sort-Object LastWriteTime -Desc | Select-Object -First 1 | ForEach-Object { $_.FullName }
> >
> > PS D:\Apps\plc_logger_app\plc_logger> if (-not $NewExe) { ERR "No agent EXE in dist\ (agent_service.exe/plclogger-agent.exe)."; exit 1 }
> > PS D:\Apps\plc_logger_app\plc_logger> OK ("Service EXE : $SvcExe")
> > Service EXE : D:\Apps\plc_logger_app\plc_logger\dist\agent_service.exe
> > PS D:\Apps\plc_logger_app\plc_logger> OK ("New build : $NewExe")
> > New build : D:\Apps\plc_logger_app\plc_logger\dist\agent_service.exe
> > PS D:\Apps\plc_logger_app\plc_logger>
> > PS D:\Apps\plc_logger_app\plc_logger> Section "Stop service and repoint binPath"

=== Stop service and repoint binPath ===
PS D:\Apps\plc_logger_app\plc_logger> Stop-Service PLCLoggerSvc -Force -ErrorAction SilentlyContinue
PS D:\Apps\plc_logger_app\plc_logger> Start-Sleep -Seconds 1
PS D:\Apps\plc_logger_app\plc_logger> sc.exe config PLCLoggerSvc binPath= "`"$NewExe`"" | Out-Null
PS D:\Apps\plc_logger_app\plc_logger> # Confirm binPath actually changed
PS D:\Apps\plc_logger_app\plc_logger> $qc = (sc.exe qc PLCLoggerSvc) -join "`n"
PS D:\Apps\plc_logger_app\plc_logger> $binOk = $qc -match [regex]::Escape($NewExe)
PS D:\Apps\plc_logger_app\plc_logger> if ($binOk) { OK "binPath updated:"; $qc } else { WRN "binPath did not reflect new EXE. Output:"; $qc }
binPath updated:
[SC] QueryServiceConfig SUCCESS

SERVICE_NAME: PLCLoggerSvc
TYPE : 10 WIN32_OWN_PROCESS
START_TYPE : 2 AUTO_START
ERROR_CONTROL : 1 NORMAL
BINARY_PATH_NAME : D:\Apps\plc_logger_app\plc_logger\dist\agent_service.exe
LOAD_ORDER_GROUP :
TAG : 0
DISPLAY_NAME : PLC Logger Agent
DEPENDENCIES :
SERVICE_START_NAME : LocalSystem
PS D:\Apps\plc_logger_app\plc_logger>
PS D:\Apps\plc_logger_app\plc_logger> Section "Start service"

=== Start service ===
PS D:\Apps\plc*logger_app\plc_logger> $svcStartOk = $true
PS D:\Apps\plc_logger_app\plc_logger> try { Start-Service PLCLoggerSvc -ErrorAction Stop } catch { $svcStartOk = $false; WRN ("Start failed: " + $*.Exception.Message) }
Start failed: Service 'PLC Logger Agent (PLCLoggerSvc)' cannot be started due to the following error: Cannot start service PLCLoggerSvc on computer '.'.
PS D:\Apps\plc_logger_app\plc_logger> Start-Sleep -Seconds 2
PS D:\Apps\plc_logger_app\plc_logger> $st = (Get-Service PLCLoggerSvc -ErrorAction SilentlyContinue).Status
PS D:\Apps\plc_logger_app\plc_logger> Write-Host ("Service status: " + $st)
Service status: Stopped
PS D:\Apps\plc_logger_app\plc_logger> if ($st -ne 'Running') {

> > Section "Service diagnostics (SCM + last 5 min)"
> > sc.exe queryex PLCLoggerSvc
> > Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Service Control Manager'; StartTime=(Get-Date).AddMinutes(-5)} `
> > | Select-Object TimeCreated, Id, LevelDisplayName, Message | Format-List
> > }

=== Service diagnostics (SCM + last 5 min) ===

SERVICE_NAME: PLCLoggerSvc
TYPE : 10 WIN32_OWN_PROCESS
STATE : 1 STOPPED
WIN32_EXIT_CODE : 0 (0x0)
SERVICE_EXIT_CODE : 0 (0x0)
CHECKPOINT : 0x0
WAIT_HINT : 0x7d0
PID : 0
FLAGS :

TimeCreated : 9/12/2025 6:53:38 PM
Id : 7000
LevelDisplayName : Error
Message : The PLC Logger Agent service failed to start due to the following error:
The service did not respond to the start or control request in a timely fashion.

TimeCreated : 9/12/2025 6:53:38 PM
Id : 7009
LevelDisplayName : Error
Message : A timeout was reached (180000 milliseconds) while waiting for the PLC Logger Agent service to
connect.

TimeCreated : 9/12/2025 6:49:27 PM
Id : 7000
LevelDisplayName : Error
Message : The PLC Logger Agent service failed to start due to the following error:
The service did not respond to the start or control request in a timely fashion.

TimeCreated : 9/12/2025 6:49:27 PM
Id : 7009
LevelDisplayName : Error
Message : A timeout was reached (180000 milliseconds) while waiting for the PLC Logger Agent service to
connect.

TimeCreated : 9/12/2025 6:49:25 PM
Id : 7000
LevelDisplayName : Error
Message : The PLC Logger Agent service failed to start due to the following error:
The service did not respond to the start or control request in a timely fashion.

TimeCreated : 9/12/2025 6:49:25 PM
Id : 7009
LevelDisplayName : Error
Message : A timeout was reached (180000 milliseconds) while waiting for the PLC Logger Agent service to
connect.

PS D:\Apps\plc_logger_app\plc_logger>
PS D:\Apps\plc_logger_app\plc_logger> # If service still not running, start console fallback so we can validate now
PS D:\Apps\plc_logger_app\plc_logger> $UsingConsole = $false
PS D:\Apps\plc_logger_app\plc_logger> $consoleOut = Join-Path $Root "agent_console.out.log"
PS D:\Apps\plc_logger_app\plc_logger> $consoleErr = Join-Path $Root "agent_console.err.log"
PS D:\Apps\plc_logger_app\plc_logger> if ($st -ne 'Running') {

> > Section "Fallback: run agent in console"
> > try { # Try EXE "debug" first (pywin32 services typically support it)
> > Start-Process -NoNewWindow -FilePath "$NewExe" -ArgumentList "debug" `      -RedirectStandardOutput $consoleOut -RedirectStandardError $consoleErr
    Start-Sleep -Seconds 2
    $UsingConsole = $true
    OK ("Console agent started. Logs: $consoleOut , $consoleErr")
  } catch {
    WRN "Could not start console EXE. Trying uvicorn from source..."
    $env:PYTHONPATH = $Root
    Start-Process -NoNewWindow -FilePath "python" -ArgumentList "-m","uvicorn","agent.plc_agent.api.app:app","--host","127.0.0.1","--port","5175"`
> > -RedirectStandardOutput $consoleOut -RedirectStandardError $consoleErr
> > Start-Sleep -Seconds 2
> > $UsingConsole = $true
> > OK ("Uvicorn started on 127.0.0.1:5175. Logs: $consoleOut , $consoleErr")
> > }
> > }

=== Fallback: run agent in console ===
Console agent started. Logs: D:\Apps\plc_logger_app\plc_logger\agent_console.out.log , D:\Apps\plc_logger_app\plc_logger\agent_console.err.log
PS D:\Apps\plc_logger_app\plc_logger>
PS D:\Apps\plc_logger_app\plc_logger> Section "Resolve lockfile (and detect stale)"

=== Resolve lockfile (and detect stale) ===
PS D:\Apps\plc_logger_app\plc_logger> $Lock = "C:\ProgramData\PLCLogger\agent\agent.lock.json"
PS D:\Apps\plc_logger_app\plc_logger> if (-not (Test-Path $Lock)) { $Lock = Join-Path $env:LOCALAPPDATA "PLCLogger\agent\agent.lock.json" }
PS D:\Apps\plc_logger_app\plc_logger> if (-not (Test-Path $Lock)) { ERR "No lockfile found (service/console may not have started)."; if ($UsingConsole){Get-Content -Tail 200 $consoleErr -ErrorAction SilentlyContinue}; exit 1 }
PS D:\Apps\plc_logger_app\plc_logger> $lf = Get-Item $Lock
PS D:\Apps\plc_logger_app\plc_logger> if ($lf.LastWriteTime -lt (Get-Date).AddMinutes(-2)) { WRN ("Lockfile looks stale (LastWriteTime=" + $lf.LastWriteTime + ")") }
Lockfile looks stale (LastWriteTime=09/12/2025 18:34:03)
PS D:\Apps\plc_logger_app\plc_logger>
PS D:\Apps\plc_logger_app\plc_logger> $L = Get-Content $Lock -Raw | ConvertFrom-Json
PS D:\Apps\plc_logger_app\plc_logger> $Base = "http://127.0.0.1:$($L.port)"; $Tok = [string]$L.token
PS D:\Apps\plc_logger_app\plc_logger> $Hdrs = @{ "Content-Type"="application/json" }
PS D:\Apps\plc_logger_app\plc_logger> if ($Tok) { $Hdrs["Authorization"]="Bearer $Tok"; $Hdrs["X-Agent-Token"]=$Tok }
PS D:\Apps\plc_logger_app\plc_logger> $tp = if ($Tok) { $Tok.Substring(0,[Math]::Min(8,$Tok.Length)) } else { "" }
PS D:\Apps\plc_logger_app\plc_logger> OK ("Lock -> base=$Base  tokenPrefix=$tp")
Lock -> base=http://127.0.0.1:5175 tokenPrefix=u8X6V9x7
PS D:\Apps\plc_logger_app\plc_logger>
PS D:\Apps\plc_logger_app\plc_logger> Section "Verify: health/ping"

=== Verify: health/ping ===
PS D:\Apps\plc_logger_app\plc_logger> try {

> > $h = Invoke-RestMethod "$Base/health" -TimeoutSec 6
> > if ($h.status -eq 'ok') { OK "Health OK" } else { WRN ("Health unexpected: " + ($h | ConvertTo-Json -Depth 3)) }
> > } catch { ERR ("Health ERR: " + $_.Exception.Message) }
Health ERR: Unable to connect to the remote server
PS D:\Apps\plc_logger_app\plc_logger> try {
>>   $b = @{ target="127.0.0.1"; count=1; timeout=0.6 } | ConvertTo-Json
>>   $p = Invoke-RestMethod -Method Post -Uri "$Base/networking/ping" -Headers $Hdrs -ContentType "application/json" -Body $b -TimeoutSec 6
>>   if ($p.ok -eq $true) { OK "Ping OK (authorized)" } else { WRN ("Ping not ok: " + ($p | ConvertTo-Json -Depth 3)) }
> > } catch { ERR ("Ping ERR: " + $\_.Exception.Message) }
> > Ping ERR: Unable to connect to the remote server
> > PS D:\Apps\plc_logger_app\plc_logger>
> > PS D:\Apps\plc_logger_app\plc_logger> Section "Verify: CORS preflight for http://tauri.localhost"

=== Verify: CORS preflight for http://tauri.localhost ===
PS D:\Apps\plc_logger_app\plc_logger> try {

> > $pre = Invoke-WebRequest -Method Options -Uri "$Base/networking/ping" -Headers @{
> > Origin='http://tauri.localhost'
> > 'Access-Control-Request-Method'='POST'
> > 'Access-Control-Request-Headers'='authorization,content-type,x-agent-token'
> > } -TimeoutSec 8
> > $allow = $pre.Headers['access-control-allow-origin']
>>   if ($allow -and ($allow -eq 'http://tauri.localhost' -or $allow -eq '*')) { OK ("CORS OK: allow-origin=" + $allow) }
>>   else { ERR ("CORS FAIL: expected http://tauri.localhost, got '" + $allow + "'") }
>> } catch { ERR ("Preflight ERR: " + $_.Exception.Message) }
Preflight ERR: Unable to connect to the remote server
PS D:\Apps\plc_logger_app\plc_logger>
PS D:\Apps\plc_logger_app\plc_logger> if ($UsingConsole) {
> > WRN "Agent is running in CONSOLE mode. Once the UI works, come back and fix the Windows service using the SCM diagnostics above."
> > Write-Host "Tail console logs: Get-Content '$consoleOut' -Wait  (and)  Get-Content '$consoleErr' -Wait" -ForegroundColor Yellow
> > }
> > Agent is running in CONSOLE mode. Once the UI works, come back and fix the Windows service using the SCM diagnostics above.
> > Tail console logs: Get-Content 'D:\Apps\plc_logger_app\plc_logger\agent_console.out.log' -Wait (and) Get-Content 'D:\Apps\plc_logger_app\plc_logger\agent_console.err.log' -Wait
> > PS D:\Apps\plc_logger_app\plc_logger>
