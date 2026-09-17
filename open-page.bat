@echo off
REM ============================================================
REM  ZhengMingBai (GovRAG) - open the web UI in default browser
REM  Probes the service first, so a double-click never lands you
REM  on a dead "connection refused" page.
REM  ASCII-only on purpose: cmd.exe may mangle non-ASCII bytes.
REM ============================================================
set "URL=http://127.0.0.1:8080"

REM No curl (very old Windows) -> skip the probe and just open the page.
where curl >nul 2>nul
if errorlevel 1 goto :open

REM -m 5: never hang longer than 5s if the stack is half-started.
curl -s -f -m 5 "%URL%/api/health" >nul 2>nul
if errorlevel 1 goto :down

echo  Service is up - opening %URL%
goto :open

:down
echo ============================================================
echo  GovRAG is NOT running
echo  (no answer from %URL%/api/health)
echo.
echo  Start it first, then double-click this shortcut again:
echo    - desktop shortcut "start", or
echo    - docker-up.bat in the project root
echo ============================================================
echo.
pause
exit /b 1

:open
start "" "%URL%"
exit /b 0
