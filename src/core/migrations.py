from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SchemaVersions:
    semantic_core: str = "0.1"
    aif_core: str = "0.3"
    writer_context: str = "0.1"
    world_runtime: str = "0.1"


MIGRATIONS = {
    ("AIF", "0.2", "0.3"): "AIF v0.3 becomes explicitly AIF-Core; writer models should consume WCF instead.",
    ("WCF", "0.0", "0.1"): "Initial Writer Context Format with locks, unknowns, transitions, freedom and narrative state.",
}


def migration_note(kind: str, source: str, target: str) -> str | None:
    return MIGRATIONS.get((kind, source, target))
