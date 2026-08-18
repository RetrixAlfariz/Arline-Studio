from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re
from typing import Any

from src.common.utils import COLORS
from src.memory.models import MemoryQueryContext
from src.narrative.rails import CharacterRailParser
from src.state_extractor.reference_resolver import EntityReferenceResolver

from .store import checksum, dumps, utc_now


MATERIALS = {
    "jersey", "rayon", "katun", "cotton", "satin", "silk", "sutra",
    "linen", "polyester", "denim", "wool", "wol", "velvet", "beludru",
}
NUMBER_WORDS = {
    "dua": 2, "tiga": 3, "empat": 4, "lima": 5,
    "enam": 6, "tujuh": 7, "delapan": 8, "sembilan": 9, "sepuluh": 10,
    "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
NEW_CUE = re.compile(
    r"(?i)\b(?:lain|baru|another|new|kedua|ketiga|second|third|"
    r"membeli|beli|bought|buy|memesan|ordered|order|mendapat|received)\b"
)
OWN_CUE = re.compile(
    r"(?i)\b(?:punya|memiliki|milikku|membeli|beli|bought|buy|owns?|owned)\b"
)
WEAR_CUE = re.compile(
    r"(?i)\b(?:memakai|pakai|mengenakan|wearing|wears?|wore)\b"
)
REFERENCE_AFTER = re.compile(r"(?i)^\s*(?:itu|tadi|tersebut|yang\s+sama|same)\b")


def _terms() -> dict[str, str]:
    result: dict[str, str] = {}
    for term, (lexical_type, _family) in EntityReferenceResolver.GARMENT_TERMS.items():
        result[str(term).casefold()] = str(lexical_type).casefold().replace(" ", "_")
    # Common repeatable garment classes not yet needed by the structural extractor.
    result.update({
        "rok": "skirt", "skirt": "skirt", "blus": "blouse", "blouse": "blouse",
        "kemeja": "shirt", "shirt": "shirt", "jaket": "jacket", "jacket": "jacket",
        "hoodie": "hoodie", "mantel": "coat", "coat": "coat",
    })
    return result


GARMENT_TERMS = _terms()
TERM_PATTERN = "|".join(
    re.escape(term).replace(r"\ ", r"\s+")
    for term in sorted(GARMENT_TERMS, key=len, reverse=True)
)
MENTION_RE = re.compile(
    rf"(?<![\w])(?P<term>{TERM_PATTERN})(?P<suffix>nya|ku|mu)?(?![\w])",
    re.I,
)


@dataclass(slots=True)
class GarmentMention:
    index: int
    start: int
    end: int
    raw: str
    garment_type: str
    suffix: str = ""
    quantity: int = 1
    attributes: dict[str, Any] = field(default_factory=dict)
    force_new: bool = False
    reference_cue: bool = False
    wearing: bool = False
    ownership: bool = False


@dataclass(slots=True)
class PhysicalItem:
    subject_key: str
    item_id: str
    garment_type: str
    label: str
    attributes: dict[str, Any]
    existing: bool = False
    family_id: str | None = None


def _item_id(origin_turn_id: str, garment_type: str, ordinal: int, copy_index: int = 1) -> str:
    seed = f"{origin_turn_id}|garment|{garment_type}|{ordinal}|{copy_index}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12].upper()
    return f"ITEM-{digest}"


def _physical_subject_key(item_id: str) -> str:
    return f"item:{item_id}"


def _physical_item_id_from_key(subject_key: str) -> str | None:
    if str(subject_key or "").startswith("item:ITEM-"):
        return str(subject_key).split(":", 1)[1]
    return None


def _clause_between(text: str, a: int, b: int) -> str:
    left, right = sorted((a, b))
    return text[left:right]


def _near_same_clause(text: str, a: int, b: int, limit: int = 140) -> bool:
    if abs(a - b) > limit:
        return False
    between = _clause_between(text, a, b)
    return not bool(re.search(r"[.!?;\n]", between))


def _quantity_before(text: str, start: int) -> int:
    prefix = text[max(0, start - 28):start]
    match = re.search(
        r"(?i)(?P<q>\d{1,2}|dua|tiga|empat|lima|enam|tujuh|delapan|sembilan|sepuluh|"
        r"two|three|four|five|six|seven|eight|nine|ten)\s*(?:buah\s+|pieces?\s+)?$",
        prefix,
    )
    if not match:
        return 1
    raw = match.group("q").casefold()
    try:
        value = int(raw)
    except ValueError:
        value = NUMBER_WORDS.get(raw, 1)
    return max(1, min(int(value), 20))


def _mentions(text: str) -> list[GarmentMention]:
    output: list[GarmentMention] = []
    for index, match in enumerate(MENTION_RE.finditer(text), 1):
        raw_term = re.sub(r"\s+", " ", match.group("term").casefold())
        garment_type = GARMENT_TERMS.get(raw_term)
        if not garment_type:
            continue
        before = text[max(0, match.start() - 55):match.start()]
        after = text[match.end():min(len(text), match.end() + 50)]
        suffix = str(match.group("suffix") or "").casefold()
        output.append(GarmentMention(
            index=index,
            start=match.start(),
            end=match.end(),
            raw=match.group(0),
            garment_type=garment_type,
            suffix=suffix,
            quantity=_quantity_before(text, match.start()),
            force_new=bool(NEW_CUE.search(before) or NEW_CUE.search(after)),
            reference_cue=bool(suffix or REFERENCE_AFTER.search(after)),
            wearing=bool(WEAR_CUE.search(before)),
            ownership=bool(OWN_CUE.search(before) or suffix == "ku"),
        ))
    _assign_attributes(text, output)
    return output


def _nearest_mention(text: str, mentions: list[GarmentMention], start: int, end: int) -> GarmentMention | None:
    center = (start + end) / 2.0
    eligible = [
        mention for mention in mentions
        if _near_same_clause(text, int(center), (mention.start + mention.end) // 2)
    ]
    if not eligible:
        return None
    return min(eligible, key=lambda mention: abs(center - ((mention.start + mention.end) / 2.0)))


def _assign_attributes(text: str, mentions: list[GarmentMention]) -> None:
    if not mentions:
        return
    color_terms = sorted(set(COLORS) | set(COLORS.values()), key=len, reverse=True)
    color_re = re.compile(r"(?i)\b(" + "|".join(re.escape(item) for item in color_terms) + r")\b")
    for match in color_re.finditer(text):
        mention = _nearest_mention(text, mentions, match.start(), match.end())
        if mention is None:
            continue
        raw = match.group(1).casefold()
        mention.attributes["color"] = COLORS.get(raw, raw)

    material_re = re.compile(r"(?i)\b(" + "|".join(re.escape(item) for item in sorted(MATERIALS, key=len, reverse=True)) + r")\b")
    for match in material_re.finditer(text):
        mention = _nearest_mention(text, mentions, match.start(), match.end())
        if mention is not None:
            mention.attributes["material"] = match.group(1).casefold()

    length_re = re.compile(
        r"(?i)\b(?:panjang(?:nya)?|length)\s*(?:=|:)?\s*"
        r"(?P<value>\d+(?:[.,]\d+)?)\s*(?P<unit>cm|m|meter|metre)\b"
    )
    for match in length_re.finditer(text):
        mention = _nearest_mention(text, mentions, match.start(), match.end())
        if mention is None:
            continue
        value = float(match.group("value").replace(",", "."))
        if match.group("unit").casefold() in {"m", "meter", "metre"}:
            value *= 100.0
        if value.is_integer():
            value = int(value)
        mention.attributes["length"] = {
            "value": value,
            "unit": "cm",
            "frame": "garment_length",
        }


def _context_for(service, turn: dict[str, Any], session: dict[str, Any]) -> MemoryQueryContext:
    world_time, story_order = service._turn_time_scope(turn)
    return MemoryQueryContext(
        project_id=session.get("project_id"),
        world_id=session.get("world_id"),
        branch_id=session.get("branch_id"),
        session_id=session.get("id"),
        world_time=world_time,
        story_order=story_order,
        context_lens="scene",
    )


def _candidate_attributes(service, subject_key: str, context: MemoryQueryContext) -> dict[str, Any]:
    output: dict[str, Any] = {}
    props = service.store.find_subject_propositions(
        project_id=context.project_id,
        world_id=context.world_id,
        subject_key=subject_key,
    )
    for prop in props:
        predicate = str(prop.get("predicate") or "")
        if not predicate.startswith("garment.") or predicate == "garment.type":
            continue
        if predicate.removeprefix("garment.") in output:
            continue
        item = service.evaluate_proposition(prop, context)
        if item.get("knowledge_state") == "canon" or int(item.get("support_count") or 0) > 0:
            output[predicate.removeprefix("garment.")] = item.get("value")
    return output


def _existing_items(service, context: MemoryQueryContext) -> list[PhysicalItem]:
    result: list[PhysicalItem] = []
    try:
        families = service.workspace.list_entity_families(None, entity_type="item")
    except Exception:
        families = []
    for family in families:
        core = family.get("shared_core") or {}
        discovery = core.get("_discovery") or {}
        garment = core.get("garment") or {}
        if core.get("kind") != "garment" and discovery.get("semantic_type") != "garment":
            continue
        item_id = str(discovery.get("physical_item_id") or "")
        subject_key = str(discovery.get("subject_key") or "")
        if not item_id or not subject_key:
            continue
        garment_type = str(garment.get("type") or "garment").casefold()
        result.append(PhysicalItem(
            subject_key=subject_key,
            item_id=item_id,
            garment_type=garment_type,
            label=str(family.get("name") or garment_type.title()),
            attributes=_candidate_attributes(service, subject_key, context),
            existing=True,
            family_id=family.get("id"),
        ))
    return result


def _value_equal(left: Any, right: Any) -> bool:
    if isinstance(left, dict) and isinstance(right, dict):
        if {"value", "unit"} <= set(left) and {"value", "unit"} <= set(right):
            try:
                return str(left["unit"]).casefold() == str(right["unit"]).casefold() and abs(float(left["value"]) - float(right["value"])) < 0.51
            except (TypeError, ValueError):
                pass
        return dumps(left) == dumps(right)
    return str(left).casefold() == str(right).casefold()


def _compatible(item: PhysicalItem, attributes: dict[str, Any]) -> tuple[bool, int]:
    score = 0
    for key, value in attributes.items():
        if key not in item.attributes:
            continue
        if not _value_equal(item.attributes[key], value):
            return False, -1
        score += 1
    return True, score


def _resolve_existing(candidates: list[PhysicalItem], garment_type: str,
                      attributes: dict[str, Any]) -> tuple[PhysicalItem | None, bool]:
    typed = [item for item in candidates if item.garment_type == garment_type]
    if not typed:
        return None, False
    scored: list[tuple[int, PhysicalItem]] = []
    for item in typed:
        okay, score = _compatible(item, attributes)
        if okay:
            scored.append((score, item))
    if not scored:
        return None, False
    if not attributes and len(scored) == 1:
        return scored[0][1], False
    best_score = max(score for score, _item in scored)
    best = [item for score, item in scored if score == best_score]
    if len(best) == 1 and (best_score > 0 or len(scored) == 1):
        return best[0], False
    return None, len(best) > 1


def _base_label(garment_type: str, attributes: dict[str, Any]) -> str:
    pieces: list[str] = []
    if isinstance(attributes.get("color"), str):
        pieces.append(attributes["color"].replace("_", " ").title())
    if isinstance(attributes.get("material"), str):
        pieces.append(attributes["material"].replace("_", " ").title())
    pieces.append(garment_type.replace("_", " ").title())
    return " ".join(pieces)


def _unique_label(base: str, used: dict[str, int]) -> str:
    key = base.casefold()
    count = used.get(key, 0) + 1
    used[key] = count
    return base if count == 1 else f"{base} · #{count}"


def _used_labels(service) -> dict[str, int]:
    counts: dict[str, int] = {}
    try:
        families = service.workspace.list_entity_families(None, entity_type="item")
    except Exception:
        families = []
    for family in families:
        core = family.get("shared_core") or {}
        if core.get("kind") != "garment":
            continue
        name = str(family.get("name") or "").strip()
        base = re.sub(r"\s+·\s+#\d+$", "", name).strip()
        if base:
            counts[base.casefold()] = max(counts.get(base.casefold(), 0), 1)
            suffix = re.search(r"#(\d+)$", name)
            if suffix:
                counts[base.casefold()] = max(counts[base.casefold()], int(suffix.group(1)))
    return counts


def _current_turn_character(service, turn_id: str, source_kind: str) -> tuple[str | None, str | None]:
    with service.store.connection() as con:
        row = con.execute(
            "SELECT p.subject_key,p.subject_label FROM discovery_propositions p "
            "JOIN discovery_instances i ON i.proposition_id=p.id "
            "WHERE i.source_turn_id=? AND i.source_kind=? AND i.active=1 "
            "AND p.subject_type='character' AND p.subject_label NOT IN ('self','character') "
            "ORDER BY p.rowid LIMIT 1",
            (turn_id, source_kind),
        ).fetchone()
        if row:
            return str(row["subject_key"]), str(row["subject_label"])
        row = con.execute(
            "SELECT p.subject_key,p.subject_label FROM discovery_propositions p "
            "JOIN discovery_instances i ON i.proposition_id=p.id "
            "WHERE i.source_turn_id=? AND i.source_kind=? AND i.active=1 "
            "AND p.operation='relation' AND p.object_type='garment' "
            "ORDER BY p.rowid LIMIT 1",
            (turn_id, source_kind),
        ).fetchone()
    if row:
        return str(row["subject_key"]), str(row["subject_label"])
    return None, None


def _invalidate_collapsed_garments(service, turn_id: str, source_kind: str) -> list[str]:
    now = utc_now()
    with service.store._lock, service.store.connection() as con:
        rows = con.execute(
            "SELECT DISTINCT p.subject_key FROM discovery_propositions p "
            "JOIN discovery_instances i ON i.proposition_id=p.id "
            "WHERE i.source_turn_id=? AND i.source_kind=? AND i.active=1 "
            "AND ((p.subject_type='garment' AND p.subject_key LIKE 'garment:%') "
            "OR (p.object_type='garment' AND p.object_key LIKE 'garment:%'))",
            (turn_id, source_kind),
        ).fetchall()
        keys = [str(row["subject_key"]) for row in rows if row["subject_key"]]
        con.execute(
            "UPDATE discovery_instances SET active=0,invalidation_reason='physical_item_identity_rewritten',updated_at=? "
            "WHERE source_turn_id=? AND source_kind=? AND active=1 AND proposition_id IN ("
            "SELECT id FROM discovery_propositions WHERE "
            "(subject_type='garment' AND subject_key LIKE 'garment:%') "
            "OR (object_type='garment' AND object_key LIKE 'garment:%'))",
            (now, turn_id, source_kind),
        )
    return keys


def _retire_orphaned_legacy_sheets(service, subject_keys: list[str]) -> None:
    if service.foundation is None:
        return
    for subject_key in sorted(set(subject_keys)):
        link = service.store.get_subject_link(project_id=None, world_id=None, subject_key=subject_key)
        # Links are normally project/world-scoped; fall back to a direct lookup.
        if not link:
            with service.store.connection() as con:
                row = con.execute(
                    "SELECT resource_type,resource_id FROM discovery_subject_links WHERE subject_key=? ORDER BY updated_at DESC LIMIT 1",
                    (subject_key,),
                ).fetchone()
            link = dict(row) if row else None
        if not link or link.get("resource_type") != "entity_family":
            continue
        with service.store.connection() as con:
            active = con.execute(
                "SELECT COUNT(*) FROM discovery_instances i JOIN discovery_propositions p ON p.id=i.proposition_id "
                "WHERE i.active=1 AND (p.subject_key=? OR p.object_key=?)",
                (subject_key, subject_key),
            ).fetchone()[0]
        if active:
            continue
        try:
            family = service.workspace.get_entity_family(link["resource_id"])
        except Exception:
            continue
        core = family.get("shared_core") or {}
        discovery = core.get("_discovery") or {}
        if not discovery.get("provisional") or discovery.get("physical_item_id"):
            continue
        try:
            service.foundation.archive("entity_family", family["id"], True)
        except Exception:
            pass


def _add_prop(service, *, source: dict[str, Any], subject_type: str, subject_key: str,
              subject_label: str, predicate: str, value: Any, operation: str = "update",
              object_type: str | None = None, object_key: str | None = None,
              object_label: str | None = None, start: int | None = None,
              end: int | None = None, span_text: str = "", confidence: float = 0.98,
              temporal_state: str = "current_or_unspecified") -> str:
    link = service.store.get_subject_link(
        project_id=source["project_id"], world_id=source["world_id"], subject_key=subject_key
    )
    prop = service.store.upsert_proposition(
        project_id=source["project_id"], world_id=source["world_id"],
        subject_type=subject_type, subject_key=subject_key, subject_label=subject_label,
        predicate=predicate, value=value, object_type=object_type, object_key=object_key,
        object_label=object_label, operation=operation, temporal_state=temporal_state,
        target_resource_type=link.get("resource_type") if link else None,
        target_resource_id=link.get("resource_id") if link else None,
    )
    service.store.add_instance(
        prop["id"], source_kind=source["source_kind"],
        source_session_id=source["session_id"], source_turn_id=source["turn_id"],
        origin_session_id=source["origin_session_id"], origin_turn_id=source["origin_turn_id"],
        source_revision=source["revision"], project_id=source["project_id"],
        world_id=source["world_id"], branch_id=source["branch_id"],
        world_time=source["world_time"], story_order=source["story_order"],
        source_segment="physical_item_identity", span_start=start, span_end=end,
        span_text=span_text, extraction_confidence=confidence, explicitness="explicit",
        qualifies_review=source["base_qualifies"],
    )
    return prop["id"]


def _record_ambiguity(service, *, source: dict[str, Any], mention: GarmentMention,
                      candidates: list[PhysicalItem]) -> None:
    if service.foundation is None:
        return
    try:
        service.foundation.log_activity(
            source["project_id"], "discovery_item_reference_ambiguous",
            "turn", source["turn_id"], label=mention.raw,
            detail={
                "garment_type": mention.garment_type,
                "candidate_item_ids": [item.item_id for item in candidates],
            },
        )
    except Exception:
        pass


def install_physical_item_identity(service) -> None:
    """Resolve repeatable garment classes into stable physical ITEM identities.

    The analytical extractor remains responsible for semantic classification.
    This adapter replaces collapsed keys such as ``garment:dress_1`` with stable
    physical subject keys. The ITEM id is derived from the source introduction,
    not from mutable attributes, so correcting color/material/length produces a
    new PROP/CHANGE on the same item rather than a new physical object.
    """
    if getattr(service, "_physical_item_identity_installed", False):
        return
    original_capture_text = service.capture_text

    def capture_text(text: str, *, source_kind: str, turn: dict[str, Any],
                     session: dict[str, Any], qualifies_review: bool | None = None):
        report = original_capture_text(
            text, source_kind=source_kind, turn=turn, session=session,
            qualifies_review=qualifies_review,
        )
        if session.get("scratch_mode"):
            return report
        compiled = CharacterRailParser.parse(text)
        evidence = str(compiled.evidence_prompt if compiled.active else text or "").strip()
        mentions = _mentions(evidence)
        if not mentions:
            return report
        lineage = turn.get("lineage") or {}
        if lineage.get("forked_from_turn_id") and source_kind != "user_edited_prose":
            return report

        revision = checksum(evidence)
        world_time, story_order = service._turn_time_scope(turn)
        base_qualifies = service.REVIEW_SOURCE_KINDS.__contains__(source_kind) if qualifies_review is None else bool(qualifies_review)
        source = {
            "source_kind": source_kind,
            "session_id": session["id"], "turn_id": turn["id"],
            "origin_session_id": str(lineage.get("forked_from_session_id") or session["id"]),
            "origin_turn_id": str(lineage.get("forked_from_turn_id") or turn["id"]),
            "revision": revision,
            "project_id": session.get("project_id"), "world_id": session.get("world_id"),
            "branch_id": session.get("branch_id"), "world_time": world_time,
            "story_order": story_order, "base_qualifies": bool(base_qualifies),
        }
        context = _context_for(service, turn, session)
        existing = _existing_items(service, context)
        known: dict[str, PhysicalItem] = {item.subject_key: item for item in existing}
        last_by_type: dict[str, PhysicalItem] = {}
        new_ordinals: dict[str, int] = {}
        used_labels = _used_labels(service)
        resolved_mentions: list[tuple[GarmentMention, list[PhysicalItem]]] = []

        for mention in mentions:
            resolved: list[PhysicalItem] = []
            local = last_by_type.get(mention.garment_type)
            if mention.quantity == 1 and local and mention.reference_cue:
                okay, _score = _compatible(local, mention.attributes)
                if okay:
                    resolved = [local]
            if not resolved and mention.quantity == 1 and not mention.force_new:
                candidate, ambiguous = _resolve_existing(
                    list(known.values()), mention.garment_type, mention.attributes
                )
                if candidate is not None:
                    resolved = [candidate]
                elif ambiguous:
                    candidates = [
                        item for item in known.values()
                        if item.garment_type == mention.garment_type and _compatible(item, mention.attributes)[0]
                    ]
                    _record_ambiguity(service, source=source, mention=mention, candidates=candidates)
                    resolved_mentions.append((mention, []))
                    continue
            if not resolved:
                count = mention.quantity
                for copy_index in range(1, count + 1):
                    ordinal = new_ordinals.get(mention.garment_type, 0) + 1
                    new_ordinals[mention.garment_type] = ordinal
                    item_id = _item_id(source["origin_turn_id"], mention.garment_type, ordinal, copy_index)
                    subject_key = _physical_subject_key(item_id)
                    if subject_key in known:
                        item = known[subject_key]
                    else:
                        label = _unique_label(_base_label(mention.garment_type, mention.attributes), used_labels)
                        item = PhysicalItem(
                            subject_key=subject_key, item_id=item_id,
                            garment_type=mention.garment_type, label=label,
                            attributes=dict(mention.attributes), existing=False,
                        )
                        known[subject_key] = item
                    resolved.append(item)
            for item in resolved:
                item.attributes.update(mention.attributes)
                last_by_type[mention.garment_type] = item
            resolved_mentions.append((mention, resolved))

        if not any(items for _mention, items in resolved_mentions):
            return report

        wearer_key, wearer_label = _current_turn_character(service, turn["id"], source_kind)
        legacy_keys = _invalidate_collapsed_garments(service, turn["id"], source_kind)
        physical_prop_ids: set[str] = set()

        for mention, items in resolved_mentions:
            if not items:
                continue
            span_start = max(0, mention.start - 48)
            span_end = min(len(evidence), mention.end + 128)
            span = evidence[span_start:span_end]
            for item in items:
                physical_prop_ids.add(_add_prop(
                    service, source=source, subject_type="garment",
                    subject_key=item.subject_key, subject_label=item.label,
                    predicate="entity.exists",
                    value={
                        "entity_type": "item", "label": item.label,
                        "item_kind": "garment", "garment_type": item.garment_type,
                        "physical_item_id": item.item_id,
                    }, operation="create", start=mention.start, end=mention.end,
                    span_text=mention.raw,
                ))
                physical_prop_ids.add(_add_prop(
                    service, source=source, subject_type="garment",
                    subject_key=item.subject_key, subject_label=item.label,
                    predicate="item.kind", value="garment", operation="update",
                    start=mention.start, end=mention.end, span_text=mention.raw,
                ))
                physical_prop_ids.add(_add_prop(
                    service, source=source, subject_type="garment",
                    subject_key=item.subject_key, subject_label=item.label,
                    predicate="garment.type", value=item.garment_type, operation="update",
                    start=mention.start, end=mention.end, span_text=mention.raw,
                ))
                for key, value in mention.attributes.items():
                    physical_prop_ids.add(_add_prop(
                        service, source=source, subject_type="garment",
                        subject_key=item.subject_key, subject_label=item.label,
                        predicate=f"garment.{key}", value=value, operation="update",
                        start=span_start, end=span_end, span_text=span,
                    ))
                if wearer_key and wearer_label and mention.wearing and mention.quantity == 1:
                    physical_prop_ids.add(_add_prop(
                        service, source=source, subject_type="character",
                        subject_key=wearer_key, subject_label=wearer_label,
                        predicate="wearing", value=True, operation="relation",
                        object_type="garment", object_key=item.subject_key,
                        object_label=item.label, start=span_start, end=span_end,
                        span_text=span, temporal_state="current",
                    ))
                if wearer_key and wearer_label and mention.ownership:
                    physical_prop_ids.add(_add_prop(
                        service, source=source, subject_type="character",
                        subject_key=wearer_key, subject_label=wearer_label,
                        predicate="owns", value=True, operation="relation",
                        object_type="garment", object_key=item.subject_key,
                        object_label=item.label, start=span_start, end=span_end,
                        span_text=span, temporal_state="current_or_unspecified",
                    ))

        _retire_orphaned_legacy_sheets(service, legacy_keys)
        with service.store.connection() as con:
            rows = con.execute(
                "SELECT DISTINCT proposition_id FROM discovery_instances "
                "WHERE source_turn_id=? AND source_kind=? AND source_revision=? AND active=1",
                (turn["id"], source_kind, revision),
            ).fetchall()
            prop_count = len(rows)
            instance_count = con.execute(
                "SELECT COUNT(*) FROM discovery_instances WHERE source_turn_id=? AND source_kind=? "
                "AND source_revision=? AND active=1",
                (turn["id"], source_kind, revision),
            ).fetchone()[0]
        return type(report)(turn["id"], source_kind, prop_count, int(instance_count), report.skipped)

    service.capture_text = capture_text
    service._physical_item_identity_installed = True
