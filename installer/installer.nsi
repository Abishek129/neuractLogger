; NSIS installer skeleton for PLC Logger (Agent + UI)
; Adjust paths and sign as needed.

!define APPNAME "PLC Logger"
!define COMPANY "PLCLogger"
!define AGENTDIR "dist\plclogger-agent"
!define INSTALLDIR "$PROGRAMFILES\PLCLogger"
!define DATADIR "$PROGRAMDATA\PLCLogger"

OutFile "plclogger-setup.exe"
InstallDir "${INSTALLDIR}"
ShowInstDetails show
RequestExecutionLevel admin

Section "Install"
  SetOutPath "${INSTALLDIR}\agent"
  File /r "${AGENTDIR}\*.*"
  CreateDirectory "${DATADIR}\agent\logs"
  ; Register and start service
  ExecWait 'powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\install_service.ps1" install'
  
  ; Prepare UI folder (optional, if bundled separately)
  CreateDirectory "${INSTALLDIR}\ui"

  ; Shortcuts: Start Menu and Desktop (only if UI exe exists)
  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  IfFileExists "${INSTALLDIR}\ui\${APPNAME}.exe" +2 0
    CreateShortcut "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" "${INSTALLDIR}\ui\${APPNAME}.exe"
  IfFileExists "${INSTALLDIR}\ui\${APPNAME}.exe" +2 0
    CreateShortcut "$DESKTOP\${APPNAME}.lnk" "${INSTALLDIR}\ui\${APPNAME}.exe"
  ; Logs folder shortcut
  CreateShortcut "$SMPROGRAMS\${APPNAME}\Agent Logs.lnk" "${DATADIR}\agent\logs"
SectionEnd

Section "Uninstall"
  ExecWait 'powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\install_service.ps1" remove'
  RMDir /r "${INSTALLDIR}"
  Delete "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk"
  Delete "$SMPROGRAMS\${APPNAME}\Agent Logs.lnk"
  RMDir "$SMPROGRAMS\${APPNAME}"
  Delete "$DESKTOP\${APPNAME}.lnk"
  ; Optional: leave data under ProgramData
SectionEnd
