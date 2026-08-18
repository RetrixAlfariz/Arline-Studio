from __future__ import annotations

import json
from typing import Any

from src.workspace.store import WORLD_BIBLE_PROJECT_ID

from .semantics import describe_claim
from .store import make_id, utc_now


def _storage_branch(service, branch_id: str | None) -> str | None:
    if not branch_id:
        return None
    try:
        branch = service.workspace.get_branch(branch_id)
    except Exception:
        return branch_id
    return None if branch.get("kind") == "main" else branch_id


def _resource_exists(service, resource_type: str | None, resource_id: str | None) -> bool:
    if not resource_type or not resource_id:
        return False
    table = {
        "entity_family": "entity_families",
        "relationship": "relationships",
        "fact": "canon_facts",
        "timeline": "timeline_events",
    }.get(resource_type)
    if not table:
        return False
    with service.workspace._connection() as con:
        return con.execute(f"SELECT 1 FROM {table} WHERE id=?", (resource_id,)).fetchone() is not None


def _existing_fact_or_timeline(service, proposition_id: str, kind: str) -> str | None:
    table = "canon_facts" if kind == "fact" else "timeline_events"
    with service.workspace._connection() as con:
        row = con.execute(
            f"SELECT id FROM {table} WHERE source_type='discovery_proposition' AND source_id=? ORDER BY created_at LIMIT 1",
            (proposition_id,),
        ).fetchone()
    return str(row["id"]) if row else None


def _existing_relationship(service, proposition: dict[str, Any], subject_variant_id: str,
                           object_variant_id: str, branch_id: str | None) -> str | None:
    candidates = service.workspace.list_relationships(
        world_id=proposition["world_id"], branch_id=branch_id
    )
    exact = []
    fallback = []
    for item in candidates:
        if item.get("subject_variant_id") != subject_variant_id:
            continue
        if item.get("object_variant_id") != object_variant_id:
            continue
        if item.get("relation_type") != proposition["predicate"]:
            continue
        if (item.get("branch_id") or None) != branch_id:
            continue
        attrs = item.get("attributes") or {}
        if attrs.get("source_proposition_id") == proposition["id"]:
            exact.append(item)
        elif attrs.get("source") == "discovery" and attrs.get("value") == proposition.get("value"):
            fallback.append(item)
    if len(exact) == 1:
        return exact[0]["id"]
    if len(exact) > 1:
        return sorted(exact, key=lambda item: str(item.get("created_at") or ""))[0]["id"]
    # Compatibility recovery for relationships created by the older promotion
    # path, before source_proposition_id was stored explicitly.
    if len(fallback) == 1:
        return fallback[0]["id"]
    return None


def _commit_promotion(service, proposition_id: str, *, resource_type: str | None,
                      resource_id: str | None, family_id: str, note: str) -> dict[str, Any]:
    now = utc_now()
    with service.store._lock, service.store.connection() as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            row = con.execute(
                "SELECT authority_state,materialized_resource_type,materialized_resource_id "
                "FROM discovery_propositions WHERE id=?", (proposition_id,),
            ).fetchone()
            if row is None:
                raise KeyError(proposition_id)
            already_canon = row["authority_state"] == "canon"
            con.execute(
                "UPDATE discovery_propositions SET authority_state='canon',"
                "promoted_at=COALESCE(promoted_at,?),materialized_resource_type=?,materialized_resource_id=?,"
                "target_resource_type='entity_family',target_resource_id=?,updated_at=? WHERE id=?",
                (now, resource_type, resource_id, family_id, now, proposition_id),
            )
            if not already_canon:
                con.execute(
                    "INSERT INTO discovery_decisions(id,proposition_id,action,note,actor,created_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (make_id("DISCDEC"), proposition_id, "canon", note.strip(), "user", now),
                )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    return service.store.get_proposition(proposition_id)


def _rollback_new_materialization(service, resource_type: str | None, resource_id: str | None) -> None:
    if not resource_type or not resource_id:
        return
    try:
        if resource_type == "relationship":
            service.workspace.delete_relationship(resource_id)
            return
        if resource_type == "fact":
            with service.workspace._lock, service.workspace._connection() as con:
                con.execute(
                    "DELETE FROM canon_facts WHERE id=? AND source_type='discovery_proposition'",
                    (resource_id,),
                )
            return
        if resource_type == "timeline":
            with service.workspace._lock, service.workspace._connection() as con:
                con.execute(
                    "DELETE FROM timeline_events WHERE id=? AND source_type='discovery_proposition'",
                    (resource_id,),
                )
    except Exception:
        # Best-effort compensation only. The promotion commit itself has not
        # happened, so any surviving row remains source-tagged and diagnosable.
        pass


def _set_nested(payload: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    output = dict(payload or {})
    keys = [item for item in str(path or "").split(".") if item]
    if not keys:
        return output
    cursor = output
    for key in keys[:-1]:
        child = cursor.get(key)
        if not isinstance(child, dict):
            child = {}
            cursor[key] = child
        cursor = child
    cursor[keys[-1]] = value
    return output


def _project_canon(service, proposition: dict[str, Any], family: dict[str, Any],
                   variant: dict[str, Any] | None) -> dict[str, Any]:
    semantics = describe_claim(proposition)
    projection = semantics.get("projection")
    path = semantics.get("projection_path")

    if proposition.get("predicate") == "entity.exists":
        current = service.workspace.get_entity_family(family["id"])
        core = dict(current.get("shared_core") or {})
        discovery = dict(core.get("_discovery") or {})
        discovery["identity_state"] = "canon"
        core["_discovery"] = discovery
        service.workspace.update_entity_family(
            family["id"], shared_core=core, note="discovery: canon identity projection"
        )
        return {"status": "applied", "target": "family.identity"}

    if projection == "family.shared_core" and path:
        current = service.workspace.get_entity_family(family["id"])
        core = _set_nested(current.get("shared_core") or {}, path, proposition.get("value"))
        service.workspace.update_entity_family(
            family["id"], shared_core=core, note="discovery: canon fact projection"
        )
        return {"status": "applied", "target": f"family.shared_core.{path}"}

    if projection and projection.startswith("variant.") and path and variant:
        section = projection.split(".", 1)[1]
        current = service.workspace.get_variant(variant["id"])
        value = _set_nested(current.get(section) or {}, path, proposition.get("value"))
        service.workspace.update_variant(
            variant["id"], note="discovery: canon fact projection", **{section: value}
        )
        return {"status": "applied", "target": f"variant.{section}.{path}"}

    return {"status": "not_required", "target": None}


def _materialize(service, proposition: dict[str, Any], context, branch_id: str | None):
    family, variant = service._ensure_subject_family(proposition, branch_id)
    predicate = proposition["predicate"]
    value = proposition.get("value")
    resource_type: str | None = None
    resource_id: str | None = None
    created = False

    old_type = proposition.get("materialized_resource_type")
    old_id = proposition.get("materialized_resource_id")
    if _resource_exists(service, old_type, old_id):
        return family, variant, old_type, old_id, False

    if proposition["operation"] == "create" and predicate == "entity.exists":
        return family, variant, "entity_family", family["id"], False

    if proposition["operation"] == "relation" and proposition.get("object_key"):
        object_props = service.store.find_subject_propositions(
            project_id=proposition.get("project_id"), world_id=proposition.get("world_id"),
            subject_key=proposition["object_key"],
        )
        object_seed = next((item for item in object_props if item["predicate"] == "entity.exists"), None)
        if object_seed:
            _object_family, object_variant = service._ensure_subject_family(object_seed, branch_id)
        else:
            object_family = service._existing_family(
                proposition.get("object_label") or proposition["object_key"],
                proposition.get("object_type") or "lore",
            )
            object_variant = (
                service.workspace.resolve_variant(object_family["id"], proposition["world_id"], branch_id)
                if object_family and proposition.get("world_id") else None
            )
        if not variant or not object_variant or not proposition.get("world_id"):
            raise ValueError("Relation cannot be canonized until both scoped entity variants exist")
        existing = _existing_relationship(
            service, proposition, variant["id"], object_variant["id"], branch_id
        )
        if existing:
            return family, variant, "relationship", existing, False
        relationship = service.workspace.create_relationship(
            proposition["world_id"], variant["id"], object_variant["id"], predicate,
            branch_id=branch_id, canon_status="canon",
            attributes={
                "value": value, "source": "discovery",
                "source_proposition_id": proposition["id"],
            },
        )
        return family, variant, "relationship", relationship["id"], True

    if proposition["operation"] == "transition" and variant:
        best = service._best_visible_instance(proposition, context)
        state_key = predicate.removeprefix("state.")
        if best and (best.get("story_order") is not None or best.get("world_time") is not None):
            existing = _existing_fact_or_timeline(service, proposition["id"], "timeline")
            if existing:
                return family, variant, "timeline", existing, False
            event = service.workspace.add_timeline_event(
                world_id=proposition["world_id"], branch_id=branch_id,
                owner_type="entity_variant", owner_id=variant["id"],
                time_label=str(best.get("world_time") or ""),
                order_key=float(best.get("story_order") or 0.0),
                event_type="discovered_state_transition",
                summary=f"User promoted discovered state: {proposition['subject_label']}.{state_key}",
                state_patch={state_key: value}, source_type="discovery_proposition",
                source_id=proposition["id"], status="canon",
            )
            return family, variant, "timeline", event["id"], True
        existing = _existing_fact_or_timeline(service, proposition["id"], "fact")
        if existing:
            return family, variant, "fact", existing, False
        fact = service.workspace.add_fact(
            WORLD_BIBLE_PROJECT_ID, "entity_variant", variant["id"],
            f"current_state.{state_key}", value,
            world_id=proposition.get("world_id"), branch_id=branch_id,
            status="canon", authority="user_promoted",
            source_type="discovery_proposition", source_id=proposition["id"],
        )
        return family, variant, "fact", fact["id"], True

    owner_type = "entity_variant" if variant else "entity_family"
    owner_id = variant["id"] if variant else family["id"]
    existing = _existing_fact_or_timeline(service, proposition["id"], "fact")
    if existing:
        return family, variant, "fact", existing, False
    fact = service.workspace.add_fact(
        WORLD_BIBLE_PROJECT_ID, owner_type, owner_id, predicate, value,
        world_id=proposition.get("world_id"), branch_id=branch_id,
        status="canon", authority="user_promoted",
        source_type="discovery_proposition", source_id=proposition["id"],
    )
    return family, variant, "fact", fact["id"], True


def install_promotion_hardening(service) -> None:
    if getattr(service, "_promotion_hardening_installed", False):
        return

    original_dismiss = service.dismiss
    original_reset = service.reset_decision

    def promote_canon(proposition_id: str, context, *, note: str = ""):
        proposition = service.store.get_proposition(proposition_id)
        semantics = describe_claim(proposition)
        if not semantics.get("canonizable", True):
            raise ValueError(
                "Lightweight spatial-zone edges cannot become canonical entity relations; "
                "canonize the scalar floor/slot claim and direct containment relation instead"
            )
        if context.project_id and proposition.get("project_id") and context.project_id != proposition.get("project_id"):
            raise ValueError("Discovery proposition belongs to a different project")
        if context.world_id and proposition.get("world_id") and context.world_id != proposition.get("world_id"):
            raise ValueError("Discovery proposition belongs to a different world")

        evaluated = service.evaluate_proposition(proposition, context, include_instances=True)
        if proposition.get("authority_state") != "canon" and int(evaluated.get("support_count") or 0) <= 0:
            raise ValueError("Discovery proposition has no visible evidence in the active branch/chat scope")

        branch_id = _storage_branch(service, context.branch_id)
        family = variant = None
        resource_type = resource_id = None
        created = False
        try:
            family, variant, resource_type, resource_id, created = _materialize(
                service, proposition, context, branch_id
            )
            committed = _commit_promotion(
                service, proposition_id, resource_type=resource_type,
                resource_id=resource_id, family_id=family["id"], note=note,
            )
        except Exception:
            if created:
                _rollback_new_materialization(service, resource_type, resource_id)
            raise

        projection = {"status": "not_required", "target": None}
        try:
            projection = _project_canon(service, committed, family, variant)
            if (
                isinstance(committed.get("value"), str)
                and committed.get("predicate") in {"identity.nickname", "identity.presentation_name"}
                and service.foundation is not None
            ):
                service.foundation.add_alias("entity_family", family["id"], committed["value"])
        except Exception as exc:
            projection = {"status": "failed", "target": None, "error": str(exc)}
            if service.foundation is not None:
                try:
                    service.foundation.log_activity(
                        committed.get("project_id"), "discovery_projection_failed",
                        "discovery_proposition", proposition_id,
                        label=committed.get("subject_label") or proposition_id,
                        detail={"error": str(exc), "materialized": [resource_type, resource_id]},
                    )
                except Exception:
                    pass

        if service.foundation is not None:
            try:
                service.foundation.log_activity(
                    committed.get("project_id"), "discovery_promoted",
                    "discovery_proposition", proposition_id,
                    label=committed.get("subject_label") or proposition_id,
                    detail={
                        "predicate": committed.get("predicate"),
                        "materialized": [resource_type, resource_id],
                        "projection": projection,
                    },
                )
            except Exception:
                pass
        result = service.evaluate_proposition(committed, context, include_instances=True)
        result["projection"] = projection
        return result

    def dismiss(proposition_id: str, context, *, note: str = ""):
        proposition = service.store.get_proposition(proposition_id)
        if proposition.get("authority_state") == "canon" or proposition.get("materialized_resource_id"):
            raise ValueError(
                "A canonized discovery cannot be dismissed from Discovery. Use the canonical Fact/Relationship/Timeline retcon or delete workflow instead."
            )
        return original_dismiss(proposition_id, context, note=note)

    def reset_decision(proposition_id: str, context, *, note: str = ""):
        proposition = service.store.get_proposition(proposition_id)
        if proposition.get("authority_state") == "canon" or proposition.get("materialized_resource_id"):
            raise ValueError(
                "A canonized discovery cannot be reset from Discovery. Use the canonical Fact/Relationship/Timeline retcon or delete workflow instead."
            )
        return original_reset(proposition_id, context, note=note)

    service.promote_canon = promote_canon
    service.dismiss = dismiss
    service.reset_decision = reset_decision
    service._promotion_hardening_installed = True
