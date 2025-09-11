Windows PowerShell
Copyright (C) Microsoft Corporation. All rights reserved.

Install the latest PowerShell for new features and improvements! https://aka.ms/PSWindows

PS C:\WINDOWS\system32> # ===== PLC Logger Restore service to packaged EXE and verify API =====
PS C:\WINDOWS\system32> $ErrorActionPreference = "Stop"
PS C:\WINDOWS\system32>
PS C:\WINDOWS\system32> # --- Paths (edit $Repo only if your repo is in a different place) ---
PS C:\WINDOWS\system32> $Repo = "D:\Apps\plc_logger_app\plc_logger"
PS C:\WINDOWS\system32> $DistExe = Join-Path $Repo "dist\plclogger-agent\plclogger-agent.exe"
PS C:\WINDOWS\system32>
PS C:\WINDOWS\system32> $SvcDir = "C:\Program Files\PLCLogger\agent"
PS C:\WINDOWS\system32> $SvcExe = Join-Path $SvcDir "plclogger-agent.exe"
PS C:\WINDOWS\system32> $WrapExe = Join-Path $SvcDir "PLCLoggerSvc.exe"
PS C:\WINDOWS\system32> $WrapXml = Join-Path $SvcDir "PLCLoggerSvc.xml"
PS C:\WINDOWS\system32> $SvcName = "PLCLoggerSvc"
PS C:\WINDOWS\system32>
PS C:\WINDOWS\system32> $Lock = "C:\ProgramData\PLCLogger\agent\agent.lock.json"
PS C:\WINDOWS\system32> $OutLog = Join-Path $SvcDir "PLCLoggerSvc.out.log"
PS C:\WINDOWS\system32> $ErrLog = Join-Path $SvcDir "PLCLoggerSvc.err.log"
PS C:\WINDOWS\system32>
PS C:\WINDOWS\system32> # --- 0) Stop anything using port 5175 & stop service ---
PS C:\WINDOWS\system32> $port = 5175
PS C:\WINDOWS\system32> try {

> > $holders = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
>>              Select-Object -ExpandProperty OwningProcess -Unique
>>   if ($holders) {
> > foreach ($pid in $holders) {
>>       try {
>>         $p = Get-Process -Id $pid -ErrorAction Stop
>>         Write-Host ("Stopping process on port {0}: {1} (PID {2})" -f $port,$p.Name,$p.Id) -ForegroundColor Yellow
>>         Stop-Process -Id $p.Id -Force
>>       } catch {}
>>     }
>>   }
>> } catch {}
PS C:\WINDOWS\system32>
PS C:\WINDOWS\system32> & "$env:WINDIR\System32\sc.exe" stop $SvcName 2>$null | Out-Null
> > PS C:\WINDOWS\system32> Start-Sleep 2
> > PS C:\WINDOWS\system32>
> > PS C:\WINDOWS\system32> # --- 1) Ensure service folder, packaged EXE, and WinSW wrapper exist ---
> > PS C:\WINDOWS\system32> New-Item -ItemType Directory $SvcDir -Force | Out-Null
> > PS C:\WINDOWS\system32>
> > PS C:\WINDOWS\system32> if (!(Test-Path $DistExe)) {
> > throw "Missing packaged EXE at $DistExe build or copy it first."
> > }
> > PS C:\WINDOWS\system32> Copy-Item $DistExe $SvcExe -Force
> > PS C:\WINDOWS\system32>
> > PS C:\WINDOWS\system32> if (!(Test-Path $WrapExe)) {
> >
> > # Fetch WinSW wrapper if missing
> >
> > [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
> > $urls = @(
>>     "https://github.com/winsw/winsw/releases/download/v3.0.0/WinSW-x64.exe",
>>     "https://github.com/winsw/winsw/releases/latest/download/WinSW-x64.exe"
>>   )
>>   $ok = $false
>>   foreach ($u in $urls) {
>>     try { Invoke-WebRequest -UseBasicParsing -Uri $u -OutFile $WrapExe -TimeoutSec 30; $ok=$true; break } catch {}
> > }
> > if (-not $ok) { throw "Could not download WinSW to $WrapExe" }
>> }
PS C:\WINDOWS\system32>
PS C:\WINDOWS\system32> # --- 2) Write WinSW XML that runs the packaged EXE (NOT python.exe) ---
PS C:\WINDOWS\system32> @"
>> <service>
>>   <id>$SvcName</id> > > <name>PLC Logger Agent</name> > > <description>Runs the PLC Logger Agent API and background jobs.</description> > > <executable>plclogger-agent.exe</executable> > > <workingdirectory>%BASE%</workingdirectory> > > <startmode>Automatic</startmode> > > <stoptimeout>15 sec</stoptimeout> > > <log mode="roll-by-size"> > > <sizeThreshold>1048576</sizeThreshold> > > <keepFiles>5</keepFiles> > > </log> > > <onfailure action="restart" delay="5 sec"/> > > <env name="ProgramData" value="C:\ProgramData"/> > > <env name="AGENT_LOG_LEVEL" value="INFO"/> >> </service>
> > "@ | Set-Content -LiteralPath $WrapXml -Encoding UTF8
PS C:\WINDOWS\system32>
PS C:\WINDOWS\system32> # --- 3) Clear stale lockfile/logs and reinstall service cleanly ---
PS C:\WINDOWS\system32> Remove-Item $Lock   -Force -ErrorAction SilentlyContinue
PS C:\WINDOWS\system32> Remove-Item $OutLog -Force -ErrorAction SilentlyContinue
PS C:\WINDOWS\system32> Remove-Item $ErrLog -Force -ErrorAction SilentlyContinue
PS C:\WINDOWS\system32>
PS C:\WINDOWS\system32> & $WrapExe uninstall 2>$null | Out-Null
> > PS C:\WINDOWS\system32> & $WrapExe install    2>$null | Out-Null
> > PS C:\WINDOWS\system32> & $WrapExe start      2>$null | Out-Null
> > PS C:\WINDOWS\system32>
> > PS C:\WINDOWS\system32> # --- 4) Wait for fresh lockfile & validate port/token ---
> > PS C:\WINDOWS\system32> $deadline = (Get-Date).AddSeconds(25)
PS C:\WINDOWS\system32> while ((Get-Date) -lt $deadline -and -not (Test-Path $Lock)) { Start-Sleep 1 }
PS C:\WINDOWS\system32>
PS C:\WINDOWS\system32> if (!(Test-Path $Lock)) {
>>   Write-Host "`n No lockfile created. Service logs:" -ForegroundColor Red
>>   if (Test-Path $ErrLog) { Write-Host "`n--- PLCLoggerSvc.err.log (tail) ---" -ForegroundColor Yellow; Get-Content $ErrLog -Tail 120 }
>>   throw "Agent did not start."
>> }
PS C:\WINDOWS\system32>
PS C:\WINDOWS\system32> $m = Get-Content $Lock -Raw | ConvertFrom-Json
PS C:\WINDOWS\system32> $port  = [int]$m.port
> > PS C:\WINDOWS\system32> $token = $m.token
PS C:\WINDOWS\system32> $base  = "http://127.0.0.1:$port"
> > PS C:\WINDOWS\system32> $h     = @{ 'Authorization'="Bearer $token"; 'X-Agent-Token'=$token }
> > PS C:\WINDOWS\system32>
> > PS C:\WINDOWS\system32> Write-Host ("Lockfile OK pid={0} port={1}" -f $m.pid, $port) -ForegroundColor Green
Lockfile OK  pid=20720  port=5175
PS C:\WINDOWS\system32>
PS C:\WINDOWS\system32> # --- 5) Ensure the port is actually listening now ---
PS C:\WINDOWS\system32> $listenOk = $false
PS C:\WINDOWS\system32> 1..10 | ForEach-Object {
>>   $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
>>   if ($conn) { $listenOk = $true; return }
>>   Start-Sleep 1
>> }
PS C:\WINDOWS\system32> if (-not $listenOk) {
>>   Write-Host " Port $port is not listening. Service likely exited. Logs:" -ForegroundColor Red
>>   if (Test-Path $ErrLog) { Write-Host "`n--- PLCLoggerSvc.err.log (tail) ---" -ForegroundColor Yellow; Get-Content $ErrLog -Tail 120 }
>>   throw "Agent not listening on $port."
>> }
PS C:\WINDOWS\system32> Write-Host "Port $port is listening." -ForegroundColor Green
Port 5175 is listening.
PS C:\WINDOWS\system32>
PS C:\WINDOWS\system32> # --- 6) Health ---
PS C:\WINDOWS\system32> try {
>>   Write-Host "`n/health:" -ForegroundColor Yellow
>>   $health = Invoke-RestMethod "$base/health"
> > $health | Format-Table | Out-String | Write-Host
>> } catch {
>>   Write-Host " /health failed: $($\_.Exception.Message)" -ForegroundColor Red
> > if (Test-Path $ErrLog) { Write-Host "`n--- PLCLoggerSvc.err.log (tail) ---" -ForegroundColor Yellow; Get-Content $ErrLog -Tail 80 }
> > throw
> > }

/health:

status agent version

---

ok plc-agent 0.1.0

PS C:\WINDOWS\system32>
PS C:\WINDOWS\system32> # --- 7) API probes: ping & opcua (these reveal missing modules if the EXE was built without them) ---
PS C:\WINDOWS\system32> $needIcmplib = $false
PS C:\WINDOWS\system32> $needOpcua = $false
PS C:\WINDOWS\system32>
PS C:\WINDOWS\system32> # Ping
PS C:\WINDOWS\system32> $pingMsg = ""
PS C:\WINDOWS\system32> try {

> > $body = @{ target="127.0.0.1"; count=1; timeout=0.8 } | ConvertTo-Json
>>   Write-Host "`nPOST /networking/ping:" -ForegroundColor Yellow
>>   $ping = Invoke-RestMethod -Method Post -Headers $h -ContentType "application/json" -Body $body "$base/networking/ping"
> > $ping | Format-List | Out-String | Write-Host
>>   $pingMsg = "$($ping.code) $($ping.message)"
> > if ($pingMsg -match 'icmplib') { $needIcmplib = $true }
>> } catch {
>>   Write-Host "  ping threw: $($\_.Exception.Message)" -ForegroundColor DarkYellow
> > }

POST /networking/ping:

ok : False
code : PING_ICMP_BLOCKED
message : No module named 'icmplib'

PS C:\WINDOWS\system32>
PS C:\WINDOWS\system32> # OPC UA
PS C:\WINDOWS\system32> $opcuaMsg = ""
PS C:\WINDOWS\system32> try {

> > $body = @{ endpoint="opc.tcp://127.0.0.1:4840"; timeout=1.0 } | ConvertTo-Json
>>   Write-Host "`nPOST /networking/opcua/test:" -ForegroundColor Yellow
>>   $opc = Invoke-RestMethod -Method Post -Headers $h -ContentType "application/json" -Body $body "$base/networking/opcua/test"
> > $opc | Format-List | Out-String | Write-Host
>>   $opcuaMsg = "$($opc.protocol) $($opc.message)"
> > if ($opcuaMsg -match 'OPCUA_PKG_MISSING' -or $opcuaMsg -match 'opcua') { $needOpcua = $true }
>> } catch {
>>   Write-Host "  opcua threw (no server on 4840 is fine); message: $($\_.Exception.Message)" -ForegroundColor DarkYellow
> > }

POST /networking/opcua/test:

ok : False
protocol : opcua
endpoint : opc.tcp://127.0.0.1:4840
message : OPCUA_PKG_MISSING

PS C:\WINDOWS\system32>
PS C:\WINDOWS\system32> # --- 8) Summary + guidance ---
PS C:\WINDOWS\system32> Write-Host "`n==== SUMMARY ====" -ForegroundColor Cyan

==== SUMMARY ====
PS C:\WINDOWS\system32> Write-Host ("Health: " + $health.status)
Health: ok
PS C:\WINDOWS\system32> Write-Host ("Ping:   " + $pingMsg)
Ping:   PING_ICMP_BLOCKED No module named 'icmplib'
PS C:\WINDOWS\system32> Write-Host ("OPC UA: " + $opcuaMsg)
OPC UA: opcua OPCUA_PKG_MISSING
PS C:\WINDOWS\system32>
PS C:\WINDOWS\system32> if ($needIcmplib -or $needOpcua) {

> > Write-Host "`n The running packaged agent lacks modules:" -ForegroundColor Yellow
  if ($needIcmplib) { Write-Host "   - icmplib (used by /networking/ping)" -ForegroundColor Yellow }
  if ($needOpcua)   { Write-Host "   - opcua (used by /networking/opcua/test)" -ForegroundColor Yellow }
  Write-Host "   -> Rebuild the EXE with these included (hidden-imports) or run the agent from your venv." -ForegroundColor Yellow
} else {
  Write-Host "`n API reachable and no 'module missing' codes returned by the endpoints tested." -ForegroundColor Green
> > }

The running packaged agent lacks modules:

- icmplib (used by /networking/ping)
- opcua (used by /networking/opcua/test)
  -> Rebuild the EXE with these included (hidden-imports) or run the agent from your venv.
  PS C:\WINDOWS\system32>
