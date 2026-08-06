@echo off
pwsh -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\funding_candidate_watchlist.ps1" %*
