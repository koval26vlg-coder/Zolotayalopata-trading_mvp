@echo off
title trading_mvp PIT n05 monitor
pwsh -NoExit -NoProfile -ExecutionPolicy Bypass -File "C:\Users\koval\Documents\ZolotyayLopata\tools\trading_active_run_monitor.ps1" -GatePath "C:\Users\koval\Documents\ZolotyayLopata\docs\agent-log\active-run-gate.json" -IntervalSec 30
