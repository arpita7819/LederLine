@echo off
setlocal
cd /d "%~dp0"
if not exist backend\.venv\Scripts\python.exe (
  echo Creating Python environment...
  py -3 -m venv backend\.venv
  call backend\.venv\Scripts\activate.bat
  python -m pip install -r backend\requirements.txt
) else (
  call backend\.venv\Scripts\activate.bat
)
if not exist backend\.env copy backend\.env.example backend\.env
start "Ledgerline API" cmd /k "cd /d ""%~dp0backend"" && call .venv\Scripts\activate.bat && uvicorn app.main:app --reload"
start "Ledgerline Website" cmd /k "cd /d ""%~dp0demo"" && py -m http.server 5173"
timeout /t 3 >nul
start http://127.0.0.1:5173
