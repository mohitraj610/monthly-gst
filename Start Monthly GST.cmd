@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run Setup.cmd once before starting Monthly GST.
  pause
  exit /b 1
)
if not exist "frontend\dist\index.html" (
  echo The interface needs building. Run Setup.cmd once.
  pause
  exit /b 1
)
set "PYTHONPATH=%~dp0backend"
echo Monthly GST - filing preparation preview
echo Open http://127.0.0.1:8765 in your browser.
echo Keep this window open while using the app. Press Ctrl+C to stop.
".venv\Scripts\python.exe" -m monthly_gst.cli --port 8765
if errorlevel 1 pause
