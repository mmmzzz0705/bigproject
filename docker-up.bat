@echo off
REM ============================================================
REM  ZhengMingBai (GovRAG) - one-click START  (Docker Compose)
REM  Full stack: gov-postgres / gov-milvus (+etcd, minio)
REM              gov-backend :8000 / gov-frontend :8080
REM
REM  ASCII-only on purpose: cmd.exe may mangle non-ASCII bytes.
REM  NOTE: this machine has no compose v2 plugin, so plain
REM        "docker compose" fails - docker-compose (hyphen) works.
REM ============================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"
set "ROOT=%CD%"
set "URL=http://127.0.0.1:8080"

echo ============================================================
echo  GovRAG - starting
echo  Root: %ROOT%
echo ============================================================
echo.

REM ---------- 1/3 docker engine ----------
docker info >nul 2>nul
if errorlevel 1 goto :no_docker
echo [1/3] Docker engine ......... OK

REM ---------- 2/3 locate compose command ----------
set "COMPOSE="
docker-compose version >nul 2>nul
if not errorlevel 1 set "COMPOSE=docker-compose"
if "!COMPOSE!"=="" (
    docker compose version >nul 2>nul
    if not errorlevel 1 set "COMPOSE=docker compose"
)
if "!COMPOSE!"=="" goto :no_compose
echo [2/3] Compose command ....... !COMPOSE!

REM ---------- 3/3 bring the stack up ----------
echo [3/3] Starting containers ...
echo.
%COMPOSE% -f docker-compose.yml up -d
if errorlevel 1 goto :up_failed

REM ---------- wait for the app to answer ----------
echo.
echo Waiting for %URL%/api/health  (up to 180s; Milvus is slow on first boot)
set "READY=0"
for /l %%i in (1,1,90) do (
    if "!READY!"=="0" (
        ping -n 3 127.0.0.1 >nul 2>nul
        curl -s -f "%URL%/api/health" >nul 2>nul
        if not errorlevel 1 set "READY=1"
    )
)

echo.
if "!READY!"=="1" goto :healthy
goto :unhealthy

:healthy
echo  Health check:
curl -s "%URL%/api/health"
echo.
echo.
echo ============================================================
echo  GovRAG is UP
echo    Frontend : %URL%
echo    Backend  : http://127.0.0.1:8000/docs
echo    Stop     : docker-down.bat
echo ============================================================
start "" "%URL%"
echo.
pause
exit /b 0

:unhealthy
echo [WARN] No answer from %URL%/api/health within 180s.
echo        Containers may still be booting (Milvus first boot is slow).
echo        Diagnose with:
echo          docker ps
echo          docker logs gov-backend --tail 50
echo.
echo        Or just open %URL% manually.
echo.
pause
exit /b 1

:no_docker
echo [ERROR] Docker engine is not running.
echo         Start Docker Desktop, wait until it says "Engine running",
echo         then run this again.
echo.
pause
exit /b 1

:no_compose
echo [ERROR] Neither "docker-compose" nor "docker compose" was found.
echo         Install Docker Desktop / the compose plugin.
echo.
pause
exit /b 1

:up_failed
echo.
echo [ERROR] "compose up" failed - see the output above.
echo.
pause
exit /b 1
