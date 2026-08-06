@echo off
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\funding_cost_assumption_gate.ps1" %*
