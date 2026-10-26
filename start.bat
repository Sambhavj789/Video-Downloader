@echo off
REM Double-click entry point for the browser UI (no terminal knowledge needed).
cd /d "%~dp0"
python -m vd ui
if errorlevel 1 (
  echo.
  echo UI start nahi hui. Terminal band mat karo - upar ka error padho.
  pause
)
