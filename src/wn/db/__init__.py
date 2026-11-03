"""SQLite access: one catalog database and one learner profile database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .migrate import migrate

MIGRATIONS = Path(__file__).parent
BACKUP_KEEP = 10


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def open_catalog(data_dir: Path) -> sqlite3.Connection:
    """Open catalog.db, creating or upgrading it. It can be rebuilt, so no backup."""
    conn = _connect(data_dir / "catalog.db")
    migrate(conn, MIGRATIONS / "catalog")
    return conn


def open_profile(data_dir: Path) -> sqlite3.Connection:
    """Open profile.db, creating or upgrading it. This is the file that matters."""
    conn = _connect(data_dir / "profile.db")
    migrate(
        conn,
        MIGRATIONS / "profile",
        backup_dir=data_dir / "backups",
        backup_keep=BACKUP_KEEP,
    )
    return conn
