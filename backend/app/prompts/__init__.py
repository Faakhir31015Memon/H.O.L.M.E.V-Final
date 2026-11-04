"""Prompt loading with an explicit version, so behaviour is reproducible."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent
DEFAULT_SYSTEM = "system_v1.md"


@lru_cache(maxsize=32)
def load_prompt(name: str = DEFAULT_SYSTEM) -> str:
    path = PROMPT_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"prompt '{name}' not found in {PROMPT_DIR}")
    return path.read_text(encoding="utf-8").strip()


def system_prompt(name: str = DEFAULT_SYSTEM) -> str:
    return load_prompt(name)


def available_prompts() -> list[str]:
    return sorted(p.name for p in PROMPT_DIR.glob("*.md"))
