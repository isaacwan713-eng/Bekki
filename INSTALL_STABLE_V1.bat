@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0INSTALL_STABLE_V1.ps1" %*
if errorlevel 1 (
  echo.
  echo Bekki Screenshot Multipass OCR V1.10.27 installation failed. The previous runtime was restored.
  pause
  exit /b 1
)
echo.
echo Bekki Screenshot Multipass OCR V1.10.27 installation completed.
pause
