@echo off
chcp 65001 > nul
echo ============================================
echo  JP KITRA screener
echo  Keep TradingView open with MaaSwing-KITRA loaded
echo ============================================
echo.

cd /d "%~dp0"
set "PYTHONPATH=%CD%\.deps;%PYTHONPATH%"
python scripts\kitra_jp_check.py

echo.
echo Done.
pause
