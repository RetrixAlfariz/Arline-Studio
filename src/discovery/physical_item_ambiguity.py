from __future__ import annotations

from src.narrative.rails import CharacterRailParser

from . import physical_items as items
from .store import checksum


def install_physical_item_ambiguity_guard(service) -> None:
    """Prevent ambiguous references from falling back to legacy type identities."""
    if getattr(service, "_physical_item_ambiguity_guard_installed", False):
        return
    original_capture_text = service.capture_text

    def capture_text(text: str, *, source_kind: str, turn: dict, session: dict,
                     qualifies_review: bool | None = None):
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
        with service.store.connection() as con:
            rows = con.execute(
                "SELECT DISTINCT i.span_start FROM discovery_instances i "
                "JOIN discovery_propositions p ON p.id=i.proposition_id "
                "WHERE i.source_turn_id=? AND i.source_kind=? AND i.source_revision=? AND i.active=1 "
                "AND p.subject_type='garment' AND p.subject_key LIKE 'item:ITEM-%' "
                "AND p.predicate='entity.exists'",
                (turn["id"], source_kind, revision),
            ).fetchall()
        resolved_starts = {int(row["span_start"]) for row in rows if row["span_start"] is not None}
        context = items._context_for(service, turn, session)
        existing = items._existing_items(service, context)
        ambiguous = False
        for mention in mentions:
            if mention.start in resolved_starts:
                continue
            candidates = [
                item for item in existing
                if item.garment_type == mention.garment_type
                and items._compatible(item, mention.attributes)[0]
            ]
            if len(candidates) > 1:
                ambiguous = True
                break
        if not ambiguous:
            return report

        legacy_keys = items._invalidate_collapsed_garments(service, turn["id"], source_kind)
        items._retire_orphaned_legacy_sheets(service, legacy_keys)
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
    service._physical_item_ambiguity_guard_installed = True
