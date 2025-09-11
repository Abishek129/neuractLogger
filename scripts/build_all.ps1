$ErrorActionPreference = 'Stop'

Write-Host "==> Building Agent (PyInstaller)"
& powershell -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot\build_agent.ps1"

Write-Host "==> Building Desktop UI (Tauri)"
Push-Location "$PSScriptRoot\..\apps\desktop"
try {
  if (Test-Path 'package-lock.json') { npm ci } else { npm install }
} catch { Write-Warning 'npm install failed, continuing'; }
try {
  npm run tauri:build
} catch {
  Write-Warning 'Tauri build failed. Ensure Rust toolchain and Tauri CLI are installed.'
}
Pop-Location

Write-Host "==> Optional: Building unified MSI via WiX"
if (Get-Command wix.exe -ErrorAction SilentlyContinue) {
  $agentDir = Join-Path "$PSScriptRoot\.." 'dist\plclogger-agent'
  # Attempt to find Tauri App folder containing the UI exe
  $bundleRoot = Join-Path "$PSScriptRoot\..\apps\desktop\src-tauri\target\release\bundle" '.'
  $uiExe = Get-ChildItem -Path $bundleRoot -Recurse -Filter '*.exe' -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq 'PLC Logger.exe' } | Select-Object -First 1
  if ($uiExe) {
    $uiDir = $uiExe.DirectoryName
    Write-Host "WiX: Using UI dir: $uiDir"
    & powershell -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot\build_wix.ps1" -AgentDir $agentDir -UiDir $uiDir -Out (Join-Path "$PSScriptRoot\..\installer" 'PLCLogger.msi')
  } else {
    Write-Warning 'UI exe not found under bundle/. Skipping unified MSI. Build Tauri first.'
  }
} else {
  Write-Warning 'wix.exe not found. Skipping MSI build.'
}

Write-Host "==> Optional: Building NSIS installer (requires makensis)"
if (Get-Command makensis.exe -ErrorAction SilentlyContinue) {
  Push-Location "$PSScriptRoot\..\installer"
  makensis.exe installer.nsi
  Pop-Location
} else {
  Write-Warning 'makensis.exe not found. Skipping NSIS build.'
}

Write-Host "Build pipeline complete. See dist/ and installer/."
