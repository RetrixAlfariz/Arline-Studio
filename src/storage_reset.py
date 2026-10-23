from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil

from src.discovery.store import DiscoveryStore
from src.history.store import HistoryStore
from src.memory.store import MemoryStore
from src.runtime_config import RuntimeConfig
from src.storage_backup import create_sqlite_recovery_backup
from src.workspace.foundation import FoundationStore
from src.workspace.store import WorkspaceStore


@dataclass(frozen=True, slots=True)
class StorageResetReport:
    mode: str
    databases: tuple[str, ...]
    backups: tuple[str, ...]
    removed_directories: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "mode": self.mode,
            "databases": list(self.databases),
            "backups": list(self.backups),
            "removed_directories": list(self.removed_directories),
            "restart_required": False,
        }


def _remove_database(path: Path) -> None:
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        candidate.unlink(missing_ok=True)


def _safe_remove_directory(path: Path, *, protected: set[Path]) -> bool:
    resolved = path.resolve()
    anchor = Path(resolved.anchor).resolve()
    if resolved in protected or resolved == anchor or len(resolved.parts) < 3:
        raise ValueError(f"Refusing to recursively remove unsafe storage path: {resolved}")
    if not resolved.exists():
        return False
    if not resolved.is_dir():
        raise ValueError(f"Configured storage path is not a directory: {resolved}")
    shutil.rmtree(resolved)
    return True


def reset_storage(config: RuntimeConfig, *, complete: bool) -> StorageResetReport:
    """Reset SQLite state and optionally all generated local data.

    The caller must serialize this against active store work. Store instances
    keep paths rather than persistent SQLite connections, so rebuilding the
    files in place leaves the running application usable.
    """
    history_path = Path(config.history.database_path).resolve()
    workspace_path = Path(config.workspace.database_path).resolve()
    database_paths = tuple(dict.fromkeys((history_path, workspace_path)))

    backups: list[str] = []
    if not complete:
        for path in database_paths:
            backup = create_sqlite_recovery_backup(path, reason="before-reset")
            if backup is not None:
                backups.append(str(backup))

    for path in database_paths:
        _remove_database(path)

    HistoryStore(history_path, backup_before_migration=False)
    WorkspaceStore(workspace_path, backup_before_migration=False)
    FoundationStore(workspace_path)
    MemoryStore(workspace_path, backup_before_migration=False)
    DiscoveryStore(workspace_path, backup_before_migration=False)

    removed: list[str] = []
    if complete:
        protected = {
            Path.cwd().resolve(),
            Path.home().resolve(),
            history_path.parent.resolve(),
            workspace_path.parent.resolve(),
        }
        candidates = {
            workspace_path.parent / "media",
            workspace_path.parent / "backups",
            Path(config.history.dataset_root),
            Path(config.artifacts.output_root),
            Path(config.artifacts.saved_root),
        }
        resolved = sorted({path.resolve() for path in candidates}, key=lambda item: len(item.parts))
        roots = [path for path in resolved if not any(parent in path.parents for parent in resolved)]
        for path in roots:
            if _safe_remove_directory(path, protected=protected):
                removed.append(str(path))

    return StorageResetReport(
        mode="complete" if complete else "database",
        databases=tuple(str(path) for path in database_paths),
        backups=tuple(backups),
        removed_directories=tuple(removed),
    )
