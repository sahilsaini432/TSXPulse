"""Timezone helpers. Replaces deprecated datetime.utcnow() while keeping SQLite-friendly naive UTC."""
from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Naive UTC 'now'. Safe for SQLite DateTime columns, matches legacy utcnow() semantics."""
    return datetime.now(UTC).replace(tzinfo=None)
