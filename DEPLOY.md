# Бесплатный облачный хостинг «Слове́сности» (`0 ₽ / мес`)

Проект спроектирован так, чтобы работать **и локально без интернета**, и **в бесплатном облаке 24/7 без абонентской платы**, причём ученики в РФ открывают задания мгновенно со смартфона и домашнего интернета без VPN.

---

## Как устроена двухконтурная бесплатная схема (`Vercel Hobby + GitHub Pages`)

Почему нельзя просто положить обычную Python-админку на бесплатный Vercel без адаптера?
У бесплатного тарифа Vercel (`Hobby`, `0 $`) файловая система доступна только для чтения (`/tmp` очищается через несколько минут), а в РФ часть мобильных операторов замедляет поддомены `*.vercel.app` на сетях Cloudflare.

В проекте уже встроен готовый двухконтурный механизм (`tools/github_storage.py` + `api/index.py` + `.github/workflows/deploy-pages.yml`):

1. **Витрина для учеников (`https://<логин>.github.io/<репо>/` — GitHub Pages, CDN Fastly):**
   - Открывается у любого ученика в РФ с телефона, планшета или ноутбука за долю секунды без VPN.
   - Все шрифты (`Literata` + `Golos Text`), обложки, QR-генератор и внешние библиотеки игр упакованы внутрь сборки (`0` внешних блокируемых запросов).
2. **Мастерская репетитора (`https://<проект>.vercel.app/admin` — Vercel Python Serverless):**
   - Репетитор заходит в `/admin` с любого устройства, перетаскивает `.html`-файл или вставляет ссылку на доску Miro / «Холст».
   - Сервер за ~1 секунду сохраняет исходник напрямую в ваш GitHub-репозиторий через `GitHubStorage`.
   - GitHub Actions автоматически пересобирает `dist/` и через 20–25 секунд обновляет витрину учеников, а QR-код в Мастерской сразу ведёт на постоянный адрес GitHub Pages.

---

## Пошаговый запуск за 5 минут (`0 ₽/мес`)

### Шаг 1. Создайте репозиторий на GitHub
1. Зайдите на [github.com/new](https://github.com/new) и создайте репозиторий (например, `slovesnost-igroteka`).
   - Для бесплатного GitHub Pages на личном аккаунте выберите **Public** (пароль админки в коде не хранится — он задаётся только в переменных окружения Vercel).
2. Запустите `setup_github_deploy.bat` или выполните в папке проекта:
   ```powershell
   git init -b main
   git add catalog.json games_inbox site_template tools api vercel.json .vercelignore .github DEPLOY.md start_catalog_server.bat open_igroteka.bat
   git commit -m "feat: запуск картотеки Словесность"
   git remote add origin https://github.com/<ВАШ_ЛОГИН>/slovesnost-igroteka.git
   git push -u origin main
   ```
3. В репозитории на GitHub откройте **Settings → Pages** и в поле **Build and deployment → Source** выберите **`GitHub Actions`**.
   Через 25 секунд витрина учеников заработает по адресу `https://<ваш_логин>.github.io/slovesnost-igroteka/`.

### Шаг 2. Выпустите токен записи для Мастерской (`Fine-grained PAT`)
1. Откройте на GitHub: **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**.
2. Назовите токен `slovesnost-vercel-admin`.
3. В **Repository access** выберите **Only select repositories** → укажите `slovesnost-igroteka`.
4. В **Permissions → Repository permissions** поставьте **Contents: `Read and write`** (больше никаких прав не нужно).
5. Скопируйте полученный токен (`github_pat_...`).

### Шаг 3. Подключите Мастерскую `/admin` на бесплатном Vercel
1. Зайдите на [vercel.com/new](https://vercel.com/new) (вход через GitHub, тариф **Hobby — Free**).
2. Нажмите **Import** напротив `slovesnost-igroteka`.
3. Раскройте блок **Environment Variables** и добавьте 3 переменные:

| Имя переменной | Значение | Назначение |
| :--- | :--- | :--- |
| `TUTOR_ADMIN_PASSWORD` | Придумайте надёжный пароль репетитора | Вход в `/admin` |
| `GITHUB_TOKEN` | Ваш токен `github_pat_...` из Шага 2 | Сохранение новых игр и досок в репозиторий |
| `GITHUB_REPO` | `<ваш_логин>/slovesnost-igroteka` | Целевой репозиторий |
| `PUBLIC_CATALOG_URL` *(необязательно)* | `https://<ваш_логин>.github.io/slovesnost-igroteka/` | Вычисляется автоматически из `GITHUB_REPO`; задайте вручную, если подключите свой домен `.ru` |

4. Нажмите **Deploy**. Готово:
   - Мастерская репетитора всегда доступна на `https://<имя-проекта>.vercel.app/admin` (в шапке загорится штамп **«GitHub Облако»**).
   - Витрина и все QR-коды для учеников работают на `https://<ваш_логин>.github.io/slovesnost-igroteka/`.

---

## Альтернатива A: Локальная работа с ноутбука репетитора (вообще без облака)

- **Открыть витрину ученикам на уроке (офлайн):** дважды нажмите [`open_igroteka.bat`](./open_igroteka.bat) — собранный файл `dist\index.html` откроется напрямую в браузере со всеми играми, шрифтами и звуком.
- **Добавить новую игру или доску через локальную Мастерскую:** дважды нажмите [`start_catalog_server.bat`](./start_catalog_server.bat) — сервер сам подберёт свободный порт, выведет пароль из `.admin_secret` и откроет Мастерскую `/admin`.

## Альтернатива B: Свой российский VPS с доменом `.ru` (по желанию в будущем)

В папке [`deploy/`](./deploy/) лежат готовые файлы [`Caddyfile`](./deploy/Caddyfile) (автоматический HTTPS Let's Encrypt + мгновенная раздача `dist/`) и [`tutor-catalog.service`](./deploy/tutor-catalog.service) (`systemd`-юнит для Ubuntu/Debian).
