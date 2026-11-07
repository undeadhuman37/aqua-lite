; Aqua Lite one-click installer. Build with: python installer/build.py  (needs NSIS / makensis)
; It bundles the app files and runs install.bat with its output shown in the window, so the exe and
; install.bat always install the same way (private Python environment in %LOCALAPPDATA%\AquaLite).
Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"

!ifndef VERSION
  !define VERSION "0.0.0"
!endif
!define APPNAME "Aqua Lite"
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\AquaLite"

Name "${APPNAME}"
OutFile "..\dist\AquaLite-Setup-${VERSION}.exe"
RequestExecutionLevel user
SetCompressor /SOLID lzma
ShowInstDetails show
BrandingText "${APPNAME} ${VERSION}  -  free and open source"
Caption "${APPNAME} Setup"

VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "${APPNAME}"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "FileDescription" "${APPNAME} Setup"
VIAddVersionKey "LegalCopyright" "MIT License"

!define MUI_ICON "..\assets\aqualite.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "build\welcome.bmp"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_RIGHT
!define MUI_HEADERIMAGE_BITMAP "build\header.bmp"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE_3LINES

!define MUI_WELCOMEPAGE_TITLE "Welcome to ${APPNAME}"
!define MUI_WELCOMEPAGE_TEXT "Free voice dictation for Windows.$\r$\n$\r$\nHold Ctrl + Win, speak, and let go: your words appear wherever you're typing - WhatsApp, Gmail, Word, anything.$\r$\n$\r$\nSetup installs what it needs (including Python, if this PC doesn't have it) and downloads the offline speech models, about 600 MB, one time. It takes a few minutes and needs an internet connection.$\r$\n$\r$\nPrivacy: no account, no tracking. Only update checks and model downloads go online, unless you add a cloud API key.$\r$\n$\r$\nClick Install to continue."
!define MUI_FINISHPAGE_TITLE "${APPNAME} is ready"
!define MUI_FINISHPAGE_TEXT "${APPNAME} is running - look for its icon in the system tray.$\r$\n$\r$\nHold Ctrl + Win and talk. Tap Ctrl + Win twice for hands-free.$\r$\n$\r$\nIt keeps itself up to date."

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_LANGUAGE "English"

Section "Aqua Lite"
  InitPluginsDir
  SetOutPath "$PLUGINSDIR\src"
  File "build\src\*.*"
  File /r "build\src\aqualite"
  File /r "build\src\assets"
  DetailPrint "Setting up ${APPNAME} ${VERSION}..."
  System::Call 'Kernel32::SetEnvironmentVariable(t "AQUALITE_SETUP", t "1")i'
  nsExec::ExecToLog '"$SYSDIR\cmd.exe" /d /c ""$PLUGINSDIR\src\install.bat""'
  Pop $0
  ${If} $0 != 0
    DetailPrint "Setup stopped (code $0)."
    MessageBox MB_ICONEXCLAMATION|MB_OK "${APPNAME} setup didn't finish. Scroll up in the window to see what went wrong, check your internet connection, and run setup again."
    Abort
  ${EndIf}

  ; entry in Settings > Apps so it can be removed like any other app
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINSTKEY}" "Publisher" "Aqua Lite (open source)"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayIcon" "$LOCALAPPDATA\AquaLite\app\assets\aqualite.ico"
  WriteRegStr HKCU "${UNINSTKEY}" "InstallLocation" "$LOCALAPPDATA\AquaLite"
  WriteRegStr HKCU "${UNINSTKEY}" "UninstallString" '"$SYSDIR\cmd.exe" /c "$LOCALAPPDATA\AquaLite\app\uninstall.bat"'
  WriteRegStr HKCU "${UNINSTKEY}" "URLInfoAbout" "https://github.com/undeadhuman37/aqua-lite"
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoRepair" 1
  WriteRegDWORD HKCU "${UNINSTKEY}" "EstimatedSize" 1100000
SectionEnd
