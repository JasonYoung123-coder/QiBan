@echo off
setlocal
cd /d "%~dp0.."
set PYTHONHOME=
set PYTHONPATH=
set PYTHONUTF8=1
if exist "runtime\python\python.exe" (
  "runtime\python\python.exe" -m backend.voice_worker dev
) else (
  ".venv\Scripts\python.exe" -m backend.voice_worker dev
)
pause
