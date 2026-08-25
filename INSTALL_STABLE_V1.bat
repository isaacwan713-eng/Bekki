@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALL_STABLE_V1.ps1" %*
if errorlevel 1 (
  echo.
  echo Bekki Stable V1.3.9.5 installation failed. The previous runtime was restored.
  pause
  exit /b 1
)
echo.
echo Bekki Stable V1.3.9.5 installation completed.
pause
