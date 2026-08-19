from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any

from src.narrative.rails import CharacterRailParser

from .service import CaptureReport, DiscoveryService
from .store import checksum


_INSTALLED = False
_ORIGINAL_CAPTURE_TEXT = DiscoveryService.capture_text


@dataclass(slots=True, frozen=True)
class GeneralCandidate:
    subject_type: str
    subject_key: str
    subject_label: str
    predicate: str
    value: Any
    operation: str
    start: int
    end: int
    span_text: str
    confidence: float = 0.8
    object_type: str | None = None
    object_key: str | None = None
    object_label: str | None = None
    temporal_state: str = "current_or_unspecified"


def _slug(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or "unknown"


def _key(kind: str, label: str) -> str:
    prefix = {"character": "char", "location": "loc", "item": "item", "organization": "org"}.get(kind, "entity")
    return f"{prefix}:{_slug(label)}"


# Proper-name shape is deliberately case-sensitive. A period is not accepted
# inside the word token because sentence boundaries like `Nova City. Alex`
# must never collapse into one entity label.
PROPER = r"[A-ZÀ-ÖØ-Þ][\wÀ-ÿ'’-]*(?:\s+[A-ZÀ-ÖØ-Þ][\wÀ-ÿ'’-]*){0,3}"

TYPE_WORDS: dict[str, str] = {
    "character": "character", "karakter": "character", "person": "character", "orang": "character",
    "man": "character", "woman": "character", "boy": "character", "girl": "character",
    "pria": "character", "wanita": "character", "cowok": "character", "cewek": "character",
    "location": "location", "lokasi": "location", "city": "location", "kota": "location",
    "village": "location", "desa": "location", "apartment": "location", "apartemen": "location",
    "house": "location", "rumah": "location", "cafe": "location", "café": "location", "kafe": "location",
    "school": "location", "sekolah": "location", "campus": "location", "kampus": "location",
    "forest": "location", "hutan": "location", "room": "location", "ruangan": "location",
    "item": "item", "artifact": "item", "artefact": "item", "artefak": "item",
    "sword": "item", "pedang": "item", "ring": "item", "cincin": "item",
    "weapon": "item", "senjata": "item", "amulet": "item", "kalung": "item",
    "guild": "organization", "order": "organization", "ordo": "organization",
    "organization": "organization", "organisasi": "organization", "clan": "organization", "klan": "organization",
    "group": "organization", "kelompok": "organization",
}

TRAIT_WORDS = {
    "shy", "pemalu", "talkative", "cerewet", "quiet", "pendiam", "calm", "tenang",
    "friendly", "ramah", "introverted", "introvert", "extroverted", "extrovert",
    "careful", "cautious", "hati-hati", "hot-headed", "pemarah", "stubborn", "keras kepala",
    "gentle", "lembut", "reserved", "impulsive", "protective", "protektif",
}

STOP_LABELS = {
    "the", "this", "that", "he", "she", "they", "aku", "saya", "dia", "sebuah", "seorang",
    "dan", "lalu", "kemudian", "setelah", "sebelum", "ketika", "saat", "karena", "namun",
    "later", "then", "after", "before", "when", "because", "however",
}


def _normalize_label(label: str, kind: str) -> str:
    parts = " ".join(label.strip().split()).split()
    while len(parts) > 1 and parts[0].casefold() in STOP_LABELS:
        parts = parts[1:]
    if len(parts) > 1 and TYPE_WORDS.get(parts[0].casefold()) == kind:
        parts = parts[1:]
    return " ".join(parts)


def _add_entity(out: list[GeneralCandidate], seen: set[tuple[str, str]], kind: str, label: str,
                start: int, end: int, span: str, confidence: float = 0.8) -> None:
    label = _normalize_label(label, kind)
    if not label or label.casefold() in STOP_LABELS or len(label) < 2:
        return
    signature = (kind, label.casefold())
    if signature in seen:
        return
    seen.add(signature)
    out.append(GeneralCandidate(
        subject_type=kind,
        subject_key=_key(kind, label),
        subject_label=label,
        predicate="entity.exists",
        value={"entity_type": kind, "label": label},
        operation="create",
        start=start,
        end=end,
        span_text=span,
        confidence=confidence,
    ))


def detect_general(text: str, *, existing: list[dict[str, Any]] | None = None) -> list[GeneralCandidate]:
    """Conservative supplement for arbitrary named narrative components."""
    out: list[GeneralCandidate] = []
    seen_entities: set[tuple[str, str]] = set()

    for family in existing or []:
        label = str(family.get("name") or "").strip()
        kind = str(family.get("entity_type") or "lore")
        if not label or kind not in {"character", "location", "item", "organization"}:
            continue
        match = re.search(rf"(?<![\w@]){re.escape(label)}(?![\w])", text, re.I)
        if match:
            _add_entity(out, seen_entities, kind, label, match.start(), match.end(), match.group(0), 0.99)

    existing_by_name = {str(item.get("name") or "").casefold(): item for item in existing or []}
    for match in re.finditer(r"@([\wÀ-ÿ.'-]{2,})", text):
        label = match.group(1)
        family = existing_by_name.get(label.casefold())
        if family:
            kind = str(family.get("entity_type") or "character")
            if kind in {"character", "location", "item", "organization"}:
                _add_entity(out, seen_entities, kind, family.get("name") or label, match.start(), match.end(), match.group(0), 0.99)

    type_pattern = "|".join(sorted((re.escape(word) for word in TYPE_WORDS), key=len, reverse=True))
    typed = re.compile(
        rf"\b(?P<type>(?i:{type_pattern}))\b\s*"
        rf"(?:(?i:bernama|named|called|berjulukan)\s+)?(?P<label>{PROPER})"
    )
    for match in typed.finditer(text):
        kind = TYPE_WORDS.get(match.group("type").casefold())
        if kind:
            _add_entity(out, seen_entities, kind, match.group("label"), match.start(), match.end(), match.group(0), 0.9)

    actor = re.compile(
        rf"(?<![\w@])(?P<label>{PROPER})\s+"
        rf"(?P<verb>(?i:adalah|is|was|berkata|said|says|tinggal|lives|resides|"
        rf"berjalan|walks|memakai|wears|menggunakan|uses|menjadi|became|becomes|"
        rf"berubah|transforms?|tersenyum|smiles|menatap|looks))\b"
    )
    for match in actor.finditer(text):
        _add_entity(out, seen_entities, "character", match.group("label"), match.start(), match.end(), match.group(0), 0.82)

    loc_types = (
        "kota|city|desa|village|kampus|campus|kafe|cafe|café|sekolah|school|"
        "apartemen|apartment|rumah|house|hutan|forest"
    )
    loc = re.compile(
        rf"\b(?i:di|ke|dari|in|at|to|from)\s+"
        rf"(?:(?i:{loc_types})\s+)?(?P<label>{PROPER})"
    )
    for match in loc.finditer(text):
        _add_entity(out, seen_entities, "location", match.group("label"), match.start(), match.end(), match.group(0), 0.88)

    trait_words = "|".join(re.escape(item) for item in sorted(TRAIT_WORDS, key=len, reverse=True))
    trait = re.compile(
        rf"(?<![\w@])(?P<label>{PROPER})\s+(?i:adalah|is|was)\s+"
        rf"(?:(?i:orang\s+yang|a|an)\s+)?(?P<trait>(?i:{trait_words}))\b"
    )
    for match in trait.finditer(text):
        label = _normalize_label(match.group("label"), "character")
        if not label or label.casefold() in STOP_LABELS:
            continue
        _add_entity(out, seen_entities, "character", label, match.start(), match.end(), match.group(0), 0.9)
        out.append(GeneralCandidate(
            subject_type="character", subject_key=_key("character", label), subject_label=label,
            predicate="personality.descriptor", value=match.group("trait").strip().lower(), operation="update",
            start=match.start(), end=match.end(), span_text=match.group(0), confidence=0.94,
        ))

    transition = re.compile(
        rf"(?<![\w@])(?P<label>{PROPER})\s+"
        rf"(?i:berubah\s+menjadi|menjadi|became|becomes|transformed?\s+into|transforms?\s+into)\s+"
        rf"(?P<value>[^.!?\n]{{2,180}})"
    )
    for match in transition.finditer(text):
        label = _normalize_label(match.group("label"), "character")
        if not label or label.casefold() in STOP_LABELS:
            continue
        value = " ".join(match.group("value").strip().split())
        _add_entity(out, seen_entities, "character", label, match.start(), match.end(), match.group(0), 0.85)
        out.append(GeneralCandidate(
            subject_type="character", subject_key=_key("character", label), subject_label=label,
            predicate="state.form_description", value=value, operation="transition",
            start=match.start(), end=match.end(), span_text=match.group(0), confidence=0.9,
            temporal_state="historical_or_current",
        ))

    pronoun_trait = re.compile(
        rf"(?<![\w@])(?P<label>(?i:Aku|Saya|I|Dia|Ia|He|She))\s+(?i:adalah|is|was)\s+"
        rf"(?:(?i:orang\s+yang|a|an)\s+)?(?P<trait>(?i:{trait_words}))\b"
    )
    for match in pronoun_trait.finditer(text):
        label = match.group("label")
        out.append(GeneralCandidate(
            subject_type="character", subject_key=f"mention:{match.start()}", subject_label=label,
            predicate="personality.descriptor", value=match.group("trait").strip().lower(), operation="update",
            start=match.start(), end=match.end(), span_text=match.group(0), confidence=0.9,
        ))

    pronoun_transition = re.compile(
        r"(?<![\w@])(?P<label>(?i:Aku|Saya|I|Dia|Ia|He|She))\s+"
        r"(?:(?i:sekarang|now)\s+)?(?i:berubah\s+menjadi|menjadi|became|becomes|transformed?\s+into)\s+"
        r"(?P<value>[^.!?\n]{2,180})"
    )
    for match in pronoun_transition.finditer(text):
        out.append(GeneralCandidate(
            subject_type="character", subject_key=f"mention:{match.start()}", subject_label=match.group("label"),
            predicate="state.form_description", value=" ".join(match.group("value").strip().split()),
            operation="transition", start=match.start(), end=match.end(), span_text=match.group(0),
            confidence=0.9, temporal_state="historical_or_current",
        ))

    residence = re.compile(
        rf"(?<![\w@])(?P<char>{PROPER})\s+(?i:tinggal|lives|resides)\s+"
        rf"(?i:di|in|at)\s+(?:(?i:kota|city|apartemen|apartment|rumah|house)\s+)?"
        rf"(?P<loc>{PROPER})"
    )
    for match in residence.finditer(text):
        char = _normalize_label(match.group("char"), "character")
        place = _normalize_label(match.group("loc"), "location")
        if not char or not place or char.casefold() in STOP_LABELS or place.casefold() in STOP_LABELS:
            continue
        _add_entity(out, seen_entities, "character", char, match.start(), match.end(), match.group(0), 0.9)
        _add_entity(out, seen_entities, "location", place, match.start(), match.end(), match.group(0), 0.9)
        out.append(GeneralCandidate(
            subject_type="character", subject_key=_key("character", char), subject_label=char,
            predicate="resides_at", value=True, operation="relation",
            start=match.start(), end=match.end(), span_text=match.group(0), confidence=0.93,
            object_type="location", object_key=_key("location", place), object_label=place,
            temporal_state="current_or_unspecified",
        ))

    return out


def _capture_text_general(self: DiscoveryService, text: str, *, source_kind: str,
                          turn: dict[str, Any], session: dict[str, Any],
                          qualifies_review: bool | None = None) -> CaptureReport:
    report = _ORIGINAL_CAPTURE_TEXT(
        self, text, source_kind=source_kind, turn=turn, session=session,
        qualifies_review=qualifies_review,
    )
    if session.get("scratch_mode"):
        return report

    compiled = CharacterRailParser.parse(text)
    evidence = (compiled.evidence_prompt if compiled.active else text or "").strip()
    if not evidence:
        return report
    lineage = turn.get("lineage") or {}
    if lineage.get("forked_from_turn_id") and source_kind != "user_edited_prose":
        return report

    try:
        existing = self.workspace.list_entity_families(None)
    except Exception:
        existing = []
    candidates = detect_general(evidence, existing=existing)
    revision = checksum(evidence)
    world_time, story_order = self._turn_time_scope(turn)
    base_qualifies = source_kind in self.REVIEW_SOURCE_KINDS if qualifies_review is None else bool(qualifies_review)
    origin_turn_id = str(lineage.get("forked_from_turn_id") or turn["id"])
    origin_session_id = str(lineage.get("forked_from_session_id") or session["id"])

    for index, item in enumerate(candidates, 1):
        resolved = self.entity_resolver.resolve(
            project_id=session.get("project_id"), world_id=session.get("world_id"),
            branch_id=session.get("branch_id"), session_id=session.get("id"),
            turn_id=turn.get("id"), source_kind=source_kind, source_text=evidence,
            entity_type=item.subject_type, raw_subject_key=item.subject_key, label=item.subject_label,
            span_start=item.start, span_end=item.end,
        )
        if not resolved.resolved:
            continue
        object_key = item.object_key
        object_label = item.object_label
        if object_key and object_label:
            resolved_object = self.entity_resolver.resolve(
                project_id=session.get("project_id"), world_id=session.get("world_id"),
                branch_id=session.get("branch_id"), session_id=session.get("id"),
                turn_id=turn.get("id"), source_kind=source_kind, source_text=evidence,
                entity_type=item.object_type or "entity", raw_subject_key=object_key, label=object_label,
                span_start=item.start, span_end=item.end,
            )
            if not resolved_object.resolved:
                continue
            object_key = resolved_object.subject_key
            object_label = resolved_object.subject_label
        link = self._subject_link(
            project_id=session.get("project_id"), world_id=session.get("world_id"),
            subject_key=str(resolved.subject_key), subject_label=resolved.subject_label,
            subject_type=item.subject_type,
        )
        proposition = self.store.upsert_proposition(
            project_id=session.get("project_id"), world_id=session.get("world_id"),
            subject_type=item.subject_type, subject_key=str(resolved.subject_key),
            subject_label=resolved.subject_label, predicate=item.predicate, value=item.value,
            object_type=item.object_type, object_key=object_key,
            object_label=object_label, operation=item.operation,
            temporal_state=item.temporal_state,
            target_resource_type=link.get("resource_type") if link else resolved.target_resource_type,
            target_resource_id=link.get("resource_id") if link else resolved.target_resource_id,
        )
        existing_instances = self.store.list_instances(proposition["id"])
        if any(
            inst.get("source_turn_id") == turn["id"]
            and inst.get("source_kind") == source_kind
            and inst.get("source_revision") == revision
            and inst.get("active")
            for inst in existing_instances
        ):
            continue
        self.store.add_instance(
            proposition["id"], source_kind=source_kind,
            source_session_id=session["id"], source_turn_id=turn["id"],
            origin_session_id=origin_session_id, origin_turn_id=origin_turn_id,
            source_revision=revision, project_id=session.get("project_id"),
            world_id=session.get("world_id"), branch_id=session.get("branch_id"),
            world_time=world_time, story_order=story_order,
            source_segment=f"general:{index}", span_start=item.start, span_end=item.end,
            span_text=item.span_text, extraction_confidence=item.confidence,
            explicitness="explicit",
            qualifies_review=bool(base_qualifies and item.confidence >= 0.7),
        )

    # Report the stable persisted state for this logical source. A second
    # idempotent capture must therefore return the same counts as the first.
    with self.store.connection() as con:
        rows = con.execute(
            "SELECT id,proposition_id FROM discovery_instances "
            "WHERE source_turn_id=? AND source_kind=? AND source_revision=? AND active=1",
            (turn["id"], source_kind, revision),
        ).fetchall()
    prop_ids = {str(row["proposition_id"]) for row in rows}
    return CaptureReport(turn["id"], source_kind, len(prop_ids), len(rows), report.skipped)


def install_general_discovery() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    DiscoveryService.capture_text = _capture_text_general
    _INSTALLED = True
