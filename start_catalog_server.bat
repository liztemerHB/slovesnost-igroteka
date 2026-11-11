@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Словесность — Мастерская репетитора
echo ───────────────────────────────────────────────────────────
echo   Запуск локального сервера «Словесность»...
echo   Браузер откроется автоматически после готовности порта.
echo ───────────────────────────────────────────────────────────
if exist ".admin_secret" (
  set /p TUTOR_PWD=<.admin_secret
  echo   Пароль Мастерской ^(.admin_secret^):
  type ".admin_secret"
  echo.
  echo ───────────────────────────────────────────────────────────
)
python "tools\admin_server.py" --host 127.0.0.1 --port 8080 --auto-port --open-browser
if errorlevel 1 (
  echo.
  echo [ОШИБКА] Не удалось запустить Python. Проверьте, что Python 3.10+ установлен и добавлен в PATH.
  pause
)
