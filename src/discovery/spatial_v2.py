from __future__ import annotations

import re

from .general import GeneralCandidate


_CONTAINER_KINDS = {
    "gedung": "building",
    "building": "building",
    "hotel": "hotel",
    "rumah": "house",
    "house": "house",
    "asrama": "dormitory",
    "dorm": "dormitory",
    "dormitory": "dormitory",
}
_LEAF_KINDS = {
    "unit": "unit",
    "ruang": "room",
    "room": "room",
    "kamar": "room",
}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_") or "unknown"


def _display(value: str) -> str:
    clean = " ".join(str(value or "").strip(" ,.;:-").split())
    if clean and clean == clean.lower():
        return clean.title()
    return clean


def _numeric_area(match) -> int | float | None:
    if not match:
        return None
    raw = match.group("area").replace(",", ".")
    value = float(raw)
    return int(value) if value.is_integer() else value


def detect_generic_location_hierarchy(text: str) -> list[GeneralCandidate]:
    container_match = re.search(
        r"(?i)(?:\blocation\s+)?\b(?P<type>gedung|building|hotel|rumah|house|asrama|dormitory|dorm)\s+"
        r"(?P<name>[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9'’.-]*(?:\s+[A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9'’.-]*){0,6}?)"
        r"(?=\s+(?:lantai|floor|unit|ruang|room|kamar)\b|\s*\[|\s*,|$)",
        text,
    )
    if not container_match:
        return []

    type_word = container_match.group("type")
    container_kind = _CONTAINER_KINDS[type_word.casefold()]
    container_label = _display(f"{type_word} {container_match.group('name')}")
    container_key = f"loc:{_slug(container_label)}"

    floor_match = re.search(r"(?i)\b(?:lantai|floor)\s*(?P<floor>\d{1,4})\b", text)
    leaf_match = re.search(
        r"(?i)\b(?P<leaf_type>unit|ruang|room|kamar)\s*(?P<leaf>[A-Za-z][A-Za-z0-9_-]{0,30}|\d[A-Za-z0-9_-]{0,30})\b",
        text,
    )
    area_match = re.search(
        r"(?i)\b(?:ukuran|luas|area)\s*(?P<area>\d+(?:[.,]\d+)?)\s*(?:m2|m²|m\b)", text
    )
    room_count_match = re.search(r"(?i)\b(?P<rooms>\d{1,3})\s*(?:kamar|rooms?)\b", text)
    city_match = re.search(
        r",\s*(?P<city>[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’.-]*(?:\s+[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’.-]*){0,3})\s*$",
        text.strip(),
    )

    matches = [m for m in (container_match, floor_match, leaf_match, area_match, room_count_match, city_match) if m]
    span_start = container_match.start()
    span_end = max(match.end() for match in matches)
    span = text[span_start:span_end]

    out: list[GeneralCandidate] = [
        GeneralCandidate(
            "location", container_key, container_label, "entity.exists",
            {"entity_type": "location", "label": container_label, "location_kind": container_kind},
            "create", container_match.start(), container_match.end(), container_match.group(0), 0.97,
        ),
        GeneralCandidate(
            "location", container_key, container_label, "location.kind", container_kind,
            "update", container_match.start(), container_match.end(), container_match.group(0), 0.98,
        ),
    ]

    if city_match:
        city = _display(city_match.group("city"))
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
                "location", container_key, container_label, "located_in", True, "relation",
                span_start, span_end, span, 0.95,
                object_type="location", object_key=city_key, object_label=city,
            ),
        ]

    floor_key = None
    floor_label = None
    floor_number = None
    if floor_match:
        floor_number = int(floor_match.group("floor"))
        floor_label = f"Floor {floor_number}"
        floor_key = f"zone:{_slug(container_label)}:floor:{floor_number}"
        out += [
            GeneralCandidate(
                "spatial_zone", floor_key, floor_label, "zone.exists",
                {
                    "zone_kind": "floor",
                    "parent_subject_key": container_key,
                    "attributes": {"floor_number": floor_number},
                },
                "create", floor_match.start(), floor_match.end(), floor_match.group(0), 0.99,
            ),
            GeneralCandidate(
                "spatial_zone", floor_key, floor_label, "part_of", True, "relation",
                floor_match.start(), floor_match.end(), floor_match.group(0), 0.99,
                object_type="location", object_key=container_key, object_label=container_label,
            ),
        ]

    attribute_subject_key = container_key
    attribute_subject_label = container_label
    if leaf_match:
        leaf_type_word = leaf_match.group("leaf_type")
        leaf_kind = _LEAF_KINDS[leaf_type_word.casefold()]
        leaf_label = _display(f"{leaf_type_word} {leaf_match.group('leaf')}")
        leaf_key = f"loc:{_slug(container_label)}:{leaf_kind}:{_slug(leaf_match.group('leaf'))}"
        attribute_subject_key = leaf_key
        attribute_subject_label = leaf_label
        out += [
            GeneralCandidate(
                "location", leaf_key, leaf_label, "entity.exists",
                {"entity_type": "location", "label": leaf_label, "location_kind": leaf_kind},
                "create", leaf_match.start(), leaf_match.end(), leaf_match.group(0), 0.99,
            ),
            GeneralCandidate(
                "location", leaf_key, leaf_label, "location.kind", leaf_kind,
                "update", leaf_match.start(), leaf_match.end(), leaf_match.group(0), 0.99,
            ),
            GeneralCandidate(
                "location", leaf_key, leaf_label, "part_of", True, "relation",
                span_start, span_end, span, 0.98,
                object_type="location", object_key=container_key, object_label=container_label,
            ),
        ]
        if floor_key:
            out += [
                GeneralCandidate(
                    "location", leaf_key, leaf_label, "located_on", True, "relation",
                    span_start, span_end, span, 0.99,
                    object_type="spatial_zone", object_key=floor_key, object_label=floor_label,
                ),
                GeneralCandidate(
                    "location", leaf_key, leaf_label, "floor_number", floor_number, "update",
                    floor_match.start(), floor_match.end(), floor_match.group(0), 0.99,
                ),
            ]

    area = _numeric_area(area_match)
    if area is not None:
        out.append(
            GeneralCandidate(
                "location", attribute_subject_key, attribute_subject_label, "area_m2", area, "update",
                area_match.start(), area_match.end(), area_match.group(0), 0.99,
            )
        )
    if room_count_match:
        out.append(
            GeneralCandidate(
                "location", attribute_subject_key, attribute_subject_label,
                "room_count", int(room_count_match.group("rooms")), "update",
                room_count_match.start(), room_count_match.end(), room_count_match.group(0), 0.98,
            )
        )

    return out


def install_spatial_v2(spatial_module) -> None:
    """Extend the high-precision spatial detector without replacing apartment rules."""
    if getattr(spatial_module, "_SPATIAL_V2_INSTALLED", False):
        return
    legacy = spatial_module.detect_location_hierarchy

    def detect_location_hierarchy(text: str):
        result = legacy(text)
        if result:
            return result
        return detect_generic_location_hierarchy(text)

    spatial_module.detect_location_hierarchy = detect_location_hierarchy
    spatial_module._SPATIAL_V2_INSTALLED = True
