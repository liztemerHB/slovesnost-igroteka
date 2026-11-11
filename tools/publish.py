#!/usr/bin/env python3
"""Сборщик статического каталога игр Tutor Games (tools/publish.py).

Собирает игры из games_inbox/ и шаблона site_template/ в готовую к выкладке папку dist/.
Обеспечивает вендоринг внешних CDN, вставку shell.js, валидацию и стабильность слагов.
"""

import datetime
import hashlib
import html
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# Упрощенная транслитерация ГОСТ 7.79-2000 (система Б)
TRANSLIT_MAP = {
    "а": "a",
    "б": "b",
    "в": "v",
    "г": "g",
    "д": "d",
    "е": "e",
    "ё": "yo",
    "ж": "zh",
    "з": "z",
    "и": "i",
    "й": "y",
    "к": "k",
    "л": "l",
    "м": "m",
    "н": "n",
    "о": "o",
    "п": "p",
    "р": "r",
    "с": "s",
    "т": "t",
    "у": "u",
    "ф": "f",
    "х": "kh",
    "ц": "ts",
    "ч": "ch",
    "ш": "sh",
    "щ": "shch",
    "ъ": "",
    "ы": "y",
    "ь": "",
    "э": "e",
    "ю": "yu",
    "я": "ya",
}

SLUG_REGEX = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def slugify(text: str) -> str:
    """Генерация слага из текста по упрощенной системе ГОСТ 7.79-2000 (сист. Б)."""
    text = text.lower()
    chars = []
    for ch in text:
        if ch in TRANSLIT_MAP:
            chars.append(TRANSLIT_MAP[ch])
        elif ch.isalnum() and ch.isascii():
            chars.append(ch)
        else:
            chars.append("-")
    slug = "".join(chars)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug if slug else "game"


def compute_topic_slug(topic: str, grade: int | None = None) -> str:
    """Генерация слага темы с учетом класса: slugify(f'{topic}-{grade}' if grade else topic)."""
    topic_str = str(topic or "").strip()
    if not topic_str:
        return ""
    target = f"{topic_str}-{grade}" if grade is not None else topic_str
    return slugify(target)


def suggest_cover(title: str = "", topic: str = "", kind: str = "game", slug: str = "") -> str:
    """Умный детерминированный подбор ключа обложки по типу, ключевым словам или хэшу."""
    if kind == "board":
        return "board"
    text = f"{title} {topic}".lower()
    if re.search(r"диктант|осень", text):
        return "autumn"
    if re.search(r"квест", text):
        return "quest"
    if re.search(r"огэ|егэ|собеседование|экзамен", text):
        return "exam"
    if re.search(r"лексик|фразеолог", text):
        return "alchemy"
    keys = ["library", "autumn", "quest", "exam", "alchemy"]
    s = slug or (slugify(title) if title else "game")
    h = int(hashlib.sha1(s.encode("utf-8")).hexdigest(), 16)
    return keys[h % len(keys)]


def format_cover_src(cover: str) -> str:
    """Форматирование пути обложки для витрины dist/covers/..."""
    if not cover:
        return "covers/library.png"
    lower = cover.lower()
    if lower.endswith((".png", ".jpg", ".jpeg", ".webp")):
        return f"covers/{cover}"
    return f"covers/{cover}.png"


def extract_meta(html_content: str, filename: str) -> dict:
    """Извлечение названия, класса, темы, живого подзаголовка и обложки из сырого HTML."""
    title_match = re.search(r"<title>(.*?)</title>", html_content, re.IGNORECASE | re.DOTALL)
    if title_match:
        raw_title = html.unescape(title_match.group(1)).strip()
        title = raw_title if raw_title else filename
    else:
        title = filename

    grade_match = re.search(r"(\d{1,2})\s*класс", title, re.IGNORECASE)
    grade = int(grade_match.group(1)) if grade_match else None

    has_audio = bool(re.search(r"<audio\b|\bnew\s+Audio\b|data:audio", html_content, re.IGNORECASE))

    count_match = re.search(
        r"(\d+)\s*(словарн\w*\s+слов\w*|слов\w*|задани[йяе]|вопрос(?:ов|а)?|раунд(?:ов|а)?)",
        html_content,
        re.IGNORECASE,
    )

    if count_match:
        num = count_match.group(1)
        word_form = count_match.group(2).lower()
        if "слов" in word_form:
            if has_audio:
                subtitle = f"{num} словарных слов, аудио-диктор"
            else:
                subtitle = f"{num} слов"
        elif "задан" in word_form:
            subtitle = f"{num} заданий, со звуком" if has_audio else f"{num} заданий"
        elif "вопрос" in word_form:
            subtitle = f"{num} вопросов, со звуком" if has_audio else f"{num} вопросов"
        elif "раунд" in word_form:
            subtitle = f"{num} раунда, со звуком" if has_audio else f"{num} раундов"
        else:
            subtitle = f"{num} заданий"
    elif has_audio:
        subtitle = "Интерактивный тренажёр, аудио-диктор"
    elif re.search(r"квест", title, re.IGNORECASE):
        subtitle = "Интерактивный квест-тренажёр"
    elif re.search(r"огэ|егэ|собеседование|экзамен", title, re.IGNORECASE):
        subtitle = "Практикум устной речи ОГЭ"
    else:
        subtitle = "Интерактивный тренажёр"

    suggested_cov = suggest_cover(title=title, topic="", kind="game", slug=slugify(title))

    return {
        "title": title,
        "grade": grade,
        "topic": "",
        "subtitle": subtitle,
        "suggested_cover": suggested_cov,
    }


def _check_id(item_id: str, seen_ids: set, idx: int) -> list[str]:
    """Проверка идентификатора элемента."""
    if not item_id:
        return [f"Элемент #{idx}: пустое поле id"]
    if item_id in seen_ids:
        return [f"Элемент #{idx}: дубликат id '{item_id}'"]
    seen_ids.add(item_id)
    return []


def _check_slug(slug: str, seen_slugs: set, idx: int) -> list[str]:
    """Проверка слага элемента."""
    if not slug or not SLUG_REGEX.match(slug):
        return [f"Элемент #{idx}: неверный slug '{slug}' (ожидается ^[a-z0-9]+(-[a-z0-9]+)*$)"]
    if slug in seen_slugs:
        return [f"Элемент #{idx}: дубликат slug '{slug}'"]
    seen_slugs.add(slug)
    return []


def _check_kind(kind: str, item: dict, idx: int) -> list[str]:
    """Проверка типа элемента (game / board) и наличия целевого ресурса."""
    if kind == "game":
        return [] if item.get("file") else [f"Элемент #{idx}: для kind='game' обязательно поле file"]
    if kind == "board":
        url = str(item.get("url") or "").strip()
        if not url:
            return [f"Элемент #{idx}: для kind='board' обязательно поле url"]
        if not re.match(r"^https?://\S+$", url, re.IGNORECASE):
            return [f"Элемент #{idx}: недопустимый url '{url}' для kind='board' (ожидается ^https?://\\S+$)"]
        return []
    return [f"Элемент #{idx}: kind должен быть 'game' или 'board', получено '{kind}'"]


def _check_details(item: dict, idx: int) -> list[str]:
    """Проверка title, grade и tags элемента."""
    errors = []
    title = str(item.get("title") or "").strip()
    if not title:
        errors.append(f"Элемент #{idx}: пустое поле title")

    grade = item.get("grade")
    if grade is not None and not isinstance(grade, int):
        errors.append(f"Элемент #{idx}: grade должен быть int или null")

    if "tags" in item and not isinstance(item["tags"], list):
        errors.append(f"Элемент #{idx}: tags должен быть списком")

    return errors


def _validate_item(item: dict, idx: int, seen_ids: set, seen_slugs: set) -> list[str]:
    """Валидация отдельного элемента каталога."""
    if not isinstance(item, dict):
        return [f"Элемент #{idx} должен быть объектом (dict)"]

    errors = []
    errors.extend(_check_id(str(item.get("id") or "").strip(), seen_ids, idx))
    errors.extend(_check_slug(str(item.get("slug") or "").strip(), seen_slugs, idx))
    errors.extend(_check_kind(item.get("kind"), item, idx))
    errors.extend(_check_details(item, idx))
    return errors


def validate_catalog(catalog_data: dict) -> list[str]:
    """Проверка структуры и валидности catalog.json."""
    if not isinstance(catalog_data, dict) or "items" not in catalog_data:
        return ["Корневой объект catalog.json должен содержать список 'items'"]

    items = catalog_data.get("items")
    if not isinstance(items, list):
        return ["Поле 'items' должно быть списком"]

    seen_ids = set()
    seen_slugs = set()
    errors = []
    for idx, item in enumerate(items):
        errors.extend(_validate_item(item, idx, seen_ids, seen_slugs))
    return errors


def sync_catalog_with_inbox(catalog_data: dict, inbox_files: dict[str, str]) -> tuple[dict, list[str]]:
    """Синхронизация catalog.json с папкой games_inbox. Дописывает авто-черновики."""
    items = list(catalog_data.get("items", []))
    warnings = []

    existing_slugs = {item.get("slug") for item in items if item.get("slug")}
    registered_files = set()
    for item in items:
        f = item.get("file")
        if f:
            registered_files.add(Path(f).name)

    for filename, content in sorted(inbox_files.items()):
        file_basename = Path(filename).name
        if file_basename in registered_files:
            continue

        meta = extract_meta(content, file_basename)
        base_slug = slugify(meta["title"])
        slug = base_slug
        counter = 2
        while slug in existing_slugs:
            slug = f"{base_slug}-{counter}"
            counter += 1

        existing_slugs.add(slug)
        registered_files.add(file_basename)

        new_item = {
            "id": slug,
            "slug": slug,
            "title": meta["title"],
            "grade": meta["grade"],
            "topic": meta["topic"],
            "subtitle": meta.get("subtitle", "Интерактивный тренажёр"),
            "cover": meta.get("suggested_cover") or suggest_cover(meta["title"], meta["topic"], "game", slug),
            "kind": "game",
            "file": file_basename,
            "tags": [],
            "order": len(items) + 1,
            "hidden": False,
            "archived": False,
        }
        items.append(new_item)
        warnings.append(
            f"[DRAFT] Добавлен черновик: '{file_basename}' -> slug '{slug}' (класс: {meta['grade']})"
        )

    updated_catalog = dict(catalog_data)
    updated_catalog["items"] = items
    return updated_catalog, warnings


def inject_shell(html_content: str, slug: str, shell_version: str) -> str:
    """Вставка скрипта оболочки shell.js перед </body> или в конец (идемпотентно)."""
    script_tag = (
        f'<script defer src="../../_shell/shell.js?v={shell_version}" '
        f'data-slug="{slug}" data-tutor-shell></script>'
    )
    if "data-tutor-shell" in html_content:
        pattern = r"<script[^>]*data-tutor-shell[^>]*>.*?</script>|<script[^>]*data-tutor-shell[^>]*>"
        return re.sub(pattern, script_tag, html_content, flags=re.IGNORECASE | re.DOTALL)

    body_matches = list(re.finditer(r"</body>", html_content, re.IGNORECASE))
    if body_matches:
        last_body = body_matches[-1]
        pos = last_body.start()
        return html_content[:pos] + script_tag + html_content[pos:]
    return html_content + script_tag


def embed_catalog(template_html: str, catalog_payload: dict) -> str:
    """Встраивание catalog.json в шаблон каталога с экранированием '</'."""
    json_str = json.dumps(catalog_payload, ensure_ascii=False, indent=2).replace("</", r"<\/").replace("-->", r"--\>")
    tag = f'<script type="application/json" id="catalog-data">\n{json_str}\n</script>'
    return template_html.replace("<!--CATALOG_DATA-->", tag)


def build_catalog_payload(
    catalog_data: dict,
    generated_iso: str | None = None,
    include_hidden: bool = False,
    include_archived: bool = False,
) -> dict:
    """Построение итогового объекта каталога для dist/catalog.json и index.html."""
    iso_time = generated_iso or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    raw_items = catalog_data.get("items", [])
    indexed_items = []
    for idx, item in enumerate(raw_items):
        is_archived = bool(item.get("archived", False))
        is_hidden = bool(item.get("hidden", False))
        if is_archived and not include_archived:
            continue
        if is_hidden and not include_hidden:
            continue
        order = item.get("order")
        if order is None or not isinstance(order, int):
            order = idx + 1
        indexed_items.append((order, idx, item))

    indexed_items.sort(key=lambda t: (t[0], str(t[2].get("title", ""))))

    items = []
    for order, idx, item in indexed_items:
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
        items.append({
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
            "order": order,
            "hidden": bool(item.get("hidden", False)),
            "archived": bool(item.get("archived", False)),
            "href": href,
        })
    return {
        "generated": iso_time,
        "items": items,
    }


def _clean_preconnects(html_content: str) -> str:
    """Удаление тегов preconnect к внешним шрифтам Google."""
    res = re.sub(
        r'<link\s+[^>]*rel=["\']preconnect["\'][^>]*href=["\']https?://(?:fonts\.googleapis\.com|fonts\.gstatic\.com)[^"\']*["\'][^>]*>\s*',
        "",
        html_content,
        flags=re.IGNORECASE,
    )
    return re.sub(
        r'<link\s+[^>]*href=["\']https?://(?:fonts\.googleapis\.com|fonts\.gstatic\.com)[^"\']*["\'][^>]*rel=["\']preconnect["\'][^>]*>\s*',
        "",
        res,
        flags=re.IGNORECASE,
    )


def _clean_failed_fonts(html_content: str, failed_fonts: set[str]) -> str:
    """Удаление link-тегов шрифтов, скачивание которых завершилось ошибкой."""
    cleaned = html_content
    for failed_url in failed_fonts:
        escaped_url = re.escape(failed_url)
        cleaned = re.sub(
            rf'<link\s+[^>]*href=["\']{escaped_url}["\'][^>]*>\s*',
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
    return cleaned


def _rewrite_tag_urls(
    html_content: str,
    pattern: str,
    vendor_map: dict[str, str],
    warnings: list[str],
    tag_name: str,
) -> str:
    """Замена CDN-ссылок в тегах src/href на локальные пути с фиксацией неизвестных URL."""
    def replacer(match):
        prefix, url, suffix = match.group(1), match.group(2), match.group(3)
        if url in vendor_map:
            return f"{prefix}{vendor_map[url]}{suffix}"
        if url.startswith("http://") or url.startswith("https://"):
            warnings.append(f"Неизвестный внешний URL в {tag_name}: {url}")
        return match.group(0)

    return re.sub(pattern, replacer, html_content, flags=re.IGNORECASE)


def rewrite_cdn(
    html_content: str,
    vendor_map: dict[str, str],
    failed_fonts: set[str] | None = None,
) -> tuple[str, list[str]]:
    """Переписывание CDN-ссылок на локальные вендорные пути и удаление внешних preconnect."""
    warnings = []
    cleaned_html = _clean_preconnects(html_content)
    if failed_fonts:
        cleaned_html = _clean_failed_fonts(cleaned_html, failed_fonts)

    script_pattern = r'(<script\s+[^>]*src=["\'])(https?://[^"\']+)(["\'][^>]*>)'
    cleaned_html = _rewrite_tag_urls(cleaned_html, script_pattern, vendor_map, warnings, "script src")

    link_pattern = r'(<link\s+[^>]*href=["\'])(https?://[^"\']+)(["\'][^>]*>)'
    cleaned_html = _rewrite_tag_urls(cleaned_html, link_pattern, vendor_map, warnings, "link href")

    return cleaned_html, warnings


class VendorManager:
    """Управление скачиванием, кэшированием и вендорингом внешних CDN ресурсов."""

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    def __init__(self, cache_dir: Path, dist_vendor_dir: Path, timeout: int = 15):
        self.cache_dir = Path(cache_dir)
        self.dist_vendor_dir = Path(dist_vendor_dir)
        self.timeout = timeout
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.dist_vendor_dir.mkdir(parents=True, exist_ok=True)
        self.warnings: list[str] = []
        self.failed_urls: set[str] = set()

    def _fetch_bytes(self, url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": self.USER_AGENT})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read()

    @staticmethod
    def _hash8(data: bytes) -> str:
        return hashlib.sha1(data).hexdigest()[:8]

    def vendor_resource(self, url: str) -> str | None:
        """Вендоринг одиночного JS/CSS ресурса (например, tailwindcss)."""
        try:
            if "tailwindcss.com" in url:
                cache_file = self.cache_dir / "tailwindcss.js"
                dist_file = self.dist_vendor_dir / "tailwindcss.js"
                if cache_file.exists():
                    data = cache_file.read_bytes()
                else:
                    data = self._fetch_bytes(url)
                    cache_file.write_bytes(data)
                dist_file.write_bytes(data)
                v = self._hash8(data)
                return f"../../_vendor/tailwindcss.js?v={v}"
        except Exception as e:
            self.warnings.append(f"Не удалось скачать {url}: {e}")
            self.failed_urls.add(url)
            return None
        return None

    def vendor_google_fonts(self, css_url: str) -> str | None:
        """Вендоринг Google Fonts в глубину: CSS + все WOFF2 шрифты."""
        try:
            url_hash = hashlib.sha1(css_url.encode("utf-8")).hexdigest()[:10]
            fonts_cache_dir = self.cache_dir / "fonts"
            fonts_dist_dir = self.dist_vendor_dir / "fonts"
            fonts_cache_dir.mkdir(parents=True, exist_ok=True)
            fonts_dist_dir.mkdir(parents=True, exist_ok=True)

            cache_css_file = fonts_cache_dir / f"fonts_{url_hash}.css"
            if cache_css_file.exists():
                css_text = cache_css_file.read_text(encoding="utf-8")
            else:
                css_bytes = self._fetch_bytes(css_url)
                css_text = css_bytes.decode("utf-8", errors="replace")
                cache_css_file.write_text(css_text, encoding="utf-8")

            font_urls = re.findall(
                r"url\s*\(\s*['\"]?(https://fonts\.gstatic\.com/[^'\"\)]+)['\"]?\s*\)",
                css_text,
            )
            rewritten_css = css_text

            for font_url in set(font_urls):
                font_filename = Path(urllib.parse.urlparse(font_url).path).name
                if not font_filename or not font_filename.endswith(".woff2"):
                    font_filename = f"{self._hash8(font_url.encode('utf-8'))}.woff2"

                cached_font = fonts_cache_dir / font_filename
                dist_font = fonts_dist_dir / font_filename

                if cached_font.exists():
                    font_bytes = cached_font.read_bytes()
                else:
                    font_bytes = self._fetch_bytes(font_url)
                    cached_font.write_bytes(font_bytes)

                dist_font.write_bytes(font_bytes)
                rewritten_css = rewritten_css.replace(font_url, f"./{font_filename}")

            dist_css_file = fonts_dist_dir / f"fonts_{url_hash}.css"
            dist_css_bytes = rewritten_css.encode("utf-8")
            dist_css_file.write_bytes(dist_css_bytes)

            v = self._hash8(dist_css_bytes)
            return f"../../_vendor/fonts/fonts_{url_hash}.css?v={v}"
        except Exception as e:
            self.warnings.append(f"Не удалось скачать шрифт {css_url}: {e}")
            self.failed_urls.add(css_url)
            return None


def _safe_rmtree(path: Path, retries: int = 5, delay: float = 0.1) -> None:
    """Безопасное удаление директории на Windows с повторными попытками при блокировке."""
    for i in range(retries):
        try:
            shutil.rmtree(path)
            return
        except (PermissionError, OSError):
            time.sleep(delay)
    shutil.rmtree(path, ignore_errors=True)


def publish(root_dir: Path | None = None, vendor_timeout: int = 15) -> int:
    """Основной процесс сборки каталога."""
    if root_dir is None:
        root_dir = Path(__file__).resolve().parent.parent

    root_dir = Path(root_dir)
    games_inbox = root_dir / "games_inbox"
    catalog_path = root_dir / "catalog.json"
    site_template = root_dir / "site_template"
    dist_dir = root_dir / "dist"
    cache_dir = root_dir / "tools" / ".vendor_cache"

    print("=== Сборка каталога Tutor Games ===")
    print(f"Корень проекта: {root_dir}")

    # 1. Чтение catalog.json
    if catalog_path.exists():
        try:
            catalog_data = json.loads(catalog_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[ОШИБКА] Не удалось прочитать catalog.json: {e}", file=sys.stderr)
            return 1
    else:
        catalog_data = {"items": []}

    # 2. Сканирование games_inbox
    inbox_files = {}
    if games_inbox.exists():
        for p in games_inbox.glob("*.html"):
            inbox_files[p.name] = p.read_text(encoding="utf-8", errors="replace")

    catalog_data, draft_warnings = sync_catalog_with_inbox(catalog_data, inbox_files)
    for dw in draft_warnings:
        print(dw)

    if draft_warnings or not catalog_path.exists():
        catalog_path.write_text(
            json.dumps(catalog_data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"[OK] Обновлен файл catalog.json ({len(catalog_data.get('items', []))} записей)")

    # 3. Валидация каталога
    errors = validate_catalog(catalog_data)
    if errors:
        print(f"[ОШИБКА ВАЛИДАЦИИ] Найдено {len(errors)} ошибок:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    # 4. Подготовка dist/
    if dist_dir.exists():
        for item in dist_dir.iterdir():
            if item.is_dir():
                _safe_rmtree(item)
            else:
                try:
                    item.unlink()
                except (PermissionError, OSError):
                    time.sleep(0.05)
                    item.unlink(missing_ok=True)
    else:
        dist_dir.mkdir(parents=True, exist_ok=True)

    # Копирование site_template в dist (игнорируя скрытые и архивные файлы)
    template_ignore = shutil.ignore_patterns("*archive*", "v2_*", ".*", "*.bak")
    if site_template.exists():
        for item in site_template.iterdir():
            if item.name.startswith(".") or "archive" in item.name.lower() or item.name.startswith("v2_"):
                continue
            dest = dist_dir / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True, ignore=template_ignore)
            else:
                shutil.copy2(item, dest)

    # 5. Определение версии shell.js
    shell_js_source = site_template / "_shell" / "shell.js"
    if shell_js_source.exists():
        shell_v = hashlib.sha1(shell_js_source.read_bytes()).hexdigest()[:8]
    else:
        shell_v = "1"

    # 6. Вендоринг CDN
    dist_vendor = dist_dir / "_vendor"
    vendor_mgr = VendorManager(cache_dir, dist_vendor, timeout=vendor_timeout)
    vendor_map = {}

    all_warnings = list(draft_warnings)
    for item in catalog_data.get("items", []):
        if item.get("kind") != "game":
            continue
        fname = item.get("file")
        if not fname or fname not in inbox_files:
            continue
        content = inbox_files[fname]

        if "cdn.tailwindcss.com" in content:
            tw_url = "https://cdn.tailwindcss.com"
            if tw_url not in vendor_map:
                local_tw = vendor_mgr.vendor_resource(tw_url)
                if local_tw:
                    vendor_map[tw_url] = local_tw

        gf_links = re.findall(
            r'<link\s+[^>]*href=["\'](https://fonts\.googleapis\.com/[^"\']+)["\']',
            content,
            re.IGNORECASE,
        )
        for gf_url in gf_links:
            if gf_url not in vendor_map:
                local_gf = vendor_mgr.vendor_google_fonts(gf_url)
                if local_gf:
                    vendor_map[gf_url] = local_gf

    all_warnings.extend(vendor_mgr.warnings)

    # 7. Сборка игр: dist/g/<slug>/index.html
    processed_games_count = 0
    for item in catalog_data.get("items", []):
        if item.get("archived"):
            continue
        if item.get("kind") != "game":
            continue
        fname = item.get("file")
        if not fname or fname not in inbox_files:
            all_warnings.append(f"[ПРЕДУПРЕЖДЕНИЕ] Файл игры '{fname}' не найден в games_inbox/")
            continue

        raw_html = inbox_files[fname]
        rewritten_html, cdn_warns = rewrite_cdn(raw_html, vendor_map, failed_fonts=vendor_mgr.failed_urls)
        all_warnings.extend(cdn_warns)

        final_html = inject_shell(rewritten_html, slug=item["slug"], shell_version=shell_v)

        game_dir = dist_dir / "g" / item["slug"]
        game_dir.mkdir(parents=True, exist_ok=True)
        (game_dir / "index.html").write_text(final_html, encoding="utf-8")
        processed_games_count += 1

    # 8. Сборка dist/catalog.json и dist/index.html
    payload = build_catalog_payload(catalog_data)
    (dist_dir / "catalog.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    dist_index = dist_dir / "index.html"
    if dist_index.exists():
        index_html = dist_index.read_text(encoding="utf-8")
        if "<!--CATALOG_DATA-->" in index_html:
            new_index_html = embed_catalog(index_html, payload)
            dist_index.write_text(new_index_html, encoding="utf-8")
            print("[OK] Каталог успешно встроен в dist/index.html")
        else:
            all_warnings.append("[ПРЕДУПРЕЖДЕНИЕ] Плейсхолдер <!--CATALOG_DATA--> не найден в dist/index.html")
    else:
        print("[INFO] site_template/index.html не найден (параллельная разработка) — dist/index.html пропущен.")

    # 9. Итоговый отчет
    print("\n--- Отчет сборки ---")
    print(f"Собрано игр: {processed_games_count}")
    print(f"Досок: {sum(1 for i in catalog_data.get('items', []) if i.get('kind') == 'board')}")
    print(f"Предупреждений: {len(all_warnings)}")
    for w in all_warnings:
        print(f"  * {w}")
    print("dist/ готов к выкладке.\n")
    return 0


build_site = publish


if __name__ == "__main__":
    sys.exit(publish())
