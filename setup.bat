@echo off
REM LoRa Coverage — setup 1 lenh cho Windows. Goi setup.sh qua Git Bash.
REM May chua co Git (tai ZIP ve thay vi clone): tu cai Git qua winget truoc.
setlocal

call :find_bash
if defined BASH goto :run

echo [setup] Khong thay Git Bash - dang cai Git for Windows qua winget...
where winget >nul 2>nul || (
  echo [setup] LOI: thieu ca winget. Cai Git thu cong: https://git-scm.com/download/win roi chay lai.
  exit /b 1
)
winget install --id Git.Git -e --silent --accept-package-agreements --accept-source-agreements
call :find_bash
if not defined BASH (
  echo [setup] LOI: da cai Git nhung chua thay bash - mo cua so cmd MOI roi chay lai setup.bat
  exit /b 1
)

:run
"%BASH%" "%~dp0setup.sh" %*
exit /b %errorlevel%

:find_bash
set "BASH="
if exist "%ProgramFiles%\Git\bin\bash.exe" set "BASH=%ProgramFiles%\Git\bin\bash.exe"
if not defined BASH if exist "%ProgramFiles(x86)%\Git\bin\bash.exe" set "BASH=%ProgramFiles(x86)%\Git\bin\bash.exe"
if not defined BASH (
  where bash >nul 2>nul && set "BASH=bash"
)
exit /b 0
