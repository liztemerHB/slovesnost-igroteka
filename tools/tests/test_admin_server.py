"""Интеграционные и unit-тесты для веб-админки и сервера (tools/admin_server.py)."""

import base64
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from tools.admin_server import AdminServerManager, create_admin_server


class TestAdminServerAPI(unittest.TestCase):
    """Сквозные тесты API админки, CSRF, сессий, загрузки игр и обложек."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.root_dir = Path(cls.temp_dir.name)

        # Структура проекта
        cls.inbox = cls.root_dir / "games_inbox"
        cls.inbox.mkdir(parents=True)
        cls.template = cls.root_dir / "site_template"
        cls.template.mkdir(parents=True)
        (cls.template / "index.html").write_text("<html><body><!--CATALOG_DATA--></body></html>", encoding="utf-8")
        (cls.template / "covers").mkdir(parents=True)

        cls.admin_ui = cls.root_dir / "tools" / "admin_ui"
        cls.admin_ui.mkdir(parents=True)
        (cls.admin_ui / "admin.html").write_text("<!DOCTYPE html><html><body>Admin UI</body></html>", encoding="utf-8")
        (cls.admin_ui / "admin.css").write_text("body { background: #080d0b; }", encoding="utf-8")

        # Начальный catalog.json
        initial_catalog = {
            "items": [
                {
                    "id": "game-initial",
                    "slug": "game-initial",
                    "title": "Начальная игра",
                    "grade": 6,
                    "topic": "Тема 1",
                    "subtitle": "Тестовая",
                    "cover": "autumn",
                    "kind": "game",
                    "file": "initial.html",
                    "tags": [],
                    "order": 1,
                    "hidden": False,
                    "archived": False,
                }
            ]
        }
        (cls.root_dir / "catalog.json").write_text(json.dumps(initial_catalog, ensure_ascii=False), encoding="utf-8")
        (cls.inbox / "initial.html").write_text("<title>Начальная игра</title><body>OK</body>", encoding="utf-8")

        # Пароль администратора
        cls.admin_password = "SuperSecretPassword123"
        os.environ["TUTOR_ADMIN_PASSWORD"] = cls.admin_password

        # Запуск сервера на случайном свободном порту (127.0.0.1, 0)
        cls.server_manager = AdminServerManager(project_root=cls.root_dir, host="127.0.0.1", port=0)
        cls.server = cls.server_manager.server
        cls.port = cls.server.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"

        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=2.0)
        cls.temp_dir.cleanup()
        if "TUTOR_ADMIN_PASSWORD" in os.environ:
            del os.environ["TUTOR_ADMIN_PASSWORD"]

    def _request(self, method: str, path: str, data: dict | None = None, headers: dict | None = None) -> tuple[int, dict | str, dict]:
        """Утилита для выполнения HTTP-запросов к серверу админки."""
        url = f"{self.base_url}{path}"
        req_headers = {"User-Agent": "TestClient/1.0"}
        if headers:
            req_headers.update(headers)

        body = None
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            req_headers["Content-Type"] = "application/json; charset=utf-8"

        req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                status = resp.status
                resp_headers = dict(resp.headers)
                raw_body = resp.read()
                content_type = resp_headers.get("Content-Type", "")
                if "application/json" in content_type:
                    parsed = json.loads(raw_body.decode("utf-8"))
                else:
                    parsed = raw_body.decode("utf-8", errors="replace")
                return status, parsed, resp_headers
        except urllib.error.HTTPError as e:
            status = e.code
            resp_headers = dict(e.headers)
            raw_body = e.read()
            content_type = resp_headers.get("Content-Type", "")
            if "application/json" in content_type:
                parsed = json.loads(raw_body.decode("utf-8"))
            else:
                parsed = raw_body.decode("utf-8", errors="replace")
            return status, parsed, resp_headers

    def test_01_unauthorized_access(self):
        """Без авторизации /api/admin/items возвращает 401 unauthorized."""
        status, body, _ = self._request("GET", "/api/admin/items")
        self.assertEqual(status, 401)
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"], "unauthorized")

        # GET /api/admin/session без куки возвращает 200, authenticated=False
        status, body, _ = self._request("GET", "/api/admin/session")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertFalse(body["authenticated"])

    def test_02_csrf_rejection_on_mutating_requests(self):
        """Мутирующие запросы POST/PUT без заголовка X-Requested-With: TutorAdmin отклоняются 403."""
        status, body, _ = self._request("POST", "/api/admin/login", {"password": self.admin_password})
        self.assertEqual(status, 403)
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"], "csrf_rejected")

    def test_03_login_and_session_cookie(self):
        """Логин с неверным паролем дает 401, с верным — 200 и Set-Cookie."""
        csrf_hdr = {"X-Requested-With": "TutorAdmin"}

        # Неверный пароль
        status, body, _ = self._request("POST", "/api/admin/login", {"password": "wrong"}, headers=csrf_hdr)
        self.assertEqual(status, 401)
        self.assertEqual(body["error"], "invalid_password")

        # Верный пароль
        status, body, headers = self._request(
            "POST",
            "/api/admin/login",
            {"password": self.admin_password},
            headers=csrf_hdr,
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])

        set_cookie = headers.get("Set-Cookie", "")
        self.assertIn("tutor_admin_session=", set_cookie)
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("SameSite=Strict", set_cookie)

        # Извлекаем куку
        cookie_val = set_cookie.split(";")[0]

        # Проверяем /api/admin/session с кукой
        status, body, _ = self._request("GET", "/api/admin/session", headers={"Cookie": cookie_val})
        self.assertEqual(status, 200)
        self.assertTrue(body["authenticated"])

    def test_04_preview_game_does_not_touch_disk(self):
        """POST /api/admin/preview-game извлекает метаданные без записи на диск."""
        csrf_hdr = {"X-Requested-With": "TutorAdmin"}
        _, _, login_headers = self._request("POST", "/api/admin/login", {"password": self.admin_password}, headers=csrf_hdr)
        cookie_val = login_headers["Set-Cookie"].split(";")[0]

        html_content = """
        <!DOCTYPE html><html><head><title>Словарный диктант 6 класс — Осень</title></head>
        <body>
            <h1>29 словарных слов</h1>
            <audio src="data:audio/mp3;base64,..."></audio>
        </body></html>
        """
        status, body, _ = self._request(
            "POST",
            "/api/admin/preview-game",
            {"filename": "test_inbox.html", "content_html": html_content},
            headers={"X-Requested-With": "TutorAdmin", "Cookie": cookie_val},
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        meta = body["meta"]
        self.assertEqual(meta["title"], "Словарный диктант 6 класс — Осень")
        self.assertEqual(meta["grade"], 6)
        self.assertIn("29", meta["subtitle"])
        self.assertEqual(meta["suggested_cover"], "autumn")

        # Проверяем, что файл test_inbox.html НЕ появился в games_inbox
        self.assertFalse((self.inbox / "test_inbox.html").exists())

    def test_05_upload_game_and_collision_safety(self):
        """Загрузка двух разных игр с одинаковым именем 'index.html' без перезаписи."""
        csrf_hdr = {"X-Requested-With": "TutorAdmin"}
        _, _, login_headers = self._request("POST", "/api/admin/login", {"password": self.admin_password}, headers=csrf_hdr)
        cookie_val = login_headers["Set-Cookie"].split(";")[0]
        auth_headers = {"X-Requested-With": "TutorAdmin", "Cookie": cookie_val}

        # 1. Загружаем первую игру
        html_1 = "<title>Игра Номер Один 5 класс</title><body>Содержимое 1</body>"
        status_1, body_1, _ = self._request(
            "POST",
            "/api/admin/upload-game",
            {"filename": "index.html", "content_html": html_1, "topic": "Морфемика"},
            headers=auth_headers,
        )
        self.assertEqual(status_1, 201)
        self.assertTrue(body_1["ok"])
        slug_1 = body_1["item"]["slug"]
        file_1 = body_1["item"]["file"]
        self.assertTrue((self.inbox / file_1).exists())
        self.assertEqual((self.inbox / file_1).read_text(encoding="utf-8"), html_1)

        # 2. Загружаем вторую игру с тем же входным именем 'index.html', но другим title
        html_2 = "<title>Игра Номер Два 7 класс</title><body>Содержимое 2</body>"
        status_2, body_2, _ = self._request(
            "POST",
            "/api/admin/upload-game",
            {"filename": "index.html", "content_html": html_2, "topic": "Синтаксис"},
            headers=auth_headers,
        )
        self.assertEqual(status_2, 201)
        slug_2 = body_2["item"]["slug"]
        file_2 = body_2["item"]["file"]

        # Первая игра НЕ перезаписана
        self.assertNotEqual(slug_1, slug_2)
        self.assertNotEqual(file_1, file_2)
        self.assertEqual((self.inbox / file_1).read_text(encoding="utf-8"), html_1)
        self.assertEqual((self.inbox / file_2).read_text(encoding="utf-8"), html_2)

        # 3. Загружаем третью игру с ТЕМ ЖЕ заголовком (коллизия слага)
        html_3 = "<title>Игра Номер Один 5 класс</title><body>Содержимое 3 дубликат</body>"
        status_3, body_3, _ = self._request(
            "POST",
            "/api/admin/upload-game",
            {"filename": "index.html", "content_html": html_3},
            headers=auth_headers,
        )
        self.assertEqual(status_3, 201)
        slug_3 = body_3["item"]["slug"]
        file_3 = body_3["item"]["file"]

        self.assertNotEqual(slug_1, slug_3)
        self.assertNotEqual(file_1, file_3)
        self.assertTrue(slug_3.startswith(slug_1))
        self.assertEqual((self.inbox / file_1).read_text(encoding="utf-8"), html_1)
        self.assertEqual((self.inbox / file_3).read_text(encoding="utf-8"), html_3)

    def test_06_add_board_and_xss_protection(self):
        """POST /api/admin/add-board валидирует URL и блокирует javascript:/data:."""
        csrf_hdr = {"X-Requested-With": "TutorAdmin"}
        _, _, login_headers = self._request("POST", "/api/admin/login", {"password": self.admin_password}, headers=csrf_hdr)
        cookie_val = login_headers["Set-Cookie"].split(";")[0]
        auth_headers = {"X-Requested-With": "TutorAdmin", "Cookie": cookie_val}

        # XSS инъекция в URL
        status, body, _ = self._request(
            "POST",
            "/api/admin/add-board",
            {"url": "javascript:alert(document.cookie)", "title": "Опасная доска"},
            headers=auth_headers,
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_url")

        # Корректная доска Miro
        valid_url = "https://miro.com/app/board/uXjVO12345="
        status, body, _ = self._request(
            "POST",
            "/api/admin/add-board",
            {"url": valid_url, "title": "Доска урока Miro", "grade": 8, "topic": "Лексика"},
            headers=auth_headers,
        )
        self.assertEqual(status, 201)
        self.assertTrue(body["ok"])
        self.assertEqual(body["item"]["kind"], "board")
        self.assertEqual(body["item"]["url"], valid_url)

    def test_07_upload_cover_validation_and_saving(self):
        """POST /api/admin/upload-cover проверяет магические байты и сохраняет в covers."""
        csrf_hdr = {"X-Requested-With": "TutorAdmin"}
        _, _, login_headers = self._request("POST", "/api/admin/login", {"password": self.admin_password}, headers=csrf_hdr)
        cookie_val = login_headers["Set-Cookie"].split(";")[0]
        auth_headers = {"X-Requested-With": "TutorAdmin", "Cookie": cookie_val}

        # 1. Попытка загрузить фейковый исполняемый файл
        fake_exe = base64.b64encode(b"MZ\x90\x00fake executable").decode("ascii")
        status, body, _ = self._request(
            "POST",
            "/api/admin/upload-cover",
            {"filename": "virus.exe", "data_base64": fake_exe},
            headers=auth_headers,
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "invalid_image")

        # 2. Валидный PNG
        valid_png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
        b64_png = base64.b64encode(valid_png_bytes).decode("ascii")
        status, body, _ = self._request(
            "POST",
            "/api/admin/upload-cover",
            {"filename": "my_cover.png", "data_base64": b64_png},
            headers=auth_headers,
        )
        self.assertEqual(status, 201)
        self.assertTrue(body["ok"])
        cover_name = body["cover"]
        self.assertTrue(cover_name.startswith("custom_"))
        self.assertTrue(cover_name.endswith(".png"))
        self.assertTrue((self.template / "covers" / cover_name).exists())

    def test_08_put_update_reorder_and_archive(self):
        """Тест частичного обновления, сортировки и архивации без удаления из inbox."""
        csrf_hdr = {"X-Requested-With": "TutorAdmin"}
        _, _, login_headers = self._request("POST", "/api/admin/login", {"password": self.admin_password}, headers=csrf_hdr)
        cookie_val = login_headers["Set-Cookie"].split(";")[0]
        auth_headers = {"X-Requested-With": "TutorAdmin", "Cookie": cookie_val}

        # 1. Обновление карточки PUT
        status, body, _ = self._request(
            "PUT",
            "/api/admin/items/game-initial",
            {"title": "Обновленная игра", "grade": 10, "hidden": True},
            headers=auth_headers,
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["item"]["title"], "Обновленная игра")
        self.assertEqual(body["item"]["grade"], 10)
        self.assertTrue(body["item"]["hidden"])

        # 2. Reorder
        status, body, _ = self._request(
            "POST",
            "/api/admin/reorder",
            {"ids": ["game-initial"]},
            headers=auth_headers,
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])

        # 3. Архивация карточки POST /api/admin/archive/<id>
        status, body, _ = self._request(
            "POST",
            "/api/admin/archive/game-initial",
            {"archived": True},
            headers=auth_headers,
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["item"]["archived"])

        # Закон №2: файл в games_inbox/initial.html остался невредим!
        self.assertTrue((self.inbox / "initial.html").exists())

    def test_09_static_serving_and_admin_ui(self):
        """GET /admin отдаёт админку, GET / отдаёт витрину, защита от Path Traversal."""
        # Витрина
        status, body, headers = self._request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))

        # Админка
        status, body, headers = self._request("GET", "/admin")
        self.assertEqual(status, 200)
        self.assertIn("Admin UI", body)

        status, body, headers = self._request("GET", "/admin_assets/admin.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", headers.get("Content-Type", ""))

        # Защита от Path Traversal
        status, _, _ = self._request("GET", "/../../secret.txt")
        self.assertIn(status, [403, 404])

    def test_10_direct_cli_invocation_without_m_flag(self):
        """Прямой запуск python tools/admin_server.py --help из чужой папки не падает с ModuleNotFoundError."""
        import subprocess
        import sys

        real_script = Path(__file__).resolve().parent.parent / "admin_server.py"
        res = subprocess.run(
            [sys.executable, str(real_script), "--help"],
            cwd=tempfile.gettempdir(),
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(res.returncode, 0, f"CLI упал: {res.stderr}")
        self.assertIn("--auto-port", res.stdout)

    def test_11_auto_port_fallback_and_bind_socket_false(self):
        """Если порт занят, auto_port=True находит свободный порт; bind_socket=False не открывает сокет."""
        import socket

        # Режим serverless (bind_socket=False)
        serverless_mgr = AdminServerManager(project_root=self.root_dir, bind_socket=False)
        self.assertIsNone(serverless_mgr.server)

        # Занимаем временный порт и проверяем auto_port=True
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        busy_port = blocker.getsockname()[1]
        try:
            fallback_mgr = AdminServerManager(
                project_root=self.root_dir,
                host="127.0.0.1",
                port=busy_port,
                auto_port=True,
            )
            try:
                bound_port = fallback_mgr.server.server_address[1]
                self.assertNotEqual(bound_port, busy_port)
                self.assertGreater(bound_port, 0)
            finally:
                fallback_mgr.server.server_close()
        finally:
            blocker.close()

    def test_12_session_metadata_and_site_template_fallback(self):
        """GET /api/admin/session отдаёт storage_mode и public_catalog_url, а статика фолбэчится в site_template."""
        status, body, _ = self._request("GET", "/api/admin/session")
        self.assertEqual(status, 200)
        self.assertIn("storage_mode", body)
        self.assertEqual(body["storage_mode"], "local")
        self.assertIn("public_catalog_url", body)

        # Создаём файл только в site_template/fonts/ и проверяем, что сервер отдаст его даже без пересборки dist
        fonts_dir = self.template / "fonts"
        fonts_dir.mkdir(parents=True, exist_ok=True)
        (fonts_dir / "fallback-check.css").write_text("/* font ok */", encoding="utf-8")
        status_f, css_body, _ = self._request("GET", "/fonts/fallback-check.css")
        self.assertEqual(status_f, 200)
        self.assertIn("font ok", css_body)

    def test_13_cloud_storage_hook_commits_only_source_files(self):
        """При подключённом GitHubStorage мутации коммитят исходники без папки dist/."""

        class DummyCloudStorage:
            def __init__(self):
                self.commits = []
                self.public_pages_url = "https://tutor.github.io/igroteka/"

            def fetch_json_if_changed(self, rel_path: str):
                return None

            def commit_files(self, files: dict[str, bytes], message: str) -> str:
                self.commits.append((dict(files), message))
                return "sha_dummy"

        dummy = DummyCloudStorage()
        old_storage = self.server_manager.cloud_storage
        self.server_manager.cloud_storage = dummy
        try:
            csrf_hdr = {"X-Requested-With": "TutorAdmin"}
            _, _, login_headers = self._request("POST", "/api/admin/login", {"password": self.admin_password}, headers=csrf_hdr)
            cookie_val = login_headers["Set-Cookie"].split(";")[0]
            auth_headers = {"X-Requested-With": "TutorAdmin", "Cookie": cookie_val}

            status, _, _ = self._request(
                "POST",
                "/api/admin/upload-game",
                {"filename": "cloud.html", "content_html": "<title>Облачный квест 8 класс</title><body>1</body>"},
                headers=auth_headers,
            )
            self.assertEqual(status, 201)
            self.assertEqual(len(dummy.commits), 1)
            committed_files, _ = dummy.commits[0]
            self.assertIn("catalog.json", committed_files)
            self.assertTrue(any(k.startswith("games_inbox/") for k in committed_files))
            self.assertFalse(any(k.startswith("dist/") for k in committed_files))
        finally:
            self.server_manager.cloud_storage = old_storage


if __name__ == "__main__":
    unittest.main()
