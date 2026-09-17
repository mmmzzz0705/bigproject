@echo off
REM ============================================================
REM  Gov QA System - stop backend(:8000) and frontend(:5173)
REM  Kills whatever process is listening on those ports.
REM ============================================================
echo ============================================================
echo  Gov QA System - stopping
echo ============================================================

for %%P in (8000 5173) do (
    echo   Port %%P ...
    powershell -NoProfile -Command ^
      "$c = Get-NetTCPConnection -LocalPort %%P -State Listen -ErrorAction SilentlyContinue; ^
       if ($c) { $c | ForEach-Object { try { Stop-Process -Id $_.OwningProcess -Force -ErrorAction Stop; ^
       Write-Host \"         killed PID $($_.OwningProcess)\" } catch {} } } ^
       else { Write-Host '         not listening' }"
)

echo.
echo  Done. If a console window is still open, close it manually.
echo ============================================================
