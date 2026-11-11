# 📚 Слове́сность — Книжная картотека уроков и Мастерская репетитора (`tutor-games-catalog`)

**Домен:** `01_projects/tutor-games-catalog/` · **Статус:** 🟢 **ЭТАПЫ 1, 2 и 3 ВЫПОЛНЕНЫ (`66/66 unittest + Headless Chrome E2E OK`, `ZERO DRIFT PASS`)**. Готовы книжно-редакционная витрина «Слове́сность 3.0» (без штампов ИИ-дизайна), двухзонный рабочий стол «Мастерской репетитора» `/admin`, безотказный локальный запуск (`.bat` и `file://`) и полный пакет бесплатного облачного хостинга `0 ₽/мес` (`GitHub Pages + Vercel Hobby` + опциональный VPS `Caddy/systemd`).
**Эталон-референс:** https://pervyyii.ru/igroteka/ и просветительские издания *Arzamas* / *Полка*.

## Архитектура
1. **Витрина учеников «Слове́сность» (`site_template/` → `dist/`):**
   - Книжно-редакционная дизайн-система: дневная хлопковая бумага (`#f7f3ea`), глубокие чернила (`#141926`), киноварь (`#bf3926`, `< 4%` площади), кобальт (`#2346a0`) для досок и тёплая вечерняя тема (`#161513`).
   - 100% локальная кириллическая типографика **`Literata`** (`normal` + `italic`) + **`Golos Text`** (`.woff2`, `0` внешних запросов) и 6 авторских книжных иллюстраций-экслибрисов (`covers/*.png`, `<= 280 КБ`).
   - Асимметричный разворот первого экрана (`7fr + 5fr`) с карточкой «На столе сегодня» в приправочных метках (`crop marks`), 2-колоночное оглавление тем `§ 1..§ 4` и изолированный **Фокус-лист урока** (`/#lesson/<topic_slug>`), куда ученик возвращается по хлопковой закладке `← В картотеку` (`_shell/shell.js`).
   - Работает и по `http://`/`https://`, и напрямую с диска по `file://` (включая авто-редирект из `site_template/index.html` в `dist/index.html` и ярлык [`open_igroteka.bat`](file:///c:/Users/user/Documents/cursor/sessions/01_projects/tutor-games-catalog/open_igroteka.bat)).
2. **«Мастерская репетитора» (`tools/admin_server.py` + `tools/admin_ui/` + `tools/github_storage.py`):**
   - Локальный запуск в 1 клик через [`start_catalog_server.bat`](file:///c:/Users/user/Documents/cursor/sessions/01_projects/tutor-games-catalog/start_catalog_server.bat) (`--auto-port --open-browser`, пароль в `.admin_secret`).
   - Бесплатный облачный режим `0 ₽/мес`: [`api/index.py`](file:///c:/Users/user/Documents/cursor/sessions/01_projects/tutor-games-catalog/api/index.py) на **Vercel Hobby** + [`github_storage.py`](file:///c:/Users/user/Documents/cursor/sessions/01_projects/tutor-games-catalog/tools/github_storage.py) (атомарный коммит исходников через GitHub Git Data API с CAS-защитой `force: False`) + автосборка витрины на **GitHub Pages** через [`deploy-pages.yml`](file:///c:/Users/user/Documents/cursor/sessions/01_projects/tutor-games-catalog/.github/workflows/deploy-pages.yml). Пошаговая инструкция — в [`DEPLOY.md`](file:///c:/Users/user/Documents/cursor/sessions/01_projects/tutor-games-catalog/DEPLOY.md).

## Журнал этапов
- [x] **Этап 1 — Ядро статического сборщика и вендоринга CDN (`31/31 OK`):** [`sessions/2026-11-10_step-01-static-catalog/`](file:///c:/Users/user/Documents/cursor/sessions/01_projects/tutor-games-catalog/sessions/2026-11-10_step-01-static-catalog/)
- [x] **Этап 2 — Прототип витрины 2.0 + Офлайн SVG QR + Бэкенд `/admin` (`52/52 OK`):** [`sessions/2026-11-10_step-02-redesign-and-admin/`](file:///c:/Users/user/Documents/cursor/sessions/01_projects/tutor-games-catalog/sessions/2026-11-10_step-02-redesign-and-admin/)
- [x] **Этап 3 — Книжно-редакционный не-ИИ редизайн «Слове́сность 3.0», починка `.bat`/`file://` и облачный деплой `0 ₽/мес` (`66/66 OK`, `ZERO DRIFT`):** [`sessions/2026-11-11_step-03-human-design-and-deploy/`](file:///c:/Users/user/Documents/cursor/sessions/01_projects/tutor-games-catalog/sessions/2026-11-11_step-03-human-design-and-deploy/)
- [ ] **Этап 4 (опционально) — Telegram-бот репетитора (Mini App + загрузка `.html` прямо из чата) и журнал результатов учеников (`window.TutorShell.sendResult`).**
