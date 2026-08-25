from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Mapping


def _read_version(con: sqlite3.Connection, table: str) -> int | None:
    exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    if not exists:
        return None
    try:
        row = con.execute(f"SELECT value FROM {table} WHERE key='schema_version'").fetchone()
    except sqlite3.DatabaseError:
        return None
    try:
        return int(row[0]) if row else None
    except (TypeError, ValueError):
        return None


def backup_sqlite_before_migrations(database_path: Path | str, targets: Mapping[str, int]) -> Path | None:
    """Create one consistent backup before any store mutates an existing SQLite DB.

    ``targets`` maps metadata table names to their expected schema versions. A
    pre-versioned/legacy database is backed up whenever it already contains user
    tables even if the metadata table does not exist yet.
    """
    path = Path(database_path)
    if not path.exists() or path.stat().st_size == 0:
        return None
    source = sqlite3.connect(path, timeout=30)
    try:
        tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()}
        if not tables:
            return None
        reasons = []
        for meta_table, target in targets.items():
            current = _read_version(source, meta_table)
            if current is None:
                reasons.append(f"{meta_table}:legacy->{target}")
            elif current < target:
                reasons.append(f"{meta_table}:{current}->{target}")
        if not reasons:
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        suffix = path.suffix or ".db"
        backup = backup_dir / f"{path.stem}.pre-migration-{stamp}{suffix}"
        target = sqlite3.connect(backup, timeout=30)
        try:
            source.backup(target)
        finally:
            target.close()
        return backup
    finally:
        source.close()


def create_sqlite_recovery_backup(
    database_path: Path | str,
    *,
    reason: str = "reset",
) -> Path | None:
    """Create a consistent, user-initiated recovery backup."""
    path = Path(database_path).resolve()
    if not path.is_file():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_dir = path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix or ".db"
    backup = backup_dir / f"{path.stem}.{reason}-{stamp}{suffix}"
    source = sqlite3.connect(path, timeout=30)
    target = sqlite3.connect(backup, timeout=30)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return backup
