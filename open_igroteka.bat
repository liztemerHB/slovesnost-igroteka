@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Словесность — Открытие витрины
if not exist "dist\index.html" (
  echo Первичная сборка витрины dist\index.html...
  python -m tools.publish
)
start "" "%~dp0dist\index.html"
