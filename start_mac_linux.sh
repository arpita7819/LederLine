#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -d backend/.venv ]; then python3 -m venv backend/.venv; fi
source backend/.venv/bin/activate
pip install -r backend/requirements.txt
[ -f backend/.env ] || cp backend/.env.example backend/.env
(cd backend && ../backend/.venv/bin/uvicorn app.main:app --reload) &
API_PID=$!
(cd demo && python3 -m http.server 5173) &
WEB_PID=$!
trap 'kill $API_PID $WEB_PID 2>/dev/null || true' EXIT
echo "Ledgerline: http://127.0.0.1:5173"
echo "API docs: http://127.0.0.1:8000/docs"
wait
