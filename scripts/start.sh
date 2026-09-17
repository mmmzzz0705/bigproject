#!/usr/bin/env bash
# ============================================================
#  Gov QA System - one-click start (Linux / macOS)
#  Starts: FastAPI backend :8000  +  Vue frontend :5173
#  Usage: ./start.sh      stop with Ctrl-C or ./stop.sh
# ============================================================
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT=$(pwd)
PY=${PYTHON:-python3}

echo "============================================================"
echo " Gov QA System - starting"
echo " Root: $ROOT"
echo "============================================================"

# Prefer the project virtualenv. Installing into whatever "python3" is on PATH
# is how you end up with "pip installed into A, uvicorn run with B" and the
# confusing ModuleNotFoundError: No module named 'fastapi'.
if [ -n "${PYTHON:-}" ]; then
    echo "[env] Using PYTHON from environment: $PYTHON"
elif [ -x "$ROOT/backend/.venv/bin/python" ]; then
    PY="$ROOT/backend/.venv/bin/python"
    echo "[env] Using project venv: backend/.venv"
else
    echo "[env] No backend/.venv found - falling back to $PY"
    echo "      Recommended: python3 -m venv backend/.venv"
fi

command -v "$PY" >/dev/null || { echo "[ERROR] $PY not found"; exit 1; }
command -v npm     >/dev/null || { echo "[ERROR] npm not found"; exit 1; }

mkdir -p "$ROOT/logs"

# ---------- dependencies ----------
echo
echo "[1/4] Checking backend dependencies..."
if ! "$PY" -c "import fastapi, uvicorn, sqlalchemy" 2>/dev/null; then
    echo "      Installing requirements.txt ..."
    "$PY" -m pip install -r "$ROOT/backend/requirements.txt"
else
    echo "      OK"
fi

echo
echo "[2/4] Checking frontend dependencies..."
if [ ! -d "$ROOT/frontend/node_modules" ]; then
    echo "      Running npm install (first run takes a while)..."
    (cd "$ROOT/frontend" && npm install)
else
    echo "      OK"
fi

cleanup() {
    echo
    echo "Shutting down..."
    [ -n "${BE_PID:-}" ] && kill "$BE_PID" 2>/dev/null || true
    [ -n "${FE_PID:-}" ] && kill "$FE_PID" 2>/dev/null || true
    exit 0
}
trap cleanup INT TERM

# ---------- backend ----------
echo
echo "[3/4] Starting backend  ->  http://127.0.0.1:8000/docs"
( cd "$ROOT/backend" && "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 ) \
    > "$ROOT/logs/backend.log" 2>&1 &
BE_PID=$!

for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
        echo "      Backend is up:"; curl -s http://127.0.0.1:8000/api/health; echo
        break
    fi
    [ "$i" = "30" ] && { echo "[WARN] backend not healthy in 60s, see logs/backend.log"; break; }
    sleep 2
done

# ---------- frontend ----------
echo
echo "[4/4] Starting frontend ->  http://127.0.0.1:5173"
( cd "$ROOT/frontend" && npm run dev ) > "$ROOT/logs/frontend.log" 2>&1 &
FE_PID=$!

echo
echo "============================================================"
echo " Done."
echo "   Frontend : http://127.0.0.1:5173"
echo "   Backend  : http://127.0.0.1:8000/docs"
echo "   Logs     : logs/backend.log , logs/frontend.log"
echo "   Stop     : Ctrl-C  (or ./scripts/stop.sh)"
echo "============================================================"

wait
