"""Бессерверная точка входа Vercel Python Runtime для Мастерской репетитора (api/index.py).

На холодном старте подготавливает рабочую директорию /tmp/tutor_workspace
(так как /var/task в Vercel доступен только для чтения), подключает GitHubStorage
(GITHUB_TOKEN + GITHUB_REPO) и обрабатывает запросы /admin и /api/admin/*
через проверенный AdminRequestHandler без открытия TCP-сокетов.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parent.parent
if str(CODE_ROOT) not in sys.path:
    sys.path.insert(0, str(CODE_ROOT))

from tools.admin_server import AdminRequestHandler, AdminServerManager  # noqa: E402

_INIT_LOCK = threading.Lock()
_MANAGER: AdminServerManager | None = None


class _ServerlessHolder:
    """Лёгкая обёртка вместо ThreadingHTTPServer для BaseHTTPRequestHandler в Vercel."""

    def __init__(self, manager: AdminServerManager):
        self.manager = manager


def get_serverless_manager() -> AdminServerManager:
    """Ленивая потокобезопасная инициализация менеджера в /tmp/tutor_workspace."""
    global _MANAGER
    if _MANAGER is not None:
        return _MANAGER

    with _INIT_LOCK:
        if _MANAGER is not None:
            return _MANAGER

        workspace = Path(tempfile.gettempdir()) / "tutor_workspace"
        if not (workspace / "catalog.json").exists():
            workspace.mkdir(parents=True, exist_ok=True)
            src_catalog = CODE_ROOT / "catalog.json"
            if src_catalog.exists():
                shutil.copy2(src_catalog, workspace / "catalog.json")
            else:
                (workspace / "catalog.json").write_text('{"items": []}\n', encoding="utf-8")

            for folder_name in ("games_inbox", "site_template"):
                src_dir = CODE_ROOT / folder_name
                dst_dir = workspace / folder_name
                if src_dir.exists() and not dst_dir.exists():
                    shutil.copytree(
                        src_dir,
                        dst_dir,
                        dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("*archive*", "v2_*", ".*", "*.bak"),
                    )

            src_cache = CODE_ROOT / "tools" / ".vendor_cache"
            dst_cache = workspace / "tools" / ".vendor_cache"
            if src_cache.exists() and not dst_cache.exists():
                dst_cache.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(src_cache, dst_cache, dirs_exist_ok=True)

        os.environ.setdefault("VERCEL", "1")
        _MANAGER = AdminServerManager(
            project_root=workspace,
            ui_root=CODE_ROOT,
            bind_socket=False,
        )
        return _MANAGER


class handler(AdminRequestHandler):  # noqa: N801 — контракт имени класса Vercel Python Runtime
    """Обработчик HTTP-запросов для Vercel Serverless Functions."""

    @property
    def manager(self) -> AdminServerManager:
        srv = getattr(self, "server", None)
        if srv is not None and hasattr(srv, "manager"):
            return srv.manager
        return get_serverless_manager()
