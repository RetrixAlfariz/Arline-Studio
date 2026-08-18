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


PROPER = r"[A-ZÀ-ÖØ-Þ][\wÀ-ÿ'’.-]*(?:\s+[A-ZÀ-ÖØ-Þ][\wÀ-ÿ'’.-]*){0,3}"

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
    "The", "This", "That", "He", "She", "They", "Aku", "Saya", "Dia", "Sebuah", "Seorang",
    "Dan", "Lalu", "Kemudian", "Setelah", "Sebelum", "Ketika", "Saat", "Karena", "Namun",
}


def _add_entity(out: list[GeneralCandidate], seen: set[tuple[str, str]], kind: str, label: str,
                start: int, end: int, span: str, confidence: float = 0.8) -> None:
    label = " ".join(label.strip().split())
    if not label or label in STOP_LABELS or len(label) < 2:
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
    """Conservative generic discovery supplement for ordinary narrative prose.

    The older structural pipeline remains primary. This layer only fills the
    obvious gap for arbitrary proper names / locations / named things and a few
    explicit state/trait constructions. Everything it emits is still non-canon.
    """
    out: list[GeneralCandidate] = []
    seen_entities: set[tuple[str, str]] = set()

    # Existing Library identities are the safest generic anchors.
    for family in existing or []:
        label = str(family.get("name") or "").strip()
        kind = str(family.get("entity_type") or "lore")
        if not label or kind not in {"character", "location", "item", "organization"}:
            continue
        match = re.search(rf"(?<![\w@]){re.escape(label)}(?![\w])", text, re.I)
        if match:
            _add_entity(out, seen_entities, kind, label, match.start(), match.end(), match.group(0), 0.99)

    # Explicit @ references that resolve to existing Library identities are safe;
    # unknown @ names default to character only when the name appears as an actor.
    existing_by_name = {str(item.get("name") or "").casefold(): item for item in existing or []}
    for match in re.finditer(r"@([\wÀ-ÿ.'-]{2,})", text):
        label = match.group(1)
        family = existing_by_name.get(label.casefold())
        if family:
            kind = str(family.get("entity_type") or "character")
            if kind in {"character", "location", "item", "organization"}:
                _add_entity(out, seen_entities, kind, family.get("name") or label, match.start(), match.end(), match.group(0), 0.99)

    # "character Alex", "kota Surabaya", "pedang bernama Aster", etc.
    type_pattern = "|".join(sorted((re.escape(word) for word in TYPE_WORDS), key=len, reverse=True))
    typed = re.compile(
        rf"\b(?P<type>{type_pattern})\b\s*(?:(?:bernama|named|called|berjulukan)\s+)?(?P<label>{PROPER})",
        re.I,
    )
    for match in typed.finditer(text):
        kind = TYPE_WORDS.get(match.group("type").casefold())
        label = match.group("label").strip()
        if kind:
            _add_entity(out, seen_entities, kind, label, match.start(), match.end(), match.group(0), 0.9)

    # Proper-name actor followed by a clear predicate. This intentionally does
    # not treat every capitalized token as a character.
    actor = re.compile(
        rf"(?<![\w@])(?P<label>{PROPER})\s+(?P<verb>adalah|is|was|berkata|said|says|"
        rf"tinggal|lives|resides|berjalan|walks|memakai|wears|menggunakan|uses|"
        rf"menjadi|became|becomes|berubah|transforms?|tersenyum|smiles|menatap|looks)\b",
        re.I,
    )
    for match in actor.finditer(text):
        _add_entity(out, seen_entities, "character", match.group("label"), match.start(), match.end(), match.group(0), 0.82)

    # Explicit locations after spatial prepositions. Require a proper name to
    # avoid creating every incidental "room/chair/table" as Library objects.
    loc = re.compile(
        rf"\b(?:di|ke|dari|in|at|to|from)\s+(?:(?:kota|city|desa|village|kampus|campus|"
        rf"kafe|cafe|café|sekolah|school|apartemen|apartment|rumah|house|hutan|forest)\s+)?(?P<label>{PROPER})",
        re.I,
    )
    for match in loc.finditer(text):
        _add_entity(out, seen_entities, "location", match.group("label"), match.start(), match.end(), match.group(0), 0.88)

    # Explicit personality descriptors only. We do not infer personality from
    # body, gender presentation, appearance, or one-off behavior.
    trait_words = "|".join(re.escape(item) for item in sorted(TRAIT_WORDS, key=len, reverse=True))
    trait = re.compile(
        rf"(?<![\w@])(?P<label>{PROPER})\s+(?:adalah|is|was)\s+(?:(?:orang\s+yang|a|an)\s+)?(?P<trait>{trait_words})\b",
        re.I,
    )
    for match in trait.finditer(text):
        label = match.group("label").strip()
        _add_entity(out, seen_entities, "character", label, match.start(), match.end(), match.group(0), 0.9)
        out.append(GeneralCandidate(
            subject_type="character", subject_key=_key("character", label), subject_label=label,
            predicate="personality.descriptor", value=match.group("trait").strip().lower(), operation="update",
            start=match.start(), end=match.end(), span_text=match.group(0), confidence=0.94,
        ))

    # Generic form/state transformation. This stores the explicit description,
    # not a fabricated ontology of what the transformed body/personality means.
    transition = re.compile(
        rf"(?<![\w@])(?P<label>{PROPER})\s+(?:berubah\s+menjadi|menjadi|became|becomes|"
        rf"transformed?\s+into|transforms?\s+into)\s+(?P<value>[^.!?\n]{{2,180}})",
        re.I,
    )
    for match in transition.finditer(text):
        label = match.group("label").strip()
        value = " ".join(match.group("value").strip().split())
        _add_entity(out, seen_entities, "character", label, match.start(), match.end(), match.group(0), 0.85)
        out.append(GeneralCandidate(
            subject_type="character", subject_key=_key("character", label), subject_label=label,
            predicate="state.form_description", value=value, operation="transition",
            start=match.start(), end=match.end(), span_text=match.group(0), confidence=0.9,
            temporal_state="historical_or_current",
        ))

    # Residence relation with an explicit named place.
    residence = re.compile(
        rf"(?<![\w@])(?P<char>{PROPER})\s+(?:tinggal|lives|resides)\s+(?:di|in|at)\s+"
        rf"(?:(?:kota|city|apartemen|apartment|rumah|house)\s+)?(?P<loc>{PROPER})",
        re.I,
    )
    for match in residence.finditer(text):
        char = match.group("char").strip(); place = match.group("loc").strip()
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
    if not candidates:
        return report

    revision = checksum(evidence)
    world_time, story_order = self._turn_time_scope(turn)
    base_qualifies = source_kind in self.REVIEW_SOURCE_KINDS if qualifies_review is None else bool(qualifies_review)
    origin_turn_id = str(lineage.get("forked_from_turn_id") or turn["id"])
    origin_session_id = str(lineage.get("forked_from_session_id") or session["id"])
    added_props: set[str] = set()
    added_instances = 0

    for index, item in enumerate(candidates, 1):
        link = self._subject_link(
            project_id=session.get("project_id"), world_id=session.get("world_id"),
            subject_key=item.subject_key, subject_label=item.subject_label,
            subject_type=item.subject_type,
        )
        proposition = self.store.upsert_proposition(
            project_id=session.get("project_id"), world_id=session.get("world_id"),
            subject_type=item.subject_type, subject_key=item.subject_key,
            subject_label=item.subject_label, predicate=item.predicate, value=item.value,
            object_type=item.object_type, object_key=item.object_key,
            object_label=item.object_label, operation=item.operation,
            temporal_state=item.temporal_state,
            target_resource_type=link.get("resource_type") if link else None,
            target_resource_id=link.get("resource_id") if link else None,
        )
        # Do not count the same logical proposition twice when the structural
        # pipeline already extracted it from this exact turn/source revision.
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
        added_props.add(proposition["id"]); added_instances += 1

    return CaptureReport(
        report.turn_id, report.source_kind,
        report.propositions + len(added_props), report.instances + added_instances,
        report.skipped,
    )


def install_general_discovery() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    DiscoveryService.capture_text = _capture_text_general
    _INSTALLED = True
