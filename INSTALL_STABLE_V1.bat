@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALL_STABLE_V1.ps1" %*
if errorlevel 1 (
  echo.
  echo Bekki Knowledge Legacy Visual Evidence Backfill V1.10.54.8 installation failed. The previous runtime was restored.
  pause
  exit /b 1
)
echo.
echo Bekki Knowledge Legacy Visual Evidence Backfill V1.10.54.8 installation completed.
pause
