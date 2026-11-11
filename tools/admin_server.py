#!/usr/bin/env python3
"""HTTP-сервер и REST API кабинета репетитора (tools/admin_server.py).

Обеспечивает раздачу статики витрины dist/, интерфейса админки /admin,
авторизацию по паролю с HMAC-сессией, защиту от CSRF и Path Traversal,
Drag & Drop загрузку игр с автоанализом, локальную пересборку каталога
и опциональную облачную фиксацию в GitHub REST API (0 ₽/мес).
"""

import argparse
import base64
import hashlib
import hmac
import http.cookies
import http.server
import json
import os
import re
import secrets
import sys
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

# Разрешаем прямой запуск `python tools\admin_server.py` из любой директории
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.github_storage import GitHubStorage
from tools.publish import (
    build_site,
    compute_topic_slug,
    extract_meta,
    format_cover_src,
    slugify,
    suggest_cover,
    validate_catalog,
)

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ttf": "font/ttf",
    ".ico": "image/x-icon",
}

MAX_HTML_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB
MAX_COVER_UPLOAD_BYTES = 5 * 1024 * 1024   # 5 MB

TEMPLATE_FALLBACK_PREFIXES = ("fonts/", "covers/", "_shell/")
TEMPLATE_FALLBACK_FILES = {"qr.js", "filter.js", "catalog.css"}


def item_with_computed(item: dict) -> dict:
    """Формирование объекта карточки со всеми вычисленными полями для витрины и админки."""
    kind = item.get("kind", "game")
    slug = item.get("slug", "")
    title = item.get("title", "")
    grade = item.get("grade")
    topic = item.get("topic", "")
    topic_slug = compute_topic_slug(topic, grade)
    cover = item.get("cover") or suggest_cover(title, topic, kind, slug)
    cover_src = format_cover_src(cover)
    subtitle = item.get("subtitle") or ("Интерактивная доска урока" if kind == "board" else "Интерактивный тренажёр")
    href = f"g/{slug}/index.html" if kind == "game" else item.get("url", "")
    return {
        "id": item.get("id", slug),
        "slug": slug,
        "title": title,
        "grade": grade,
        "topic": topic,
        "topic_slug": topic_slug,
        "kind": kind,
        "tags": item.get("tags", []),
        "subtitle": subtitle,
        "cover": cover,
        "cover_src": cover_src,
        "order": item.get("order", 1),
        "hidden": bool(item.get("hidden", False)),
        "archived": bool(item.get("archived", False)),
        "href": href,
        "file": item.get("file"),
        "url": item.get("url"),
    }


def atomic_save_json(path: Path, data: dict) -> None:
    """Атомарная запись JSON-файла через временный файл и замену."""
    path = Path(path)
    tmp_path = path.parent / f"{path.name}.tmp.{secrets.token_hex(4)}"
    tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)


class AdminRequestHandler(http.server.BaseHTTPRequestHandler):
    """Обработчик HTTP-запросов витрины, админки и защищенного REST API."""

    server_version = "TutorAdminServer/3.0"

    @property
    def manager(self):
        return self.server.manager

    def log_message(self, format, *args):
        if os.environ.get("TUTOR_LOG_HTTP"):
            super().log_message(format, *args)

    def _is_https_request(self) -> bool:
        proto = (self.headers.get("X-Forwarded-Proto") or "").lower()
        return proto == "https" or bool(os.environ.get("VERCEL"))

    def _send_json(self, status: int, data: dict, headers: dict | None = None) -> None:
        """Отправка JSON-ответа с правильными заголовками."""
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, status: int, error_code: str, message: str) -> None:
        """Стандартизированный JSON-ответ с ошибкой."""
        self._send_json(status, {"ok": False, "error": error_code, "message": message})

    def _is_authenticated(self) -> bool:
        """Проверка валидности HMAC-сессии в cookie tutor_admin_session."""
        if not self.manager.password_configured:
            return False
        cookie_header = self.headers.get("Cookie", "")
        cookies = http.cookies.SimpleCookie()
        try:
            cookies.load(cookie_header)
            token = cookies.get("tutor_admin_session")
            if not token:
                return False
            expected = self.manager.expected_session_token
            return hmac.compare_digest(token.value, expected)
        except Exception:
            return False

    def _read_json_body(self, max_bytes: int = MAX_HTML_UPLOAD_BYTES) -> tuple[dict | None, str | None]:
        """Чтение и парсинг JSON тела запроса с ограничением размера."""
        content_length_str = self.headers.get("Content-Length")
        if not content_length_str:
            return None, "Отсутствует заголовок Content-Length"
        try:
            length = int(content_length_str)
        except ValueError:
            return None, "Некорректный заголовок Content-Length"

        if length > max_bytes:
            return None, "PAYLOAD_TOO_LARGE"

        raw_bytes = self.rfile.read(length)
        if len(raw_bytes) > max_bytes:
            return None, "PAYLOAD_TOO_LARGE"

        try:
            parsed = json.loads(raw_bytes.decode("utf-8"))
            if not isinstance(parsed, dict):
                return None, "Тело запроса должно быть JSON-объектом"
            return parsed, None
        except Exception as e:
            return None, f"Ошибка парсинга JSON: {e}"

    def _serve_file(self, target_file: Path) -> None:
        ext = target_file.suffix.lower()
        mime = MIME_TYPES.get(ext, "application/octet-stream")
        content = target_file.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    # --------------------------------------------------------------------------
    # Обработка GET
    # --------------------------------------------------------------------------
    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        # 1. API сессии
        if path == "/api/admin/session":
            self._send_json(
                200,
                {
                    "ok": True,
                    "authenticated": self._is_authenticated(),
                    "storage_mode": self.manager.storage_mode,
                    "public_catalog_url": self.manager.get_public_catalog_url(self.headers),
                    "password_configured": self.manager.password_configured,
                },
            )
            return

        # 2. Защищенный API списка записей
        if path == "/api/admin/items":
            if not self._is_authenticated():
                self._send_error_json(401, "unauthorized", "Требуется вход в кабинет репетитора")
                return

            with self.manager.lock:
                catalog = self.manager.load_catalog()
                items = [item_with_computed(it) for it in catalog.get("items", [])]
                topics = sorted(list({str(it.get("topic")).strip() for it in items if str(it.get("topic") or "").strip()}))

                # Сбор обложек: стандартные 6 + кастомные
                covers = ["library", "autumn", "quest", "exam", "board", "alchemy"]
                covers_dir = self.manager.project_root / "site_template" / "covers"
                if covers_dir.exists():
                    for p in sorted(covers_dir.glob("custom_*.*")):
                        if p.name not in covers:
                            covers.append(p.name)

                self._send_json(200, {
                    "ok": True,
                    "items": items,
                    "covers": covers,
                    "topics": topics,
                    "storage_mode": self.manager.storage_mode,
                    "public_catalog_url": self.manager.get_public_catalog_url(self.headers),
                })
            return

        # 3. Страница админки /admin и /admin/
        if path in ("/admin", "/admin/"):
            admin_file = self.manager.ui_root / "tools" / "admin_ui" / "admin.html"
            if admin_file.exists():
                content = admin_file.read_bytes()
            else:
                stub_html = (
                    "<!DOCTYPE html><html lang='ru'><head><meta charset='utf-8'>"
                    "<title>Кабинет репетитора</title></head><body>"
                    "<h1>Кабинет репетитора</h1><p>Интерфейс в разработке.</p></body></html>"
                )
                content = stub_html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        # 4. Статика админки /admin_assets/<file> и прямые алиасы /admin.css, /admin.js
        if path.startswith("/admin_assets/") or path in ("/admin.css", "/admin.js", "/admin/admin.css", "/admin/admin.js"):
            if path.startswith("/admin_assets/"):
                rel_asset = path[len("/admin_assets/"):].lstrip("/")
            else:
                rel_asset = path.rsplit("/", 1)[-1]
            asset_dir = (self.manager.ui_root / "tools" / "admin_ui").resolve()
            target_asset = (asset_dir / rel_asset).resolve()
            if not target_asset.is_relative_to(asset_dir) or not target_asset.is_file():
                self.send_error(404, "Asset Not Found")
                return
            self._serve_file(target_asset)
            return

        # 5. Статика каталога из dist/ (с безопасным фолбэком в site_template/)
        dist_dir = (self.manager.project_root / "dist").resolve()
        rel_path = "index.html" if path in ("", "/") else path.lstrip("/")
        target_file = (dist_dir / rel_path).resolve()

        if not target_file.is_relative_to(dist_dir):
            self.send_error(403, "Forbidden")
            return

        if target_file.exists() and target_file.is_file():
            self._serve_file(target_file)
            return

        # Фолбэк для шрифтов, обложек и qr.js из site_template/ (полезно в тестах и облаке)
        if rel_path in TEMPLATE_FALLBACK_FILES or rel_path.startswith(TEMPLATE_FALLBACK_PREFIXES):
            for base_root in (self.manager.project_root, self.manager.ui_root):
                tpl_dir = (base_root / "site_template").resolve()
                fallback_file = (tpl_dir / rel_path).resolve()
                if fallback_file.is_relative_to(tpl_dir) and fallback_file.is_file():
                    self._serve_file(fallback_file)
                    return

        self.send_error(404, "Not Found")

    # --------------------------------------------------------------------------
    # Обработка POST и PUT
    # --------------------------------------------------------------------------
    def _check_csrf_and_auth(self, require_auth: bool = True) -> bool:
        """Проверка CSRF-заголовка X-Requested-With: TutorAdmin и сессии."""
        csrf_val = self.headers.get("X-Requested-With", "")
        if csrf_val != "TutorAdmin":
            self._send_error_json(403, "csrf_rejected", "Отсутствует защитный заголовок запроса")
            return False

        if require_auth and not self._is_authenticated():
            self._send_error_json(401, "unauthorized", "Требуется вход в кабинет репетитора")
            return False

        return True

    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        # 1. Логин
        if path == "/api/admin/login":
            if not self._check_csrf_and_auth(require_auth=False):
                return
            if not self.manager.password_configured:
                self._send_error_json(
                    503,
                    "password_not_configured",
                    "В облаке не задана переменная окружения TUTOR_ADMIN_PASSWORD",
                )
                return
            body, err = self._read_json_body()
            if err:
                self._send_error_json(400, "invalid_json", err)
                return
            password = str(body.get("password") or "")
            if not hmac.compare_digest(password, self.manager.admin_password):
                time.sleep(0.12)
                self._send_error_json(401, "invalid_password", "Неверный пароль")
                return

            secure_attr = "; Secure" if self._is_https_request() else ""
            cookie_hdr = (
                f"tutor_admin_session={self.manager.expected_session_token}; "
                f"Path=/; HttpOnly; SameSite=Strict; Max-Age=2592000{secure_attr}"
            )
            self._send_json(200, {"ok": True}, headers={"Set-Cookie": cookie_hdr})
            return

        # 2. Логаут
        if path == "/api/admin/logout":
            if not self._check_csrf_and_auth(require_auth=False):
                return
            secure_attr = "; Secure" if self._is_https_request() else ""
            cookie_hdr = f"tutor_admin_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0{secure_attr}"
            self._send_json(200, {"ok": True}, headers={"Set-Cookie": cookie_hdr})
            return

        # 3. Предпросмотр игры (Drag & Drop preview)
        if path == "/api/admin/preview-game":
            if not self._check_csrf_and_auth(require_auth=True):
                return
            body, err = self._read_json_body()
            if err:
                self._send_error_json(400, "invalid_json", err)
                return
            filename = str(body.get("filename") or "game.html")
            content_html = str(body.get("content_html") or "")
            if not content_html.strip():
                self._send_error_json(400, "empty_content", "HTML-файл пуст")
                return

            meta = extract_meta(content_html, filename)
            self._send_json(200, {"ok": True, "meta": meta})
            return

        # 4. Загрузка игры
        if path == "/api/admin/upload-game":
            if not self._check_csrf_and_auth(require_auth=True):
                return
            body, err = self._read_json_body(max_bytes=MAX_HTML_UPLOAD_BYTES)
            if err == "PAYLOAD_TOO_LARGE":
                self._send_error_json(413, "payload_too_large", "Размер файла превышает лимит 25 МБ")
                return
            if err:
                self._send_error_json(400, "invalid_json", err)
                return

            filename = str(body.get("filename") or "game.html")
            content_html = str(body.get("content_html") or "")
            if not content_html.strip():
                self._send_error_json(400, "empty_content", "HTML-файл пуст")
                return

            with self.manager.lock:
                meta = extract_meta(content_html, filename)
                title = str(body.get("title") or meta["title"]).strip()
                grade = body.get("grade") if "grade" in body else meta.get("grade")
                topic = str(body.get("topic") or meta.get("topic") or "").strip()
                subtitle = str(body.get("subtitle") or meta.get("subtitle") or "").strip()
                tags = body.get("tags") if isinstance(body.get("tags"), list) else []
                hidden = bool(body.get("hidden", False))

                catalog = self.manager.load_catalog()
                existing_slugs = {it["slug"] for it in catalog.get("items", []) if it.get("slug")}

                base_slug = slugify(title)
                slug = base_slug
                c = 2
                while slug in existing_slugs:
                    slug = f"{base_slug}-{c}"
                    c += 1

                cover = str(body.get("cover") or meta.get("suggested_cover") or suggest_cover(title, topic, "game", slug))

                # Безопасное сохранение в games_inbox без перезаписи (Закон №2)
                target_fname = f"{slug}.html"
                fc = 2
                inbox_dir = self.manager.project_root / "games_inbox"
                inbox_dir.mkdir(parents=True, exist_ok=True)
                while (inbox_dir / target_fname).exists():
                    target_fname = f"{slug}-{fc}.html"
                    fc += 1

                (inbox_dir / target_fname).write_text(content_html, encoding="utf-8")

                new_item = {
                    "id": slug,
                    "slug": slug,
                    "title": title,
                    "grade": grade,
                    "topic": topic,
                    "subtitle": subtitle,
                    "cover": cover,
                    "kind": "game",
                    "file": target_fname,
                    "tags": tags,
                    "order": len(catalog.get("items", [])) + 1,
                    "hidden": hidden,
                    "archived": False,
                }
                catalog.setdefault("items", []).append(new_item)
                atomic_save_json(self.manager.catalog_path, catalog)

                build_site(self.manager.project_root, vendor_timeout=5)
                cloud_warn = self.manager.push_to_cloud(
                    extra_files={f"games_inbox/{target_fname}": content_html.encode("utf-8")},
                    message=f"admin: добавлен тренажёр «{title}»",
                )

                comp_item = item_with_computed(new_item)
                self._send_json(201, {
                    "ok": True,
                    "item": comp_item,
                    "url": f"g/{slug}/index.html",
                    "warnings": [cloud_warn] if cloud_warn else [],
                })
            return

        # 5. Добавление доски Miro / Холст
        if path == "/api/admin/add-board":
            if not self._check_csrf_and_auth(require_auth=True):
                return
            body, err = self._read_json_body()
            if err:
                self._send_error_json(400, "invalid_json", err)
                return

            url = str(body.get("url") or "").strip()
            if not re.match(r"^https?://\S+$", url, re.IGNORECASE):
                self._send_error_json(400, "invalid_url", "Ссылка должна начинаться с https:// или http://")
                return

            title = str(body.get("title") or "").strip()
            if not title:
                self._send_error_json(400, "empty_title", "Поле title обязательно")
                return

            grade = body.get("grade")
            topic = str(body.get("topic") or "").strip()
            subtitle = str(body.get("subtitle") or "Интерактивная доска урока").strip()
            cover = str(body.get("cover") or "board").strip()
            tags = body.get("tags") if isinstance(body.get("tags"), list) else []
            hidden = bool(body.get("hidden", False))

            with self.manager.lock:
                catalog = self.manager.load_catalog()
                existing_slugs = {it["slug"] for it in catalog.get("items", []) if it.get("slug")}

                base_slug = slugify(title)
                slug = base_slug
                c = 2
                while slug in existing_slugs:
                    slug = f"{base_slug}-{c}"
                    c += 1

                new_item = {
                    "id": slug,
                    "slug": slug,
                    "title": title,
                    "grade": grade,
                    "topic": topic,
                    "subtitle": subtitle,
                    "cover": cover,
                    "kind": "board",
                    "url": url,
                    "tags": tags,
                    "order": len(catalog.get("items", [])) + 1,
                    "hidden": hidden,
                    "archived": False,
                }
                catalog.setdefault("items", []).append(new_item)
                atomic_save_json(self.manager.catalog_path, catalog)

                build_site(self.manager.project_root, vendor_timeout=5)
                cloud_warn = self.manager.push_to_cloud(
                    extra_files={},
                    message=f"admin: добавлена доска «{title}»",
                )

                comp_item = item_with_computed(new_item)
                self._send_json(
                    201,
                    {
                        "ok": True,
                        "item": comp_item,
                        "url": url,
                        "warnings": [cloud_warn] if cloud_warn else [],
                    },
                )
            return

        # 6. Загрузка кастомной обложки
        if path == "/api/admin/upload-cover":
            if not self._check_csrf_and_auth(require_auth=True):
                return
            body, err = self._read_json_body(max_bytes=MAX_COVER_UPLOAD_BYTES * 2)
            if err:
                self._send_error_json(400, "invalid_json", err)
                return

            b64_data = str(body.get("data_base64") or "")
            try:
                raw_bytes = base64.b64decode(b64_data)
            except Exception:
                self._send_error_json(400, "invalid_base64", "Некорректная кодировка base64")
                return

            if len(raw_bytes) > MAX_COVER_UPLOAD_BYTES:
                self._send_error_json(413, "payload_too_large", "Размер обложки превышает 5 МБ")
                return

            ext = None
            if raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
                ext = "png"
            elif raw_bytes.startswith(b"\xff\xd8\xff"):
                ext = "jpg"
            elif raw_bytes[:4] == b"RIFF" and raw_bytes[8:12] == b"WEBP":
                ext = "webp"

            if not ext:
                self._send_error_json(400, "invalid_image", "Поддерживаются только изображения PNG, JPEG или WEBP")
                return

            token = secrets.token_hex(4)
            cover_name = f"custom_{token}.{ext}"

            with self.manager.lock:
                covers_template = self.manager.project_root / "site_template" / "covers"
                covers_template.mkdir(parents=True, exist_ok=True)
                (covers_template / cover_name).write_bytes(raw_bytes)

                dist_covers = self.manager.project_root / "dist" / "covers"
                if dist_covers.exists():
                    (dist_covers / cover_name).write_bytes(raw_bytes)

                cloud_warn = self.manager.push_to_cloud(
                    extra_files={f"site_template/covers/{cover_name}": raw_bytes},
                    message=f"admin: загружена обложка {cover_name}",
                    include_catalog=False,
                )

            self._send_json(201, {
                "ok": True,
                "cover": cover_name,
                "cover_src": f"covers/{cover_name}",
                "warnings": [cloud_warn] if cloud_warn else [],
            })
            return

        # 7. Изменение порядка карточек
        if path == "/api/admin/reorder":
            if not self._check_csrf_and_auth(require_auth=True):
                return
            body, err = self._read_json_body()
            if err:
                self._send_error_json(400, "invalid_json", err)
                return

            ids = body.get("ids")
            if not isinstance(ids, list):
                self._send_error_json(400, "invalid_ids", "Поле ids должно быть списком")
                return

            with self.manager.lock:
                catalog = self.manager.load_catalog()
                id_to_order = {item_id: idx + 1 for idx, item_id in enumerate(ids)}
                for it in catalog.get("items", []):
                    item_id = it.get("id") or it.get("slug")
                    if item_id in id_to_order:
                        it["order"] = id_to_order[item_id]

                atomic_save_json(self.manager.catalog_path, catalog)
                build_site(self.manager.project_root, vendor_timeout=5)
                cloud_warn = self.manager.push_to_cloud({}, "admin: обновлён порядок материалов")
                self._send_json(200, {"ok": True, "warnings": [cloud_warn] if cloud_warn else []})
            return

        # 8. Архивация карточки POST /api/admin/archive/<id>
        archive_match = re.match(r"^/api/admin/archive/(?P<id>[^/]+)$", path)
        if archive_match:
            if not self._check_csrf_and_auth(require_auth=True):
                return
            target_id = archive_match.group("id")
            body, err = self._read_json_body()
            archived_flag = True if err or "archived" not in body else bool(body["archived"])

            with self.manager.lock:
                catalog = self.manager.load_catalog()
                found = None
                for it in catalog.get("items", []):
                    if it.get("id") == target_id or it.get("slug") == target_id:
                        found = it
                        break

                if not found:
                    self._send_error_json(404, "not_found", "Запись не найдена")
                    return

                found["archived"] = archived_flag
                atomic_save_json(self.manager.catalog_path, catalog)
                build_site(self.manager.project_root, vendor_timeout=5)
                state_word = "в архив" if archived_flag else "из архива"
                cloud_warn = self.manager.push_to_cloud({}, f"admin: перемещение {state_word} ({target_id})")

                self._send_json(
                    200,
                    {
                        "ok": True,
                        "item": item_with_computed(found),
                        "warnings": [cloud_warn] if cloud_warn else [],
                    },
                )
            return

        self.send_error(404, "Not Found")

    # --------------------------------------------------------------------------
    # Обработка PUT
    # --------------------------------------------------------------------------
    def do_PUT(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        # PUT /api/admin/items/<id>
        item_match = re.match(r"^/api/admin/items/(?P<id>[^/]+)$", path)
        if item_match:
            if not self._check_csrf_and_auth(require_auth=True):
                return
            target_id = item_match.group("id")
            body, err = self._read_json_body()
            if err:
                self._send_error_json(400, "invalid_json", err)
                return

            with self.manager.lock:
                catalog = self.manager.load_catalog()
                found = None
                for it in catalog.get("items", []):
                    if it.get("id") == target_id or it.get("slug") == target_id:
                        found = it
                        break

                if not found:
                    self._send_error_json(404, "not_found", "Запись не найдена")
                    return

                # Частичное обновление полей
                if "title" in body:
                    new_title = str(body["title"]).strip()
                    if not new_title:
                        self._send_error_json(400, "invalid_title", "Название не может быть пустым")
                        return
                    found["title"] = new_title

                if "grade" in body:
                    found["grade"] = body["grade"] if (body["grade"] is None or isinstance(body["grade"], int)) else found["grade"]
                if "topic" in body:
                    found["topic"] = str(body["topic"]).strip()
                if "subtitle" in body:
                    found["subtitle"] = str(body["subtitle"]).strip()
                if "cover" in body:
                    found["cover"] = str(body["cover"]).strip()
                if "tags" in body and isinstance(body["tags"], list):
                    found["tags"] = body["tags"]
                if "hidden" in body:
                    found["hidden"] = bool(body["hidden"])
                if "archived" in body:
                    found["archived"] = bool(body["archived"])
                if "order" in body and isinstance(body["order"], int):
                    found["order"] = body["order"]

                if "url" in body and found.get("kind") == "board":
                    new_url = str(body["url"]).strip()
                    if not re.match(r"^https?://\S+$", new_url, re.IGNORECASE):
                        self._send_error_json(400, "invalid_url", "Ссылка должна начинаться с https:// или http://")
                        return
                    found["url"] = new_url

                val_errors = validate_catalog(catalog)
                if val_errors:
                    self._send_error_json(400, "validation_error", "; ".join(val_errors))
                    return

                atomic_save_json(self.manager.catalog_path, catalog)
                build_site(self.manager.project_root, vendor_timeout=5)
                cloud_warn = self.manager.push_to_cloud({}, f"admin: обновлена карточка «{found.get('title', target_id)}»")
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "item": item_with_computed(found),
                        "warnings": [cloud_warn] if cloud_warn else [],
                    },
                )
            return

        self.send_error(404, "Not Found")


class AdminServerManager:
    """Менеджер состояния сервера админки: пароль, каталог, облачная синхронизация и запуск."""

    def __init__(
        self,
        project_root: Path | None = None,
        host: str = "127.0.0.1",
        port: int = 8080,
        bind_socket: bool = True,
        auto_port: bool = False,
        cloud_storage: GitHubStorage | None = None,
        ui_root: Path | None = None,
    ):
        default_code_root = Path(__file__).resolve().parent.parent
        if project_root is None:
            project_root = default_code_root

        self.project_root = Path(project_root).resolve()
        self.ui_root = Path(ui_root).resolve() if ui_root else (
            self.project_root if (self.project_root / "tools" / "admin_ui").exists() else default_code_root
        )
        self.host = host
        self.port = port
        self.is_serverless = bool(os.environ.get("VERCEL"))
        self.catalog_path = self.project_root / "catalog.json"
        self.lock = threading.Lock()
        self.cloud_storage = cloud_storage if cloud_storage is not None else GitHubStorage.from_env()

        self.password_configured = True
        self.admin_password = self._init_password()
        self.expected_session_token = hmac.new(
            self.admin_password.encode("utf-8"),
            b"tutor_admin_session_v1",
            hashlib.sha256,
        ).hexdigest()

        if not self.is_serverless:
            self._ensure_gitignore()

        dist_index = self.project_root / "dist" / "index.html"
        if not dist_index.exists():
            build_site(self.project_root, vendor_timeout=5)

        if bind_socket:
            self.server = create_admin_server(
                self.project_root,
                self.host,
                self.port,
                manager=self,
                auto_port=auto_port,
            )
        else:
            self.server = None

    @property
    def storage_mode(self) -> str:
        return "github" if self.cloud_storage is not None else "local"

    def get_public_catalog_url(self, headers=None) -> str:
        """Базовый URL публичной витрины для генерации ученических ссылок и QR-кодов."""
        explicit = (os.environ.get("PUBLIC_CATALOG_URL") or "").strip()
        if explicit:
            return explicit.rstrip("/") + "/"
        if self.cloud_storage is not None:
            return self.cloud_storage.public_pages_url
        if headers:
            host_hdr = headers.get("Host")
            if host_hdr:
                proto = (headers.get("X-Forwarded-Proto") or "http").split(",")[0].strip()
                return f"{proto}://{host_hdr}/"
        if self.server:
            bound_port = self.server.server_address[1]
            return f"http://{self.host}:{bound_port}/"
        return "/"

    def _init_password(self) -> str:
        """Получение или генерация пароля администратора."""
        env_pwd = os.environ.get("TUTOR_ADMIN_PASSWORD")
        if env_pwd and env_pwd.strip():
            return env_pwd.strip()

        if self.is_serverless:
            self.password_configured = False
            return secrets.token_urlsafe(16)

        secret_file = self.project_root / ".admin_secret"
        if secret_file.exists():
            pwd = secret_file.read_text(encoding="utf-8").strip()
            if pwd:
                return pwd

        new_pwd = secrets.token_urlsafe(9)
        secret_file.write_text(new_pwd, encoding="utf-8")
        print("\n┌─────────────────────────────────────────────────────────┐")
        print("│ Пароль администратора Мастерской репетитора:            │")
        print(f"│    {new_pwd:<53}│")
        print("│ Сохранён в .admin_secret (не передавайте третьим лицам) │")
        print("└─────────────────────────────────────────────────────────┘\n")
        return new_pwd

    def _ensure_gitignore(self) -> None:
        """Добавление .admin_secret в .gitignore."""
        gi_path = self.project_root / ".gitignore"
        lines = []
        if gi_path.exists():
            lines = gi_path.read_text(encoding="utf-8").splitlines()

        needed = [".admin_secret", "__pycache__/", ".vendor_cache/"]
        modified = False
        for item in needed:
            if item not in lines:
                lines.append(item)
                modified = True

        if modified or not gi_path.exists():
            gi_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def sync_from_cloud_if_needed(self) -> None:
        """Подтягивание свежего catalog.json из GitHub при смене удалённого HEAD SHA."""
        if self.cloud_storage is None:
            return
        try:
            remote_catalog = self.cloud_storage.fetch_json_if_changed("catalog.json")
            if isinstance(remote_catalog, dict) and "items" in remote_catalog:
                atomic_save_json(self.catalog_path, remote_catalog)
        except Exception as exc:
            print(f"[GitHubStorage] Предупреждение синхронизации чтения: {exc}", file=sys.stderr)

    def push_to_cloud(
        self,
        extra_files: dict[str, bytes],
        message: str,
        include_catalog: bool = True,
    ) -> str | None:
        """Отправка изменённых исходников в GitHub REST API (без папки dist/)."""
        if self.cloud_storage is None:
            return None
        payload_files = dict(extra_files)
        if include_catalog and self.catalog_path.exists():
            payload_files["catalog.json"] = self.catalog_path.read_bytes()
        try:
            self.cloud_storage.commit_files(payload_files, message=message)
            return None
        except Exception as exc:
            warn_msg = f"Локально сохранено, но облачный коммит в GitHub отложен: {exc}"
            print(f"[GitHubStorage] {warn_msg}", file=sys.stderr)
            return warn_msg

    def load_catalog(self) -> dict:
        """Чтение catalog.json с предварительной сверкой облака."""
        self.sync_from_cloud_if_needed()
        if self.catalog_path.exists():
            try:
                return json.loads(self.catalog_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"items": []}


def create_admin_server(
    project_root: Path,
    host: str = "127.0.0.1",
    port: int = 8080,
    manager: AdminServerManager | None = None,
    auto_port: bool = False,
) -> http.server.ThreadingHTTPServer:
    """Создание и привязка экземпляра ThreadingHTTPServer с поддержкой автоподбора порта."""
    if manager is None:
        mgr = AdminServerManager(project_root=project_root, host=host, port=port, auto_port=auto_port)
        return mgr.server

    candidates = [port]
    if auto_port and port != 0:
        candidates.extend(range(port + 1, port + 20))
        candidates.append(0)

    last_err: OSError | None = None
    for candidate_port in candidates:
        try:
            server = http.server.ThreadingHTTPServer((host, candidate_port), AdminRequestHandler)
            server.manager = manager
            return server
        except OSError as exc:
            last_err = exc
            if not auto_port:
                raise
            continue

    if last_err:
        raise last_err
    raise OSError("Не удалось привязать HTTP-порт")


def main():
    parser = argparse.ArgumentParser(description="Словесность — сервер Игротеки и Мастерской репетитора")
    parser.add_argument("--host", default="127.0.0.1", help="Хост для привязки (по умолч. 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="Порт (по умолч. 8080)")
    parser.add_argument("--auto-port", action="store_true", help="Автоматически выбрать свободный порт, если указанный занят")
    parser.add_argument("--open-browser", action="store_true", help="Открыть Мастерскую в браузере после успешного старта сокета")
    parser.add_argument("--root", default=None, help="Корень проекта (по умолч. автоопределение)")
    args = parser.parse_args()

    project_root = Path(args.root) if args.root else None
    mgr = AdminServerManager(
        project_root=project_root,
        host=args.host,
        port=args.port,
        auto_port=args.auto_port,
    )
    real_port = mgr.server.server_address[1]
    admin_url = f"http://{args.host}:{real_port}/admin"

    print("───────────────────────────────────────────────────────────")
    print("  Словесность — Игротека и Мастерская репетитора запущены")
    print(f"  Витрина учеников:      http://{args.host}:{real_port}/")
    print(f"  Мастерская репетитора: {admin_url}")
    print(f"  Режим хранения:        {'GitHub Облако' if mgr.storage_mode == 'github' else 'Локальный диск'}")
    print("  Для остановки закройте окно или нажмите Ctrl+C")
    print("───────────────────────────────────────────────────────────")

    if args.open_browser:
        threading.Timer(0.25, lambda: webbrowser.open(admin_url)).start()

    try:
        mgr.server.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановка сервера...")
    finally:
        mgr.server.shutdown()
        mgr.server.server_close()
        print("Сервер остановлен.")


if __name__ == "__main__":
    main()
