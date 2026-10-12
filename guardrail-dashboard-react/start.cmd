@echo off
cd /d "%~dp0"
set "DASH_NODE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
if not exist "%DASH_NODE%" set "DASH_NODE=node"
if not exist "node_modules\vite\bin\vite.js" (
  echo Dependencies missing. Please follow README.md.
  pause
  exit /b 1
)
"%DASH_NODE%" node_modules\vite\bin\vite.js preview --host 127.0.0.1 --port 5173 --strictPort
pause
