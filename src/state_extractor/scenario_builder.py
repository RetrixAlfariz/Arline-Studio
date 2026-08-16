from __future__ import annotations


class ScenarioBuilder:
    VERSION = "0.3.3"

    @classmethod
    def default(cls):
        return cls()

    def build(self, claims, state):
        requested_events = []
        focus = {}

        for claim in claims.get("claims", []):
            if claim.get("kind") == "scenario_event":
                meta = claim.get("metadata", {})
                requested_events.append({
                    "id": f"scenario_evt_{len(requested_events)+1:03d}",
                    "type": claim["predicate"],
                    "causer": claim.get("subject"),
                    "patient": claim.get("object"),
                    "target": meta.get("target"),
                    "recurrence": meta.get("recurrence", "unspecified"),
                    "realization_status": meta.get("realization_status", "requested_not_realized"),
                    "confidence": claim["confidence"],
                    "source_claim": claim["id"],
                    "source_segment": claim["source_segment"],
                })
                focus.update({
                    "appearance": 0.95,
                    "clothing_fit": 0.95,
                    "interpersonal": 0.88,
                    "bodily_sensation": 0.72,
                })
                if meta.get("recurrence") == "first_time":
                    focus["novelty"] = 1.0

            pred = claim.get("predicate", "")
            if pred.startswith("relationship.") or pred.startswith("social."):
                focus["relationship"] = max(focus.get("relationship", 0.0), 0.82)
            if pred.startswith("garment."):
                focus["clothing"] = max(focus.get("clothing", 0.0), 0.78)
            if pred.startswith("experience."):
                focus["familiarity"] = max(focus.get("familiarity", 0.0), 0.80)
            if pred.startswith("norm."):
                focus["social_boundary"] = max(focus.get("social_boundary", 0.0), 0.82)

        for directive in state.get("directives", []):
            low = directive["text"].lower()
            if "detail" in low:
                focus["physical_detail"] = max(focus.get("physical_detail", 0.0), 0.90)
            if "atmospher" in low or "atmosfer" in low:
                focus["atmosphere"] = max(focus.get("atmosphere", 0.0), 0.90)
            if "karakter" in low:
                focus["character"] = max(focus.get("character", 0.0), 0.88)

        return {
            "version": self.VERSION,
            "requested_events": requested_events,
            "scene_focus": focus,
            "diagnostics": [],
        }
