@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

rem ============================================================
rem  push.bat - commit & push to GitHub in one shot
rem
rem  Usage (run from anywhere):
rem      scripts\push.bat "your commit message"
rem      scripts\push.bat nogate "your commit message"   (skip quality gate)
rem
rem  Steps: quality gate -> git add -A -> git commit -> git push
rem  Note: keep this file ASCII-only so cmd never garbles it.
rem ============================================================

cd /d "%~dp0\.."

set "MSG=%~1"
set "RUN_GATE=1"

if /i "%~1"=="nogate" (
    set "RUN_GATE=0"
    set "MSG=%~2"
)

if "%MSG%"=="" set "MSG=chore: sync updates"

echo.
echo ==== [1/4] quality gate ====
if "%RUN_GATE%"=="1" (
    python scripts\quality_gate.py
    if errorlevel 1 (
        echo.
        echo [ABORT] quality gate failed - nothing was committed.
        exit /b 1
    )
) else (
    echo (skipped)
)

echo.
echo ==== [2/4] git add -A ====
git add -A
if errorlevel 1 (
    echo [ABORT] git add failed.
    exit /b 1
)

echo.
echo ==== [3/4] git commit ====
git commit -m "%MSG%"
if errorlevel 1 echo (nothing to commit - continuing to push)

echo.
echo ==== [4/4] git push ====
git push
if errorlevel 1 (
    echo.
    echo [FAILED] push rejected. If remote has new commits, run: git pull --rebase
    exit /b 1
)

echo.
echo ==== done ====
git status -sb
endlocal
