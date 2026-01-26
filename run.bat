@echo off
chcp 65001 > nul
echo ========================================
echo    AGM Backend Server - Запуск
echo ========================================
echo.

REM Проверка наличия Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python не найден! Установите Python 3.8+
    pause
    exit /b 1
)

echo ✅ Python найден
echo.

REM Проверка виртуального окружения
if not exist "venv\" (
    echo 📦 Создание виртуального окружения...
    python -m venv venv
    echo ✅ Виртуальное окружение создано
    echo.
)

REM Активация виртуального окружения
echo 🔄 Активация виртуального окружения...
call venv\Scripts\activate.bat

REM Установка зависимостей
echo 📦 Установка зависимостей...
pip install -r requirements.txt --quiet
echo ✅ Зависимости установлены
echo.

REM Запуск сервера
echo 🚀 Запуск сервера...
echo.
python app.py

pause
