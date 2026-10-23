from __future__ import annotations

from typing import Any

from . import provisional as p
from .provisional_runtime import _best_active_instance, _sync_family_source_branches
from .service import DiscoveryService
from .store import loads


def materialize_proposition_branch_aware(
    service: DiscoveryService, proposition_id: str
) -> p.ProvisionalMaterializationReport:
    """Materialize one semantic proposition using its active provenance branch.

    Propositions are deliberately branch-neutral; their source instances are not.
    The original v1.2.1 provisional draft used proposition.branch_id (which does
    not exist) and could create a base/main variant before later repair. This
    function is installed before the first startup/backfill materialization so
    branch-only discoveries never acquire a ghost base variant in the first place.
    """
    p._ensure_schema(service)
    prop = service.store.get_proposition(proposition_id)
    report = p.ProvisionalMaterializationReport(claims=1)
    if prop.get("authority_state") == "dismissed":
        return report

    instance = _best_active_instance(service, proposition_id)
    branch_id = instance.get("branch_id") if instance else None
    subject_type = str(prop.get("subject_type") or "")
    location_kind = p._location_kind_for(service, prop) if subject_type == "location" else None

    if subject_type == "spatial_zone":
        value = prop.get("value") if isinstance(prop.get("value"), dict) else {}
        _, created = p._ensure_zone(
            service,
            project_id=prop.get("project_id"), world_id=prop.get("world_id"),
            branch_id=branch_id, subject_key=prop["subject_key"],
            label=prop.get("subject_label") or prop["subject_key"],
            zone_kind=str(value.get("zone_kind") or "zone"),
            parent_subject_key=value.get("parent_subject_key"),
            attributes=value.get("attributes") if isinstance(value.get("attributes"), dict) else {},
        )
        report.zones += int(created)
    else:
        family, _variant, created = p._ensure_sheet_for(
            service,
            project_id=prop.get("project_id"), world_id=prop.get("world_id"),
            branch_id=branch_id, subject_type=subject_type,
            subject_key=prop["subject_key"],
            subject_label=prop.get("subject_label") or prop["subject_key"],
            location_kind=location_kind,
        )
        if family:
            p._update_target(service, prop["id"], family["id"])
            _sync_family_source_branches(
                service, family, world_id=prop.get("world_id"), subject_key=prop["subject_key"]
            )
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
            _, created = p._ensure_zone(
                service,
                project_id=prop.get("project_id"), world_id=prop.get("world_id"),
                branch_id=branch_id, subject_key=prop["object_key"], label=label,
                zone_kind=str(zone_value.get("zone_kind") or "zone"),
                parent_subject_key=zone_value.get("parent_subject_key"),
                attributes=zone_value.get("attributes") if isinstance(zone_value.get("attributes"), dict) else {},
            )
            report.zones += int(created)
        elif object_type in p.SUPPORTED_SHEET_TYPES:
            object_family, _variant, created = p._ensure_sheet_for(
                service,
                project_id=prop.get("project_id"), world_id=prop.get("world_id"),
                branch_id=branch_id, subject_type=object_type,
                subject_key=prop["object_key"],
                subject_label=prop.get("object_label") or prop["object_key"],
            )
            _sync_family_source_branches(
                service, object_family, world_id=prop.get("world_id"), subject_key=prop["object_key"]
            )
            report.sheets += int(created)
        report.relations += 1

    change_id = p._record_change(service, {**prop, "branch_id": branch_id})
    report.changes += int(bool(change_id))
    return report
