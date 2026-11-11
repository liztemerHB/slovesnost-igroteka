"""Тесты фронтенда каталога и логики фильтрации."""

import os
import re
import subprocess
import unittest
from pathlib import Path


class TestFrontend(unittest.TestCase):
    """Проверка шаблона каталога, фильтрации и браузерных тестов."""

    @classmethod
    def setUpClass(cls):
        cls.root_dir = Path(__file__).resolve().parent.parent.parent
        cls.site_template_dir = cls.root_dir / "site_template"
        cls.tests_dir = cls.root_dir / "tools" / "tests"
        cls.chrome_path = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")

    def test_filter_runner_in_headless_chrome(self):
        """Запуск браузерных тестов test_filter.html через Chrome headless."""
        if not self.chrome_path.exists():
            self.skipTest(f"Chrome не найден по пути: {self.chrome_path}")

        test_html = self.tests_dir / "test_filter.html"
        self.assertTrue(test_html.exists(), f"Файл {test_html} должен существовать")

        file_url = test_html.as_uri()
        cmd = [
            str(self.chrome_path),
            "--headless=new",
            "--disable-gpu",
            "--dump-dom",
            file_url,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
            )
        except subprocess.TimeoutExpired:
            self.fail("Таймаут выполнения headless Chrome (60с)")

        stdout = result.stdout
        self.assertIn(
            'data-status="passed"',
            stdout,
            f"Тесты в браузере не прошли! Вывод DOM:\n{stdout[:2000]}",
        )
        self.assertNotIn('data-status="failed"', stdout)

    def test_site_template_index_html_contracts(self):
        """Проверка контракта site_template/index.html: плейсхолдер и отсутствие внешних CDN."""
        index_html_path = self.site_template_dir / "index.html"
        self.assertTrue(
            index_html_path.exists(),
            f"Шаблон каталога {index_html_path} должен существовать",
        )

        content = index_html_path.read_text(encoding="utf-8")

        # Ровно один плейсхолдер <!--CATALOG_DATA-->
        placeholder_count = content.count("<!--CATALOG_DATA-->")
        self.assertEqual(
            placeholder_count,
            1,
            f"Ожидался ровно один <!--CATALOG_DATA-->, найдено {placeholder_count}",
        )

        # Никаких внешних http/https ссылок в src/href (полная офлайн-работа)
        external_urls = re.findall(r'(?:src|href)\s*=\s*["\'](https?://[^"\']+)["\']', content, re.IGNORECASE)
        self.assertEqual(
            external_urls,
            [],
            f"Найдены внешние ссылки в src/href: {external_urls}. Разрешены только локальные/относительные пути.",
        )

        # Проверка мета-тега viewport для mobile-first
        self.assertIn('name="viewport"', content)
        self.assertIn('width=device-width', content)

    def test_catalog_css_contracts(self):
        """Проверка catalog.css: файл существует и не содержит внешних url(...)."""
        css_path = self.site_template_dir / "catalog.css"
        self.assertTrue(css_path.exists(), f"Файл {css_path} должен существовать")
        css_content = css_path.read_text(encoding="utf-8")
        external_css_urls = re.findall(r'url\s*\(\s*["\']?(https?://[^"\'\)]+)', css_content, re.IGNORECASE)
        self.assertEqual(
            external_css_urls,
            [],
            f"Найдены внешние ресурсы в CSS: {external_css_urls}",
        )

    def test_filter_js_exists_and_contains_contract(self):
        """Проверка наличия и сигнатур site_template/filter.js."""
        filter_js_path = self.site_template_dir / "filter.js"
        self.assertTrue(filter_js_path.exists(), f"Файл {filter_js_path} должен существовать")
        content = filter_js_path.read_text(encoding="utf-8")
        self.assertIn("CatalogFilter", content)
        self.assertIn("normalize", content)
        self.assertIn("filterItems", content)
        self.assertIn("collectGrades", content)
        self.assertIn("slugifyTopic", content)
        self.assertIn("groupByTopics", content)
        self.assertIn("parseRouteHash", content)

    def test_qr_js_exists_and_contains_contract(self):
        """Проверка наличия и сигнатур site_template/qr.js (0 внешних вызовов)."""
        qr_js_path = self.site_template_dir / "qr.js"
        self.assertTrue(qr_js_path.exists(), f"Файл {qr_js_path} должен существовать")
        content = qr_js_path.read_text(encoding="utf-8")
        self.assertIn("TutorQR", content)
        self.assertIn("renderSVG", content)
        self.assertIn("getMatrix", content)
        self.assertNotIn("eval(", content)
        self.assertNotIn("document.createElement", content)  # чистый расчёт без привязки к DOM

    def test_admin_ui_files_and_contracts(self):
        """Проверка файлов веб-админки tools/admin_ui/: отсутствие внешних CDN."""
        admin_ui_dir = self.root_dir / "tools" / "admin_ui"
        self.assertTrue(admin_ui_dir.exists(), f"Папка {admin_ui_dir} должна существовать")

        admin_html = admin_ui_dir / "admin.html"
        admin_css = admin_ui_dir / "admin.css"
        admin_js = admin_ui_dir / "admin.js"

        self.assertTrue(admin_html.exists(), f"Файл {admin_html} должен существовать")
        self.assertTrue(admin_css.exists(), f"Файл {admin_css} должен существовать")
        self.assertTrue(admin_js.exists(), f"Файл {admin_js} должен существовать")

        html_content = admin_html.read_text(encoding="utf-8")
        ext_html = re.findall(r'(?:src|href)\s*=\s*["\'](https?://[^"\']+)["\']', html_content, re.IGNORECASE)
        self.assertEqual(ext_html, [], f"Найдены внешние ссылки в admin.html: {ext_html}")

        css_content = admin_css.read_text(encoding="utf-8")
        ext_css = re.findall(r'url\s*\(\s*["\']?(https?://[^"\'\)]+)', css_content, re.IGNORECASE)
        self.assertEqual(ext_css, [], f"Найдены внешние ссылки в admin.css: {ext_css}")

        js_content = admin_js.read_text(encoding="utf-8")
        self.assertIn("X-Requested-With", js_content)
        self.assertIn("TutorAdmin", js_content)

    def test_shell_script_exists_and_contains_contract(self):
        """Проверка наличия и сигнатуры site_template/_shell/shell.js."""
        shell_js_path = self.site_template_dir / "_shell" / "shell.js"
        self.assertTrue(
            shell_js_path.exists(),
            f"Скрипт оболочки {shell_js_path} должен существовать",
        )

        content = shell_js_path.read_text(encoding="utf-8")
        self.assertIn("TutorShell", content)
        self.assertIn("sendResult", content)
        self.assertIn("data-tutor-shell", content)


if __name__ == "__main__":
    unittest.main()
