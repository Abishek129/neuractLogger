param(
  [string]$Base = 'http://127.0.0.1:5175'
)

$ErrorActionPreference = 'SilentlyContinue'

$lf = Join-Path $env:ProgramData 'PLCLogger\agent\agent.lock.json'
if (-not (Test-Path $lf)) { Write-Host "Lockfile not found: $lf" -ForegroundColor Yellow }
$tok = ''
try { $tok = (Get-Content $lf -Raw | ConvertFrom-Json).token } catch {}
$h = @{ }
if ($tok) { $h['Authorization'] = "Bearer $tok"; $h['X-Agent-Token'] = $tok }

Write-Host "GET /health" -ForegroundColor Cyan
try { Invoke-RestMethod -Uri "$Base/health" -Headers $h -TimeoutSec 5 | Format-List | Out-String | Write-Host } catch { Write-Host $_.Exception.Message -ForegroundColor Red }

Write-Host "`nPOST /networking/ping" -ForegroundColor Cyan
try { Invoke-RestMethod -Method Post -Uri "$Base/networking/ping" -Headers $h -ContentType 'application/json' -Body (@{ target='127.0.0.1'; count=1; timeoutMs=800 } | ConvertTo-Json) | Format-List | Out-String | Write-Host } catch { Write-Host $_.Exception.Message -ForegroundColor Yellow }

Write-Host "`nPOST /networking/opcua/test" -ForegroundColor Cyan
try { Invoke-RestMethod -Method Post -Uri "$Base/networking/opcua/test" -Headers $h -ContentType 'application/json' -Body (@{ endpoint='opc.tcp://127.0.0.1:4840' } | ConvertTo-Json) | Format-List | Out-String | Write-Host } catch { Write-Host $_.Exception.Message -ForegroundColor Yellow }

