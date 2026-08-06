@echo off
echo This audits whether the trading_mvp objective can be marked complete.
echo It is read-only and does not start collectors, postprocess, replay, grid-search, live orders, API keys, leverage or margin.
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\trading_goal_completion_audit.ps1"
pause
