"""Unit-тесты облачного адаптера GitHub REST API (tools/github_storage.py)."""

import base64
import json
import os
import unittest
from unittest.mock import patch

from tools.github_storage import GitHubAPIError, GitHubStorage


class FakeTransport:
    """Детерминированный in-memory мок GitHub REST API без внешних сетевых вызовов."""

    def __init__(self, fail_ref_patch_times: int = 0):
        self.fail_ref_patch_times = fail_ref_patch_times
        self.patch_attempts = 0
        self.calls: list[tuple[str, str, dict | None]] = []
        self.head_sha = "sha_commit_1"
        self.tree_sha = "sha_tree_1"
        self.blobs: dict[str, bytes] = {}
        self.committed_trees: list[list[dict]] = []
        self.remote_catalog = {"items": [{"id": "remote-1", "slug": "remote-1", "title": "Из облака", "kind": "board", "url": "https://miro.com/1"}]}

    def __call__(self, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        self.calls.append((method, path, payload))

        if method == "GET" and path.endswith("/git/ref/heads/main"):
            return 200, {"object": {"sha": self.head_sha}}

        if method == "GET" and path.startswith("/repos/owner/tutor-games/git/commits/"):
            return 200, {"sha": self.head_sha, "tree": {"sha": self.tree_sha}}

        if method == "POST" and path.endswith("/git/blobs"):
            raw = base64.b64decode(payload["content"])
            blob_sha = f"blob_{len(self.blobs) + 1}"
            self.blobs[blob_sha] = raw
            return 201, {"sha": blob_sha}

        if method == "POST" and path.endswith("/git/trees"):
            self.committed_trees.append(payload["tree"])
            return 201, {"sha": f"tree_new_{len(self.committed_trees)}"}

        if method == "POST" and path.endswith("/git/commits"):
            return 201, {"sha": f"commit_new_{len(self.committed_trees)}"}

        if method == "PATCH" and path.endswith("/git/refs/heads/main"):
            self.patch_attempts += 1
            if self.patch_attempts <= self.fail_ref_patch_times:
                self.head_sha = f"concurrent_sha_{self.patch_attempts}"
                raise GitHubAPIError(409, "Reference cannot be fast-forwarded")
            self.head_sha = payload["sha"]
            return 200, {"object": {"sha": self.head_sha}}

        if method == "GET" and "/contents/catalog.json" in path:
            encoded = base64.b64encode(json.dumps(self.remote_catalog, ensure_ascii=False).encode("utf-8")).decode("ascii")
            return 200, {"sha": "file_sha_1", "encoding": "base64", "content": encoded}

        raise AssertionError(f"Unexpected call: {method} {path}")


class TestGitHubStorage(unittest.TestCase):
    """Проверка атомарных коммитов, CAS-повторов и формирования публичного URL."""

    def test_01_from_env_and_public_pages_url(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(GitHubStorage.from_env())

        with patch.dict(
            os.environ,
            {"GITHUB_TOKEN": "ghp_test123", "GITHUB_REPO": "liztemerHB/slovesnost-igroteka"},
            clear=True,
        ):
            storage = GitHubStorage.from_env()
            self.assertIsNotNone(storage)
            self.assertEqual(storage.repo, "liztemerHB/slovesnost-igroteka")
            self.assertEqual(storage.branch, "main")
            self.assertEqual(storage.public_pages_url, "https://liztemerhb.github.io/slovesnost-igroteka/")

    def test_02_atomic_multi_file_commit(self):
        transport = FakeTransport()
        storage = GitHubStorage(
            token="ghp_test",
            repo="owner/tutor-games",
            branch="main",
            transport=transport,
        )

        new_sha = storage.commit_files(
            {
                "catalog.json": b'{"items": []}\n',
                "games_inbox/diktant.html": "<title>Диктант</title>".encode("utf-8"),
                "site_template/covers/custom_a1b2.png": b"\x89PNG\r\n\x1a\n",
            },
            message="admin: добавлен тренажёр Диктант",
        )

        self.assertEqual(new_sha, "commit_new_1")
        self.assertEqual(len(transport.committed_trees), 1)
        paths = [entry["path"] for entry in transport.committed_trees[0]]
        self.assertEqual(
            sorted(paths),
            ["catalog.json", "games_inbox/diktant.html", "site_template/covers/custom_a1b2.png"],
        )
        # Проверяем, что force=False передаётся в PATCH ref
        patch_calls = [c for c in transport.calls if c[0] == "PATCH"]
        self.assertEqual(len(patch_calls), 1)
        self.assertFalse(patch_calls[0][2].get("force", True))

    def test_03_cas_retry_on_409_conflict(self):
        transport = FakeTransport(fail_ref_patch_times=2)
        storage = GitHubStorage(
            token="ghp_test",
            repo="owner/tutor-games",
            branch="main",
            transport=transport,
        )

        new_sha = storage.commit_files(
            {"catalog.json": b'{"items": []}\n'},
            message="admin: обновление при конкурентной записи",
        )
        self.assertEqual(new_sha, "commit_new_3")
        self.assertEqual(transport.patch_attempts, 3)

    def test_04_fetch_remote_catalog_when_sha_changes(self):
        transport = FakeTransport()
        storage = GitHubStorage(
            token="ghp_test",
            repo="owner/tutor-games",
            branch="main",
            transport=transport,
        )
        data = storage.fetch_json_if_changed("catalog.json")
        self.assertIsNotNone(data)
        self.assertEqual(data["items"][0]["id"], "remote-1")

        # Повторный вызов при том же HEAD SHA не скачивает файл заново
        second = storage.fetch_json_if_changed("catalog.json")
        self.assertIsNone(second)

    def test_05_vercel_serverless_entrypoint_imports_without_socket(self):
        """Проверка холодного старта api/index.py без открытия портов и при отсутствии пароля."""
        import api.index as vercel_api

        vercel_api._MANAGER = None
        with patch.dict(os.environ, {"VERCEL": "1"}, clear=False):
            os.environ.pop("TUTOR_ADMIN_PASSWORD", None)
            mgr = vercel_api.get_serverless_manager()
            self.assertIsNone(mgr.server)
            self.assertFalse(mgr.password_configured)
        vercel_api._MANAGER = None


if __name__ == "__main__":
    unittest.main()
