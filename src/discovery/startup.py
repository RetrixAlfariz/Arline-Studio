from __future__ import annotations

from threading import Timer
from typing import Any

from .store import utc_now


HISTORICAL_BRANCH_REPAIR_BATCH = 192
GARMENT_MIGRATION_META_KEY = "garment_namespace_migration_v1"


def install_minimal_performance_schema(performance_module, service) -> None:
    """Keep first-start performance metadata cheap.

    The original performance schema also created several secondary indexes over
    potentially large Discovery tables. Those indexes are useful for maintenance
    and larger-corpus tuning, but building them is derived work and must not hold
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


def install_deferred_garment_migration(garment_module, service, *, delay: float = 4.0) -> None:
    """Move legacy non-Canon garment cleanup out of application startup."""
    if getattr(service, "_deferred_garment_migration_installed", False):
        return

    with service.store.connection() as con:
        row = con.execute(
            "SELECT value FROM discovery_meta WHERE key=?",
            (GARMENT_MIGRATION_META_KEY,),
        ).fetchone()
    if row and str(row["value"]) == "done":
        service._deferred_garment_migration_installed = True
        return

    migrate = garment_module._migrate_unmaterialized_garment_predicates

    def run() -> None:
        try:
            migrated = int(migrate(service) or 0)
            with service.store._lock, service.store.connection() as con:
                con.execute(
                    "INSERT INTO discovery_meta(key,value) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (GARMENT_MIGRATION_META_KEY, "done"),
                )
            metrics = dict(getattr(service, "_performance_metrics", {}) or {})
            metrics["garment_namespace_migrated"] = migrated
            service._performance_metrics = metrics
        except Exception as exc:
            metrics = dict(getattr(service, "_performance_metrics", {}) or {})
            metrics["garment_namespace_migration_error"] = str(exc)
            service._performance_metrics = metrics

    timer = Timer(max(0.1, float(delay)), run)
    timer.daemon = True
    timer.start()
    service._garment_migration_timer = timer
    service._deferred_garment_migration_installed = True


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


def install_incremental_branch_repair(runtime_module, service) -> None:
    """Replace historical branch repair with small restart-safe batches.

    Per-turn repair remains immediate. Only legacy/historical projection cleanup
    uses this batcher. The cache timestamp is derived state; losing it merely
    causes harmless revalidation.
    """
    if getattr(service, "_incremental_branch_repair_installed", False):
        return

    repair_one = runtime_module.repair_proposition_branch_projection

    def dirty_rows(service_obj, limit: int):
        cap = max(1, min(int(limit), HISTORICAL_BRANCH_REPAIR_BATCH))
        with service_obj.store.connection() as con:
            return con.execute(
                "SELECT d.proposition_id,d.latest FROM ("
                "SELECT proposition_id,MAX(updated_at) AS latest FROM discovery_instances "
                "WHERE active=1 GROUP BY proposition_id"
                ") d LEFT JOIN discovery_branch_projection_cache c "
                "ON c.proposition_id=d.proposition_id "
                "WHERE c.proposition_id IS NULL OR c.updated_at<d.latest "
                "ORDER BY d.latest,d.proposition_id LIMIT ?",
                (cap,),
            ).fetchall()

    def has_pending(service_obj) -> bool:
        with service_obj.store.connection() as con:
            row = con.execute(
                "SELECT 1 FROM ("
                "SELECT proposition_id,MAX(updated_at) AS latest FROM discovery_instances "
                "WHERE active=1 GROUP BY proposition_id"
                ") d LEFT JOIN discovery_branch_projection_cache c "
                "ON c.proposition_id=d.proposition_id "
                "WHERE c.proposition_id IS NULL OR c.updated_at<d.latest LIMIT 1"
            ).fetchone()
        return row is not None

    def repair_existing(service_obj, limit: int = HISTORICAL_BRANCH_REPAIR_BATCH) -> dict[str, Any]:
        rows = dirty_rows(service_obj, limit)
        processed = 0
        for row in rows:
            prop_id = str(row["proposition_id"])
            repair_one(service_obj, prop_id)
            with service_obj.store._lock, service_obj.store.connection() as con:
                con.execute(
                    "INSERT INTO discovery_branch_projection_cache(proposition_id,fingerprint,updated_at) "
                    "VALUES(?,?,?) ON CONFLICT(proposition_id) DO UPDATE SET "
                    "fingerprint=excluded.fingerprint,updated_at=excluded.updated_at",
                    (prop_id, f"source:{row['latest']}", utc_now()),
                )
            processed += 1
        return {"processed": processed, "pending": has_pending(service_obj)}

    runtime_module.repair_existing_branch_projections = repair_existing
    service.repair_existing_branch_projections = lambda limit=HISTORICAL_BRANCH_REPAIR_BATCH: repair_existing(
        service, limit=limit
    )
    service._incremental_branch_repair_installed = True


def install_combined_historical_drain(provisional_module, service) -> None:
    """Drain materialization and branch repair together in bounded batches."""
    materialize = provisional_module.materialize_existing
    repair = getattr(service, "repair_existing_branch_projections", None)

    def combined(*, limit: int = 5000):
        materialization = materialize(service, limit=limit)
        repair_report = repair(limit=min(max(1, int(limit)), HISTORICAL_BRANCH_REPAIR_BATCH)) if callable(repair) else {
            "processed": 0,
            "pending": False,
        }
        result = dict(materialization)
        result["branch_repair"] = repair_report
        result["pending"] = bool(materialization.get("pending")) or bool(repair_report.get("pending"))
        return result

    service.materialize_existing = combined
