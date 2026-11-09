@echo off
setlocal
cd /d "%~dp0"
echo Requires Python 3.12 or newer. A source checkout also needs Node.js 24 with npm.
python -c "import sys; assert sys.version_info >= (3,12), 'Python 3.12 or newer is required'"
if errorlevel 1 goto failed
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements-lock.txt
if errorlevel 1 goto failed
if exist "frontend\dist\index.html" goto ready
call npm --prefix frontend ci --ignore-scripts --no-audit --no-fund
if errorlevel 1 goto failed
call npm --prefix frontend run build
if errorlevel 1 goto failed
:ready
echo Ready. Open "Start Monthly GST.cmd" and follow the printed address.
pause
exit /b 0
:failed
echo Setup stopped. Read the error above before retrying.
pause
exit /b 1
