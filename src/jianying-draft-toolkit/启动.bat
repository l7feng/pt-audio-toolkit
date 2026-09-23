@echo off
rem ============================================================================
rem jianying-draft-toolkit launcher
rem
rem Resolves the NEWEST build under the exe root and starts it.
rem Why dynamic: exe outputs live in a versioned folder
rem (pt-audio-toolkit-v<version>-<date>\<tool>\), so a hardcoded path goes stale
rem on every rebuild. History: this file used to point at packaging\dist\, which
rem kept launching an OLD build after new ones were produced elsewhere.
rem
rem Override the root:  启动.bat D:\somewhere\exe
rem
rem Keep this file ASCII-only -- cmd.exe reads .bat as ANSI/GBK and non-ASCII
rem bytes can corrupt parsing.
rem ============================================================================

setlocal enabledelayedexpansion
set "EXE_ROOT=D:\Ai-Files\Agent-Preset\exe"
if not "%~1"=="" set "EXE_ROOT=%~1"

set "LATEST="
for /f "delims=" %%D in ('dir /b /ad /o-d "%EXE_ROOT%\pt-audio-toolkit-v*" 2^>nul') do (
    if not defined LATEST set "LATEST=%%D"
)

if not defined LATEST (
    echo [error] No build found under "%EXE_ROOT%".
    echo         Build first:  python tools\build.py
    pause
    exit /b 1
)

set "EXE=%EXE_ROOT%\%LATEST%\jianying-draft-toolkit\jianying-draft-toolkit.exe"
if not exist "%EXE%" (
    echo [error] exe not found: "%EXE%"
    echo         Try:  python tools\build.py jianying-draft-toolkit
    pause
    exit /b 1
)

echo [info] launching %LATEST%
start "" "%EXE%"
