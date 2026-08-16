from __future__ import annotations

import re

from src.common.utils import MONTHS, COLORS, clean, cm


class StateExtractor:
    VERSION = "0.3.3"

    @classmethod
    def default(cls):
        return cls()

    def F(self, value, segment, confidence=.95, epistemic="explicit", inferred=False):
        return {
            "value": value,
            "epistemic": epistemic,
            "confidence": round(float(confidence), 4),
            "source_segment": segment,
            "inferred": inferred,
        }

    def extract(self, resolved_segments, entity_data, claims=None):
        claims = claims or {"claims": []}
        entities = {e["id"]: dict(e) for e in entity_data.get("entities", [])}
        directives, requests, unknowns, relations = [], [], [], []
        experience, norms, knowledge, beliefs, relationship_timeline = [], [], [], [], []

        char_id = entity_data.get("self_entity") or next(
            (k for k, v in entities.items() if v.get("type") == "character"),
            "char:self",
        )
        entities.setdefault(char_id, {
            "id": char_id,
            "type": "character",
            "label": "self",
            "attributes": {},
            "provisional": True,
        })
        A = entities[char_id].setdefault("attributes", {})
        for key, default in (
            ("identity", {}),
            ("physical", {}),
            ("hair", {"baseline": {}, "current": {}}),
            ("skills", {}),
            ("transformations", {}),
            ("endocrine", {}),
            ("biological_context", {}),
            ("scene_state", {}),
        ):
            A.setdefault(key, default)

        loc = entities.get("loc:apartment_1")
        if loc:
            loc.setdefault("attributes", {})

        # Initial runtime is state asserted as already true at scene start.
        initial_runtime = {
            char_id: {
                "hair": {},
                "wearing": {},
                "transformations": {},
                "comfort": {},
            }
        }

        # ------------------------------------------------------------------
        # Conservative baseline extraction retained from v0.3.1.
        # ------------------------------------------------------------------
        for s in resolved_segments.get("segments", []):
            text = s.get("normalized_text") or s["text"]
            low = text.lower()
            sid = s["id"]
            scope = s.get("scope", {})

            if "directive" in s.get("roles", []):
                directives.append({"segment_id": sid, "text": s.get("raw_text") or s["text"]})
            if "request" in s.get("roles", []) or scope.get("modality") == "request":
                requests.append({"segment_id": sid, "text": s.get("raw_text") or s["text"]})
            if scope.get("modality") in {"request", "hypothetical", "intent"}:
                continue
            positive = scope.get("polarity", "positive") == "positive"

            m = re.search(r"\bnamaku\s+([\wÀ-ÿ'-]+)(?:\s+singkatnya\s+([\wÀ-ÿ'-]+))?", text, re.I)
            if m and positive:
                A["identity"]["name"] = self.F(m.group(1).lower(), sid, .99)
                if m.group(2):
                    A["identity"]["nickname"] = self.F(m.group(2).lower(), sid, .99)

            m = re.search(r"\b(?:sekarang\s+)?(?:umur|usia)\s*[:=]?\s*(\d{1,3})\b", text, re.I)
            if m and positive:
                A["identity"]["age"] = self.F(int(m.group(1)), sid, .99)

            m = re.search(r"\blahir\s+(?:tanggal\s+)?(\d{1,2})\s+(" + "|".join(MONTHS) + r")\b", text, re.I)
            if m and positive:
                A["identity"]["birth"] = {
                    "day": self.F(int(m.group(1)), sid, .99),
                    "month": self.F(MONTHS[m.group(2).lower()], sid, .99),
                }

            m = re.search(r"\b(?:pakai|memakai|menggunakan)\s+nama\s+(?:perempuan\s+)?([\wÀ-ÿ'-]+)", text, re.I)
            if m and positive:
                A["identity"]["presentation_name"] = self.F(m.group(1).lower(), sid, .98)

            m = re.search(
                r"\b(?:tinggi(?:ku|nya)?|height)\s*(?:sekitar|kurang lebih|=|:)?\s*"
                r"(\d+(?:[.,]\d+)?)\s*(cm|m|meter)\b",
                text,
                re.I,
            )
            if m and positive:
                A["physical"]["height_cm"] = self.F(
                    clean(cm(float(m.group(1).replace(",", ".")), m.group(2))), sid, .995
                )

            morph = {}
            if re.search(r"\b(?:ramping|slim)\b", low):
                morph["frame"] = "slim"
            if re.search(r"\b(?:mirip\s+dengan\s+perempuan|seperti\s+cewek|feminin|feminine)\b", low):
                morph["presentation"] = "feminine"
            if "kaki jenjang" in low:
                morph["leg_proportion"] = "long"
            if re.search(r"tangan\s+(?:halus\s+)?ramping", low):
                morph["hand_build"] = "slender"
            if "bokong" in low and "montok" in low:
                morph["gluteal_fullness"] = "full"
            if "pinggul ramping" in low:
                morph["hip_descriptor"] = "slender"
            if morph and positive:
                A["physical"].setdefault("morphology", {})
                for k, v in morph.items():
                    A["physical"]["morphology"][k] = self.F(v, sid, .90)

            if "sensitif" in low and positive:
                A["physical"].setdefault("sensitivity", {})["skin"] = self.F("high", sid, .84)

            cup = re.search(r"\b([A-H])\s*cup\b", text, re.I)
            if cup and positive:
                A["physical"].setdefault("chest", {})["reference_cup"] = self.F(cup.group(1).upper(), sid, .99)
                unknowns.append({
                    "candidate": "exact_chest_circumference_cm",
                    "status": "blocked",
                    "reason": "cup letter alone is insufficient",
                    "source_segment": sid,
                })

            if re.search(r"rambut(?:ku|nya)?\s+pendek", low) and positive:
                A["hair"]["baseline"]["length_class"] = self.F("short", sid, .99)
                initial_runtime[char_id]["hair"]["length_class"] = "short"

            combined = (s.get("context_text", "") + " " + text).lower()
            hm = re.search(
                r"(?:rambut|wig).{0,320}?(?:panjang(?:nya)?(?:\s+itu)?\s*)"
                r"(\d+(?:[.,]\d+)?)\s*(cm|m|meter)\b",
                combined,
                re.I | re.S,
            )
            if hm and positive:
                A["hair"]["current"]["length_cm"] = self.F(
                    clean(cm(float(hm.group(1).replace(",", ".")), hm.group(2))), sid, .98
                )
            if re.search(r"\b(?:lebat\s+banget|sangat\s+lebat)\b", combined) and positive:
                A["hair"]["current"]["density"] = self.F("very_high", sid, .96)

            if "voice acting" in low:
                A["skills"]["voice_acting"] = self.F(True, sid, .98)
            if re.search(r"mengubah\s+suar[au].{0,80}(?:perempuan|cewek)", low):
                A["skills"]["feminine_voice_imitation"] = self.F(True, sid, .92)

            if loc:
                fl = re.search(r"\b(?:lantai|floor)\s*(?:ke-?)?\s*(\d{1,3})\b", text, re.I)
                if fl:
                    loc["attributes"]["floor"] = self.F(int(fl.group(1)), sid, .99)
                ar = re.search(r"\bluas\s*(?:[:=])?\s*(\d+(?:[.,]\d+)?)\s*(m2|m²|meter\s*persegi)\b", text, re.I)
                if ar:
                    loc["attributes"]["area_m2"] = self.F(clean(float(ar.group(1).replace(",", "."))), sid, .99)
                else:
                    ar = re.search(r"\bluas\s*(?:[:=])?\s*(\d+(?:[.,]\d+)?)\s*m\b", text, re.I)
                    if ar:
                        loc["attributes"]["area_m2"] = self.F(clean(float(ar.group(1).replace(",", "."))), sid, .82, "inferred", True)
                city = re.search(r"\b(?:di|merantau\s+di)\s+(surabaya|jayapura|jakarta|bandung|malang|makassar)\b", low)
                if city:
                    loc["attributes"]["city"] = self.F(city.group(1).title(), sid, .97)

            if re.search(r"(?:wig.{0,240})?(?:menyatu|nyatu).{0,200}rambut", combined, re.S) and "item:wig_1" in entities:
                A["transformations"]["wig_integrated_as_hair"] = self.F(True, sid, .95)
                relations.append({
                    "subject": "item:wig_1",
                    "predicate": "integrated_into",
                    "object": char_id + ".hair",
                    "confidence": .94,
                    "source_segment": sid,
                    "temporal_scope": "current_after_transition",
                })

            if (
                re.search(r"(?:prosteti[ck]|prosthetic).{0,450}(?:melebur|menyatu|mengubah|berubah)", combined, re.S)
                or (("melebur" in combined or "menyatu" in combined)
                    and ("mengubah" in combined or "berubah" in combined)
                    and "item:transformation_item_1" in entities)
            ):
                A["transformations"]["fictional_anatomical_transformation"] = self.F(
                    {"active": True, "scope": "anatomical", "source_type": "prosthetic_like_fictional_item"},
                    sid,
                    .93,
                )

            if "tinggal sendiri" in low and loc:
                relations.append({
                    "subject": char_id,
                    "predicate": "lives_alone_at",
                    "object": "loc:apartment_1",
                    "confidence": .97,
                    "source_segment": sid,
                    "temporal_scope": "current",
                })

        # ------------------------------------------------------------------
        # Claim materialization.
        # ------------------------------------------------------------------
        for claim in claims.get("claims", []):
            pred = claim["predicate"]
            subject = claim.get("subject")
            obj = claim.get("object")
            value = claim.get("value")
            sid = claim["source_segment"]
            conf = claim["confidence"]
            epistemic = claim.get("epistemic", "explicit")
            temporal = claim.get("scope", {}).get("temporal", "current_or_unspecified")
            kind = claim.get("kind")

            # Character attributes.
            if subject == char_id:
                if pred == "physical.morphology.presentation":
                    A["physical"].setdefault("morphology", {})["presentation"] = self.F(value, sid, conf, epistemic, epistemic != "explicit")
                elif pred == "physical.chest.reference_cup":
                    A["physical"].setdefault("chest", {})["reference_cup"] = self.F(value, sid, conf, epistemic, epistemic != "explicit")
                elif pred == "physical.chest.softness":
                    A["physical"].setdefault("chest", {})["softness"] = self.F(value, sid, conf, epistemic, epistemic != "explicit")
                elif pred == "physical.chest.compliance":
                    A["physical"].setdefault("chest", {})["compliance"] = self.F(value, sid, conf, epistemic, epistemic != "explicit")
                elif pred == "physical.chest.growth_profile":
                    A["physical"].setdefault("chest", {})["growth_profile"] = self.F(value, sid, conf, epistemic, epistemic != "explicit")
                elif pred == "endocrine.feminizing_hormone_production":
                    A["endocrine"]["feminizing_hormone_production"] = self.F(value, sid, conf, epistemic, epistemic != "explicit")
                elif pred == "biological_context.baseline_sex":
                    A["biological_context"]["baseline_sex"] = self.F(value, sid, conf, epistemic, epistemic != "explicit")
                elif pred == "hair.length_relative":
                    A["hair"]["current"]["length_relative"] = self.F(value, sid, conf, epistemic, epistemic != "explicit")
                elif pred == "comfort.thermal":
                    A["scene_state"]["thermal_comfort"] = self.F(value, sid, conf, epistemic, epistemic != "explicit")
                    initial_runtime[char_id]["comfort"]["thermal"] = value

            # Garment attributes.
            if subject in entities and entities[subject].get("type") == "garment":
                G = entities[subject].setdefault("attributes", {})
                attr_map = {
                    "garment.color": "color",
                    "garment.material": "material",
                    "garment.length": "length",
                    "garment.front_length": "front_length",
                    "garment.back_length": "back_length",
                    "garment.flowiness": "flowiness",
                    "garment.size_class": "size_class",
                    "garment.construction": "construction",
                }
                if pred in attr_map:
                    G[attr_map[pred]] = self.F(value, sid, conf, epistemic, epistemic != "explicit")

            # Current wearing state assertion.
            if pred == "garment.wearing" and subject == char_id and obj:
                relations.append({
                    "subject": char_id,
                    "predicate": "wearing",
                    "object": obj,
                    "confidence": conf,
                    "source_segment": sid,
                    "temporal_scope": "current",
                })
                initial_runtime[char_id]["wearing"][obj] = True

            # Relations / history / social / provenance.
            if kind in {"relation", "knowledge"} or pred.startswith("relationship.") or pred.startswith("social.") or pred.startswith("knowledge.") or pred in {"garment.purchased_for", "garment.fits"}:
                if pred not in {"garment.wearing"}:
                    relations.append({
                        "subject": subject,
                        "predicate": pred,
                        "object": obj,
                        "value": value,
                        "confidence": conf,
                        "epistemic": epistemic,
                        "source_segment": sid,
                        "temporal_scope": temporal,
                        "metadata": claim.get("metadata", {}),
                    })

            if kind == "experience" or pred.startswith("experience."):
                experience.append({
                    "subject": subject,
                    "predicate": pred,
                    "object": obj,
                    "value": value,
                    "confidence": conf,
                    "source_segment": sid,
                    "temporal_scope": temporal,
                })

            if kind == "norm" or pred.startswith("norm."):
                norms.append({
                    "subject": subject,
                    "predicate": pred,
                    "object": obj,
                    "value": value,
                    "confidence": conf,
                    "source": claim.get("source", {}),
                    "source_segment": sid,
                    "temporal_scope": temporal,
                    "metadata": claim.get("metadata", {}),
                })

            if kind == "knowledge" or pred.startswith("knowledge."):
                knowledge.append({
                    "knower": subject,
                    "predicate": pred,
                    "known_object": obj,
                    "value": value,
                    "confidence": conf,
                    "source_segment": sid,
                })

            if kind == "belief" or pred.startswith("belief."):
                beliefs.append({
                    "believer": subject,
                    "predicate": pred,
                    "object": obj,
                    "belief": value,
                    "truth_status": claim.get("metadata", {}).get("truth_status", "unknown"),
                    "confidence": conf,
                    "source_segment": sid,
                })

            if kind == "transition" and pred == "relationship.transition":
                relationship_timeline.append({
                    "relationship": subject,
                    "participants": [char_id, obj] if obj else [char_id],
                    "transition": value,
                    "confidence": conf,
                    "source_segment": sid,
                })

        # Temporal-aware claim contradiction detection. Claims only conflict
        # when subject + predicate + temporal scope match but values disagree.
        claim_conflicts = []
        claim_slots = {}
        for c in claims.get("claims", []):
            key = (
                c.get("subject"), c.get("predicate"),
                c.get("scope", {}).get("temporal", "current_or_unspecified"),
            )
            val = repr(c.get("value"))
            if key in claim_slots and claim_slots[key][0] != val:
                claim_conflicts.append({
                    "type": "claim_value_conflict",
                    "subject": key[0],
                    "predicate": key[1],
                    "temporal_scope": key[2],
                    "values": [claim_slots[key][1], c.get("value")],
                    "source_segments": [claim_slots[key][2], c.get("source_segment")],
                })
            else:
                claim_slots[key] = (val, c.get("value"), c.get("source_segment"))

        # Semantic deduplication.
        rel_out, seen = [], set()
        for r in relations:
            key = (
                r.get("subject"), r.get("predicate"), r.get("object"),
                repr(r.get("value")), r.get("temporal_scope"),
            )
            if key not in seen:
                seen.add(key)
                rel_out.append(r)

        u_out, u_seen = [], set()
        for u in unknowns:
            key = (u.get("candidate"), u.get("source_segment"))
            if key not in u_seen:
                u_seen.add(key)
                u_out.append(u)

        return {
            "version": self.VERSION,
            "entities": list(entities.values()),
            "relations": rel_out,
            "experience": experience,
            "norms": norms,
            "knowledge": knowledge,
            "beliefs": beliefs,
            "relationship_timeline": relationship_timeline,
            "initial_runtime": initial_runtime,
            "claim_conflicts": claim_conflicts,
            "directives": directives,
            "requests": requests,
            "unknowns": u_out,
            "claims": claims.get("claims", []),
            "diagnostics": [],
        }
