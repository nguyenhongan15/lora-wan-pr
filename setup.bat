@echo off
REM LoRa Coverage — setup 1 lenh cho Windows. Goi setup.sh qua Git Bash
REM (Git for Windows co san bash; nguoi dung da clone repo nen chac chan co Git).
setlocal

set "BASH="
where bash >nul 2>nul && set "BASH=bash"
if not defined BASH if exist "%ProgramFiles%\Git\bin\bash.exe" set "BASH=%ProgramFiles%\Git\bin\bash.exe"
if not defined BASH if exist "%ProgramFiles(x86)%\Git\bin\bash.exe" set "BASH=%ProgramFiles(x86)%\Git\bin\bash.exe"
if not defined BASH (
  echo [setup] LOI: khong tim thay bash. Cai Git for Windows: https://git-scm.com/download/win
  exit /b 1
)

"%BASH%" "%~dp0setup.sh" %*
