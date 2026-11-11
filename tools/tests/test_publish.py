"""Unit-тесты для инструментов публикации каталога игр (tools/publish.py)."""

import io
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from tools.publish import (
    VendorManager,
    build_catalog_payload,
    build_site,
    compute_topic_slug,
    embed_catalog,
    extract_meta,
    format_cover_src,
    inject_shell,
    publish,
    rewrite_cdn,
    slugify,
    suggest_cover,
    sync_catalog_with_inbox,
    validate_catalog,
)


class TestTranslitSlugify(unittest.TestCase):
    """Тесты транслитерации и генерации слагов (ГОСТ 7.79-2000 соотв.)."""

    def test_slugify_lexicology(self):
        """«Лексикология и фразеология» → leksikologiya-i-frazeologiya"""
        self.assertEqual(
            slugify("Лексикология и фразеология"),
            "leksikologiya-i-frazeologiya",
        )

    def test_slugify_yozhik(self):
        """«Ёжик в тумане» → yozhik-v-tumane"""
        self.assertEqual(
            slugify("Ёжик в тумане"),
            "yozhik-v-tumane",
        )

    def test_slugify_empty_string(self):
        """Пустая строка → 'game'"""
        self.assertEqual(slugify(""), "game")
        self.assertEqual(slugify("   "), "game")
        self.assertEqual(slugify("---!@#$---"), "game")

    def test_slugify_special_chars_and_dashes(self):
        """Спецсимволы, кавычки, дефисы схлопываются и обрезаются."""
        text = "«Квест: Архитектура Слова • Проверка ДЗ!»"
        slug = slugify(text)
        self.assertTrue(re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", slug))
        self.assertNotIn("•", slug)
        self.assertNotIn("«", slug)
        self.assertNotIn("--", slug)


class TestExtractMeta(unittest.TestCase):
    """Тесты извлечения метаданных из HTML."""

    def test_extract_meta_with_grade(self):
        html = "<!DOCTYPE html><html><head><title>Словарный диктант 6 класс — Осенний тренажёр</title></head></html>"
        meta = extract_meta(html, "6.html")
        self.assertEqual(meta["title"], "Словарный диктант 6 класс — Осенний тренажёр")
        self.assertEqual(meta["grade"], 6)
        self.assertEqual(meta["topic"], "")

    def test_extract_meta_double_digit_grade(self):
        html = "<!DOCTYPE html><html><head><title>Тест 11 класс: Итоговый</title></head></html>"
        meta = extract_meta(html, "test.html")
        self.assertEqual(meta["grade"], 11)

    def test_extract_meta_no_grade(self):
        html = "<!DOCTYPE html><html><head><title>Квест: Архитектура Слова</title></head></html>"
        meta = extract_meta(html, "quest.html")
        self.assertIsNone(meta["grade"])

    def test_extract_meta_html_unescape(self):
        html = "<title>&laquo;Тренажер&raquo; &amp; игра</title>"
        meta = extract_meta(html, "game.html")
        self.assertEqual(meta["title"], "«Тренажер» & игра")

    def test_extract_meta_fallback_to_filename(self):
        html = "<html><head></head><body>Без заголовка</body></html>"
        meta = extract_meta(html, "my_custom_game.html")
        self.assertEqual(meta["title"], "my_custom_game.html")
        self.assertIsNone(meta["grade"])


class TestValidateCatalog(unittest.TestCase):
    """Тесты валидатора catalog.json."""

    def test_valid_catalog(self):
        catalog = {
            "items": [
                {
                    "id": "dictant-6",
                    "slug": "dictant-6",
                    "title": "Словарный диктант 6 класс",
                    "grade": 6,
                    "topic": "Лексика",
                    "kind": "game",
                    "file": "6.html",
                    "tags": ["словарный", "диктант"],
                },
                {
                    "id": "miro-board",
                    "slug": "miro-board",
                    "title": "Доска Miro",
                    "grade": None,
                    "topic": "Теория",
                    "kind": "board",
                    "url": "https://miro.com/app/board/123",
                    "tags": [],
                },
            ]
        }
        errors = validate_catalog(catalog)
        self.assertEqual(errors, [])

    def test_duplicate_id(self):
        catalog = {
            "items": [
                {"id": "same-id", "slug": "slug-1", "title": "Game 1", "kind": "game", "file": "1.html", "tags": []},
                {"id": "same-id", "slug": "slug-2", "title": "Game 2", "kind": "game", "file": "2.html", "tags": []},
            ]
        }
        errors = validate_catalog(catalog)
        self.assertTrue(any("дубликат id" in err.lower() or "duplicate id" in err.lower() for err in errors))

    def test_duplicate_slug(self):
        catalog = {
            "items": [
                {"id": "id-1", "slug": "same-slug", "title": "Game 1", "kind": "game", "file": "1.html", "tags": []},
                {"id": "id-2", "slug": "same-slug", "title": "Game 2", "kind": "game", "file": "2.html", "tags": []},
            ]
        }
        errors = validate_catalog(catalog)
        self.assertTrue(any("дубликат slug" in err.lower() or "duplicate slug" in err.lower() for err in errors))

    def test_empty_title(self):
        catalog = {
            "items": [
                {"id": "id-1", "slug": "slug-1", "title": "   ", "kind": "game", "file": "1.html", "tags": []},
            ]
        }
        errors = validate_catalog(catalog)
        self.assertTrue(any("title" in err.lower() for err in errors))

    def test_kind_game_without_file(self):
        catalog = {
            "items": [
                {"id": "id-1", "slug": "slug-1", "title": "Game", "kind": "game", "tags": []},
            ]
        }
        errors = validate_catalog(catalog)
        self.assertTrue(any("file" in err.lower() for err in errors))

    def test_kind_board_without_url(self):
        catalog = {
            "items": [
                {"id": "id-1", "slug": "slug-1", "title": "Board", "kind": "board", "tags": []},
            ]
        }
        errors = validate_catalog(catalog)
        self.assertTrue(any("url" in err.lower() for err in errors))

    def test_invalid_slug_format(self):
        catalog = {
            "items": [
                {"id": "id-1", "slug": "Bad_Slug!", "title": "Game", "kind": "game", "file": "1.html", "tags": []},
            ]
        }
        errors = validate_catalog(catalog)
        self.assertTrue(any("slug" in err.lower() for err in errors))


class TestCatalogSyncAndStability(unittest.TestCase):
    """Тесты авто-черновиков, уникальности и стабильности slug."""

    def test_autodraft_collision_suffix(self):
        """При коллизии слагов создаются суффиксы -2, -3."""
        existing_catalog = {
            "items": [
                {
                    "id": "yozhik-v-tumane",
                    "slug": "yozhik-v-tumane",
                    "title": "Ёжик в тумане",
                    "grade": None,
                    "topic": "",
                    "kind": "game",
                    "file": "game1.html",
                    "tags": [],
                }
            ]
        }
        inbox_files = {
            "game2.html": "<title>Ёжик в тумане</title>",
            "game3.html": "<title>Ёжик в тумане</title>",
        }
        updated_catalog, warnings = sync_catalog_with_inbox(existing_catalog, inbox_files)
        slugs = [item["slug"] for item in updated_catalog["items"]]
        self.assertIn("yozhik-v-tumane", slugs)
        self.assertIn("yozhik-v-tumane-2", slugs)
        self.assertIn("yozhik-v-tumane-3", slugs)
        self.assertEqual(len(warnings), 2)

    def test_slug_stability_upon_rebuild(self):
        """Слаг, записанный в catalog.json, не меняется даже при смене title в файле."""
        saved_catalog = {
            "items": [
                {
                    "id": "stable-slug-qr",
                    "slug": "stable-slug-qr",
                    "title": "Старое название",
                    "grade": 5,
                    "topic": "",
                    "kind": "game",
                    "file": "my_game.html",
                    "tags": [],
                }
            ]
        }
        inbox_files = {"my_game.html": "<title>Новое название 7 класс</title>"}
        updated_catalog, warnings = sync_catalog_with_inbox(saved_catalog, inbox_files)
        item = updated_catalog["items"][0]
        self.assertEqual(item["slug"], "stable-slug-qr")
        self.assertEqual(item["id"], "stable-slug-qr")
        self.assertEqual(warnings, [])


class TestInjectShell(unittest.TestCase):
    """Тесты вставки оболочки shell.js."""

    def test_inject_shell_before_closing_body(self):
        html = "<html><body><h1>Игра</h1></body></html>"
        res = inject_shell(html, slug="test-game", shell_version="abc12345")
        expected_tag = '<script defer src="../../_shell/shell.js?v=abc12345" data-slug="test-game" data-tutor-shell></script>'
        self.assertIn(expected_tag, res)
        self.assertTrue(res.endswith(f"{expected_tag}</body></html>"))

    def test_inject_shell_idempotent(self):
        html = '<html><body><h1>Игра</h1><script defer src="../../_shell/shell.js?v=old" data-slug="test-game" data-tutor-shell></script></body></html>'
        res = inject_shell(html, slug="test-game", shell_version="new12345")
        self.assertEqual(res.count("data-tutor-shell"), 1)
        self.assertIn("new12345", res)
        self.assertNotIn("old", res)

    def test_inject_shell_no_body_tag(self):
        html = "<div>Игра без body</div>"
        res = inject_shell(html, slug="test-game", shell_version="1.0")
        self.assertIn("data-tutor-shell", res)
        self.assertTrue(res.endswith('data-tutor-shell></script>'))


class TestEmbedCatalog(unittest.TestCase):
    """Тесты встраивания catalog.json в шаблон каталога."""

    def test_embed_catalog_escaping(self):
        template = "<html><body><!--CATALOG_DATA--></body></html>"
        payload = {
            "generated": "2026-11-10T00:00:00Z",
            "items": [
                {
                    "id": "test",
                    "slug": "test",
                    "title": "Инъекция </script><script>alert(1)</script>",
                    "grade": None,
                    "topic": "",
                    "kind": "game",
                    "tags": [],
                    "href": "g/test/index.html",
                }
            ],
        }
        res = embed_catalog(template, payload)
        self.assertNotIn("<!--CATALOG_DATA-->", res)
        self.assertIn('<script type="application/json" id="catalog-data">', res)
        self.assertNotIn("</script><script>", res)
        self.assertIn(r"<\/script>", res)


class TestRewriteCdn(unittest.TestCase):
    """Тесты переписывания CDN-ссылок и вендоринга."""

    def test_rewrite_tailwind_and_fonts(self):
        html = (
            '<!DOCTYPE html><html><head>'
            '<link rel="preconnect" href="https://fonts.googleapis.com">'
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap" rel="stylesheet">'
            '<script src="https://cdn.tailwindcss.com"></script>'
            '</head><body>Content</body></html>'
        )
        vendor_map = {
            "https://cdn.tailwindcss.com": "../../_vendor/tailwindcss.js?v=11112222",
            "https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap": "../../_vendor/fonts/fonts_inter.css?v=33334444",
        }
        rewritten, warnings = rewrite_cdn(html, vendor_map)
        self.assertNotIn("cdn.tailwindcss.com", rewritten)
        self.assertNotIn("fonts.googleapis.com", rewritten)
        self.assertNotIn("fonts.gstatic.com", rewritten)
        self.assertIn('../../_vendor/tailwindcss.js?v=11112222', rewritten)
        self.assertIn('../../_vendor/fonts/fonts_inter.css?v=33334444', rewritten)
        self.assertEqual(warnings, [])

    def test_rewrite_unknown_cdn_warning(self):
        html = '<script src="https://unknown-cdn.example.com/lib.js"></script>'
        vendor_map = {}
        rewritten, warnings = rewrite_cdn(html, vendor_map)
        self.assertEqual(len(warnings), 1)
        self.assertIn("https://unknown-cdn.example.com/lib.js", warnings[0])


class TestVendorManagerOfflineMock(unittest.TestCase):
    """Тесты VendorManager с мокированием сети (urlopen): скачивание, woff2, кэширование."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cache_dir = Path(self.temp_dir.name) / ".vendor_cache"
        self.dist_vendor = Path(self.temp_dir.name) / "dist" / "_vendor"
        self.manager = VendorManager(self.cache_dir, self.dist_vendor)

        fixtures_dir = Path(__file__).resolve().parent / "fixtures"
        self.sample_css = (fixtures_dir / "sample_font.css").read_text(encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("tools.publish.urllib.request.urlopen")
    def test_vendor_tailwind_and_fonts_offline(self, mock_urlopen):
        """Проверка вендоринга tailwind и Google Fonts (CSS + woff2) в изолированный кэш."""
        def urlopen_side_effect(req, *args, **kwargs):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            resp = MagicMock()
            resp.__enter__.return_value = resp
            if "tailwindcss.com" in url:
                resp.read.return_value = b"/* tailwind stub */"
            elif "fonts.googleapis.com" in url:
                resp.read.return_value = self.sample_css.encode("utf-8")
            elif "fonts.gstatic.com" in url:
                resp.read.return_value = b"/* woff2 binary stub */"
            else:
                raise URLError("Unknown URL")
            return resp

        mock_urlopen.side_effect = urlopen_side_effect

        tailwind_url = "https://cdn.tailwindcss.com"
        local_tailwind = self.manager.vendor_resource(tailwind_url)
        self.assertIsNotNone(local_tailwind)
        self.assertIn("_vendor/tailwindcss.js", local_tailwind)
        self.assertTrue((self.dist_vendor / "tailwindcss.js").exists())

        css_url = "https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap"
        local_css = self.manager.vendor_google_fonts(css_url)
        self.assertIsNotNone(local_css)
        self.assertIn("_vendor/fonts/", local_css)

        # Проверяем, что созданный локальный CSS не содержит fonts.gstatic.com
        fonts_dist_dir = self.dist_vendor / "fonts"
        css_files = list(fonts_dist_dir.glob("*.css"))
        self.assertEqual(len(css_files), 1)
        css_content = css_files[0].read_text(encoding="utf-8")
        self.assertNotIn("fonts.gstatic.com", css_content)
        self.assertIn(".woff2", css_content)

        # Проверяем наличие скачанных шрифтов woff2 в dist/_vendor/fonts
        woff2_files = list(fonts_dist_dir.glob("*.woff2"))
        self.assertEqual(len(woff2_files), 2)

    @patch("tools.publish.urllib.request.urlopen")
    def test_vendor_offline_network_failure(self, mock_urlopen):
        """Если сеть недоступна, возвращается None и ошибка логгируется (не падает)."""
        mock_urlopen.side_effect = URLError("Network unreachable")

        res = self.manager.vendor_google_fonts("https://fonts.googleapis.com/css2?family=Roboto")
        self.assertIsNone(res)
        self.assertEqual(len(self.manager.warnings), 1)
        self.assertIn("не удалось скачать", self.manager.warnings[0].lower())


class TestBoardUrlSecurity(unittest.TestCase):
    """Тесты защиты от XSS через поле url в карточках kind='board'."""

    def test_valid_board_urls(self):
        catalog = {
            "items": [
                {
                    "id": "board-1",
                    "slug": "board-1",
                    "title": "Доска Miro",
                    "kind": "board",
                    "url": "https://miro.com/app/board/uXjVO12345=",
                },
                {
                    "id": "board-2",
                    "slug": "board-2",
                    "title": "Доска Holst",
                    "kind": "board",
                    "url": "http://localhost:3000/boards/1",
                },
            ]
        }
        errors = validate_catalog(catalog)
        self.assertEqual(errors, [])

    def test_reject_javascript_and_data_urls(self):
        bad_urls = [
            "javascript:alert(document.domain)",
            "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
            "vbscript:msgbox(1)",
            "ftp://files.example.com",
            "//schemaless.com",
        ]
        for bad_url in bad_urls:
            catalog = {
                "items": [
                    {
                        "id": "bad-board",
                        "slug": "bad-board",
                        "title": "Вредоносная доска",
                        "kind": "board",
                        "url": bad_url,
                    }
                ]
            }
            errors = validate_catalog(catalog)
            self.assertTrue(
                any("url" in err.lower() or "недопустимый" in err.lower() for err in errors),
                f"URL '{bad_url}' должен быть отклонён валидатором!",
            )


class TestExtendedMetadataAndCovers(unittest.TestCase):
    """Тесты извлечения subtitle, автоподбора обложек и генерации topic_slug."""

    def test_extract_meta_subtitle_audio_and_tasks(self):
        html_with_audio_and_tasks = """
        <!DOCTYPE html><html><head><title>Словарный диктант 6 класс</title></head>
        <body>
            <h1>29 словарных слов</h1>
            <audio src="data:audio/mp3;base64,..."></audio>
        </body></html>
        """
        meta = extract_meta(html_with_audio_and_tasks, "6.html")
        self.assertIn("29", meta.get("subtitle", ""))
        self.assertTrue(
            "аудио" in meta.get("subtitle", "").lower()
            or "звук" in meta.get("subtitle", "").lower()
        )

    def test_extract_meta_fallback_subtitle(self):
        html_plain = "<html><head><title>Игра</title></head><body>Просто текст</body></html>"
        meta = extract_meta(html_plain, "plain.html")
        self.assertTrue(len(meta.get("subtitle", "")) > 0)

    def test_suggest_cover_keywords(self):
        self.assertEqual(suggest_cover("Словарный диктант", "Орфография"), "autumn")
        self.assertEqual(suggest_cover("Осенний урок", ""), "autumn")
        self.assertEqual(suggest_cover("Квест: Архитектура слова", ""), "quest")
        self.assertEqual(suggest_cover("Тренажёр ОГЭ", "Собеседование"), "exam")
        self.assertEqual(suggest_cover("Домашнее задание", "Лексикология и фразеология"), "alchemy")
        self.assertEqual(suggest_cover("Любая доска", "", kind="board"), "board")

    def test_suggest_cover_deterministic_hash(self):
        cover1 = suggest_cover("Обычная игра 1", "", kind="game", slug="game-1")
        cover2 = suggest_cover("Обычная игра 1", "", kind="game", slug="game-1")
        self.assertEqual(cover1, cover2)
        self.assertIn(cover1, ["library", "autumn", "quest", "exam", "alchemy"])

    def test_format_cover_src(self):
        self.assertEqual(format_cover_src("autumn"), "covers/autumn.png")
        self.assertEqual(format_cover_src("custom_123.webp"), "covers/custom_123.webp")
        self.assertEqual(format_cover_src("custom_456.PNG"), "covers/custom_456.PNG")

    def test_compute_topic_slug(self):
        self.assertEqual(
            compute_topic_slug("Лексикология и фразеология", 6),
            "leksikologiya-i-frazeologiya-6",
        )
        self.assertEqual(
            compute_topic_slug("Теория", None),
            "teoriya",
        )
        self.assertEqual(compute_topic_slug("", 6), "")


class TestPublishExtendedFlow(unittest.TestCase):
    """Тесты скрытых и архивных карточек при сборке dist/."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temp_dir.name)
        self.inbox = self.root_dir / "games_inbox"
        self.inbox.mkdir(parents=True)
        self.template = self.root_dir / "site_template"
        self.template.mkdir(parents=True)
        (self.template / "index.html").write_text("<!--CATALOG_DATA-->", encoding="utf-8")

        # Создаем 3 тестовых игры
        (self.inbox / "visible.html").write_text("<title>Видимая игра</title><body>OK</body>", encoding="utf-8")
        (self.inbox / "hidden.html").write_text("<title>Скрытая игра</title><body>Secret</body>", encoding="utf-8")
        (self.inbox / "archived.html").write_text("<title>Архивная игра</title><body>Old</body>", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_hidden_and_archived_filtering(self):
        catalog = {
            "items": [
                {
                    "id": "visible",
                    "slug": "visible",
                    "title": "Видимая игра",
                    "grade": 5,
                    "topic": "Тема 1",
                    "kind": "game",
                    "file": "visible.html",
                    "order": 1,
                    "hidden": False,
                    "archived": False,
                },
                {
                    "id": "hidden",
                    "slug": "hidden",
                    "title": "Скрытая игра",
                    "grade": 5,
                    "topic": "Тема 1",
                    "kind": "game",
                    "file": "hidden.html",
                    "order": 2,
                    "hidden": True,
                    "archived": False,
                },
                {
                    "id": "archived",
                    "slug": "archived",
                    "title": "Архивная игра",
                    "grade": 5,
                    "topic": "Тема 1",
                    "kind": "game",
                    "file": "archived.html",
                    "order": 3,
                    "hidden": False,
                    "archived": True,
                },
            ]
        }
        (self.root_dir / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")

        # Запускаем сборку
        exit_code = build_site(self.root_dir, vendor_timeout=5)
        self.assertEqual(exit_code, 0)

        dist_catalog_file = self.root_dir / "dist" / "catalog.json"
        self.assertTrue(dist_catalog_file.exists())
        dist_payload = json.loads(dist_catalog_file.read_text(encoding="utf-8"))
        dist_slugs = [item["slug"] for item in dist_payload["items"]]

        # 1. В dist/catalog.json должна быть ТОЛЬКО видимая игра
        self.assertIn("visible", dist_slugs)
        self.assertNotIn("hidden", dist_slugs)
        self.assertNotIn("archived", dist_slugs)

        # 2. dist/g/visible/index.html ДОЛЖНА собраться
        self.assertTrue((self.root_dir / "dist" / "g" / "visible" / "index.html").exists())

        # 3. dist/g/hidden/index.html ТОЖЕ ДОЛЖНА собраться (для прямой ссылки)
        self.assertTrue((self.root_dir / "dist" / "g" / "hidden" / "index.html").exists())

        # 4. dist/g/archived/index.html НЕ ДОЛЖНА собраться (в архиве)
        self.assertFalse((self.root_dir / "dist" / "g" / "archived" / "index.html").exists())

        # 5. Исходный файл в games_inbox/archived.html НЕ удален
        self.assertTrue((self.inbox / "archived.html").exists())

        # 6. Повторная синхронизация не воскрешает архивный файл как дубликат
        updated_cat, warnings = sync_catalog_with_inbox(
            catalog,
            {"archived.html": "<title>Архивная игра</title><body>Old</body>"}
        )
        self.assertEqual(len(updated_cat["items"]), 3)


class TestVendorManagerTimeout(unittest.TestCase):
    """Тест настраиваемого таймаута в VendorManager."""

    def test_custom_timeout(self):
        vm = VendorManager(Path(".cache"), Path(".dist_vendor"), timeout=7)
        self.assertEqual(vm.timeout, 7)


if __name__ == "__main__":
    unittest.main()
