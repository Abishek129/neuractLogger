param(
  [string]$OutDir = 'apps\\desktop\\src-tauri\\icons'
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir -Force | Out-Null }

Add-Type -AssemblyName System.Drawing

# Create a simple 64x64 green square icon as a placeholder
$bmp = New-Object System.Drawing.Bitmap 64,64
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.Clear([System.Drawing.Color]::FromArgb(255,34,160,107))  # #22a06b
$g.Dispose()

# Convert Bitmap -> Icon and save to ICO file
$hIcon = $bmp.GetHicon()
$icon = [System.Drawing.Icon]::FromHandle($hIcon)
$outPath = Join-Path $OutDir 'icon.ico'
$fs = [System.IO.File]::Open($outPath,'Create')
$icon.Save($fs)
$fs.Close()
$bmp.Dispose()

Write-Host "Created placeholder icon at $outPath"

