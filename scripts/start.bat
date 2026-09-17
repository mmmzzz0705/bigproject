@echo off
REM ============================================================
REM  Gov QA System - one-click start (Windows)
REM  Starts: FastAPI backend :8000  +  Vue frontend :5173
REM  ASCII-only on purpose: cmd.exe may mangle non-ASCII bytes.
REM ============================================================
setlocal EnableDelayedExpansion

cd /d "%~dp0.."
set "ROOT=%CD%"

echo ============================================================
echo  Gov QA System - starting
echo  Root: %ROOT%
echo ============================================================

REM ---------- 0. prerequisite checks ----------
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] python not found in PATH. Install Python 3.10+ first.
    exit /b 1
)
where npm >nul 2>nul
if errorlevel 1 (
    echo [ERROR] npm not found in PATH. Install Node.js 18+ first.
    exit /b 1
)

REM ---------- 0.5 prefer the project virtualenv ----------
REM Installing into whatever "python" happens to be on PATH is how you end up
REM with "pip installed into A, uvicorn run with B" and the confusing
REM ModuleNotFoundError: No module named 'fastapi'.
set "PY=python"
set "VENV=%ROOT%\backend\.venv"
if exist "%VENV%\Scripts\python.exe" (
    set "PY=%VENV%\Scripts\python.exe"
    echo [env] Using project venv: backend\.venv
) else (
    echo [env] No backend\.venv found - falling back to PATH python.
    echo       Recommended: python -m venv "%VENV%"
)

REM ---------- 1. backend dependencies ----------
echo.
echo [1/4] Checking backend dependencies...
"%PY%" -c "import fastapi, uvicorn, sqlalchemy" >nul 2>nul
if errorlevel 1 (
    echo       Installing requirements.txt ...
    "%PY%" -m pip install -r "%ROOT%\backend\requirements.txt"
    if errorlevel 1 (
        echo [ERROR] pip install failed.
        exit /b 1
    )
) else (
    echo       OK
)

REM ---------- 2. frontend dependencies ----------
echo.
echo [2/4] Checking frontend dependencies...
if not exist "%ROOT%\frontend\node_modules" (
    echo       Running npm install (first run takes a while)...
    pushd "%ROOT%\frontend"
    call npm install
    if errorlevel 1 (
        popd
        echo [ERROR] npm install failed.
        exit /b 1
    )
    popd
) else (
    echo       OK
)

REM ---------- 3. backend ----------
echo.
echo [3/4] Starting backend  ->  http://127.0.0.1:8000/docs
REM Activate the venv inside the child window (relative path avoids quoting
REM problems when the project path contains spaces).
set "BE_CMD=python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
if exist "%VENV%\Scripts\activate.bat" (
    set "BE_CMD=call .venv\Scripts\activate.bat && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
)
start "gov-backend  :8000" cmd /k "cd /d %ROOT%\backend && %BE_CMD%"

echo       Waiting for backend to become healthy (max 60s)...
set "READY=0"
for /l %%i in (1,1,30) do (
    if "!READY!"=="0" (
        timeout /t 2 >nul
        curl -s -f http://127.0.0.1:8000/api/health >nul 2>nul
        if not errorlevel 1 set "READY=1"
    )
)
if "!READY!"=="1" (
    echo       Backend is up:
    curl -s http://127.0.0.1:8000/api/health
    echo.
) else (
    echo [WARN] Backend did not answer /api/health within 60s.
    echo        Check the backend window for errors.
)

REM ---------- 4. frontend ----------
echo.
echo [4/4] Starting frontend ->  http://127.0.0.1:5173
start "gov-frontend :5173" cmd /k "cd /d %ROOT%\frontend && npm run dev"

echo.
echo ============================================================
echo  Done.
echo    Frontend : http://127.0.0.1:5173
echo    Backend  : http://127.0.0.1:8000/docs
echo    Stop     : scripts\stop.bat
echo ============================================================
endlocal
