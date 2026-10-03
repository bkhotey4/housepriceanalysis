@echo off
cd /d "%~dp0"
python app.py
if errorlevel 1 (
  echo.
  echo Could not start. If Python is not found, try: py app.py
  pause
)
