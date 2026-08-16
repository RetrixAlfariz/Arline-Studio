from __future__ import annotations

import re


class EntityReferenceResolver:
    VERSION = "0.3.3"

    GARMENT_TERMS = {
        "gamis": ("gamis", "full_body_garment"),
        "khimar": ("khimar", "head_upper_body_covering"),
        "dress": ("dress", "dress"),
        "bra": ("bra", "undergarment"),
        "celana dalam": ("underwear", "undergarment"),
        "pakaian dalam": ("underwear_set", "undergarment"),
        "kemben": ("kemben", "chest_binding_garment"),
    }

    @classmethod
    def default(cls):
        return cls()

    def resolve(self, normalized_segments: dict, annotations: dict | None = None) -> dict:
        registry: dict[str, dict] = {}
        refs = []
        aliases = []
        lifecycle = []
        annotations = annotations or {"annotations": []}
        segs = normalized_segments.get("segments", [])

        def add(entity_id, entity_type, label, segment=None, provisional=False, attrs=None):
            if entity_id not in registry:
                registry[entity_id] = {
                    "id": entity_id,
                    "type": entity_type,
                    "label": label,
                    "attributes": attrs or {},
                    "introduced_by": segment,
                    "provisional": provisional,
                }
                lifecycle.append({"op": "create", "entity": entity_id, "source_segment": segment})
            elif attrs:
                registry[entity_id].setdefault("attributes", {}).update(attrs)
                lifecycle.append({"op": "refine", "entity": entity_id, "source_segment": segment})
            return registry[entity_id]

        explicit_self_id = None

        # Explicit identity and broad entity discovery.
        for seg in segs:
            text = seg.get("normalized_text") or seg["text"]
            low = text.lower()

            m = re.search(r"\bnamaku\s+([\wÀ-ÿ'-]+)(?:\s+singkatnya\s+([\wÀ-ÿ'-]+))?", text, re.I)
            if m:
                label = (m.group(2) or m.group(1)).lower()
                explicit_self_id = f"char:{label}"
                add(explicit_self_id, "character", label, seg["id"], False, {"canonical_name_hint": m.group(1).lower()})

            # Named Fano references; intentionally conservative for now.
            if re.search(r"\bfano\b", low):
                add("char:fano", "character", "fano", seg["id"], True)

            if "apartemen" in low or "apartment" in low:
                add("loc:apartment_1", "location", "apartment", seg["id"], False)

            for term, (lexical_type, family) in self.GARMENT_TERMS.items():
                # Indonesian possessive/demonstrative suffixes are commonly
                # attached directly to borrowed garment nouns: dressnya,
                # gamisnya, branya, khimarnya. Multi-word terms remain exact.
                if " " in term:
                    present = re.search(rf"\b{re.escape(term)}(?:nya|ku|mu)?\b", low)
                else:
                    present = re.search(rf"\b{re.escape(term)}(?:nya|ku|mu)?\b", low)
                if present:
                    base = lexical_type.replace(" ", "_")
                    entity_id = f"garment:{base}_1"
                    add(entity_id, "garment", lexical_type, seg["id"], False, {
                        "ontology": {"garment_family": family, "lexical_type": lexical_type}
                    })

            if re.search(r"\bpakaian\s+(?:cewek|perempuan)\b", low) and not any(t in low for t in ("dress", "gamis", "khimar")):
                add(
                    "garment:feminine_clothing_1",
                    "garment",
                    "feminine_clothing",
                    seg["id"],
                    True,
                    {"ontology": {"garment_family": "feminine_clothing", "lexical_type": "feminine_clothing"}},
                )

            if "wig" in low:
                add("item:wig_1", "item", "wig", seg["id"], False)
            if re.search(r"prosteti[ck]|prosthetic", low):
                add("item:transformation_item_1", "item", "transformation_item", seg["id"], False)

            # Families / parents are useful even when unnamed.
            if re.search(r"\b(?:orang\s+tuaku|orang\s+tua\s+ku|keluargaku|mama(?:ku)?)\b", low):
                add("family:self", "family", "self_family", seg["id"], True)
            if re.search(r"\b(?:keluarga\s+fano|ibunya\s+fano|ibu\s+fano)\b", low):
                add("family:fano", "family", "fano_family", seg["id"], True)
            if re.search(r"\b(?:mama|mamaku)\b", low):
                add("char:self_mother", "character", "self_mother", seg["id"], True)
            if re.search(r"\b(?:ibunya\s+fano|ibu\s+fano)\b", low):
                add("char:fano_mother", "character", "fano_mother", seg["id"], True)

        # Annotation-based refinements, especially temanku[cowok-fano].
        for ann in annotations.get("annotations", []):
            for hint in ann.get("hints", []):
                if hint.get("type") == "person_identity":
                    name = hint["name"].lower()
                    add(
                        f"char:{name}",
                        "character",
                        name,
                        ann.get("segment_id"),
                        True,
                        {"gender": {
                            "value": hint.get("gender"),
                            "epistemic": "explicit",
                            "confidence": 0.95,
                            "source_segment": ann.get("segment_id"),
                            "inferred": False,
                        }},
                    )

        has_self_language = any(
            re.search(r"\b(?:aku|saya|ku|tubuhku|bodyku|dadaku|rambutku|keluargaku)\b", (s.get("normalized_text") or s["text"]).lower())
            for s in segs
        )

        if explicit_self_id:
            self_id = explicit_self_id
            aliases.append({
                "alias": "char:self",
                "canonical": self_id,
                "reason": "explicit self identity discovered",
            })
            lifecycle.append({"op": "alias", "entity": "char:self", "canonical": self_id})
        elif has_self_language:
            self_id = "char:self"
            add(self_id, "character", "self", None, True)
        else:
            self_id = "char:character"
            add(self_id, "character", "character", None, True)

        # Relationship entity if Fano + relationship vocabulary is present.
        joined = " ".join((s.get("normalized_text") or s["text"]).lower() for s in segs)
        if "char:fano" in registry and re.search(r"\b(?:teman|pacar|dijodohkan|pacaran|hubungan)\b", joined):
            add(
                "relationship:self_fano",
                "relationship",
                "self_fano",
                None,
                True,
                {"participants": [self_id, "char:fano"]},
            )

        # Reference resolution.
        last_item = None
        last_garment = None
        last_person = None
        for seg in segs:
            low = (seg.get("normalized_text") or seg["text"]).lower()

            if "prosteti" in low or "prosthetic" in low:
                last_item = "item:transformation_item_1"
            if "wig" in low:
                last_item = "item:wig_1"

            for eid, entity in registry.items():
                label = str(entity.get("label") or "")
                if entity["type"] == "garment" and label:
                    if re.search(rf"\b{re.escape(label)}(?:nya|ku|mu)?\b", low):
                        last_garment = eid
            if "fano" in low:
                last_person = "char:fano"

            if "benda itu" in low and last_item:
                refs.append({"segment_id": seg["id"], "mention": "benda itu", "target_entity": last_item, "confidence": 0.86})
            if "prostetik tadi" in low or "prostetic tadi" in low:
                refs.append({"segment_id": seg["id"], "mention": "prostetik tadi", "target_entity": "item:transformation_item_1", "confidence": 0.94})
            if "wig tadi" in low:
                refs.append({"segment_id": seg["id"], "mention": "wig tadi", "target_entity": "item:wig_1", "confidence": 0.95})
            if "warna senada" in low:
                # Prefer the garment described by the immediately enclosing
                # annotation context (e.g. dress(...) [underwear same colour])
                # instead of whichever undergarment happened to be mentioned
                # last inside this segment.
                context = str(seg.get("context_text") or "").lower()
                context_target = None
                for candidate in ("dress", "gamis", "khimar", "kemben"):
                    eid = f"garment:{candidate}_1"
                    if eid in registry and re.search(rf"\b{candidate}(?:nya|ku|mu)?\b", context):
                        context_target = eid
                        break
                target = context_target or last_garment
                if target:
                    refs.append({"segment_id": seg["id"], "mention": "warna senada", "target_entity": target, "confidence": 0.9 if context_target else 0.88})
            if re.search(r"\b(?:dia|dia-nya)\b", low) and last_person:
                refs.append({"segment_id": seg["id"], "mention": "dia", "target_entity": last_person, "confidence": 0.72})
            if re.search(r"\b(?:aku|saya|tubuhku|bodyku|dadaku|rambutku|keluargaku)\b", low):
                refs.append({"segment_id": seg["id"], "mention": "self", "target_entity": self_id, "confidence": 0.99})

        return {
            "version": self.VERSION,
            "entities": list(registry.values()),
            "resolutions": refs,
            "aliases": aliases,
            "self_entity": self_id,
            "lifecycle": lifecycle,
            "diagnostics": [],
        }
