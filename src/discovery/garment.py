from __future__ import annotations

from typing import Any

from .store import loads, proposition_key, utc_now


GARMENT_ATTRIBUTE_PREDICATES = {
    "color",
    "material",
    "length",
    "front_length",
    "back_length",
    "flowiness",
    "size_class",
    "construction",
}


def _garment_type(label: str, subject_key: str) -> str:
    clean = str(label or "").strip().casefold().replace(" ", "_")
    key = str(subject_key or "")
    if key.startswith("garment:"):
        tail = key.split(":", 1)[1]
        if tail.endswith("_1"):
            tail = tail[:-2]
        if tail:
            return tail
    return clean or "garment"


def _display_label(label: str) -> str:
    raw = str(label or "").strip()
    if raw and raw == raw.lower():
        return raw.title()
    return raw or "Garment"


def _namespaced_predicate(subject_type: str, predicate: str, operation: str) -> str:
    predicate = str(predicate or "")
    if (
        subject_type == "garment"
        and operation != "relation"
        and predicate in GARMENT_ATTRIBUTE_PREDICATES
    ):
        return f"garment.{predicate}"
    return predicate


def _migrate_unmaterialized_garment_predicates(service) -> int:
    """Namespace old non-canon garment observations in place.

    Canon/materialized rows are intentionally untouched: changing their path
    would require an explicit canonical migration/retcon rather than a Discovery
    cleanup. If a namespaced proposition already exists, the old observation is
    simply made inactive so it cannot double-count the same evidence.
    """
    marks = ",".join("?" for _ in GARMENT_ATTRIBUTE_PREDICATES)
    migrated = 0
    now = utc_now()
    with service.store._lock, service.store.connection() as con:
        rows = con.execute(
            f"SELECT * FROM discovery_propositions WHERE subject_type='garment' "
            f"AND predicate IN ({marks}) AND authority_state='observed' "
            "AND materialized_resource_id IS NULL ORDER BY rowid",
            sorted(GARMENT_ATTRIBUTE_PREDICATES),
        ).fetchall()
        for row in rows:
            new_predicate = f"garment.{row['predicate']}"
            value = loads(row["value_json"], None)
            new_key = proposition_key(
                project_id=row["project_id"], world_id=row["world_id"],
                subject_type=row["subject_type"], subject_key=row["subject_key"],
                predicate=new_predicate, value=value, object_key=row["object_key"],
                operation=row["operation"],
            )
            conflict = con.execute(
                "SELECT id FROM discovery_propositions WHERE proposition_key=? AND id!=?",
                (new_key, row["id"]),
            ).fetchone()
            if conflict:
                con.execute(
                    "UPDATE discovery_instances SET active=0,"
                    "invalidation_reason='garment_namespace_superseded',updated_at=? "
                    "WHERE proposition_id=? AND active=1",
                    (now, row["id"]),
                )
                continue
            con.execute(
                "UPDATE discovery_propositions SET predicate=?,proposition_key=?,updated_at=? WHERE id=?",
                (new_predicate, new_key, now, row["id"]),
            )
            migrated += 1
    return migrated


def install_garment_runtime(service) -> None:
    """Preserve garment ontology when analytical attributes enter Discovery."""
    if getattr(service, "_GARMENT_RUNTIME_INSTALLED", False):
        return
    _migrate_unmaterialized_garment_predicates(service)
    original_capture_prop = service._capture_prop

    def capture_prop(*args, **kwargs):
        subject_type = str(kwargs.get("subject_type") or "")
        operation = str(kwargs.get("operation") or "update")
        predicate = str(kwargs.get("predicate") or "")
        kwargs["predicate"] = _namespaced_predicate(subject_type, predicate, operation)
        return original_capture_prop(*args, **kwargs)

    service._capture_prop = capture_prop
    service._GARMENT_RUNTIME_INSTALLED = True


def install_garment_materialization(provisional_module) -> None:
    """Materialize semantic garment entities as callable Library Item sheets."""
    if getattr(provisional_module, "_GARMENT_MATERIALIZATION_INSTALLED", False):
        return

    original = provisional_module._ensure_sheet_for
    provisional_module.SUPPORTED_SHEET_TYPES.add("garment")

    def ensure_sheet_for(
        service,
        *,
        project_id: str | None,
        world_id: str | None,
        branch_id: str | None,
        subject_type: str,
        subject_key: str,
        subject_label: str,
        location_kind: str | None = None,
    ):
        if subject_type != "garment":
            return original(
                service,
                project_id=project_id,
                world_id=world_id,
                branch_id=branch_id,
                subject_type=subject_type,
                subject_key=subject_key,
                subject_label=subject_label,
                location_kind=location_kind,
            )

        family, variant, created = original(
            service,
            project_id=project_id,
            world_id=world_id,
            branch_id=branch_id,
            subject_type="item",
            subject_key=subject_key,
            subject_label=_display_label(subject_label),
            location_kind=None,
        )
        if family:
            current = service.workspace.get_entity_family(family["id"])
            core: dict[str, Any] = dict(current.get("shared_core") or {})
            changed = False
            if not core.get("kind"):
                core["kind"] = "garment"
                changed = True
            garment = dict(core.get("garment") or {})
            if not garment.get("type"):
                garment["type"] = _garment_type(subject_label, subject_key)
                changed = True
            core["garment"] = garment
            discovery = dict(core.get("_discovery") or {})
            if discovery.get("semantic_type") != "garment":
                discovery["semantic_type"] = "garment"
                changed = True
            core["_discovery"] = discovery
            if changed:
                service.workspace.update_entity_family(
                    family["id"],
                    shared_core=core,
                    note="discovery: garment item projection",
                )
                family = service.workspace.get_entity_family(family["id"])
        return family, variant, created

    provisional_module._ensure_sheet_for = ensure_sheet_for
    provisional_module._GARMENT_MATERIALIZATION_INSTALLED = True
