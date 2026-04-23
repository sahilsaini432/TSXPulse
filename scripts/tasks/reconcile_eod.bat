@echo off
REM Wrapper called by Windows Task Scheduler for EOD reconcile.

set PROJECT_ROOT=E:\Projects\TSXPulse
cd /d "%PROJECT_ROOT%"
call "%PROJECT_ROOT%\.venv\Scripts\activate.bat"
python "%PROJECT_ROOT%\scripts\reconcile_eod.py"
exit /b %ERRORLEVEL%
