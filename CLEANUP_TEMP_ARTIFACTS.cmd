@echo off
setlocal
cd /d "%~dp0"
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\cleanup_temp_artifacts.ps1" %*
endlocal
