#!/usr/bin/env bash
# ============================================================
#  Gov QA System - stop backend(:8000) and frontend(:5173)
# ============================================================
echo "============================================================"
echo " Gov QA System - stopping"
echo "============================================================"

kill_port() {
    local port=$1
    local pids
    pids=$(lsof -ti tcp:"$port" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        echo "  Port $port -> killing $pids"
        kill -9 $pids 2>/dev/null || true
    else
        echo "  Port $port -> not listening"
    fi
}

kill_port 8000
kill_port 5173

# fallback: uvorn / vite processes started by scripts/start.sh
pkill -f "uvicorn app.main:app" 2>/dev/null || true
pkill -f "vite" 2>/dev/null || true

echo
echo " Done."
echo "============================================================"
