@echo off
echo This is a read-only visible monitor for the active trading_mvp run.
echo It does not start collectors, postprocess, replay, grid-search, live orders, API keys, leverage or margin.
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\trading_active_run_monitor.ps1" -IntervalSec 60
pause
