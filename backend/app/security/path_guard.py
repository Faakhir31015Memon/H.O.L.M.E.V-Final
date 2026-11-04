"""Confines every filesystem tool to the user-selected workspace root.

This is the one layer that must never be "convenient". Every path coming from a
model is treated as hostile until it survives resolution here.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from app.config.settings import settings

# Windows device names remain reserved even with an extension.
_RESERVED = re.compile(
    r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$", re.IGNORECASE
)

CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")

DEFAULT_DENY_GLOBS = (
    ".git/**",
    ".env",
    ".env.*",
    "**/id_rsa",
    "**/id_ed25519",
    "**/*.pem",
    "**/credentials",
    "**/known_hosts",
    "**/.ssh/**",
    "**/AppData/**",
    "**/NTUSER.DAT*",
    "**/sam",
    "**/systems32/**",
)


class PathRejected(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class GuardedPath:
    requested: str
    resolved: Path
    relative: str

    @property
    def exists(self) -> bool:
        return self.resolved.exists()

    @property
    def is_dir(self) -> bool:
        return self.resolved.is_dir()


def workspace_root() -> Path:
    return Path(settings.WORKSPACE_ROOT).expanduser().resolve(strict=False)


def _has_symlink_component(path: Path, root: Path) -> bool:
    """Reject any junction/symlink hop between the root and the target."""

    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return True
    return False


def sanitize_filename(name: str) -> str:
    cleaned = CONTROL_CHARS.sub("", (name or "").strip())
    cleaned = cleaned.replace("/", "_").replace("\\", "_")
    cleaned = re.sub(r'[<>:"|?*]', "_", cleaned)
    cleaned = cleaned.strip(" .")
    if not cleaned or _RESERVED.match(cleaned):
        return "holmev_item"
    return cleaned[:180]


def guard(raw_path: str, root: Path | None = None, deny_globs: tuple[str, ...] = DEFAULT_DENY_GLOBS,
          must_exist: bool = False) -> GuardedPath:
    """Resolve `raw_path` inside the workspace root or raise PathRejected."""

    if raw_path is None or not str(raw_path).strip():
        raise PathRejected("empty path")

    text = str(raw_path)
    if CONTROL_CHARS.search(text):
        raise PathRejected("path contains control characters")

    base = (root or workspace_root()).resolve(strict=False)
    candidate = Path(text)

    # Absolute paths and UNC shares are only acceptable when already inside root.
    if candidate.is_absolute() or text.startswith("\\\\") or re.match(r"^[A-Za-z]:", text):
        resolved = Path(os.path.realpath(candidate))
    else:
        resolved = Path(os.path.realpath(base / candidate))

    if not _is_within(resolved, base):
        raise PathRejected(f"path escapes the workspace root ({base})")

    if _RESERVED.match(resolved.name):
        raise PathRejected(f"'{resolved.name}' is a reserved device name")

    try:
        relative = resolved.relative_to(base)
    except ValueError:
        raise PathRejected("path resolves outside the workspace root") from None

    rel_text = relative.as_posix().lower()
    for pattern in deny_globs:
        if _matches_glob(rel_text, pattern.lower()):
            raise PathRejected(f"'{relative}' is on the protected-paths list")

    if _has_symlink_component(resolved, base):
        raise PathRejected("path contains a symlink or junction hop")

    if must_exist and not resolved.exists():
        raise PathRejected(f"'{relative}' does not exist")

    return GuardedPath(requested=text, resolved=resolved, relative=relative.as_posix())


def _is_within(candidate: Path, base: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(base.resolve(strict=False))
        return True
    except ValueError:
        return False


def _matches_glob(rel_path: str, pattern: str) -> bool:
    from fnmatch import fnmatch

    if fnmatch(rel_path, pattern):
        return True
    if pattern.endswith("/**") and (rel_path.startswith(pattern[:-3] + "/") or rel_path == pattern[:-3]):
        return True
    return any(fnmatch(part, pattern) for part in rel_path.split("/"))


def ensure_root_exists() -> Path:
    root = workspace_root()
    root.mkdir(parents=True, exist_ok=True)
    return root
