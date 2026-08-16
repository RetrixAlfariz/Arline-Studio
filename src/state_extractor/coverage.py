from __future__ import annotations

import re


class CoverageAnalyzer:
    VERSION = "0.3.3"

    @classmethod
    def default(cls):
        return cls()

    def analyze(self, resolved, claims, state, events, scenario):
        segments = resolved.get("segments", [])
        claims_by_seg = {}
        for claim in claims.get("claims", []):
            claims_by_seg.setdefault(claim["source_segment"], []).append(claim)

        event_by_seg = {}
        for event in events.get("events", []):
            event_by_seg.setdefault(event["source_segment"], []).append(event)
        for event in scenario.get("requested_events", []):
            event_by_seg.setdefault(event["source_segment"], []).append(event)

        recognized = set(claims_by_seg) | set(event_by_seg)
        for item in state.get("directives", []):
            recognized.add(item["segment_id"])
        for item in state.get("requests", []):
            recognized.add(item["segment_id"])

        structural_total = sum(max(1, len(s["text"])) for s in segments)
        structural_covered = sum(max(1, len(s["text"])) for s in segments if s["id"] in recognized)
        structural_score = structural_covered / structural_total if structural_total else 1.0

        estimated_claims = 0
        resolved_claims = len(claims.get("claims", []))
        unresolved = []

        for seg in segments:
            text = (seg.get("normalized_text") or seg["text"]).lower()
            opportunities = self._estimate_claim_opportunities(text)
            estimated_claims += opportunities
            got = len(claims_by_seg.get(seg["id"], [])) + len(event_by_seg.get(seg["id"], []))
            if opportunities >= 2 and got == 0:
                unresolved.append({
                    "segment_id": seg["id"],
                    "text_preview": seg["text"][:220],
                    "estimated_semantic_units": opportunities,
                    "candidate_meanings": self._candidate_meanings(text),
                    "resolution_status": "unsupported_or_unresolved_pattern",
                })

        # Runtime/scenario events count as resolved semantic units too.
        semantic_resolved = resolved_claims + len(events.get("events", [])) + len(scenario.get("requested_events", []))
        claim_score = min(1.0, semantic_resolved / max(1, estimated_claims))

        entity_mentions = sum(1 for s in segments if re.search(r"\b(?:aku|fano|keluarga|mama|gamis|khimar|dress|wig|prosteti|apartemen)\b", (s.get("normalized_text") or s["text"]).lower()))
        entity_score = min(1.0, len(state.get("entities", [])) / max(1, entity_mentions * 0.7))

        relation_score = min(1.0, len(state.get("relations", [])) / max(1, self._estimate_relation_opportunities(segments)))

        overall = 0.25 * structural_score + 0.45 * claim_score + 0.15 * entity_score + 0.15 * relation_score

        warnings = []
        if claim_score < 0.55:
            warnings.append({"type": "low_claim_coverage", "score": round(claim_score, 4)})
        if unresolved:
            warnings.append({"type": "unresolved_semantic_queue", "count": len(unresolved)})

        return {
            "version": self.VERSION,
            "semantic_coverage_score": round(overall, 4),
            "coverage_by_layer": {
                "structural": round(structural_score, 4),
                "claim": round(claim_score, 4),
                "entity": round(entity_score, 4),
                "relation": round(relation_score, 4),
            },
            "total_segments": len(segments),
            "recognized_segments": len({s["id"] for s in segments if s["id"] in recognized}),
            "estimated_semantic_units": estimated_claims,
            "resolved_semantic_units": semantic_resolved,
            "claim_count": resolved_claims,
            "runtime_event_count": len(events.get("events", [])),
            "scenario_event_count": len(scenario.get("requested_events", [])),
            "unresolved_semantic_queue": unresolved,
            "warnings": warnings,
        }

    def _estimate_claim_opportunities(self, text: str) -> int:
        patterns = [
            r"\b(?:tinggi|umur|lahir|cup|panjang|warna|bahan|luas|lantai)\b",
            r"\b(?:gamis|khimar|dress|wig|prosteti|pakaian)\b",
            r"\b(?:teman|pacar|keluarga|mama|orang tua|dijodohkan)\b",
            r"\b(?:sering|kadang|bukan yang pertama|awalnya|lama-lama)\b",
            r"\b(?:memakai|ganti|berubah|menyatu|membeli|belikan|dekat|tahu|boleh)\b",
            r"\b(?:karena|sehingga|kalau|tapi|walaupun)\b",
        ]
        count = sum(1 for p in patterns if re.search(p, text))
        if len(text) > 140:
            count += 1
        if len(text) > 280:
            count += 1
        return max(1 if text.strip() else 0, count)

    def _estimate_relation_opportunities(self, segments) -> int:
        n = 0
        for s in segments:
            text = (s.get("normalized_text") or s["text"]).lower()
            if re.search(r"\b(?:teman|pacar|dekat|dijodohkan|belikan|memakai|tinggal sendiri|tahu|boleh)\b", text):
                n += 1
        return max(1, n)

    def _candidate_meanings(self, text: str) -> list[str]:
        out = []
        if re.search(r"\b(?:teman|pacar|dijodohkan)\b", text): out.append("relationship_history")
        if re.search(r"\b(?:keluarga|mama|orang tua|ibunya)\b", text): out.append("social_or_kinship")
        if re.search(r"\b(?:gamis|khimar|dress|pakaian)\b", text): out.append("garment_state_or_attributes")
        if re.search(r"\b(?:sering|kadang|bukan yang pertama)\b", text): out.append("habit_or_experience")
        if re.search(r"\b(?:karena|sehingga|kalau|tapi)\b", text): out.append("discourse_relation")
        if re.search(r"\b(?:boleh|tidak boleh|harus)\b", text): out.append("normative_rule")
        return out or ["unknown_information_dense"]
