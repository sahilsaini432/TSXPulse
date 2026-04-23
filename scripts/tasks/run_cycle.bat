@echo off
REM Wrapper called by Windows Task Scheduler to run one orchestrator cycle.
REM Activates the project venv and invokes run_cycle.py. All stdout/stderr goes
REM to logs/runner.log via the Python logging setup.

set PROJECT_ROOT=E:\Projects\TSXPulse
cd /d "%PROJECT_ROOT%"
call "%PROJECT_ROOT%\.venv\Scripts\activate.bat"
python "%PROJECT_ROOT%\scripts\run_cycle.py"
exit /b %ERRORLEVEL%
