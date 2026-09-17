@echo off
REM ============================================================
REM  ZhengMingBai (GovRAG) - one-click STOP (Docker Compose)
REM  Stops and removes the containers. Named volumes are KEPT,
REM  so the database and the vector store survive.
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

%COMPOSE% -f docker-compose.yml down
if errorlevel 1 (
    echo.
    echo [ERROR] "compose down" failed - see the output above.
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Done. Volumes were kept, your data is intact.
echo  Only use "down -v" if you really want to wipe the databases.
echo ============================================================
echo.
pause
