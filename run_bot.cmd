@echo off
REM Переходим в папку со скриптом
cd /d "%~dp0"

echo ================================
echo Установка зависимостей...
echo ================================
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo Ошибка при установке зависимостей.
    pause
    exit /b 1
)

echo.
echo ================================
echo Запуск бота...
echo ================================
python bot.py

echo.
echo Бот остановлен. Нажмите любую клавишу, чтобы выйти.
pause
