@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Словесность — Подготовка к облачной выкладке (GitHub + Vercel)
echo ───────────────────────────────────────────────────────────────────
echo   Подготовка репозитория «Словесность» к бесплатному хостингу 0 ₽/мес
echo ───────────────────────────────────────────────────────────────────

if not exist ".git" (
  echo [1/3] Инициализация локального Git-репозитория...
  git init -b main
) else (
  echo [1/3] Локальный Git-репозиторий уже инициализирован.
)

echo [2/3] Проверка сборки витрины dist\...
python -m tools.publish
if errorlevel 1 (
  echo [ОШИБКА] Сборка не прошла. Проверьте сообщения выше.
  pause
  exit /b 1
)

echo.
echo [3/3] Готово! Чтобы опубликовать сайт в облако за 5 минут (0 ₽/мес):
echo   1. Создайте пустой репозиторий на GitHub ^(например, slovesnost-igroteka^).
echo   2. Выполните команды отправки ^(подставьте свой логин и имя репо^):
echo      git add catalog.json games_inbox site_template tools api vercel.json .vercelignore .github DEPLOY.md start_catalog_server.bat open_igroteka.bat .gitignore
echo      git commit -m "feat: картотека и мастерская Словесность"
echo      git remote add origin https://github.com/ВАШ_ЛОГИН/slovesnost-igroteka.git
echo      git push -u origin main
echo   3. В настройках GitHub -> Settings -> Pages выберите Source: GitHub Actions.
echo   4. Подключите этот же репозиторий в Vercel ^(Hobby 0 $^), задав 3 переменные:
echo      TUTOR_ADMIN_PASSWORD, GITHUB_TOKEN, GITHUB_REPO.
echo.
echo   Подробная пошаговая памятка лежит в файле DEPLOY.md.
echo ───────────────────────────────────────────────────────────────────
pause
