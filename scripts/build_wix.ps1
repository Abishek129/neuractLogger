param(
  [string]$AgentDir = 'dist\plclogger-agent',
  [string]$UiDir = '',
  [string]$Out = 'installer\PLCLogger.msi'
)

$ErrorActionPreference = 'Stop'

# Ensure WiX 3.x tools are available (add common install path if needed)
$wix3bin = 'C:\Program Files (x86)\WiX Toolset v3.14\bin'
if (Test-Path -LiteralPath $wix3bin) {
  if ($env:Path -notlike "*$wix3bin*") { $env:Path = "$wix3bin;$env:Path" }
}


# PS 5.1-safe detection (no null-conditional operator)
$heatCmd   = Get-Command heat.exe   -ErrorAction SilentlyContinue
$candleCmd = Get-Command candle.exe -ErrorAction SilentlyContinue
$lightCmd  = Get-Command light.exe  -ErrorAction SilentlyContinue

$heat   = if ($heatCmd)   { $heatCmd.Source }   else { $null }
$candle = if ($candleCmd) { $candleCmd.Source } else { $null }
$light  = if ($lightCmd)  { $lightCmd.Source }  else { $null }

if (-not ($heat -and $candle -and $light)) {
  Write-Error "WiX 3.x not found. Make sure Heat/Candle/Light are on PATH (e.g., Chocolatey wixtoolset)."
}

# Work folder
New-Item -ItemType Directory -Path 'installer\wix' -Force | Out-Null

# Ensure agent_service.exe exists in AgentDir; copy from dist root if available
try {
  $svcInFolder = Join-Path $AgentDir 'agent_service.exe'
  $distRootSvc = Join-Path (Join-Path (Split-Path $PSScriptRoot -Parent) 'dist') 'agent_service.exe'
  if (-not (Test-Path $svcInFolder) -and (Test-Path $distRootSvc)) {
    Copy-Item -Force $distRootSvc $svcInFolder
  }
} catch {}

# Auto-detect UI dir if not provided
if (-not $UiDir -or -not (Test-Path $UiDir)) {
  try {
    $guess = Get-ChildItem 'apps\desktop\src-tauri\target\release' -Recurse -Filter '*.exe' -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($guess) { $UiDir = $guess.DirectoryName }
  } catch {}
}

# Harvest Agent files (WiX 3 heat)
& $heat dir $AgentDir `
  -dr AGENTDIR `
  -cg AgentGroup `
  -ke -srd -sreg -scom -sfrag `
  -var var.AgentDir `
  -out installer\wix\AgentGroup.wxs
if ($LASTEXITCODE -ne 0) { throw "WiX heat (Agent) failed with code $LASTEXITCODE" }

# Optionally harvest UI files
$uiExeName = ''
if ($UiDir -and (Test-Path $UiDir)) {
  & $heat dir $UiDir `
    -dr UIDIR `
    -cg UiGroup `
    -ke -srd -sreg -scom -sfrag `
    -var var.UiDir `
    -out installer\wix\UiGroup.wxs
  if ($LASTEXITCODE -ne 0) { throw "WiX heat (UI) failed with code $LASTEXITCODE" }

  try {
    $uiExe = Get-ChildItem -Path $UiDir -Recurse -Filter '*.exe' -File | Select-Object -First 1
    if ($uiExe) { $uiExeName = $uiExe.Name }
  } catch {}
} else {
  # Empty UI group (WiX 3 schema)
  Set-Content -Path 'installer\wix\UiGroup.wxs' -Encoding UTF8 -Value @"
<?xml version="1.0" encoding="UTF-8"?>
<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi">
  <Fragment>
    <ComponentGroup Id="UiGroup" />
  </Fragment>
</Wix>
"@
}

# Main.wxs (WiX 3 schema)
$main = @"
<?xml version="1.0" encoding="UTF-8"?>
<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi">
  <Product Id="*" Name="PLC Logger" Manufacturer="PLCLogger" Version="0.1.0" Language="1033" UpgradeCode="{E4D7E1C0-DEAD-BEEF-C0DE-1234567890AB}">
    <Package InstallerVersion="500" Compressed="yes" InstallScope="perMachine" />
    <MajorUpgrade DowngradeErrorMessage="A newer version is already installed." />
    <MediaTemplate />

    <Feature Id="MainFeature" Title="PLC Logger" Level="1">
      <ComponentGroupRef Id="AgentGroup" />
      <ComponentGroupRef Id="UiGroup" />
      <ComponentGroupRef Id="ExtrasGroup" />
    </Feature>
  </Product>

  <Fragment>
    <Directory Id="TARGETDIR" Name="SourceDir">
      <Directory Id="ProgramFiles64Folder">
        <Directory Id="INSTALLDIR" Name="PLCLogger">
          <Directory Id="AGENTDIR" Name="agent" />
          <Directory Id="UIDIR" Name="ui" />
        </Directory>
      </Directory>

      <Directory Id="ProgramMenuFolder">
        <Directory Id="AppProgramMenuDir" Name="PLC Logger" />
      </Directory>

      <Directory Id="DesktopFolder" />

      <Directory Id="CommonAppDataFolder">
        <Directory Id="PD_ROOT"  Name="PLCLogger">
          <Directory Id="PD_AGENT" Name="agent">
            <Directory Id="PD_LOGS" Name="logs" />
          </Directory>
        </Directory>
      </Directory>
    </Directory>
  </Fragment>
</Wix>
"@
Set-Content -Path 'installer\wix\Main.wxs' -Encoding UTF8 -Value $main

# Extras.wxs with Start Menu/Desktop shortcuts (valid KeyPath via registry values)
if ($uiExeName) {
  $extras = @"
<?xml version="1.0" encoding="UTF-8"?>
<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi">
  <Fragment>
    <ComponentGroup Id="ExtrasGroup">
      <Component Id="CreateDataDirs" Guid="{D22A0A6B-6A8F-4D2D-A2B1-9BF7D9B7F001}" Directory="PD_LOGS">
        <CreateFolder />
        <RegistryValue Root="HKLM" Key="Software\PLCLogger" Name="PD_LOGS" Type="integer" Value="1" KeyPath="yes" />
      </Component>

      <Component Id="UiStartMenuShortcut" Guid="{D22A0A6B-6A8F-4D2D-A2B1-9BF7D9B7F002}" Directory="AppProgramMenuDir">
        <Shortcut Id="StartMenuShortcut" Name="PLC Logger" Target="[UIDIR]$uiExeName" WorkingDirectory="UIDIR" />
        <RemoveFile Id="RmStartMenuShortcut" On="uninstall" Name="PLC Logger.lnk" />
        <RegistryValue Root="HKLM" Key="Software\PLCLogger" Name="SM_Shortcut" Type="integer" Value="1" KeyPath="yes" />
      </Component>

      <Component Id="UiDesktopShortcut" Guid="{D22A0A6B-6A8F-4D2D-A2B1-9BF7D9B7F003}" Directory="DesktopFolder">
        <Shortcut Id="DesktopShortcut" Name="PLC Logger" Target="[UIDIR]$uiExeName" WorkingDirectory="UIDIR" />
        <RemoveFile Id="RmDesktopShortcut" On="uninstall" Name="PLC Logger.lnk" />
        <RegistryValue Root="HKLM" Key="Software\PLCLogger" Name="Desk_Shortcut" Type="integer" Value="1" KeyPath="yes" />
      </Component>
    </ComponentGroup>
  </Fragment>
</Wix>
"@
} else {
  $extras = @"
<?xml version="1.0" encoding="UTF-8"?>
<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi">
  <Fragment>
    <ComponentGroup Id="ExtrasGroup">
      <Component Id="CreateDataDirs" Guid="{D22A0A6B-6A8F-4D2D-A2B1-9BF7D9B7F001}" Directory="PD_LOGS">
        <CreateFolder />
        <RegistryValue Root="HKLM" Key="Software\PLCLogger" Name="PD_LOGS" Type="integer" Value="1" KeyPath="yes" />
      </Component>
    </ComponentGroup>
  </Fragment>
</Wix>
"@
}
Set-Content -Path 'installer\wix\Extras.wxs' -Encoding UTF8 -Value $extras

# Inject ServiceInstall/ServiceControl into harvested AgentGroup (v3 namespace)
$agentWxsPath = 'installer\wix\AgentGroup.wxs'
if (Test-Path $agentWxsPath) {
  try {
    [xml]$x = Get-Content -LiteralPath $agentWxsPath -Raw
    $nsUri = $x.DocumentElement.NamespaceURI
    if (-not $nsUri) { $nsUri = 'http://schemas.microsoft.com/wix/2006/wi' }

    # Find the Component that includes agent_service.exe (namespace-agnostic)
    $svcComp = $x.SelectSingleNode("//*[local-name()='Component'][descendant::*[local-name()='File' and @Name='agent_service.exe']]")
    if ($svcComp -ne $null) {
      $hasInstall = $svcComp.SelectSingleNode("*[local-name()='ServiceInstall']")
      $hasControl = $svcComp.SelectSingleNode("*[local-name()='ServiceControl']")

      if (-not $hasInstall) {
        $svcInstall = $x.CreateElement('ServiceInstall', $nsUri)
        $svcInstall.SetAttribute('Id', 'AgentServiceInstall')
        $svcInstall.SetAttribute('Name', 'PLCLoggerAgent')
        $svcInstall.SetAttribute('DisplayName', 'PLC Logger Agent')
        $svcInstall.SetAttribute('Description', 'Runs the PLC Logger Agent API and background jobs as a Windows service.')
        $svcInstall.SetAttribute('Start', 'auto')
        $svcInstall.SetAttribute('Type', 'ownProcess')
        $svcInstall.SetAttribute('ErrorControl', 'normal')
        [void]$svcComp.AppendChild($svcInstall)
      }

      if (-not $hasControl) {
        $svcCtrl = $x.CreateElement('ServiceControl', $nsUri)
        $svcCtrl.SetAttribute('Id', 'AgentServiceControl')
        $svcCtrl.SetAttribute('Name', 'PLCLoggerAgent')
        $svcCtrl.SetAttribute('Start', 'install')
        $svcCtrl.SetAttribute('Stop', 'both')
        $svcCtrl.SetAttribute('Remove', 'uninstall')
        $svcCtrl.SetAttribute('Wait', 'yes')
        [void]$svcComp.AppendChild($svcCtrl)
      }

      $x.Save((Resolve-Path $agentWxsPath))
    } else {
      Write-Warning "agent_service.exe not found in harvested AgentGroup; service wiring skipped."
    }
  } catch {
    Write-Warning "Failed to inject ServiceInstall/ServiceControl: $_"
  }
}

# BUILD with WiX 3.x: candle + light (x64)
$objs = @()
$wxss = @('installer\wix\Main.wxs','installer\wix\AgentGroup.wxs','installer\wix\Extras.wxs')
if (Test-Path 'installer\wix\UiGroup.wxs') { $wxss += 'installer\wix\UiGroup.wxs' }

foreach ($w in $wxss) {
  $outObj = [System.IO.Path]::ChangeExtension($w, '.wixobj')
  if ($UiDir) {
    & $candle -arch x64 -dAgentDir="$AgentDir" -dUiDir="$UiDir" -out $outObj $w
  } else {
    & $candle -arch x64 -dAgentDir="$AgentDir" -out $outObj $w
  }
  if ($LASTEXITCODE -ne 0) { throw "WiX candle failed for $w with code $LASTEXITCODE" }
  $objs += $outObj
}

& $light -out $Out $objs
if ($LASTEXITCODE -ne 0) { throw "WiX light failed with code $LASTEXITCODE" }

Write-Host "✅ MSI built at $Out"
