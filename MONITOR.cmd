@echo off
title 72H DENSE WS COLLECTOR MONITOR
:loop
cls
echo ======================================================================
echo   72H DENSE WS COLLECTOR LIVE MONITOR (MEXC + GATE.IO)
echo ======================================================================
echo.
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\show_ws_monitor.ps1"
echo.
echo [Note] completed_cycles=0 / rows=0 in raw gate output is completely normal:
echo WS collectors stream continuous ticks directly into .jsonl files.
echo ======================================================================
echo Press Ctrl+C to exit monitor (Collector keeps running in background)
timeout /t 5 >nul
goto loop
