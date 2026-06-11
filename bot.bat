@echo off
chcp 65001 >nul
title Instagram Bot

cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [KHATA] Python peyda nashod. Lotfan Python ra install konid.
    pause
    exit /b 1
)

python -c "import colorama" >nul 2>&1
if errorlevel 1 (
    echo  Colorama dar hal install shodanost...
    python -m pip install colorama --quiet
)

python bot.py
if errorlevel 1 (
    echo.
    echo  [KHATA] Bot ba khata khatm shod.
    pause
)
