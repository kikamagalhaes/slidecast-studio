@echo off
REM Script para iniciar o SlideCast Studio no Windows

cd /d "%~dp0"

IF EXIST ".venv\Scripts\activate.bat" (
    call .venv\Scripts\activate.bat
)

python main.py %*
pause
