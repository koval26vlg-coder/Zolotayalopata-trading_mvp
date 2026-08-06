@echo off
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\start_funding_collect_visible.ps1" -Days 7 -PlanOnly
pause
