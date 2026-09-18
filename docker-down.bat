@echo off
REM ============================================================
REM  ZhengMingBai (GovRAG) - one-click STOP (Docker Compose)
REM
REM  Shutdown ORDER matters: backend goes down FIRST, while Milvus
REM  is still alive, so it can close its connections cleanly and we
REM  avoid a wall of "vector store unreachable" errors. Only then
REM  the vector store, then whatever is left.
REM
REM  Named volumes are KEPT, so the database and vectors survive.
REM ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================================
echo  GovRAG - stopping
echo ============================================================
echo.

docker info >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Docker engine is not running - nothing to stop.
    echo.
    pause
    exit /b 1
)

set "COMPOSE="
docker-compose version >nul 2>nul
if not errorlevel 1 set "COMPOSE=docker-compose"
if "!COMPOSE!"=="" (
    docker compose version >nul 2>nul
    if not errorlevel 1 set "COMPOSE=docker compose"
)
if "!COMPOSE!"=="" (
    echo [ERROR] Neither "docker-compose" nor "docker compose" was found.
    echo.
    pause
    exit /b 1
)

echo [1/3] Stopping backend (frontend goes with it) ...
%COMPOSE% -f docker-compose.yml stop backend frontend
if errorlevel 1 goto :failed

echo.
echo [2/3] Stopping vector store (milvus) ...
%COMPOSE% -f docker-compose.yml stop milvus
if errorlevel 1 goto :failed

echo.
echo [3/3] Removing the rest (postgres / etcd / minio) ...
%COMPOSE% -f docker-compose.yml down
if errorlevel 1 goto :failed

echo.
echo ============================================================
echo  Done. Order: backend + frontend, then milvus, then the rest.
echo  Volumes were kept, your data is intact.
echo  Only use "down -v" if you really want to wipe the databases.
echo ============================================================
echo.
pause
exit /b 0

:failed
echo.
echo [ERROR] the stop sequence failed - see the output above.
echo.
pause
exit /b 1
