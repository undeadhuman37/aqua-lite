@echo off
setlocal
title Aqua Lite uninstall
echo Closing Aqua Lite...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name like 'python%%'\" | Where-Object { $_.CommandLine -like '*AquaLite.pyw*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
echo Removing shortcuts...
powershell -NoProfile -Command "foreach($f in @('Programs','Desktop','Startup')){ $p=[Environment]::GetFolderPath($f)+'\Aqua Lite.lnk'; if(Test-Path $p){ Remove-Item $p } }"
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\AquaLite" /f >nul 2>&1
echo Removing the app...
rmdir /s /q "%LOCALAPPDATA%\AquaLite" 2>nul
echo.
choice /m "Also delete your settings, dictionary, snippets and history"
if errorlevel 2 goto done
rmdir /s /q "%APPDATA%\AquaLite" 2>nul
:done
echo Aqua Lite has been removed.
pause
