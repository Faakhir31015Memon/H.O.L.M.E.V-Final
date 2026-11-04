"""Put the monorepo root on `sys.path` so `python_services.*` resolves.

This runs from the lifespan instead of at import time: doing it between imports
is what forced every later import below a `# noqa: E402`, and it made the import
order of the app a side effect of file layout.
"""

from __future__ import annotations

import sys
from pathlib import Path

MONOREPO_ROOT = Path(__file__).resolve().parents[2]


def ensure_monorepo_path() -> Path:
    candidate = str(MONOREPO_ROOT)
    if candidate not in sys.path:
        sys.path.insert(0, candidate)
    return MONOREPO_ROOT
