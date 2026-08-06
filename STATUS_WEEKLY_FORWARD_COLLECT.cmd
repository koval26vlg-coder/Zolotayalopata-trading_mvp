@echo off
schtasks /Query /TN "Trading MVP Weekly Forward Collect" /V /FO LIST | findstr /C:"TaskName" /C:"Status" /C:"Last Run Time" /C:"Last Result" /C:"Next Run Time"
echo.
echo Last log lines:
for /f "delims=" %%f in ('dir /b /o-d "C:\Users\koval\Documents\ZolotyayLopata\logs\weekly-forward\*.log" 2^>nul') do (
    powershell -NoProfile -Command "Get-Content 'C:\Users\koval\Documents\ZolotyayLopata\logs\weekly-forward\%%f' -Tail 5"
    goto :done
)
:done
pause
