@echo off
REM Kannur Prices Auto-Startup Script with Logging
REM Uses Python 3.13 (pythonw.exe)

set PYTHONW="C:\Users\hp\AppData\Local\Programs\Python\Python313\pythonw.exe"
set SCRIPT="C:\scripts\pepper4.py"
set OUTPUT="C:\scripts\prices.html"
set LOGFILE="C:\scripts\kannur_prices_log.txt"

echo [%DATE% %TIME%] Starting Kannur Prices script... >> %LOGFILE%
%PYTHONW% %SCRIPT% --commodities black-pepper,rubber,arecanut --auto-variants --output %OUTPUT% >> %LOGFILE% 2>&1

echo [%DATE% %TIME%] Finished. >> %LOGFILE%
exit
