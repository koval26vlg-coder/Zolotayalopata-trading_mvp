@echo off
rem Регистрирует еженедельный forward-сбор (research-only, публичные REST, без ключей).
rem Понедельник 09:05, лог: logs\weekly-forward, отчёт: docs\analysis\funding-forward.
schtasks /Create /F /TN "Trading MVP Weekly Forward Collect" /SC WEEKLY /D MON /ST 09:05 ^
 /TR "pwsh.exe -NoProfile -File \"C:\Users\koval\Documents\ZolotyayLopata\tools\run_weekly_forward_collect.ps1\""
if %ERRORLEVEL% EQU 0 (echo OK: task registered. Check: STATUS_WEEKLY_FORWARD_COLLECT.cmd) else (echo FAILED: exit %ERRORLEVEL%)
pause
