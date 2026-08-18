from __future__ import annotations

import re
from typing import Any

from src.narrative.rails import CharacterRailParser

from .general import GeneralCandidate
from .service import CaptureReport, DiscoveryService
from .store import checksum


_INSTALLED = False


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_") or "unknown"


def _display_name(value: str) -> str:
    clean = " ".join(value.strip(" ,.;:-").split())
    if clean and clean == clean.lower():
        return clean.title()
    return clean


def detect_location_hierarchy(text: str) -> list[GeneralCandidate]:
    """Extract a persistent apartment/building/floor/unit containment chain.

    Classification words such as `apartemen` are types, not physical nodes.
    Floors are lightweight spatial zones; buildings/cities/units are callable
    Location sheets. Scalar measurements remain attributes on the unit.
    """
    building_match = re.search(
        r"(?i)(?:\blocation\s+)?\b(?:apartemen|apartment)\s+"
        r"(?P<building>[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9'’.-]*(?:\s+[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9'’.-]*){0,5}?)"
        r"(?=\s+(?:lantai|floor)\b|\s+unit\b|\s*\[|\s*,|$)",
        text,
    )
    if not building_match:
        return []

    building = _display_name(building_match.group("building"))
    if not building:
        return []
    floor_match = re.search(r"(?i)\b(?:lantai|floor)\s*(?P<floor>\d{1,4})\b", text)
    unit_match = re.search(r"(?i)\bunit\s*(?P<unit>[A-Za-z0-9][A-Za-z0-9_-]{0,20})\b", text)
    area_match = re.search(
        r"(?i)\b(?:ukuran|luas|area)\s*(?P<area>\d+(?:[.,]\d+)?)\s*(?:m2|m²|m\b)", text
    )
    room_match = re.search(r"(?i)\b(?P<rooms>\d{1,3})\s*(?:kamar|rooms?)\b", text)
    city_match = re.search(
        r",\s*(?P<city>[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’.-]*(?:\s+[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’.-]*){0,3})\s*$",
        text.strip(),
    )

    building_key = f"loc:{_slug(building)}"
    span_start = building_match.start()
    span_end = max(
        [m.end() for m in (building_match, floor_match, unit_match, area_match, room_match, city_match) if m]
    )
    span = text[span_start:span_end]
    out: list[GeneralCandidate] = [
        GeneralCandidate(
            "location", building_key, building, "entity.exists",
            {"entity_type": "location", "label": building, "location_kind": "apartment_building"},
            "create", building_match.start(), building_match.end(), building_match.group(0), 0.98,
        ),
        GeneralCandidate(
            "location", building_key, building, "location.kind", "apartment_building",
            "update", building_match.start(), building_match.end(), building_match.group(0), 0.99,
        ),
    ]

    city_key = None
    city = None
    if city_match:
        city = _display_name(city_match.group("city"))
        city_key = f"loc:{_slug(city)}"
        out += [
            GeneralCandidate(
                "location", city_key, city, "entity.exists",
                {"entity_type": "location", "label": city, "location_kind": "city"},
                "create", city_match.start(), city_match.end(), city_match.group(0), 0.94,
            ),
            GeneralCandidate(
                "location", city_key, city, "location.kind", "city",
                "update", city_match.start(), city_match.end(), city_match.group(0), 0.96,
            ),
            GeneralCandidate(
                "location", building_key, building, "located_in", True, "relation",
                span_start, span_end, span, 0.95,
                object_type="location", object_key=city_key, object_label=city,
            ),
        ]

    floor_key = None
    floor_label = None
    if floor_match:
        floor_number = int(floor_match.group("floor"))
        floor_label = f"Floor {floor_number}"
        floor_key = f"zone:{_slug(building)}:floor:{floor_number}"
        out += [
            GeneralCandidate(
                "spatial_zone", floor_key, floor_label, "zone.exists",
                {
                    "zone_kind": "floor",
                    "parent_subject_key": building_key,
                    "attributes": {"floor_number": floor_number},
                },
                "create", floor_match.start(), floor_match.end(), floor_match.group(0), 0.99,
            ),
            GeneralCandidate(
                "spatial_zone", floor_key, floor_label, "part_of", True, "relation",
                floor_match.start(), floor_match.end(), floor_match.group(0), 0.99,
                object_type="location", object_key=building_key, object_label=building,
            ),
        ]

    if unit_match:
        unit_code = unit_match.group("unit").upper()
        unit_label = f"Unit {unit_code}"
        # Unit identity is namespaced by building so two buildings can both own A0325.
        unit_key = f"loc:{_slug(building)}:unit:{_slug(unit_code)}"
        out += [
            GeneralCandidate(
                "location", unit_key, unit_label, "entity.exists",
                {"entity_type": "location", "label": unit_label, "location_kind": "apartment_unit"},
                "create", unit_match.start(), unit_match.end(), unit_match.group(0), 0.99,
            ),
            GeneralCandidate(
                "location", unit_key, unit_label, "location.kind", "apartment_unit",
                "update", unit_match.start(), unit_match.end(), unit_match.group(0), 0.99,
            ),
        ]
        if floor_key:
            out.append(
                GeneralCandidate(
                    "location", unit_key, unit_label, "located_on", True, "relation",
                    span_start, span_end, span, 0.99,
                    object_type="spatial_zone", object_key=floor_key, object_label=floor_label,
                )
            )
        else:
            out.append(
                GeneralCandidate(
                    "location", unit_key, unit_label, "part_of", True, "relation",
                    span_start, span_end, span, 0.96,
                    object_type="location", object_key=building_key, object_label=building,
                )
            )
        if area_match:
            raw = area_match.group("area").replace(",", ".")
            area = float(raw)
            if area.is_integer():
                area = int(area)
            out.append(
                GeneralCandidate(
                    "location", unit_key, unit_label, "area_m2", area, "update",
                    area_match.start(), area_match.end(), area_match.group(0), 0.99,
                )
            )
        if room_match:
            out.append(
                GeneralCandidate(
                    "location", unit_key, unit_label, "room_count", int(room_match.group("rooms")), "update",
                    room_match.start(), room_match.end(), room_match.group(0), 0.99,
                )
            )

    return out


def install_spatial_discovery() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    original_capture_text = DiscoveryService.capture_text

    def capture_text_with_spatial(
        self: DiscoveryService,
        text: str,
        *,
        source_kind: str,
        turn: dict[str, Any],
        session: dict[str, Any],
        qualifies_review: bool | None = None,
    ) -> CaptureReport:
        report = original_capture_text(
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
        candidates = detect_location_hierarchy(evidence)
        if not candidates:
            return report

        revision = checksum(evidence)
        world_time, story_order = self._turn_time_scope(turn)
        base_qualifies = self.REVIEW_SOURCE_KINDS.__contains__(source_kind) if qualifies_review is None else bool(qualifies_review)
        origin_turn_id = str(lineage.get("forked_from_turn_id") or turn["id"])
        origin_session_id = str(lineage.get("forked_from_session_id") or session["id"])
        added_props: set[str] = set()
        added_instances = 0

        for index, item in enumerate(candidates, 1):
            prop = self.store.upsert_proposition(
                project_id=session.get("project_id"), world_id=session.get("world_id"),
                subject_type=item.subject_type, subject_key=item.subject_key,
                subject_label=item.subject_label, predicate=item.predicate, value=item.value,
                object_type=item.object_type, object_key=item.object_key,
                object_label=item.object_label, operation=item.operation,
                temporal_state=item.temporal_state,
            )
            existing = self.store.list_instances(prop["id"])
            if any(
                inst.get("source_turn_id") == turn["id"]
                and inst.get("source_kind") == source_kind
                and inst.get("source_revision") == revision
                and inst.get("active")
                for inst in existing
            ):
                continue
            self.store.add_instance(
                prop["id"], source_kind=source_kind,
                source_session_id=session["id"], source_turn_id=turn["id"],
                origin_session_id=origin_session_id, origin_turn_id=origin_turn_id,
                source_revision=revision, project_id=session.get("project_id"),
                world_id=session.get("world_id"), branch_id=session.get("branch_id"),
                world_time=world_time, story_order=story_order,
                source_segment=f"spatial:{index}", span_start=item.start, span_end=item.end,
                span_text=item.span_text, extraction_confidence=item.confidence,
                explicitness="explicit",
                qualifies_review=bool(base_qualifies and item.confidence >= 0.7),
            )
            added_props.add(prop["id"])
            added_instances += 1

        return CaptureReport(
            report.turn_id, report.source_kind,
            report.propositions + len(added_props), report.instances + added_instances,
            report.skipped,
        )

    DiscoveryService.capture_text = capture_text_with_spatial
    _INSTALLED = True
