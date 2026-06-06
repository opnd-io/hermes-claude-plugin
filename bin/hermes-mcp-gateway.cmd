@echo off
rem hermes-bridge launcher (plan-3 D6=B, Windows) — run adapter under Hermes venv python.
rem 우선순위: %HERMES_VENV_PY% > `hermes` 옆 python.exe > python(폴백). install(install.ps1, W4)이 검증/기록.
setlocal enabledelayedexpansion
set "DIR=%~dp0"
set "ADAPTER=%DIR%hermes_mcp_gateway.py"

rem install(install.ps1, W4)이 기록한 절대경로 (PATH 미상속 대비, opnd-codex #105)
set "ENV_FILE=%USERPROFILE%\.hermes-bridge\env.cmd"
if exist "%ENV_FILE%" call "%ENV_FILE%"

set "PY=%HERMES_VENV_PY%"
if "%PY%"=="" (
  for /f "delims=" %%i in ('where hermes 2^>nul') do (
    if "!PY!"=="" (
      set "HB=%%i"
      for %%d in ("!HB!") do set "HB_DIR=%%~dpd"
      if exist "!HB_DIR!python.exe" set "PY=!HB_DIR!python.exe"
    )
  )
)
if "%PY%"=="" (
  echo hermes-bridge: Hermes venv python 미발견 - install.ps1 재실행 또는 HERMES_VENV_PY 설정 ^(plan-3 FP8^) 1>&2
  set "PY=python"
)

"%PY%" "%ADAPTER%" %*
exit /b %ERRORLEVEL%
