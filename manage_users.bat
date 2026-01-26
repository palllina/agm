@echo off
chcp 65001 >nul
echo.
echo ============================================
echo   Управление пользователями AGM
echo ============================================
echo.

call venv\Scripts\activate.bat

python create_user.py

echo.
pause

