@echo off
setlocal EnableExtensions
title Aqua Lite setup
cd /d "%~dp0"

set "DEST=%LOCALAPPDATA%\AquaLite"
set "APPDIR=%DEST%\app"
set "VENV=%DEST%\venv"

echo.
echo  ================================================
echo    Aqua Lite setup  -  voice dictation for Windows
echo  ================================================
echo.

rem ---- stop a running copy so files can be replaced
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name like 'python%%'\" | Where-Object { ($_.CommandLine -like '*AquaLite.pyw*' -or $_.CommandLine -like '*Flowlite.pyw*') -and $_.CommandLine -notlike '*--selftest*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1

rem ---- remove the old "Flowlite" install (same app, previous name); settings move over automatically
powershell -NoProfile -Command "foreach($f in @('Programs','Desktop','Startup')){ $p=[Environment]::GetFolderPath($f)+'\Flowlite.lnk'; if(Test-Path $p){ Remove-Item $p } }" >nul 2>&1
if exist "%LOCALAPPDATA%\Flowlite" rmdir /s /q "%LOCALAPPDATA%\Flowlite" >nul 2>&1

rem ---- 1. find Python 3.11-3.13 (or install 3.12)
set "PY="
for %%v in (3.12 3.13 3.11) do (
  if not defined PY (
    py -%%v -c "import sys" >nul 2>&1 && set "PY=py -%%v"
  )
)
if not defined PY (
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)
if not defined PY (
  echo [1/5] Python not found - installing Python 3.12 with winget...
  winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  ) else (
    echo.
    echo  Could not install Python automatically.
    echo  Install Python 3.12 from https://www.python.org/downloads/ ^(tick "Add to PATH"^), then run this again.
    pause
    exit /b 1
  )
) else (
  echo [1/5] Using Python: %PY%
)

rem ---- 2. copy the app
echo [2/5] Copying Aqua Lite to %APPDIR%
if not exist "%APPDIR%" mkdir "%APPDIR%"
robocopy "%~dp0." "%APPDIR%" /E /NFL /NDL /NJH /NJS /NP /XD .venv __pycache__ /XF *.zip >nul
if errorlevel 8 (
  echo  Copy failed.
  pause
  exit /b 1
)

rem ---- 3. private Python environment + packages
if not exist "%VENV%\Scripts\python.exe" (
  echo [3/5] Creating a private Python environment...
  if exist "%PY%" ( "%PY%" -m venv "%VENV%" ) else ( %PY% -m venv "%VENV%" )
)
if not exist "%VENV%\Scripts\python.exe" (
  echo  Could not create the Python environment.
  pause
  exit /b 1
)
echo [3/5] Installing packages (first time takes a few minutes)...
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip --quiet --disable-pip-version-check
"%VENV%\Scripts\python.exe" -m pip install -r "%APPDIR%\requirements.txt" --quiet --disable-pip-version-check
if errorlevel 1 (
  echo  Package install failed - check your internet connection and run install.bat again.
  pause
  exit /b 1
)

rem ---- 4. check everything works
echo [4/5] Running self-test...
"%VENV%\Scripts\python.exe" "%APPDIR%\AquaLite.pyw" --selftest
if errorlevel 1 (
  echo  Self-test failed - see the message above.
  pause
  exit /b 1
)
echo       Downloading the offline speech model (small, ~480 MB, one time)...
"%VENV%\Scripts\python.exe" -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8'); print('      model ready')"
if errorlevel 1 echo       (Model download skipped - it will download on first offline use, or use a Groq key.)

rem ---- 5. shortcuts: Start menu, Desktop, run at startup
echo [5/5] Creating shortcuts...
set "PS=$w=New-Object -ComObject WScript.Shell; $t='%VENV%\Scripts\pythonw.exe'; $a='\"%APPDIR%\AquaLite.pyw\"'; $i='%APPDIR%\assets\aqualite.ico';"
set "PS=%PS% foreach($f in @('Programs','Desktop','Startup')){ $p=[Environment]::GetFolderPath($f)+'\Aqua Lite.lnk'; $s=$w.CreateShortcut($p); $s.TargetPath=$t; $s.Arguments=$a; $s.WorkingDirectory='%APPDIR%'; $s.IconLocation=$i; $s.Description='Aqua Lite voice dictation'; $s.Save() }"
powershell -NoProfile -ExecutionPolicy Bypass -Command "%PS%"

echo.
echo  Done! Aqua Lite is starting - look for the small bar at the bottom of your screen
echo  and the icon in the system tray. Hold CTRL + WIN, speak, and let go.
echo.
start "" "%VENV%\Scripts\pythonw.exe" "%APPDIR%\AquaLite.pyw"
timeout /t 8 >nul
endlocal
