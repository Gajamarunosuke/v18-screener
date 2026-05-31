@echo off
chcp 65001 > nul
echo ============================================
echo  US KITRA screener
echo  Keep TradingView open with MaaSwing-KITRA loaded
echo ============================================
echo.

cd /d "%~dp0"
node scripts\kitra_us_check.mjs --post-workspace

echo.
echo Done.
pause
