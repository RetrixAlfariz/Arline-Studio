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


def _physical_item_id(subject_key: str) -> str | None:
    key = str(subject_key or "")
    if key.startswith("item:ITEM-"):
        return key.split(":", 1)[1]
    return None


def _garment_type(service, label: str, subject_key: str) -> str:
    key = str(subject_key or "")
    if key.startswith("garment:"):
        tail = key.split(":", 1)[1]
        if tail.endswith("_1"):
            tail = tail[:-2]
        if tail:
            return tail
    try:
        props = service.store.find_subject_propositions(
            project_id=None, world_id=None, subject_key=subject_key
        )
    except Exception:
        props = []
    if not props:
        with service.store.connection() as con:
            row = con.execute(
                "SELECT value_json FROM discovery_propositions WHERE subject_key=? AND predicate='garment.type' "
                "ORDER BY rowid DESC LIMIT 1",
                (subject_key,),
            ).fetchone()
        if row:
            value = loads(row["value_json"], None)
            if isinstance(value, str) and value.strip():
                return value.strip().casefold().replace(" ", "_")
    for prop in props:
        if prop.get("predicate") == "garment.type" and isinstance(prop.get("value"), str):
            return prop["value"].strip().casefold().replace(" ", "_")
    clean = str(label or "").strip().casefold().replace(" ", "_")
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
    """Materialize semantic garments as callable physical Library Item sheets.

    A physical subject key (``item:ITEM-*``) bypasses generic name-based identity
    reuse. Two identical garments are allowed to have two different ITEM ids and
    therefore two different Library sheets even if their descriptive labels are
    initially the same. Legacy collapsed garment keys keep the compatibility
    path until their source turns are re-scanned by the physical-item resolver.
    """
    if getattr(provisional_module, "_GARMENT_MATERIALIZATION_INSTALLED", False):
        return

    original = provisional_module._ensure_sheet_for
    provisional_module.SUPPORTED_SHEET_TYPES.add("garment")

    def ensure_physical_sheet(
        service,
        *,
        project_id: str | None,
        world_id: str | None,
        branch_id: str | None,
        subject_key: str,
        subject_label: str,
    ):
        item_id = _physical_item_id(subject_key)
        if not item_id:
            return None, None, False
        link = service.store.get_subject_link(
            project_id=project_id, world_id=world_id, subject_key=subject_key
        )
        family = None
        if link and link.get("resource_type") == "entity_family":
            try:
                family = service.workspace.get_entity_family(link["resource_id"])
            except Exception:
                family = None

        created = False
        garment_type = _garment_type(service, subject_label, subject_key)
        if family is None:
            core = {
                "kind": "garment",
                "garment": {"type": garment_type},
                "_discovery": {
                    "provisional": True,
                    "subject_key": subject_key,
                    "semantic_type": "garment",
                    "physical_item_id": item_id,
                    "identity_model": "physical_instance_v1",
                    "generated_label": True,
                    "identity_state": "detected",
                },
            }
            family = service.workspace.create_entity_family(
                None,
                _display_label(subject_label),
                entity_type="item",
                description="Physical garment item discovered indirectly from narrative evidence.",
                shared_core=core,
                create_variant_in_world=world_id,
                branch_id=provisional_module._branch_storage_id(service.workspace, branch_id),
            )
            created = True

        service.store.upsert_subject_link(
            project_id=project_id,
            world_id=world_id,
            subject_key=subject_key,
            resource_type="entity_family",
            resource_id=family["id"],
        )

        variant = None
        if world_id:
            storage_branch = provisional_module._branch_storage_id(service.workspace, branch_id)
            variant = service.workspace.resolve_variant(family["id"], world_id, storage_branch)
            if variant is None:
                variant = service.workspace.create_variant(
                    family["id"], world_id, branch_id=storage_branch,
                    canon_status="draft", summary="Provisional physical garment item.",
                )

        current = service.workspace.get_entity_family(family["id"])
        core = dict(current.get("shared_core") or {})
        discovery = dict(core.get("_discovery") or {})
        garment = dict(core.get("garment") or {})
        changed = False
        expected = {
            "provisional": True,
            "subject_key": subject_key,
            "semantic_type": "garment",
            "physical_item_id": item_id,
            "identity_model": "physical_instance_v1",
        }
        for key, value in expected.items():
            if discovery.get(key) != value:
                discovery[key] = value
                changed = True
        if core.get("kind") != "garment":
            core["kind"] = "garment"
            changed = True
        if garment.get("type") != garment_type:
            garment["type"] = garment_type
            changed = True
        core["garment"] = garment
        core["_discovery"] = discovery
        if changed:
            service.workspace.update_entity_family(
                family["id"], shared_core=core,
                note="discovery: physical garment identity projection",
            )
            family = service.workspace.get_entity_family(family["id"])

        if service.foundation is not None:
            try:
                service.foundation.add_alias("entity_family", family["id"], item_id)
            except Exception:
                pass
        return family, variant, created

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

        physical_id = _physical_item_id(subject_key)
        if physical_id:
            return ensure_physical_sheet(
                service,
                project_id=project_id,
                world_id=world_id,
                branch_id=branch_id,
                subject_key=subject_key,
                subject_label=subject_label,
            )

        # Compatibility path for pre-physical-instance garment discoveries.
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
                garment["type"] = _garment_type(service, subject_label, subject_key)
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
