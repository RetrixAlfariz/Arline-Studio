from __future__ import annotations


class WorldModelBuilder:
    VERSION = "0.3.3"

    @classmethod
    def default(cls):
        return cls()

    def build(self, state, transitions):
        final = transitions["snapshots"][-1]["state"] if transitions.get("snapshots") else {"runtime": {}, "relations": []}
        relations = list(state.get("relations", []))
        for r in final.get("relations", []):
            key = (r.get("subject"), r.get("predicate"), r.get("object"))
            if not any((x.get("subject"), x.get("predicate"), x.get("object")) == key for x in relations):
                relations.append({**r, "confidence": 1.0, "source": "state_transition", "temporal_scope": "current"})
        return {
            "version": self.VERSION,
            "entities": state.get("entities", []),
            "relations": relations,
            "experience": state.get("experience", []),
            "norms": state.get("norms", []),
            "knowledge": state.get("knowledge", []),
            "beliefs": state.get("beliefs", []),
            "relationship_timeline": state.get("relationship_timeline", []),
            "timeline": transitions.get("patches", []),
            "current_runtime_state": final.get("runtime", {}),
            "invariants": [
                {"name": "entity_identity_stable"},
                {"name": "state_changes_require_event_or_explicit_override"},
                {"name": "habitual_statements_do_not_materialize_as_current_events"},
            ],
            "diagnostics": [],
        }
