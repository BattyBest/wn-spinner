"""A tiny migration runner keyed on SQLite's PRAGMA user_version.

Migrations are files named ``NNN_name.sql`` in one folder. Each runs in its own
transaction and bumps user_version to NNN, so a failed migration changes nothing.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

_NAME = re.compile(r"^(\d{3})_.+\.sql$")


def _migrations(folder: Path) -> list[tuple[int, Path]]:
    found = []
    for path in sorted(folder.glob("*.sql")):
        match = _NAME.match(path.name)
        if match:
            found.append((int(match.group(1)), path))
    numbers = [n for n, _ in found]
    if numbers != sorted(set(numbers)):
        raise ValueError(f"duplicate or unordered migration numbers in {folder}")
    return found


def current_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def _backup(conn: sqlite3.Connection, backup_dir: Path, keep: int) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target = backup_dir / f"profile-v{current_version(conn)}-{stamp}.db"
    dest = sqlite3.connect(target)
    try:
        conn.backup(dest)
    finally:
        dest.close()
    for old in sorted(backup_dir.glob("profile-v*.db"))[:-keep]:
        old.unlink()
    return target


def migrate(
    conn: sqlite3.Connection,
    folder: Path,
    *,
    backup_dir: Path | None = None,
    backup_keep: int = 10,
) -> int:
    """Apply pending migrations and return the new version.

    If ``backup_dir`` is given and the database already holds data (version > 0),
    a copy is written there before anything changes.
    """
    version = current_version(conn)
    pending = [(n, p) for n, p in _migrations(folder) if n > version]
    if not pending:
        return version
    if backup_dir is not None and version > 0:
        _backup(conn, backup_dir, backup_keep)
    for number, path in pending:
        sql = path.read_text(encoding="utf-8")
        try:
            conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;")
        except sqlite3.Error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    return current_version(conn)
