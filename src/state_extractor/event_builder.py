from __future__ import annotations

import re


class EventBuilder:
    VERSION = "0.3.3"

    @classmethod
    def default(cls):
        return cls()

    def build(self, resolved_segments, state, scenario=None):
        entities = {e["id"]: e for e in state.get("entities", [])}
        char = next(
            (
                e["id"] for e in state.get("entities", [])
                if e.get("type") == "character" and e.get("label") not in {"fano", "self_mother", "fano_mother"}
            ),
            "char:self",
        )
        A = entities.get(char, {}).get("attributes", {})
        hair = A.get("hair", {}).get("current", {})
        initial_wearing = state.get("initial_runtime", {}).get(char, {}).get("wearing", {})

        events = []
        candidates = []

        def candidate(seg, event_type, score, reasons, rejected_reason=None):
            record = {
                "segment_id": seg["id"],
                "event_type": event_type,
                "score": round(score, 3),
                "reasons": reasons,
                "status": "accepted" if score >= 0.55 and not rejected_reason else "rejected",
            }
            if rejected_reason:
                record["rejected_reason"] = rejected_reason
            candidates.append(record)
            return record["status"] == "accepted"

        def add(seg, event_type, target=None, cause=None, effects=None, relations=None, score=0.9, reasons=None):
            events.append({
                "id": f"evt_{len(events)+1:03d}",
                "type": event_type,
                "actor": char,
                "target": target,
                "cause": cause,
                "source_segment": seg["id"],
                "source_text": seg.get("raw_text") or seg["text"],
                "source_span": {"start": seg["start"], "end": seg["end"]},
                "effects": effects or [],
                "relation_effects": relations or [],
                "temporal_constraints": [],
                "eligibility": "realized_event",
                "eventhood_score": round(score, 3),
                "eventhood_reasons": reasons or [],
            })

        for seg in resolved_segments.get("segments", []):
            text = seg.get("normalized_text") or seg["text"]
            low = text.lower()
            aspect = seg.get("aspect", {})
            status = aspect.get("event_status", "current_or_unspecified")
            modality = seg.get("scope", {}).get("modality", "asserted")

            if modality in {"request", "hypothetical"} or status in {"habitual", "historical", "intended", "requested_scenario", "hypothetical"}:
                # Still emit rejected high-likelihood lexical event candidates for debugging.
                if re.search(r"\b(?:jalan|berjalan)\b", low):
                    candidate(seg, "walk", 0.15, [f"aspect={status}"], "non-realized aspect")
                continue

            # State assertions do not become put_on events: "aku memakai gamis".
            if re.search(r"\baku\s+memakai\b", low) and not re.search(r"\b(?:ketika|lalu|kemudian|baru|mencoba)\b", low):
                candidate(seg, "put_on", 0.25, ["present state assertion"], "state assertion, not transition")

            # Explicit clothing change.
            change = re.search(r"\b(?:aku\s+)?(?:ganti\s+baju|berganti\s+baju|ganti\s+pakaian)\b.{0,80}\b(?:jadi|ke)\s+(dress|gamis|baju)\b", low, re.S)
            if change:
                kind = change.group(1)
                target = {
                    "dress": "garment:dress_1",
                    "gamis": "garment:gamis_1",
                }.get(kind, "garment:feminine_clothing_1")
                reasons = ["explicit change verb", "explicit target garment"]
                if "sehingga" in low or "karena" in low or "gerah" in low:
                    reasons.append("causal/discomfort context")
                if candidate(seg, "dress_change", 0.96, reasons):
                    effects = []
                    # Remove known full-body garment if changing from it.
                    for worn_id in initial_wearing:
                        if worn_id != target and any(x in worn_id for x in ("gamis", "dress", "feminine_clothing")):
                            effects.append({"op": "delete", "path": f"runtime.{char}.wearing.{worn_id}"})
                    effects.append({"op": "set", "path": f"runtime.{char}.wearing.{target}", "value": True})
                    add(
                        seg,
                        "dress_change",
                        target,
                        "state:thermal_discomfort" if "gerah" in low else None,
                        effects,
                        [{"op": "add", "subject": char, "predicate": "wearing", "object": target}],
                        .96,
                        reasons,
                    )

            # Older explicit "mencoba memakai" transition.
            if "mencoba memakai" in low and ("dress" in low or "pakaian" in low):
                target = "garment:dress_1" if "garment:dress_1" in entities else "garment:feminine_clothing_1"
                reasons = ["attemptive action marker", "specific clothing action"]
                if candidate(seg, "dress_change", 0.9, reasons):
                    add(
                        seg,
                        "dress_change",
                        target,
                        None,
                        [{"op": "set", "path": f"runtime.{char}.wearing.{target}", "value": True}],
                        [{"op": "add", "subject": char, "predicate": "wearing", "object": target}],
                        .9,
                        reasons,
                    )

            # Transformation application.
            if (
                re.search(r"(?:prosteti[ck]|prosthetic).{0,320}(?:tempel|tempelin|pakai|gunakan)", low, re.S)
                or (("tempel" in low or "tempelin" in low) and "item:transformation_item_1" in entities)
            ):
                reasons = ["specific application action", "transformation item present"]
                if candidate(seg, "apply_transformation_item", 0.96, reasons):
                    add(seg, "apply_transformation_item", "item:transformation_item_1", None, score=.96, reasons=reasons)

            if (
                re.search(r"(?:prosteti[ck]|prosthetic).{0,460}(?:melebur|menyatu).{0,260}(?:mengubah|berubah)", low, re.S)
                or (("melebur" in low or "menyatu" in low) and ("mengubah" in low or "berubah" in low) and "item:transformation_item_1" in entities)
            ):
                reasons = ["explicit state-change verb", "caused by transformation item"]
                if candidate(seg, "anatomical_transformation", 0.98, reasons):
                    add(
                        seg,
                        "anatomical_transformation",
                        char,
                        "item:transformation_item_1",
                        [{"op": "set", "path": f"runtime.{char}.transformations.anatomical_active", "value": True}],
                        score=.98,
                        reasons=reasons,
                    )

            # Wig application and hair transformation.
            if re.search(r"\b(?:ketika\s+)?(?:aku\s+)?(?:pakai|memakai|pasang)\s+wig\b", low):
                reasons = ["specific temporal/action marker", "wig target"]
                if candidate(seg, "apply_wig", 0.95, reasons):
                    add(seg, "apply_wig", "item:wig_1", None, score=.95, reasons=reasons)

            if (("nyatu" in low or "menyatu" in low) and "rambut" in low and "item:wig_1" in entities):
                reasons = ["explicit hair state change", "wig integration"]
                if candidate(seg, "hair_transformation", 0.97, reasons):
                    effects = [{"op": "delete", "path": f"runtime.{char}.hair.length_class"}]
                    if "length_cm" in hair:
                        effects.append({"op": "set", "path": f"runtime.{char}.hair.length_cm", "value": hair["length_cm"]["value"]})
                    if "length_relative" in hair:
                        effects.append({"op": "set", "path": f"runtime.{char}.hair.length_relative", "value": hair["length_relative"]["value"]})
                    if "density" in hair:
                        effects.append({"op": "set", "path": f"runtime.{char}.hair.density", "value": hair["density"]["value"]})
                    add(
                        seg,
                        "hair_transformation",
                        char + ".hair",
                        "item:wig_1",
                        effects,
                        [{"op": "add", "subject": "item:wig_1", "predicate": "integrated_into", "object": char + ".hair"}],
                        .97,
                        reasons,
                    )

            # Moment-specific observation only.
            if re.search(r"\b(?:tidak|nggak|gak)\s+lagi\s+(?:terlihat|kelihatan).{0,160}(?:cowok|laki-laki|male)", low, re.S):
                reasons = ["change marker=lagi", "moment-specific observation"]
                if candidate(seg, "appearance_observation", 0.9, reasons):
                    add(seg, "appearance_observation", char, None, score=.9, reasons=reasons)

            # Generic locomotion must beat habitual/background penalties.
            if re.search(r"\b(?:berjalan|jalan)\b", low):
                score = 0.62
                reasons = ["locomotion verb"]
                if re.search(r"\b(?:kadang|sering|biasanya)\b", low):
                    score -= 0.55
                    reasons.append("habitual marker penalty")
                if re.search(r"\b(?:sekarang|lalu|kemudian)\b", low):
                    score += 0.15
                    reasons.append("current/sequence marker")
                accepted = candidate(seg, "walk", score, reasons, "habitual/background" if score < .55 else None)
                if accepted:
                    add(seg, "walk", score=score, reasons=reasons)

        # Temporal constraints.
        id_to_event = {e["id"]: e for e in events}
        apply_t = [e["id"] for e in events if e["type"] == "apply_transformation_item"]
        transforms = [e["id"] for e in events if e["type"] == "anatomical_transformation"]
        dresses = [e["id"] for e in events if e["type"] == "dress_change"]
        apply_w = [e["id"] for e in events if e["type"] == "apply_wig"]
        hairs = [e["id"] for e in events if e["type"] == "hair_transformation"]

        for a in apply_t:
            for b in transforms:
                id_to_event[a]["temporal_constraints"].append({"relation": "before", "event": b, "confidence": .99, "source_segment": "causal_order"})
        for a in apply_w:
            for b in hairs:
                id_to_event[a]["temporal_constraints"].append({"relation": "before", "event": b, "confidence": .99, "source_segment": "causal_order"})
        for seg in resolved_segments.get("segments", []):
            low = (seg.get("normalized_text") or seg["text"]).lower()
            if "sebelum pakai pakaian" in low or "sebelum memakai pakaian" in low:
                for a in transforms:
                    for b in dresses:
                        id_to_event[a]["temporal_constraints"].append({"relation": "before", "event": b, "confidence": .99, "source_segment": seg["id"]})

        # Stable topological-ish sort.
        ordered = sorted(events, key=lambda e: e["source_span"]["start"])
        for _ in range(100):
            pos = {e["id"]: i for i, e in enumerate(ordered)}
            moved = False
            for e in list(ordered):
                for tc in e["temporal_constraints"]:
                    if tc["relation"] == "before" and e["id"] in pos and tc["event"] in pos and pos[e["id"]] > pos[tc["event"]]:
                        item = ordered.pop(pos[e["id"]])
                        ordered.insert(pos[tc["event"]], item)
                        moved = True
                        break
                if moved:
                    break
            if not moved:
                break
        for i, e in enumerate(ordered, 1):
            e["order"] = i

        return {
            "version": self.VERSION,
            "events": ordered,
            "scenario_events": (scenario or {}).get("requested_events", []),
            "event_candidates": candidates,
            "diagnostics": [],
        }
