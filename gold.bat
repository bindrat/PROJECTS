@echo off
REM ===== configure these =====
SET PROJECT_DIR=C:\SCRIPTS
SET VENV_DIR=%PROJECT_DIR%\venv
SET LOGFILE=%PROJECT_DIR%\start_gold_app.log
REM ============================

REM switch to project folder (works across drives)
cd /d "%PROJECT_DIR%"

REM record timestamp
echo ==== Starting at %DATE% %TIME% ==== >> "%LOGFILE%"

REM activate venv (cmd)
if exist "%VENV_DIR%\Scripts\activate.bat" (
    call "%VENV_DIR%\Scripts\activate.bat"
) else (
    echo Virtualenv activate not found at "%VENV_DIR%\Scripts\activate.bat" >> "%LOGFILE%"
    echo Virtualenv activate not found. Exiting. >> "%LOGFILE%"
    pause
    exit /b 1
)

REM run the app and append logs; keep console open on crash
python gold.py >> "%LOGFILE%" 2>&1
if %ERRORLEVEL% neq 0 (
    echo Application exited with error code %ERRORLEVEL% >> "%LOGFILE%"
    echo See log at "%LOGFILE%"
    pause
)
