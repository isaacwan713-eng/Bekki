@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALL_STABLE_V1.ps1" %*
if errorlevel 1 (
  echo.
  echo Bekki Verified Video Site + Companion Bridge Hotfix V1.10.47.3 installation failed. The previous runtime was restored.
  pause
  exit /b 1
)
echo.
echo Bekki Verified Video Site + Companion Bridge Hotfix V1.10.47.3 installation completed.
pause
