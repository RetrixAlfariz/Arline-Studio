from __future__ import annotations


class SurfacePlanner:
    VERSION = "0.3.3"

    @classmethod
    def default(cls):
        return cls()

    def plan(self, analysis, history=None, scene_focus=None):
        if hasattr(history, "records"):
            history = set(getattr(history, "records", {}).keys())
        elif isinstance(history, dict):
            history = set((history.get("records") or history).keys())
        else:
            history = set(history or [])
        scene_focus = scene_focus or {}
        items = []
        weights = {"hidden": 0.0, "imply": 1.0, "mention_if_natural": .72, "explicit": 1.0}

        for c in analysis.get("consequences", []):
            base_novelty = c.get("novelty", 1.0)
            novelty = min(base_novelty, .35) if c["effect"] in history else base_novelty
            tags = c.get("focus_tags", [])
            focus_match = max([scene_focus.get(tag, 0.0) for tag in tags] or [0.0])
            # Context facts with no matching focus are mildly suppressed rather than deleted.
            context_penalty = .78 if c.get("event_id") == "context" and focus_match == 0 else 1.0
            score = (
                c["salience"] * c["confidence"] * novelty
                * weights.get(c["surface_policy"], .8)
                * (1.0 + .18 * focus_match)
                * context_penalty
            )
            score = round(min(score, 1.0), 4)
            items.append({
                "effect": c["effect"],
                "event_id": c["event_id"],
                "surface_policy": c["surface_policy"],
                "score": score,
                "novelty": novelty,
                "focus_match": round(focus_match, 3),
                "instruction": (
                    "show_as_natural_consequence" if c["surface_policy"] == "imply"
                    else "internal_only" if c["surface_policy"] == "hidden"
                    else "mention_only_if_natural"
                ),
                "why_relevant": c.get("why_relevant", []),
                "avoid": c.get("avoid", []),
                "graph_node": c["graph_node"],
            })

        items.sort(key=lambda x: x["score"], reverse=True)
        return {
            "version": self.VERSION,
            "scene_focus": scene_focus,
            "writer_context": [i for i in items if i["score"] >= .45 and i["surface_policy"] != "hidden"],
            "suppressed": [i for i in items if i["score"] < .45 or i["surface_policy"] == "hidden"],
            "diagnostics": [],
        }
