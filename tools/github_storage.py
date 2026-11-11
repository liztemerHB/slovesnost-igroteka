#!/usr/bin/env python3
"""Адаптер облачного хранения исходников каталога в GitHub REST API (tools/github_storage.py).

Работает на чистой стандартной библиотеке Python (0 внешних зависимостей).
Коммитит исключительно исходные мутации (catalog.json, games_inbox/*.html,
site_template/covers/custom_*), не перегоняя папку dist/ по сети, чтобы гарантированно
укладываться в лимит бесплатного тарифа Vercel Hobby (<= 1.5 сек), а сборку dist/
выполняет GitHub Actions -> GitHub Pages.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable


class GitHubAPIError(RuntimeError):
    """Ошибка вызова GitHub REST API с HTTP-кодом."""

    def __init__(self, status: int, message: str):
        super().__init__(f"GitHub API {status}: {message}")
        self.status = status
        self.api_message = message


TransportFn = Callable[[str, str, dict | None], tuple[int, dict]]


class GitHubStorage:
    """Клиент атомарной фиксации изменений каталога через GitHub Git Data API."""

    API_BASE = "https://api.github.com"

    def __init__(
        self,
        token: str,
        repo: str,
        branch: str = "main",
        timeout: int = 8,
        transport: TransportFn | None = None,
    ):
        self.token = token.strip()
        self.repo = repo.strip().strip("/")
        self.branch = (branch or "main").strip()
        self.timeout = timeout
        self._transport = transport or self._default_transport
        self._last_seen_head_sha: str | None = None

    @classmethod
    def from_env(cls) -> GitHubStorage | None:
        """Инициализация из переменных окружения GITHUB_TOKEN + GITHUB_REPO."""
        token = (os.environ.get("GITHUB_TOKEN") or "").strip()
        repo = (os.environ.get("GITHUB_REPO") or "").strip()
        if not token or not repo or "/" not in repo:
            return None
        branch = (os.environ.get("GITHUB_BRANCH") or "main").strip()
        return cls(token=token, repo=repo, branch=branch)

    @property
    def public_pages_url(self) -> str:
        """Расчёт стандартного адреса витрины GitHub Pages (или переопределение из PUBLIC_CATALOG_URL)."""
        explicit = (os.environ.get("PUBLIC_CATALOG_URL") or "").strip()
        if explicit:
            return explicit.rstrip("/") + "/"
        parts = self.repo.split("/", 1)
        if len(parts) != 2:
            return "/"
        owner, name = parts[0].lower(), parts[1]
        if name.lower() == f"{owner}.github.io":
            return f"https://{owner}.github.io/"
        return f"https://{owner}.github.io/{name}/"

    def _default_transport(self, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        url = f"{self.API_BASE}{path}"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "SlovesnostTutorCatalog/3.0",
        }
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                parsed = json.loads(raw.decode("utf-8")) if raw else {}
                return resp.status, parsed
        except urllib.error.HTTPError as exc:
            err_raw = exc.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(err_raw)
                msg = err_json.get("message") or err_raw
            except Exception:
                msg = err_raw
            raise GitHubAPIError(exc.code, msg) from exc

    def get_head_sha(self) -> str:
        """Получение актуального SHA коммита ветки."""
        encoded_branch = urllib.parse.quote(self.branch, safe="/")
        _, ref_data = self._transport("GET", f"/repos/{self.repo}/git/ref/heads/{encoded_branch}", None)
        return str(ref_data["object"]["sha"])

    def fetch_json_if_changed(self, rel_path: str) -> dict | None:
        """Скачивает JSON-файл из репозитория, только если удалённый HEAD изменился."""
        head_sha = self.get_head_sha()
        if head_sha == self._last_seen_head_sha:
            return None
        clean_path = rel_path.lstrip("/").replace("\\", "/")
        encoded_path = urllib.parse.quote(clean_path, safe="/")
        encoded_ref = urllib.parse.quote(self.branch, safe="")
        _, data = self._transport(
            "GET",
            f"/repos/{self.repo}/contents/{encoded_path}?ref={encoded_ref}",
            None,
        )
        content_b64 = str(data.get("content") or "").replace("\n", "")
        raw_bytes = base64.b64decode(content_b64)
        parsed = json.loads(raw_bytes.decode("utf-8"))
        self._last_seen_head_sha = head_sha
        return parsed

    def commit_files(self, files: dict[str, bytes], message: str, max_retries: int = 3) -> str:
        """Атомарный коммит нескольких файлов в один Git-коммит с CAS-защитой (force=False)."""
        if not files:
            return self.get_head_sha()

        # 1. Создаём блобы один раз (они контентно-адресуемы и не зависят от родителя)
        blob_entries: list[dict] = []
        for rel_path, raw_bytes in files.items():
            clean_path = rel_path.lstrip("/").replace("\\", "/")
            if clean_path.startswith("dist/"):
                continue
            b64_str = base64.b64encode(raw_bytes).decode("ascii")
            _, blob_resp = self._transport(
                "POST",
                f"/repos/{self.repo}/git/blobs",
                {"content": b64_str, "encoding": "base64"},
            )
            blob_entries.append({
                "path": clean_path,
                "mode": "100644",
                "type": "blob",
                "sha": blob_resp["sha"],
            })

        if not blob_entries:
            return self.get_head_sha()

        encoded_branch = urllib.parse.quote(self.branch, safe="/")

        # 2. CAS-цикл обновления ссылки ветки (без перезаписи чужих коммитов)
        last_err: Exception | None = None
        for attempt in range(1, max_retries + 1):
            head_sha = self.get_head_sha()
            _, commit_info = self._transport("GET", f"/repos/{self.repo}/git/commits/{head_sha}", None)
            base_tree_sha = commit_info["tree"]["sha"]

            _, new_tree = self._transport(
                "POST",
                f"/repos/{self.repo}/git/trees",
                {"base_tree": base_tree_sha, "tree": blob_entries},
            )

            _, new_commit = self._transport(
                "POST",
                f"/repos/{self.repo}/git/commits",
                {
                    "message": message,
                    "tree": new_tree["sha"],
                    "parents": [head_sha],
                },
            )
            new_commit_sha = str(new_commit["sha"])

            try:
                self._transport(
                    "PATCH",
                    f"/repos/{self.repo}/git/refs/heads/{encoded_branch}",
                    {"sha": new_commit_sha, "force": False},
                )
                self._last_seen_head_sha = new_commit_sha
                return new_commit_sha
            except GitHubAPIError as exc:
                last_err = exc
                if exc.status in (409, 422) and attempt < max_retries:
                    time.sleep(0.15 * attempt)
                    continue
                raise

        if last_err:
            raise last_err
        raise RuntimeError("Не удалось зафиксировать коммит в GitHub")
