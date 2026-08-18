from __future__ import annotations

from .store import utc_now


IMMUTABLE_ITEM_IDENTITY_PREDICATES = {"entity.exists", "item.kind", "garment.type"}


def install_safe_anaphora_merge(refinement_module) -> None:
    if getattr(refinement_module, "_SAFE_ITEM_MERGE_INSTALLED", False):
        return

    def merge_turn_subject(service, *, from_key: str, to_key: str, turn_id: str,
                           source_kind: str, revision: str) -> int:
        if from_key == to_key:
            return 0
        target_label = refinement_module._target_label(service, to_key)
        with service.store.connection() as con:
            rows = con.execute(
                "SELECT i.* FROM discovery_instances i "
                "JOIN discovery_propositions p ON p.id=i.proposition_id "
                "WHERE i.source_turn_id=? AND i.source_kind=? AND i.source_revision=? AND i.active=1 "
                "AND (p.subject_key=? OR p.object_key=?) ORDER BY i.created_at,i.id",
                (turn_id, source_kind, revision, from_key, from_key),
            ).fetchall()

        moved = 0
        source_instance_ids: list[str] = []
        for row in rows:
            instance = service.store._instance_row(row)
            prop = service.store.get_proposition(instance["proposition_id"])
            source_instance_ids.append(instance["id"])
            if (
                prop.get("subject_key") == from_key
                and prop.get("predicate") in IMMUTABLE_ITEM_IDENTITY_PREDICATES
            ):
                # The secondary ITEM identity is discarded; never copy its own
                # physical id/classification records onto the antecedent ITEM.
                continue
            subject_key = to_key if prop.get("subject_key") == from_key else prop.get("subject_key")
            object_key = to_key if prop.get("object_key") == from_key else prop.get("object_key")
            subject_label = target_label if prop.get("subject_key") == from_key else prop.get("subject_label")
            object_label = target_label if prop.get("object_key") == from_key else prop.get("object_label")
            new_prop = service.store.upsert_proposition(
                project_id=prop.get("project_id"), world_id=prop.get("world_id"),
                subject_type=prop.get("subject_type") or "garment",
                subject_key=subject_key, subject_label=subject_label,
                predicate=prop.get("predicate") or "related_to", value=prop.get("value"),
                object_type=prop.get("object_type"), object_key=object_key,
                object_label=object_label, operation=prop.get("operation") or "update",
                temporal_state=prop.get("temporal_state") or "current_or_unspecified",
                target_resource_type=prop.get("target_resource_type"),
                target_resource_id=prop.get("target_resource_id"),
            )
            refinement_module._copy_instance(service, instance, new_prop["id"])
            moved += 1

        if source_instance_ids:
            marks = ",".join("?" for _ in source_instance_ids)
            with service.store._lock, service.store.connection() as con:
                con.execute(
                    f"UPDATE discovery_instances SET active=0,"
                    f"invalidation_reason='explicit_anaphora_merged',updated_at=? WHERE id IN ({marks})",
                    [utc_now(), *source_instance_ids],
                )
        refinement_module._retire_subject_family(service, from_key)
        return moved

    refinement_module._merge_turn_subject = merge_turn_subject
    refinement_module._SAFE_ITEM_MERGE_INSTALLED = True
