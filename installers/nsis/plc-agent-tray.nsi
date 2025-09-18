!include "MUI2.nsh"

Name "Neuract Agent Tray"
OutFile "dist\\installer\\PLC_Agent_Tray_Setup.exe"
InstallDir "C:\\Program Files\\NeuractLogger\\agent-tray"
RequestExecutionLevel admin

!define MUI_ABORTWARNING
!define MUI_ICON "apps\\desktop\\src-tauri\\icons\\icon.ico"
!define MUI_UNICON "apps\\desktop\\src-tauri\\icons\\icon.ico"

!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

Section "Core files" SEC_CORE
  SetOutPath "$INSTDIR"
  File /r "dist\\plc-agent-tray\\*"
  File /r "dist\\plc-agent-core\\*"
  ; Start Menu shortcut
  CreateDirectory "$SMPROGRAMS\\NeuractLogger"
  CreateShortCut "$SMPROGRAMS\\NeuractLogger\\Neuract Agent Tray.lnk" "$INSTDIR\\plc-agent-tray.exe"
SectionEnd

Section /o "Autostart on login" SEC_AUTOSTART
  WriteRegStr HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Run" "NeuractLoggerAgentTray" '"$INSTDIR\\plc-agent-tray.exe"'
SectionEnd

Section "Uninstall"
  Delete "$SMPROGRAMS\\NeuractLogger\\Neuract Agent Tray.lnk"
  RMDir "$SMPROGRAMS\\NeuractLogger"
  DeleteRegValue HKCU "Software\\Microsoft\\Windows\\CurrentVersion\\Run" "NeuractLoggerAgentTray"
  RMDir /r "$INSTDIR"
SectionEnd


