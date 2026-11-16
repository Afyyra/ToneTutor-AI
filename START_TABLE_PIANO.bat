@echo off
setlocal
cd /d "%~dp0"
if exist "venv\Scripts\python.exe" (set "PY=venv\Scripts\python.exe") else if exist ".venv\Scripts\python.exe" (set "PY=.venv\Scripts\python.exe") else (set "PY=python")
echo Starting the optional local webcam piano for learner DEMO-001...
"%PY%" table_piano.py --mode coach --learner DEMO-001
if errorlevel 1 echo See TABLE_PIANO_SETUP.md for the model download and webcam library setup.
pause
