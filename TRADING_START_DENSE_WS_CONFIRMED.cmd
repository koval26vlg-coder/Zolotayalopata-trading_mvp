@echo off
echo This starts a visible 72-hour research-only dense WS collect for the sweep/reversal branch.
echo Do not run unless the user explicitly approved this long run.
echo Research-only: no live orders, no API keys, no leverage, no margin.
echo Running pre-start readiness check...
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\trading_ws_collect_readiness.ps1"
if errorlevel 1 (
  echo Readiness check failed. Start cancelled before asking for START72H.
  pause
  exit /b 1
)
echo Readiness check passed.
echo Running approval contract check...
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\trading_collect_approval_contract.ps1"
if errorlevel 1 (
  echo Approval contract check failed. Start cancelled before asking for START72H.
  pause
  exit /b 1
)
echo Approval contract check passed.
echo Building approval evidence packet...
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\trading_ws_collect_approval_packet.ps1"
if errorlevel 1 (
  echo Approval evidence packet failed. Start cancelled before asking for START72H.
  pause
  exit /b 1
)
echo Approval evidence packet written.
set /p CONFIRM=Type START72H to begin: 
if /I not "%CONFIRM%"=="START72H" (
  echo Start cancelled.
  pause
  exit /b 1
)
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\start_ws_collect_visible.ps1" -Hours 72 -Exchanges "mexc,gateio" -UniversePath "%~dp0exports\trading-mvp\universe\no_binance_dense_ws_sweep_20260628.csv" -MaxSymbols 300 -MaxPairsPerExchange 16 -UpdateInterval "100ms" -EarlyDensityCheckAfterMinutes 60 -EarlyDensityMinLinesPerMinute 10 -EarlyDensityMinRawLines 600 -EarlyDensityMinRawFiles 1 -ZeroLineAbortAfterMinutes 10 -SchemaProbeAfterMinutes 1 -SchemaProbeMaxLines 20 -ConfirmedLongRun
