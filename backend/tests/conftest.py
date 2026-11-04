"""Shared fixtures: every test gets a throwaway SQLite DB and workspace root."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND.parent

for candidate in (str(BACKEND), str(REPO_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


@pytest.fixture(autouse=True)
def isolated_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from app.config.settings import settings
    from app.database import session as db_session

    db_url = f"sqlite+aiosqlite:///{(tmp_path / 'holmev_test.db').as_posix()}"
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(settings, "DATABASE_URL", db_url)
    monkeypatch.setattr(settings, "WORKSPACE_ROOT", str(workspace))
    monkeypatch.setattr(settings, "PRIVACY_LEVEL", "local_only")
    monkeypatch.setattr(settings, "BRAIN_ALLOW_EXTERNAL", False)

    db_session.use_database(db_url)
    asyncio.run(db_session.init_db())
    return workspace
