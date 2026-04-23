"""Initialize SQLite schema. Idempotent — safe to run multiple times."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from TSXPulse.storage.models import init_db


def main() -> int:
    db_path = PROJECT_ROOT / "data" / "TSXPulse.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    init_db(db_path)
    print(f"DB initialized at {db_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
