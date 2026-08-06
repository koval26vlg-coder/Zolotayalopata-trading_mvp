@echo off
echo This starts a visible 7-day research-only funding/basis collect.
echo Do not run unless the user explicitly approved this long run.
set /p CONFIRM=Type START7D to begin: 
if /I not "%CONFIRM%"=="START7D" (
  echo Start cancelled.
  pause
  exit /b 1
)
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\start_funding_collect_visible.ps1" -Days 7 -ConfirmedLongRun
