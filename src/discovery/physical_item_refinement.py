from __future__ import annotations

from typing import Any

from src.narrative.rails import CharacterRailParser

from . import physical_items as items
from .store import loads, utc_now


GENERIC_CHARACTER_LABELS = {"self", "character", "person", "someone", "unknown"}


def _install_session_character_fallback(service) -> None:
    if getattr(items, "_SESSION_CHARACTER_FALLBACK_INSTALLED", False):
        return
    original = items._current_turn_character

    def current_turn_character(service_obj, turn_id: str, source_kind: str):
        key, label = original(service_obj, turn_id, source_kind)
        if key and label and str(label).casefold() not in GENERIC_CHARACTER_LABELS:
            return key, label
        with service_obj.store.connection() as con:
            source = con.execute(
                "SELECT source_session_id FROM discovery_instances WHERE source_turn_id=? AND source_kind=? "
                "ORDER BY created_at DESC LIMIT 1",
                (turn_id, source_kind),
            ).fetchone()
            if not source or not source["source_session_id"]:
                return key, label
            row = con.execute(
                "SELECT p.subject_key,p.subject_label FROM discovery_propositions p "
                "JOIN discovery_instances i ON i.proposition_id=p.id "
                "WHERE i.source_session_id=? AND i.active=1 AND p.subject_type='character' "
                "AND LOWER(p.subject_label) NOT IN ('self','character','person','someone','unknown') "
                "ORDER BY i.created_at DESC,p.rowid DESC LIMIT 1",
                (source["source_session_id"],),
            ).fetchone()
        if row:
            return str(row["subject_key"]), str(row["subject_label"])
        return key, label

    items._current_turn_character = current_turn_character
    items._SESSION_CHARACTER_FALLBACK_INSTALLED = True


def _copy_instance(service, source_instance: dict[str, Any], proposition_id: str) -> None:
    service.store.add_instance(
        proposition_id,
        source_kind=source_instance["source_kind"],
        source_session_id=source_instance.get("source_session_id"),
        source_turn_id=source_instance.get("source_turn_id"),
        origin_session_id=source_instance.get("origin_session_id"),
        origin_turn_id=source_instance.get("origin_turn_id"),
        source_revision=source_instance["source_revision"],
        project_id=source_instance.get("project_id"),
        world_id=source_instance.get("world_id"),
        branch_id=source_instance.get("branch_id"),
        world_time=source_instance.get("world_time"),
        story_order=source_instance.get("story_order"),
        source_segment=source_instance.get("source_segment"),
        span_start=source_instance.get("span_start"),
        span_end=source_instance.get("span_end"),
        span_text=source_instance.get("span_text") or "",
        extraction_confidence=float(source_instance.get("extraction_confidence") or 1.0),
        explicitness=str(source_instance.get("explicitness") or "explicit"),
        qualifies_review=bool(source_instance.get("qualifies_review")),
    )


def _target_label(service, subject_key: str) -> str:
    with service.store.connection() as con:
        row = con.execute(
            "SELECT subject_label FROM discovery_propositions WHERE subject_key=? AND predicate='entity.exists' "
            "ORDER BY rowid LIMIT 1",
            (subject_key,),
        ).fetchone()
    return str(row["subject_label"]) if row else subject_key


def _retire_subject_family(service, subject_key: str) -> None:
    if service.foundation is None:
        return
    with service.store.connection() as con:
        active = con.execute(
            "SELECT COUNT(*) FROM discovery_instances i JOIN discovery_propositions p ON p.id=i.proposition_id "
            "WHERE i.active=1 AND (p.subject_key=? OR p.object_key=?)",
            (subject_key, subject_key),
        ).fetchone()[0]
        link = con.execute(
            "SELECT resource_id FROM discovery_subject_links WHERE subject_key=? AND resource_type='entity_family' "
            "ORDER BY updated_at DESC LIMIT 1",
            (subject_key,),
        ).fetchone()
    if active or not link:
        return
    try:
        family = service.workspace.get_entity_family(link["resource_id"])
    except Exception:
        return
    discovery = (family.get("shared_core") or {}).get("_discovery") or {}
    if discovery.get("provisional") and discovery.get("physical_item_id"):
        try:
            service.foundation.archive("entity_family", family["id"], True)
        except Exception:
            pass


def _merge_turn_subject(service, *, from_key: str, to_key: str, turn_id: str,
                        source_kind: str, revision: str) -> int:
    if from_key == to_key:
        return 0
    target_label = _target_label(service, to_key)
    with service.store.connection() as con:
        rows = con.execute(
            "SELECT i.id AS instance_id,i.* FROM discovery_instances i "
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
        _copy_instance(service, instance, new_prop["id"])
        source_instance_ids.append(instance["id"])
        moved += 1

    if source_instance_ids:
        marks = ",".join("?" for _ in source_instance_ids)
        with service.store._lock, service.store.connection() as con:
            con.execute(
                f"UPDATE discovery_instances SET active=0,invalidation_reason='explicit_anaphora_merged',updated_at=? "
                f"WHERE id IN ({marks})",
                [utc_now(), *source_instance_ids],
            )
    _retire_subject_family(service, from_key)
    return moved


def _identity_rows(service, turn_id: str, source_kind: str, revision: str) -> list[dict[str, Any]]:
    with service.store.connection() as con:
        rows = con.execute(
            "SELECT p.subject_key,p.subject_label,p.value_json,i.span_start,i.span_end,i.span_text "
            "FROM discovery_propositions p JOIN discovery_instances i ON i.proposition_id=p.id "
            "WHERE i.source_turn_id=? AND i.source_kind=? AND i.source_revision=? AND i.active=1 "
            "AND p.subject_type='garment' AND p.subject_key LIKE 'item:ITEM-%' "
            "AND p.predicate='entity.exists' ORDER BY COALESCE(i.span_start,999999),i.created_at,i.id",
            (turn_id, source_kind, revision),
        ).fetchall()
    output = []
    for row in rows:
        value = loads(row["value_json"], {})
        output.append({
            "subject_key": str(row["subject_key"]),
            "subject_label": str(row["subject_label"]),
            "garment_type": str(value.get("garment_type") or "garment"),
            "span_start": row["span_start"],
            "span_end": row["span_end"],
            "span_text": row["span_text"],
        })
    return output


def install_physical_item_refinement(service) -> None:
    if getattr(service, "_physical_item_refinement_installed", False):
        return
    _install_session_character_fallback(service)
    original_capture_text = service.capture_text

    def capture_text(text: str, *, source_kind: str, turn: dict[str, Any],
                     session: dict[str, Any], qualifies_review: bool | None = None):
        report = original_capture_text(
            text, source_kind=source_kind, turn=turn, session=session,
            qualifies_review=qualifies_review,
        )
        compiled = CharacterRailParser.parse(text)
        evidence = str(compiled.evidence_prompt if compiled.active else text or "").strip()
        mentions = items._mentions(evidence)
        if not mentions:
            return report
        revision = checksum(evidence)
        rows = _identity_rows(service, turn["id"], source_kind, revision)
        if not rows:
            return report

        by_start: dict[int, str] = {}
        type_by_key: dict[str, str] = {}
        for row in rows:
            if row.get("span_start") is not None:
                by_start[int(row["span_start"])] = row["subject_key"]
            type_by_key[row["subject_key"]] = row["garment_type"]

        previous_by_type: dict[str, str] = {}
        for mention in mentions:
            current_key = by_start.get(mention.start)
            if not current_key:
                continue
            previous = previous_by_type.get(mention.garment_type)
            if mention.reference_cue and previous and current_key != previous:
                _merge_turn_subject(
                    service, from_key=current_key, to_key=previous,
                    turn_id=turn["id"], source_kind=source_kind, revision=revision,
                )
                current_key = previous
            previous_by_type[mention.garment_type] = current_key

        with service.store.connection() as con:
            prop_count = con.execute(
                "SELECT COUNT(DISTINCT proposition_id) FROM discovery_instances "
                "WHERE source_turn_id=? AND source_kind=? AND source_revision=? AND active=1",
                (turn["id"], source_kind, revision),
            ).fetchone()[0]
            instance_count = con.execute(
                "SELECT COUNT(*) FROM discovery_instances WHERE source_turn_id=? AND source_kind=? "
                "AND source_revision=? AND active=1",
                (turn["id"], source_kind, revision),
            ).fetchone()[0]
        return type(report)(turn["id"], source_kind, int(prop_count), int(instance_count), report.skipped)

    service.capture_text = capture_text
    service._physical_item_refinement_installed = True
