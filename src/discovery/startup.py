from __future__ import annotations

from typing import Any

from .store import utc_now


def install_minimal_performance_schema(performance_module, service) -> None:
    """Keep first-start performance metadata cheap.

    The original performance schema also created several secondary indexes over
    potentially large Discovery tables. Those indexes are useful for maintenance
    and larger corpus tuning, but building them is derived work and must not hold
    application startup hostage. Cache tables are tiny and are the only schema
    required by the hot path.
    """

    def ensure(service_obj) -> None:
        if getattr(service_obj, "_discovery_performance_schema_ready", False):
            return
        with service_obj.store._lock, service_obj.store.connection() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS discovery_capture_cache(
                    source_turn_id TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_revision TEXT NOT NULL,
                    pipeline_revision TEXT NOT NULL,
                    propositions INTEGER NOT NULL,
                    instances INTEGER NOT NULL,
                    skipped INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(source_turn_id,source_kind)
                );

                CREATE TABLE IF NOT EXISTS discovery_materialization_cache(
                    source_turn_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    report_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS discovery_branch_projection_cache(
                    proposition_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            con.execute(
                "INSERT INTO discovery_meta(key,value) VALUES('performance_schema_version',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (performance_module.PERFORMANCE_SCHEMA_VERSION,),
            )
        service_obj._discovery_performance_schema_ready = True

    performance_module._ensure_performance_schema = ensure
    ensure(service)
    service.ensure_discovery_performance_schema = lambda: ensure(service)


def deferred_materialization_report(provisional_module) -> dict[str, Any]:
    report = provisional_module.ProvisionalMaterializationReport().to_dict()
    report.update({
        "processed": 0,
        "pending": -1,
        "deferred": True,
        "startup": True,
        "updated_at": utc_now(),
    })
    return report
