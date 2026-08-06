@echo off
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\start_ws_collect_visible.ps1" -Hours 72 -MaxPairsPerExchange 16 -UniversePath "%~dp0exports\trading-mvp\universe\no_binance_dense_ws_sweep_20260628.csv" -PlanOnly
pause
