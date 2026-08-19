from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from uuid import uuid4

from src.memory.models import MemoryQueryContext
from src.domain_events import get_domain_event_bus
from src.workspace.store import WORLD_BIBLE_PROJECT_ID

from .identity import resolve_existing_family
from .service import DiscoveryService
from .store import checksum, dumps, loads, make_id, utc_now


PROVISIONAL_SCHEMA_VERSION = 1
SUPPORTED_SHEET_TYPES = {"character", "location", "item", "organization", "lore", "world_rule"}
SPATIAL_RELATIONS = {"located_in", "located_on", "part_of", "inside", "stored_in"}


@dataclass(slots=True)
class ProvisionalMaterializationReport:
    sheets: int = 0
    zones: int = 0
    claims: int = 0
    relations: int = 0
    changes: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "sheets": self.sheets,
            "zones": self.zones,
            "claims": self.claims,
            "relations": self.relations,
            "changes": self.changes,
        }


def _branch_storage_id(workspace, branch_id: str | None) -> str | None:
    if not branch_id:
        return None
    try:
        branch = workspace.get_branch(branch_id)
    except Exception:
        return branch_id
    return None if branch.get("kind") == "main" else branch_id


def _ensure_schema(service: DiscoveryService) -> None:
    """Mark the store-owned Provisional schema as available for this service."""
    service._provisional_schema_ready = True


def _resource_subject_links(service: DiscoveryService, resource_id: str) -> list[dict[str, Any]]:
    with service.store.connection() as con:
        rows = con.execute(
            "SELECT project_id,world_id,subject_key,resource_type,resource_id FROM discovery_subject_links "
            "WHERE resource_type='entity_family' AND resource_id=? ORDER BY updated_at DESC",
            (resource_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _existing_family(service: DiscoveryService, label: str, entity_type: str) -> dict[str, Any] | None:
    return resolve_existing_family(service.workspace, service.foundation, label, entity_type)


def _update_target(service: DiscoveryService, proposition_id: str, family_id: str) -> None:
    with service.store._lock, service.store.connection() as con:
        con.execute(
            "UPDATE discovery_propositions SET target_resource_type='entity_family',target_resource_id=?,updated_at=? "
            "WHERE id=?",
            (family_id, utc_now(), proposition_id),
        )


def _ensure_sheet_for(
    service: DiscoveryService,
    *,
    project_id: str | None,
    world_id: str | None,
    branch_id: str | None,
    subject_type: str,
    subject_key: str,
    subject_label: str,
    location_kind: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, bool]:
    mapped = subject_type if subject_type in SUPPORTED_SHEET_TYPES else None
    if mapped is None:
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
    if family is None:
        family = _existing_family(service, subject_label, mapped)
    if family is None:
        core: dict[str, Any] = {
            "_discovery": {
                "provisional": True,
                "subject_key": subject_key,
                "identity_state": "detected",
            }
        }
        if mapped == "location" and location_kind:
            core["kind"] = location_kind
        family = service.workspace.create_entity_family(
            None,
            subject_label,
            entity_type=mapped,
            description="Provisional sheet discovered indirectly from narrative evidence.",
            shared_core=core,
            create_variant_in_world=world_id,
            branch_id=_branch_storage_id(service.workspace, branch_id),
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
        storage_branch = _branch_storage_id(service.workspace, branch_id)
        variant = service.workspace.resolve_variant(family["id"], world_id, storage_branch)
        if variant is None:
            variant = service.workspace.create_variant(
                family["id"],
                world_id,
                branch_id=storage_branch,
                canon_status="draft",
                summary="Provisional narrative discovery.",
            )

    if mapped == "location" and location_kind:
        current = service.workspace.get_entity_family(family["id"])
        core = dict(current.get("shared_core") or {})
        # Discovery may fill a missing type, but never overwrite a user-authored one.
        if not core.get("kind"):
            core["kind"] = location_kind
            service.workspace.update_entity_family(
                family["id"], shared_core=core, note="discovery: project location kind"
            )

    return family, variant, created


def _ensure_zone(
    service: DiscoveryService,
    *,
    project_id: str | None,
    world_id: str | None,
    branch_id: str | None,
    subject_key: str,
    label: str,
    zone_kind: str,
    parent_subject_key: str | None = None,
    attributes: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, bool]:
    if not world_id:
        return None, False
    storage_branch = _branch_storage_id(service.workspace, branch_id)
    now = utc_now()
    with service.store._lock, service.store.connection() as con:
        row = con.execute(
            "SELECT * FROM discovery_spatial_zones WHERE world_id=? AND branch_id IS ? AND subject_key=?",
            (world_id, storage_branch, subject_key),
        ).fetchone()
        if row:
            con.execute(
                "UPDATE discovery_spatial_zones SET label=?,zone_kind=?,parent_subject_key=COALESCE(?,parent_subject_key),"
                "attributes_json=?,updated_at=? WHERE id=?",
                (label, zone_kind, parent_subject_key, dumps(attributes or loads(row["attributes_json"], {})), now, row["id"]),
            )
            zone_id = row["id"]
            created = False
        else:
            zone_id = make_id("ZONE")
            con.execute(
                "INSERT INTO discovery_spatial_zones(id,project_id,world_id,branch_id,subject_key,label,zone_kind,"
                "parent_subject_key,attributes_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    zone_id, project_id, world_id, storage_branch, subject_key, label,
                    zone_kind, parent_subject_key, dumps(attributes or {}), now, now,
                ),
            )
            created = True
        result = con.execute(
            "SELECT * FROM discovery_spatial_zones WHERE id=?", (zone_id,)
        ).fetchone()
    item = dict(result)
    item["attributes"] = loads(item.pop("attributes_json"), {})
    return item, created


def _location_kind_for(service: DiscoveryService, proposition: dict[str, Any]) -> str | None:
    value = proposition.get("value")
    if proposition.get("predicate") == "location.kind" and isinstance(value, str):
        return value
    if proposition.get("predicate") == "entity.exists" and isinstance(value, dict):
        raw = value.get("location_kind") or value.get("kind")
        return str(raw) if raw else None
    with service.store.connection() as con:
        row = con.execute(
            "SELECT value_json FROM discovery_propositions WHERE project_id IS ? AND world_id IS ? "
            "AND subject_key=? AND predicate='location.kind' ORDER BY rowid DESC LIMIT 1",
            (proposition.get("project_id"), proposition.get("world_id"), proposition["subject_key"]),
        ).fetchone()
    if row:
        raw = loads(row["value_json"], None)
        return str(raw) if raw else None
    return None


def _record_change(service: DiscoveryService, proposition: dict[str, Any]) -> str | None:
    predicate = str(proposition.get("predicate") or "")
    if predicate in {"entity.exists", "zone.exists"} or proposition.get("operation") == "relation":
        return None
    with service.store._lock, service.store.connection() as con:
        current = con.execute(
            "SELECT rowid,value_json FROM discovery_propositions WHERE id=?", (proposition["id"],)
        ).fetchone()
        if current is None:
            return None
        previous = con.execute(
            "SELECT id,value_json,operation FROM discovery_propositions WHERE project_id IS ? AND world_id IS ? "
            "AND subject_type=? AND subject_key=? AND predicate=? AND rowid<? "
            "AND authority_state!='dismissed' ORDER BY rowid DESC LIMIT 1",
            (
                proposition.get("project_id"), proposition.get("world_id"),
                proposition.get("subject_type"), proposition.get("subject_key"), predicate,
                current["rowid"],
            ),
        ).fetchone()
        if previous is None or str(previous["value_json"]) == str(current["value_json"]):
            return None
        operation = str(proposition.get("operation") or "update")
        if operation == "correction":
            kind = "user_correction"
        elif operation == "transition" or predicate.startswith("state."):
            kind = "state_transition"
        else:
            kind = "observed_revision"
        existing = con.execute(
            "SELECT id FROM discovery_changes WHERE from_proposition_id=? AND to_proposition_id=? AND change_kind=?",
            (previous["id"], proposition["id"], kind),
        ).fetchone()
        if existing:
            return existing["id"]
        change_id = make_id("CHANGE")
        con.execute(
            "INSERT INTO discovery_changes(id,project_id,world_id,branch_id,subject_key,predicate,"
            "from_proposition_id,to_proposition_id,change_kind,source_type,source_id,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                change_id, proposition.get("project_id"), proposition.get("world_id"),
                proposition.get("branch_id"), proposition["subject_key"], predicate,
                previous["id"], proposition["id"], kind,
                "discovery", proposition["id"], utc_now(),
            ),
        )
        return change_id


def _materialize_proposition(service: DiscoveryService, proposition_id: str) -> ProvisionalMaterializationReport:
    _ensure_schema(service)
    prop = service.store.get_proposition(proposition_id)
    report = ProvisionalMaterializationReport(claims=1)
    if prop.get("authority_state") == "dismissed":
        return report

    subject_type = str(prop.get("subject_type") or "")
    location_kind = _location_kind_for(service, prop) if subject_type == "location" else None
    if subject_type == "spatial_zone":
        value = prop.get("value") if isinstance(prop.get("value"), dict) else {}
        _, created = _ensure_zone(
            service,
            project_id=prop.get("project_id"), world_id=prop.get("world_id"),
            branch_id=prop.get("branch_id"), subject_key=prop["subject_key"],
            label=prop.get("subject_label") or prop["subject_key"],
            zone_kind=str(value.get("zone_kind") or "zone"),
            parent_subject_key=value.get("parent_subject_key"),
            attributes=value.get("attributes") if isinstance(value.get("attributes"), dict) else {},
        )
        report.zones += int(created)
    else:
        family, _variant, created = _ensure_sheet_for(
            service,
            project_id=prop.get("project_id"), world_id=prop.get("world_id"),
            branch_id=prop.get("branch_id"), subject_type=subject_type,
            subject_key=prop["subject_key"], subject_label=prop.get("subject_label") or prop["subject_key"],
            location_kind=location_kind,
        )
        if family:
            _update_target(service, prop["id"], family["id"])
            report.sheets += int(created)

    if prop.get("operation") == "relation" and prop.get("object_key"):
        object_type = str(prop.get("object_type") or "")
        if object_type == "spatial_zone":
            zone_value: dict[str, Any] = {}
            with service.store.connection() as con:
                seed = con.execute(
                    "SELECT value_json,subject_label FROM discovery_propositions WHERE project_id IS ? AND world_id IS ? "
                    "AND subject_key=? AND predicate='zone.exists' ORDER BY rowid DESC LIMIT 1",
                    (prop.get("project_id"), prop.get("world_id"), prop["object_key"]),
                ).fetchone()
            if seed:
                zone_value = loads(seed["value_json"], {}) if seed["value_json"] else {}
                label = seed["subject_label"]
            else:
                label = prop.get("object_label") or prop["object_key"]
            _, created = _ensure_zone(
                service,
                project_id=prop.get("project_id"), world_id=prop.get("world_id"),
                branch_id=prop.get("branch_id"), subject_key=prop["object_key"], label=label,
                zone_kind=str(zone_value.get("zone_kind") or "zone"),
                parent_subject_key=zone_value.get("parent_subject_key"),
                attributes=zone_value.get("attributes") if isinstance(zone_value.get("attributes"), dict) else {},
            )
            report.zones += int(created)
        elif object_type in SUPPORTED_SHEET_TYPES:
            _family, _variant, created = _ensure_sheet_for(
                service,
                project_id=prop.get("project_id"), world_id=prop.get("world_id"),
                branch_id=prop.get("branch_id"), subject_type=object_type,
                subject_key=prop["object_key"],
                subject_label=prop.get("object_label") or prop["object_key"],
            )
            report.sheets += int(created)
        report.relations += 1

    change_id = _record_change(service, prop)
    report.changes += int(bool(change_id))
    return report


def _turn_proposition_ids(service: DiscoveryService, turn_id: str) -> list[str]:
    with service.store.connection() as con:
        rows = con.execute(
            "SELECT DISTINCT proposition_id FROM discovery_instances WHERE source_turn_id=? AND active=1 ORDER BY created_at,id",
            (turn_id,),
        ).fetchall()
    return [str(row["proposition_id"]) for row in rows]


def materialize_turn(service: DiscoveryService, turn_id: str) -> dict[str, Any]:
    total = ProvisionalMaterializationReport()
    for prop_id in _turn_proposition_ids(service, turn_id):
        item = _materialize_proposition(service, prop_id)
        for field in ("sheets", "zones", "claims", "relations", "changes"):
            setattr(total, field, getattr(total, field) + getattr(item, field))
    return total.to_dict()


def materialize_existing(service: DiscoveryService, *, limit: int = 5000) -> dict[str, Any]:
    _ensure_schema(service)
    with service.store.connection() as con:
        rows = con.execute(
            "SELECT DISTINCT p.id FROM discovery_propositions p JOIN discovery_instances i ON i.proposition_id=p.id "
            "WHERE i.active=1 AND p.authority_state!='dismissed' ORDER BY p.rowid ASC LIMIT ?",
            (max(1, min(int(limit), 20000)),),
        ).fetchall()
    total = ProvisionalMaterializationReport()
    for row in rows:
        item = _materialize_proposition(service, row["id"])
        for field in ("sheets", "zones", "claims", "relations", "changes"):
            setattr(total, field, getattr(total, field) + getattr(item, field))
    return total.to_dict()


def _visible_user_edit(instance: dict[str, Any], context: MemoryQueryContext) -> bool:
    if not instance.get("active"):
        return False
    if context.project_id and instance.get("project_id") not in {None, context.project_id}:
        return False
    if context.world_id and instance.get("world_id") not in {None, context.world_id}:
        return False
    if context.branch_id and instance.get("branch_id") not in {None, context.branch_id}:
        return False
    return True


def _resource_context_rows(service: DiscoveryService, resource_id: str, context: MemoryQueryContext) -> tuple[list[str], list[dict[str, Any]]]:
    links = _resource_subject_links(service, resource_id)
    scoped = [
        row for row in links
        if (not context.project_id or row.get("project_id") in {None, "", context.project_id})
        and (not context.world_id or row.get("world_id") in {None, "", context.world_id})
    ]
    keys = sorted({str(row["subject_key"]) for row in (scoped or links)})
    return keys, scoped or links


def _zone_labels(service: DiscoveryService, context: MemoryQueryContext) -> dict[str, dict[str, Any]]:
    if not context.world_id:
        return {}
    storage_branch = _branch_storage_id(service.workspace, context.branch_id)
    with service.store.connection() as con:
        rows = con.execute(
            "SELECT * FROM discovery_spatial_zones WHERE world_id=? AND (branch_id IS NULL OR branch_id IS ?) ORDER BY created_at",
            (context.world_id, storage_branch),
        ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        item = dict(row)
        item["attributes"] = loads(item.pop("attributes_json"), {})
        out[item["subject_key"]] = item
    return out


def resource_view(service: DiscoveryService, resource_id: str, context: MemoryQueryContext) -> dict[str, Any]:
    family = service.workspace.get_entity_family(resource_id)
    subject_keys, _links = _resource_context_rows(service, resource_id, context)
    if not subject_keys:
        return {
            "resource": family, "provisional": False, "knowledge_state": None,
            "claims": [], "relations": [], "changes": [], "spatial_path": [],
        }

    placeholders = ",".join("?" for _ in subject_keys)
    with service.store.connection() as con:
        rows = con.execute(
            f"SELECT * FROM discovery_propositions WHERE (subject_key IN ({placeholders}) OR object_key IN ({placeholders})) "
            "AND authority_state!='dismissed' ORDER BY rowid ASC",
            [*subject_keys, *subject_keys],
        ).fetchall()
    evaluated: list[dict[str, Any]] = []
    for row in rows:
        item = service.evaluate_proposition(service.store._prop_row(row), context, include_instances=True)
        if item["knowledge_state"] == "canon" or item["support_count"] > 0:
            evaluated.append(item)

    subject_claims = [item for item in evaluated if item["subject_key"] in subject_keys and item["operation"] != "relation"]
    relations = [item for item in evaluated if item["operation"] == "relation"]
    prop_ids = [item["id"] for item in evaluated]
    changes: list[dict[str, Any]] = []
    if prop_ids:
        marks = ",".join("?" for _ in prop_ids)
        with service.store.connection() as con:
            change_rows = con.execute(
                f"SELECT * FROM discovery_changes WHERE from_proposition_id IN ({marks}) OR to_proposition_id IN ({marks}) "
                "ORDER BY created_at,id",
                [*prop_ids, *prop_ids],
            ).fetchall()
        changes = [dict(row) for row in change_rows]

    labels: dict[str, str] = {}
    for item in evaluated:
        labels[item["subject_key"]] = item.get("subject_label") or item["subject_key"]
        if item.get("object_key"):
            labels[item["object_key"]] = item.get("object_label") or item["object_key"]
    zones = _zone_labels(service, context)
    for key, zone in zones.items():
        labels[key] = zone["label"]

    current_key = subject_keys[0]
    hierarchy: dict[str, tuple[str, str]] = {}
    priority = {"located_on": 0, "inside": 1, "part_of": 2, "located_in": 3, "stored_in": 4}
    for item in relations:
        if item.get("subject_key") and item.get("object_key") and item.get("predicate") in SPATIAL_RELATIONS:
            key = item["subject_key"]
            candidate = (item["predicate"], item["object_key"])
            if key not in hierarchy or priority.get(candidate[0], 99) < priority.get(hierarchy[key][0], 99):
                hierarchy[key] = candidate

    path = [{"key": current_key, "label": family.get("name") or labels.get(current_key, current_key), "type": family.get("entity_type") or "location"}]
    seen = {current_key}
    cursor = current_key
    for _ in range(8):
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

    identity = next((item for item in subject_claims if item["predicate"] == "entity.exists"), None)
    core = family.get("shared_core") or {}
    provisional = bool((core.get("_discovery") or {}).get("provisional"))
    continuity_payload = {
        "current": {"version": "1.2.2a1", "heads": [], "ambiguous": [], "superseded_proposition_ids": []},
        "forms": [], "history": [], "events": [], "conflicts": [], "mentions": [],
    }
    resolver = getattr(service, "continuity", None)
    if resolver is not None:
        seen_heads: set[str] = set()
        seen_forms: set[str] = set()
        seen_history: set[str] = set()
        seen_events: set[str] = set()
        seen_conflicts: set[str] = set()
        seen_mentions: set[str] = set()
        for key in subject_keys:
            current = resolver.current_view(context, subject_key=key)
            for head in current.get("heads", []):
                if head["id"] not in seen_heads:
                    continuity_payload["current"]["heads"].append(head); seen_heads.add(head["id"])
            continuity_payload["current"]["ambiguous"].extend(current.get("ambiguous", []))
            continuity_payload["current"]["superseded_proposition_ids"].extend(current.get("superseded_proposition_ids", []))
            for item in resolver.list_forms(context, subject_key=key):
                if item["id"] not in seen_forms:
                    continuity_payload["forms"].append(item); seen_forms.add(item["id"])
            for item in resolver.change_history(context, subject_key=key):
                if item["id"] not in seen_history:
                    continuity_payload["history"].append(item); seen_history.add(item["id"])
            for item in resolver.list_events(context, subject_key=key):
                if item["id"] not in seen_events:
                    continuity_payload["events"].append(item); seen_events.add(item["id"])
            for item in resolver.list_conflicts(context, subject_key=key, include_resolved=True):
                if item["id"] not in seen_conflicts:
                    continuity_payload["conflicts"].append(item); seen_conflicts.add(item["id"])
            for item in service.store.list_mentions_for_subject(
                project_id=context.project_id, world_id=context.world_id, subject_key=key, limit=80
            ):
                if item["id"] not in seen_mentions:
                    continuity_payload["mentions"].append(item); seen_mentions.add(item["id"])
        continuity_payload["current"]["superseded_proposition_ids"] = sorted(set(continuity_payload["current"]["superseded_proposition_ids"]))
    return {
        "resource": family,
        "provisional": provisional,
        "knowledge_state": identity.get("knowledge_state") if identity else "detected",
        "claims": subject_claims,
        "relations": relations,
        "changes": changes,
        "spatial_path": path if family.get("entity_type") == "location" else [],
        "zones": list(zones.values()),
        "continuity": continuity_payload,
    }


def _find_link_context(service: DiscoveryService, family_id: str, world_id: str | None) -> dict[str, Any] | None:
    links = _resource_subject_links(service, family_id)
    return next((row for row in links if not world_id or row.get("world_id") == world_id), links[0] if links else None)


def _flatten_changes(before: Any, after: Any, prefix: str = "") -> list[tuple[str, Any]]:
    if isinstance(before, dict) and isinstance(after, dict):
        out: list[tuple[str, Any]] = []
        for key in sorted(set(before) | set(after)):
            path = f"{prefix}.{key}" if prefix else str(key)
            if before.get(key) == after.get(key):
                continue
            if isinstance(before.get(key), dict) and isinstance(after.get(key), dict):
                out.extend(_flatten_changes(before.get(key), after.get(key), path))
            else:
                out.append((path, after.get(key)))
        return out
    return [(prefix, after)] if before != after and prefix else []


def record_user_variant_edit(service: DiscoveryService, before: dict[str, Any], after: dict[str, Any], changes: dict[str, Any]) -> int:
    link = _find_link_context(service, after["family_id"], after.get("world_id"))
    if not link:
        return 0
    subject_key = link["subject_key"]
    project_id = link.get("project_id") or None
    world_id = after.get("world_id")
    branch_id = after.get("branch_id")
    edit_id = f"EDIT-{uuid4().hex[:12].upper()}"
    count = 0
    sections = {
        "attributes": "",
        "voice": "voice.",
        "knowledge": "knowledge.",
        "beliefs": "beliefs.",
        "current_state": "state.",
    }
    for section, prefix in sections.items():
        if section not in changes:
            continue
        old_value = before.get(section) or {}
        new_value = after.get(section) or {}
        for path, value in _flatten_changes(old_value, new_value):
            predicate = prefix + path
            prop = service.store.upsert_proposition(
                project_id=project_id,
                world_id=world_id,
                subject_type=after.get("entity_type") or "entity",
                subject_key=subject_key,
                subject_label=after.get("family_name") or after.get("display_name") or subject_key,
                predicate=predicate,
                value=value,
                operation="correction",
                temporal_state="current_or_unspecified",
                target_resource_type="entity_family",
                target_resource_id=after["family_id"],
            )
            service.store.add_instance(
                prop["id"],
                source_kind="user_library_edit",
                source_session_id=None,
                source_turn_id=None,
                origin_session_id=None,
                origin_turn_id=f"{edit_id}:{predicate}",
                source_revision=checksum(dumps(value)),
                project_id=project_id,
                world_id=world_id,
                branch_id=branch_id,
                span_text=f"User corrected {predicate} in Library",
                extraction_confidence=1.0,
                explicitness="explicit",
                qualifies_review=True,
            )
            _materialize_proposition(service, prop["id"])
            count += 1
    return count


def record_explicit_edit(
    service: DiscoveryService,
    proposition_id: str,
    value: Any,
    context: MemoryQueryContext,
    *,
    mode: str = "correction",
) -> dict[str, Any]:
    if mode not in {"correction", "story_change"}:
        raise ValueError("mode must be correction or story_change")
    old = service.store.get_proposition(proposition_id)
    operation = "transition" if mode == "story_change" else "correction"
    new = service.store.upsert_proposition(
        project_id=old.get("project_id"), world_id=old.get("world_id"),
        subject_type=old["subject_type"], subject_key=old["subject_key"],
        subject_label=old["subject_label"], predicate=old["predicate"], value=value,
        object_type=old.get("object_type"), object_key=old.get("object_key"),
        object_label=old.get("object_label"), operation=operation,
        temporal_state="historical_or_current" if mode == "story_change" else "current_or_unspecified",
        target_resource_type=old.get("target_resource_type"), target_resource_id=old.get("target_resource_id"),
    )
    edit_id = f"EDIT-{uuid4().hex[:12].upper()}"
    service.store.add_instance(
        new["id"], source_kind="user_library_edit",
        source_session_id=context.session_id, source_turn_id=None,
        origin_session_id=context.session_id, origin_turn_id=edit_id,
        source_revision=checksum(dumps(value)), project_id=context.project_id or old.get("project_id"),
        world_id=context.world_id or old.get("world_id"), branch_id=context.branch_id,
        world_time=context.world_time, story_order=context.story_order,
        span_text=f"User {mode.replace('_', ' ')} of {old['predicate']}",
        extraction_confidence=1.0, explicitness="explicit", qualifies_review=True,
    )
    _materialize_proposition(service, new["id"])
    return service.evaluate_proposition(new, context, include_instances=True)


def bind_workspace_edit_hooks(service: DiscoveryService) -> None:
    if getattr(service, "_provisional_workspace_hooks_bound", False):
        return

    def variant_updated(event) -> None:
        payload = event.payload
        note = str(payload.get("note") or "updated")
        if note.startswith("discovery:"):
            return
        before = payload.get("before") or {}
        after = payload.get("after") or {}
        changes = payload.get("changes") or {}
        if not after:
            return
        record_user_variant_edit(service, before, after, changes)

    def family_updated(event) -> None:
        payload = event.payload
        note = str(payload.get("note") or "updated")
        if note.startswith("discovery:"):
            return
        before = payload.get("before") or {}
        after = payload.get("after") or {}
        changes = payload.get("changes") or {}
        family_id = after.get("id")
        new_name = changes.get("name")
        if not family_id or not new_name or new_name == before.get("name"):
            return

        links = _resource_subject_links(service, family_id)
        keys = [row["subject_key"] for row in links]
        if keys:
            marks = ",".join("?" for _ in keys)
            with service.store._lock, service.store.connection() as con:
                con.execute(
                    f"UPDATE discovery_propositions SET subject_label=?,updated_at=? "
                    f"WHERE subject_key IN ({marks})",
                    [after["name"], utc_now(), *keys],
                )
                con.execute(
                    f"UPDATE discovery_propositions SET object_label=?,updated_at=? "
                    f"WHERE object_key IN ({marks})",
                    [after["name"], utc_now(), *keys],
                )
        if service.foundation is not None and before.get("name"):
            service.foundation.add_alias("entity_family", family_id, before["name"])

    event_bus = get_domain_event_bus(service.workspace.path)
    event_bus.subscribe(
        "workspace.variant_updated",
        variant_updated,
        key="discovery.provisional.variant_updated",
    )
    event_bus.subscribe(
        "workspace.entity_family_updated",
        family_updated,
        key="discovery.provisional.family_updated",
    )
    service._provisional_workspace_hooks_bound = True


def install_provisional_discovery(service: DiscoveryService) -> None:
    if getattr(service, "_provisional_installed", False):
        return
    _ensure_schema(service)

    original_capture_turn = service.capture_turn
    original_instance_allowed = service._instance_allowed
    original_evaluate = service.evaluate_proposition
    original_memory_candidates = service.memory_candidates

    def capture_turn_with_materialization(turn_id: str, *, source_kind: str = "user_prompt"):
        report = original_capture_turn(turn_id, source_kind=source_kind)
        materialize_turn(service, turn_id)
        return report

    def instance_allowed_with_user_edit(instance: dict[str, Any], context: MemoryQueryContext) -> bool:
        if instance.get("source_kind") == "user_library_edit":
            return _visible_user_edit(instance, context)
        return original_instance_allowed(instance, context)

    def evaluate_with_user_review(proposition: dict[str, Any], context: MemoryQueryContext, *, include_instances: bool = False):
        item = original_evaluate(proposition, context, include_instances=True)
        visible_ids = set(item.get("visible_instance_ids") or [])
        has_user_edit = any(
            inst.get("id") in visible_ids and inst.get("source_kind") == "user_library_edit" and inst.get("active")
            for inst in item.get("instances") or []
        )
        if has_user_edit and item.get("knowledge_state") == "detected":
            item["knowledge_state"] = "reviewed"
            item["review_reason"] = "explicit_user_library_edit"
        if not include_instances:
            item.pop("instances", None)
            item.pop("visible_instance_ids", None)
        return item

    def memory_candidates_with_relation_labels(plan):
        candidates = original_memory_candidates(plan)
        for candidate in candidates:
            if not str(candidate.id).startswith("DISCOVERY:"):
                continue
            prop_id = str(candidate.id).split(":", 1)[1]
            try:
                prop = service.store.get_proposition(prop_id)
            except Exception:
                continue
            if prop.get("operation") == "relation" and prop.get("object_label"):
                state = str(candidate.metadata.get("knowledge_state") or "detected").upper()
                candidate.text = (
                    f"[{state} NON-CANON] {prop.get('subject_label')} "
                    f"{prop.get('predicate')} {prop.get('object_label')}"
                )
        return candidates

    service.capture_turn = capture_turn_with_materialization
    service._instance_allowed = instance_allowed_with_user_edit
    service.evaluate_proposition = evaluate_with_user_review
    service.memory_candidates = memory_candidates_with_relation_labels
    service.materialize_turn = lambda turn_id: materialize_turn(service, turn_id)
    service.materialize_existing = lambda limit=5000: materialize_existing(service, limit=limit)
    service.resource_view = lambda resource_id, context: resource_view(service, resource_id, context)
    service.record_explicit_edit = lambda proposition_id, value, context, mode="correction": record_explicit_edit(
        service, proposition_id, value, context, mode=mode
    )

    bind_workspace_edit_hooks(service)
    # Existing discoveries become callable sheets immediately after upgrade.
    materialize_existing(service)
    service._provisional_installed = True
