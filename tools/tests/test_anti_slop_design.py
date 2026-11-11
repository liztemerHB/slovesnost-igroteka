"""Автотест-линтер студийного редизайна (Hallmark + Impeccable Anti-AI Slop Gates)."""

import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


class TestAntiSlopDesign(unittest.TestCase):
    """Проверка дизайн-системы, типографики, контраста, вёрстки и работы file://."""

    @classmethod
    def setUpClass(cls):
        cls.root_dir = Path(__file__).resolve().parent.parent.parent
        cls.tpl_dir = cls.root_dir / "site_template"
        cls.admin_ui_dir = cls.root_dir / "tools" / "admin_ui"
        cls.dist_dir = cls.root_dir / "dist"
        cls.chrome_path = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")

    def test_01_css_anti_slop_tokens_and_gates(self):
        """Проверка отсутствия штампов ИИ-дизайна в catalog.css и shell.js."""
        css = (self.tpl_dir / "catalog.css").read_text(encoding="utf-8")
        shell = (self.tpl_dir / "_shell" / "shell.js").read_text(encoding="utf-8")
        typo = (self.tpl_dir / "fonts" / "typography.css").read_text(encoding="utf-8")

        # Gate 61: запрет transition: all
        self.assertIsNone(
            re.search(r"transition\s*:\s*all\b", css, re.IGNORECASE),
            "В catalog.css запрещён 'transition: all'",
        )
        self.assertIsNone(
            re.search(r"transition\s*:\s*all\b", shell, re.IGNORECASE),
            "В shell.js запрещён 'transition: all'",
        )
        self.assertNotIn("dblclick", shell, "В shell.js запрещён скрытый жест dblclick")

        # Gate 29: запрет старой неоново-чёрной гаммы ИИ-шаблонов
        for banned_hex in ("#080d0b", "#2ee585", "#1df28c"):
            self.assertNotIn(banned_hex, css.lower(), f"Найден кислотно-тёмный ИИ-цвет {banned_hex}")

        # Gate 54 & 67: запрет капсовых меток (text-transform: uppercase)
        self.assertIsNone(
            re.search(r"text-transform\s*:\s*uppercase\b", css, re.IGNORECASE),
            "В catalog.css запрещён text-transform: uppercase (используем строчный/предложенческий регистр)",
        )

        # Gate 51: ровно 2 шрифтовых семейства (Literata + Golos Text), без Unbounded
        self.assertIn("Literata", typo)
        self.assertIn("Golos Text", typo)
        self.assertNotIn("Unbounded", css)

        # Обязательные признаки студийной вёрстки (Hallmark Floor Gates)
        required_tokens = [
            "--color-paper",
            "--color-ink",
            "--color-accent",
            "--font-display",
            "--font-body",
            ":focus-visible",
            "prefers-reduced-motion",
            "overflow-x: clip",
            "::selection",
            "tabular-nums",
            "text-wrap: balance",
        ]
        for tok in required_tokens:
            self.assertIn(tok, css, f"В catalog.css отсутствует обязательный токен/правило: {tok}")

    def test_02_russian_editorial_copy_without_middle_dots(self):
        """Gate 63: отсутствие искусственных разделителей • и · в catalog.json и шаблоне витрины."""
        catalog_raw = (self.root_dir / "catalog.json").read_text(encoding="utf-8")
        index_raw = (self.tpl_dir / "index.html").read_text(encoding="utf-8")

        for dot_char in ("•", "·"):
            self.assertNotIn(dot_char, catalog_raw, f"В catalog.json найден искусственный буллит '{dot_char}'")
            self.assertNotIn(dot_char, index_raw, f"В site_template/index.html найден буллит '{dot_char}'")

        # Убеждаемся, что все 4 базовых слага остались 100% неизменными
        catalog = json.loads(catalog_raw)
        slugs = [it["slug"] for it in catalog["items"]]
        expected_slugs = [
            "slovarnyy-diktant-6-klass-osenniy-trenazhyor",
            "kvest-arkhitektura-slova-proverka-domashnego-zadaniya",
            "trenazhyor-itogovoe-sobesedovanie-oge-str-323-329",
            "domashnee-zadanie-kvest-leksikologiya-i-frazeologiya",
        ]
        for s in expected_slugs:
            self.assertIn(s, slugs)

    def test_03_headless_chrome_file_protocol_and_redirect(self):
        """Проверка работы dist/index.html по file:// и авто-редиректа из site_template/index.html."""
        if not self.chrome_path.exists():
            self.skipTest("Chrome не найден")

        dist_index = self.dist_dir / "index.html"
        self.assertTrue(dist_index.exists(), "dist/index.html должен быть собран")

        # 1. Прямое открытие dist/index.html по file:// рендерит карточки и светлую бумажную тему
        cmd_dist = [
            str(self.chrome_path),
            "--headless=new",
            "--disable-gpu",
            "--virtual-time-budget=2000",
            "--dump-dom",
            dist_index.as_uri(),
        ]
        res_dist = subprocess.run(
            cmd_dist,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        self.assertIn('id="card-slovarnyy-diktant-6-klass-osenniy-trenazhyor"', res_dist.stdout)
        self.assertNotIn("Найдено: 0 материалов", res_dist.stdout)

        # 2. Открытие несобранного site_template/index.html по file:// перекидывает на dist/index.html
        tpl_index = self.tpl_dir / "index.html"
        cmd_tpl = [
            str(self.chrome_path),
            "--headless=new",
            "--disable-gpu",
            "--virtual-time-budget=3000",
            "--dump-dom",
            tpl_index.as_uri(),
        ]
        res_tpl = subprocess.run(
            cmd_tpl,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        self.assertIn(
            'id="card-slovarnyy-diktant-6-klass-osenniy-trenazhyor"',
            res_tpl.stdout,
            "Авто-редирект из site_template/index.html не сработал!",
        )

    def test_04_responsive_zero_horizontal_overflow(self):
        """Проверка отсутствия горизонтального переполнения и контраста в реальном браузере."""
        if not self.chrome_path.exists():
            self.skipTest("Chrome не найден")

        # Создаём мини-харнес с iframe на 6 эталонных ширинах из Hallmark Gate 44c
        dist_uri = (self.dist_dir / "index.html").as_uri()
        with tempfile.TemporaryDirectory() as tmp:
            harness = Path(tmp) / "audit_viewports.html"
            harness.write_text(
                f"""<!DOCTYPE html>
<html><body>
<div id="audit-out" data-ready="0"></div>
<script>
(async function() {{
  const widths = [320, 375, 768, 1280, 1440, 1920];
  const failures = [];
  for (const w of widths) {{
    const ifr = document.createElement('iframe');
    ifr.style.width = w + 'px';
    ifr.style.height = '800px';
    ifr.style.border = '0';
    document.body.appendChild(ifr);
    await new Promise((resolve) => {{
      ifr.onload = () => setTimeout(resolve, 180);
      ifr.src = {json.dumps(dist_uri)};
    }});
    const doc = ifr.contentDocument;
    const win = ifr.contentWindow;
    const sw = doc.documentElement.scrollWidth;
    const cw = doc.documentElement.clientWidth;
    if (sw > cw + 1) {{
      failures.push('overflow@' + w + ':' + sw + '>' + cw);
    }}
    if (w === 1280) {{
      const bg = win.getComputedStyle(doc.body).backgroundColor;
      if (bg === 'rgb(8, 13, 11)') {{
        failures.push('dark-ai-bg-detected');
      }}
      const cards = doc.querySelectorAll('.game-card');
      if (cards.length < 4) {{
        failures.push('missing-cards:' + cards.length);
      }}
    }}
    document.body.removeChild(ifr);
  }}
  const out = document.getElementById('audit-out');
  out.setAttribute('data-ready', '1');
  out.setAttribute('data-status', failures.length === 0 ? 'passed' : 'failed');
  out.textContent = failures.join('; ') || 'ALL_VIEWPORTS_CLEAN';
}})();
</script>
</body></html>""",
                encoding="utf-8",
            )
            res = subprocess.run(
                [
                    str(self.chrome_path),
                    "--headless=new",
                    "--disable-gpu",
                    "--allow-file-access-from-files",
                    "--virtual-time-budget=6000",
                    "--dump-dom",
                    harness.as_uri(),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=45,
            )
            self.assertIn(
                'data-status="passed"',
                res.stdout,
                f"Аудит адаптивности провален:\n{res.stdout}",
            )

    def test_05_admin_ui_anti_slop_and_workbench_contracts(self):
        """Проверка отсутствия ИИ-штампов и наличия 4 состояний в Мастерской /admin."""
        admin_html = (self.admin_ui_dir / "admin.html").read_text(encoding="utf-8")
        admin_css = (self.admin_ui_dir / "admin.css").read_text(encoding="utf-8")
        admin_js = (self.admin_ui_dir / "admin.js").read_text(encoding="utf-8")

        self.assertIsNone(
            re.search(r"transition\s*:\s*all\b", admin_css, re.IGNORECASE),
            "В admin.css запрещён 'transition: all'",
        )
        self.assertIsNone(
            re.search(r"text-transform\s*:\s*uppercase\b", admin_css, re.IGNORECASE),
            "В admin.css запрещён text-transform: uppercase",
        )
        for banned_hex in ("#080d0b", "#2ee585", "#1df28c"):
            self.assertNotIn(banned_hex, admin_css.lower())
        self.assertNotIn("Unbounded", admin_css)

        for dot_char in ("•", "·"):
            self.assertNotIn(dot_char, admin_html, f"В admin.html найден буллит '{dot_char}'")

        for tok in ("--color-paper", "--color-ink", ":focus-visible", "prefers-reduced-motion", "overflow-x: clip", "tabular-nums"):
            self.assertIn(tok, admin_css, f"В admin.css отсутствует: {tok}")

        self.assertIn("X-Requested-With", admin_js)
        self.assertIn("TutorAdmin", admin_js)
        self.assertIn("public_catalog_url", admin_js)
        self.assertIn("storage-mode-badge", admin_html)


if __name__ == "__main__":
    unittest.main()
