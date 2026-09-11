@echo off
setlocal
cd /d "%~dp0"
set ELECTRON_RUN_AS_NODE=
if exist "runtime\electron\electron.exe" (
  start "" "runtime\electron\electron.exe" "desktop\main.cjs"
  exit /b 0
)
if exist "node_modules\electron\dist\electron.exe" (
  start "" "node_modules\electron\dist\electron.exe" "desktop\main.cjs"
  exit /b 0
)
echo Runtime missing. Copy the complete portable folder, or run scripts\setup.ps1 for a source checkout.
pause
exit /b 1
