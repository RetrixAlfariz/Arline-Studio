from __future__ import annotations

from typing import Any

from src.memory.models import MemoryQueryContext

from .provisional import (
    SPATIAL_RELATIONS,
    SUPPORTED_SHEET_TYPES,
    _branch_storage_id,
    _ensure_sheet_for,
    _ensure_zone,
    _resource_context_rows,
    _zone_labels,
)
from .service import DiscoveryService
from .store import loads


_INSTALLED = False


def _best_active_instance(service: DiscoveryService, proposition_id: str) -> dict[str, Any] | None:
    instances = [item for item in service.store.list_instances(proposition_id) if item.get("active")]
    if not instances:
        return None
    return max(
        instances,
        key=lambda item: (
            bool(item.get("qualifies_review")),
            float(item.get("extraction_confidence") or 0.0),
            str(item.get("updated_at") or item.get("created_at") or ""),
            str(item.get("id") or ""),
        ),
    )


def _source_branch_ids(service: DiscoveryService, *, world_id: str, subject_key: str) -> list[str]:
    with service.store.connection() as con:
        rows = con.execute(
            "SELECT DISTINCT i.branch_id FROM discovery_instances i "
            "JOIN discovery_propositions p ON p.id=i.proposition_id "
            "WHERE i.active=1 AND i.world_id=? AND (p.subject_key=? OR p.object_key=?) "
            "AND i.branch_id IS NOT NULL ORDER BY i.branch_id",
            (world_id, subject_key, subject_key),
        ).fetchall()
    return [str(row["branch_id"]) for row in rows if row["branch_id"]]


def _sync_family_source_branches(
    service: DiscoveryService,
    family: dict[str, Any] | None,
    *,
    world_id: str | None,
    subject_key: str,
) -> None:
    if not family or not world_id:
        return
    current = service.workspace.get_entity_family(family["id"])
    core = dict(current.get("shared_core") or {})
    meta = dict(core.get("_discovery") or {})
    if not meta.get("provisional"):
        return
    branch_ids = _source_branch_ids(service, world_id=world_id, subject_key=subject_key)
    if meta.get("source_branch_ids") == branch_ids and meta.get("source_world_id") == world_id:
        return
    meta["source_branch_ids"] = branch_ids
    meta["source_world_id"] = world_id
    core["_discovery"] = meta
    service.workspace.update_entity_family(
        family["id"], shared_core=core, note="discovery: sync provisional branch visibility"
    )


def repair_proposition_branch_projection(service: DiscoveryService, proposition_id: str) -> None:
    """Project callable sheets/zones into the source instance's actual branch.

    Discovery propositions intentionally stay branch-neutral semantic statements;
    branch visibility lives on source instances. Provisional Library projection
    therefore derives branch from active provenance, and the family keeps a
    rebuildable source-branch list for writer-facing Library/@ visibility.
    """
    prop = service.store.get_proposition(proposition_id)
    instance = _best_active_instance(service, proposition_id)
    if not instance or not prop.get("world_id"):
        return
    branch_id = instance.get("branch_id")
    subject_type = str(prop.get("subject_type") or "")

    if subject_type in SUPPORTED_SHEET_TYPES:
        family, _variant, _created = _ensure_sheet_for(
            service,
            project_id=prop.get("project_id"),
            world_id=prop.get("world_id"),
            branch_id=branch_id,
            subject_type=subject_type,
            subject_key=prop["subject_key"],
            subject_label=prop.get("subject_label") or prop["subject_key"],
        )
        _sync_family_source_branches(
            service, family, world_id=prop.get("world_id"), subject_key=prop["subject_key"]
        )
    elif subject_type == "spatial_zone":
        value = prop.get("value") if isinstance(prop.get("value"), dict) else {}
        _ensure_zone(
            service,
            project_id=prop.get("project_id"),
            world_id=prop.get("world_id"),
            branch_id=branch_id,
            subject_key=prop["subject_key"],
            label=prop.get("subject_label") or prop["subject_key"],
            zone_kind=str(value.get("zone_kind") or "zone"),
            parent_subject_key=value.get("parent_subject_key"),
            attributes=value.get("attributes") if isinstance(value.get("attributes"), dict) else {},
        )

    if prop.get("operation") == "relation" and prop.get("object_key"):
        object_type = str(prop.get("object_type") or "")
        if object_type in SUPPORTED_SHEET_TYPES:
            object_family, _variant, _created = _ensure_sheet_for(
                service,
                project_id=prop.get("project_id"),
                world_id=prop.get("world_id"),
                branch_id=branch_id,
                subject_type=object_type,
                subject_key=prop["object_key"],
                subject_label=prop.get("object_label") or prop["object_key"],
            )
            _sync_family_source_branches(
                service, object_family, world_id=prop.get("world_id"), subject_key=prop["object_key"]
            )
        elif object_type == "spatial_zone":
            with service.store.connection() as con:
                seed = con.execute(
                    "SELECT value_json,subject_label FROM discovery_propositions "
                    "WHERE project_id IS ? AND world_id IS ? AND subject_key=? AND predicate='zone.exists' "
                    "ORDER BY rowid DESC LIMIT 1",
                    (prop.get("project_id"), prop.get("world_id"), prop["object_key"]),
                ).fetchone()
            value = loads(seed["value_json"], {}) if seed else {}
            _ensure_zone(
                service,
                project_id=prop.get("project_id"),
                world_id=prop.get("world_id"),
                branch_id=branch_id,
                subject_key=prop["object_key"],
                label=(seed["subject_label"] if seed else prop.get("object_label")) or prop["object_key"],
                zone_kind=str(value.get("zone_kind") or "zone"),
                parent_subject_key=value.get("parent_subject_key"),
                attributes=value.get("attributes") if isinstance(value.get("attributes"), dict) else {},
            )

    # Change records are derived projections too; scope them using their newest
    # supporting proposition's source instance instead of silently recording main.
    with service.store._lock, service.store.connection() as con:
        con.execute(
            "UPDATE discovery_changes SET branch_id=? WHERE to_proposition_id=?",
            (_branch_storage_id(service.workspace, branch_id), proposition_id),
        )


def repair_turn_branch_projection(service: DiscoveryService, turn_id: str) -> None:
    with service.store.connection() as con:
        rows = con.execute(
            "SELECT DISTINCT proposition_id FROM discovery_instances WHERE source_turn_id=? AND active=1",
            (turn_id,),
        ).fetchall()
    for row in rows:
        repair_proposition_branch_projection(service, str(row["proposition_id"]))


def repair_existing_branch_projections(service: DiscoveryService, limit: int = 10000) -> None:
    with service.store.connection() as con:
        rows = con.execute(
            "SELECT DISTINCT proposition_id FROM discovery_instances WHERE active=1 ORDER BY created_at,id LIMIT ?",
            (max(1, min(int(limit), 50000)),),
        ).fetchall()
    for row in rows:
        repair_proposition_branch_projection(service, str(row["proposition_id"]))


def _scoped_spatial_relations(service: DiscoveryService, context: MemoryQueryContext) -> list[dict[str, Any]]:
    if not context.world_id:
        return []
    predicates = sorted(SPATIAL_RELATIONS)
    marks = ",".join("?" for _ in predicates)
    where = ["world_id=?", "operation='relation'", f"predicate IN ({marks})", "authority_state!='dismissed'"]
    params: list[Any] = [context.world_id, *predicates]
    if context.project_id:
        where.append("(project_id IS NULL OR project_id=?)")
        params.append(context.project_id)
    with service.store.connection() as con:
        rows = con.execute(
            f"SELECT * FROM discovery_propositions WHERE {' AND '.join(where)} ORDER BY rowid ASC",
            params,
        ).fetchall()
    output: list[dict[str, Any]] = []
    for row in rows:
        item = service.evaluate_proposition(service.store._prop_row(row), context, include_instances=False)
        if item.get("knowledge_state") == "canon" or int(item.get("support_count") or 0) > 0:
            output.append(item)
    return output


def _full_spatial_path(service: DiscoveryService, resource_id: str, context: MemoryQueryContext) -> list[dict[str, Any]]:
    family = service.workspace.get_entity_family(resource_id)
    if family.get("entity_type") != "location" or not context.world_id:
        return []
    subject_keys, _ = _resource_context_rows(service, resource_id, context)
    if not subject_keys:
        return []

    relations = _scoped_spatial_relations(service, context)
    zones = _zone_labels(service, context)
    labels: dict[str, str] = {}
    for relation in relations:
        labels[str(relation.get("subject_key") or "")] = str(relation.get("subject_label") or relation.get("subject_key") or "")
        if relation.get("object_key"):
            labels[str(relation["object_key"])] = str(relation.get("object_label") or relation["object_key"])
    for key, zone in zones.items():
        labels[key] = str(zone.get("label") or key)

    hierarchy: dict[str, tuple[str, str]] = {}
    priority = {"located_on": 0, "inside": 1, "part_of": 2, "located_in": 3, "stored_in": 4}
    for relation in relations:
        subject_key = str(relation.get("subject_key") or "")
        object_key = str(relation.get("object_key") or "")
        predicate = str(relation.get("predicate") or "")
        if not subject_key or not object_key or predicate not in SPATIAL_RELATIONS:
            continue
        candidate = (predicate, object_key)
        current = hierarchy.get(subject_key)
        if current is None or priority.get(predicate, 99) < priority.get(current[0], 99):
            hierarchy[subject_key] = candidate

    # Zones are lightweight structural nodes; their parent metadata is a safe
    # fallback even if the dedicated zone→building relation is not part of the
    # sheet's direct relation list.
    for key, zone in zones.items():
        parent = zone.get("parent_subject_key")
        if parent and key not in hierarchy:
            hierarchy[key] = ("part_of", str(parent))

    current_key = str((family.get("shared_core") or {}).get("_discovery", {}).get("subject_key") or subject_keys[0])
    path = [{
        "key": current_key,
        "label": family.get("name") or labels.get(current_key, current_key),
        "type": "location",
    }]
    seen = {current_key}
    cursor = current_key
    for _ in range(12):
        edge = hierarchy.get(cursor)
        if not edge:
            break
        relation, parent_key = edge
        if parent_key in seen:
            break
        seen.add(parent_key)
        zone = zones.get(parent_key)
        path.append({
            "key": parent_key,
            "label": labels.get(parent_key, parent_key),
            "type": "spatial_zone" if zone else "location",
            "relation": relation,
            "zone_kind": zone.get("zone_kind") if zone else None,
        })
        cursor = parent_key
    path.reverse()
    return path


def install_provisional_runtime_fix(service: DiscoveryService) -> None:
    global _INSTALLED
    if getattr(service, "_provisional_runtime_fix_installed", False):
        return

    original_resource_view = service.resource_view
    original_materialize_turn = service.materialize_turn
    original_materialize_existing = service.materialize_existing
    original_promote_canon = service.promote_canon

    def resource_view_with_full_spatial(resource_id: str, context: MemoryQueryContext):
        result = original_resource_view(resource_id, context)
        path = _full_spatial_path(service, resource_id, context)
        if path:
            result["spatial_path"] = path
        return result

    def materialize_turn_with_branch(turn_id: str):
        result = original_materialize_turn(turn_id)
        repair_turn_branch_projection(service, turn_id)
        return result

    def materialize_existing_with_branch(limit: int = 5000):
        result = original_materialize_existing(limit=limit)
        repair_existing_branch_projections(service, max(limit, 10000))
        return result

    def promote_canon_guard(proposition_id: str, context: MemoryQueryContext, *, note: str = ""):
        prop = service.store.get_proposition(proposition_id)
        if prop.get("operation") == "relation" and prop.get("object_type") == "spatial_zone":
            raise ValueError(
                "Lightweight spatial-zone edges are not directly canonizable. "
                "Canonize the scalar floor/slot attribute and the entity-to-entity containment relation instead."
            )
        return original_promote_canon(proposition_id, context, note=note)

    service.resource_view = resource_view_with_full_spatial
    service.materialize_turn = materialize_turn_with_branch
    service.materialize_existing = materialize_existing_with_branch
    service.promote_canon = promote_canon_guard
    repair_existing_branch_projections(service)
    service._provisional_runtime_fix_installed = True
    _INSTALLED = True
