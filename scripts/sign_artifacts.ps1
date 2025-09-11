param(
  [Parameter(Mandatory=$true)] [string]$Path,
  [string]$Thumbprint = $env:SIGN_CERT_THUMBPRINT,
  [string]$Timestamp = 'http://timestamp.digicert.com'
)

$ErrorActionPreference = 'Stop'

if (-not (Get-Command signtool.exe -ErrorAction SilentlyContinue)) {
  Write-Error 'signtool.exe not found. Install Windows SDK Signing Tools.'
}

if (-not $Thumbprint) { Write-Error 'Provide certificate thumbprint via -Thumbprint or SIGN_CERT_THUMBPRINT env var.' }

$files = Get-ChildItem -Path $Path -Recurse -Include *.exe,*.msi -File
foreach ($f in $files) {
  Write-Host "Signing $($f.FullName)"
  & signtool.exe sign /fd SHA256 /td SHA256 /tr $Timestamp /sha1 $Thumbprint "$($f.FullName)"
}
