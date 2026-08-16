from __future__ import annotations

import copy

from src.common.utils import getp, setp


def delete_path(data, path):
    parts = path.split(".")
    cur = data
    for part in parts[:-1]:
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    if not isinstance(cur, dict):
        return None
    return cur.pop(parts[-1], None)


class StateTransitionResolver:
    VERSION = "0.3.3"

    @classmethod
    def default(cls):
        return cls()

    def resolve(self, state, events):
        char = next(
            (
                e["id"] for e in state.get("entities", [])
                if e.get("type") == "character" and e.get("label") not in {"fano", "self_mother", "fano_mother"}
            ),
            "char:self",
        )

        current = {
            "runtime": copy.deepcopy(state.get("initial_runtime", {})),
            "relations": [],
        }
        current["runtime"].setdefault(char, {"hair": {}, "wearing": {}, "transformations": {}, "comfort": {}})

        # Current state relations such as wearing should exist at S0.
        for relation in state.get("relations", []):
            if relation.get("temporal_scope") == "current" and relation.get("predicate") in {"wearing"}:
                current["relations"].append({
                    "subject": relation["subject"],
                    "predicate": relation["predicate"],
                    "object": relation["object"],
                })

        snapshots = [{"id": "S0", "after_event": None, "state": copy.deepcopy(current)}]
        patches = []
        conflicts = list(state.get("claim_conflicts", []))

        for i, event in enumerate(events.get("events", []), 1):
            patch = []
            for effect in event.get("effects", []):
                op = effect["op"]
                path = effect["path"]
                if op == "delete":
                    old = delete_path(current, path)
                    patch.append({"op": "delete", "path": path, "from": old})
                    # Remove matching wearing relation if deleting wear state.
                    if ".wearing." in path:
                        garment_id = path.split(".wearing.", 1)[1]
                        current["relations"] = [
                            r for r in current["relations"]
                            if not (r.get("subject") == char and r.get("predicate") == "wearing" and r.get("object") == garment_id)
                        ]
                    continue

                old = getp(current, path)
                new = effect.get("value")
                setp(current, path, new)
                patch.append({
                    "op": "replace" if old is not None and old != new else "set",
                    "path": path,
                    "from": old,
                    "value": new,
                })

            for rel in event.get("relation_effects", []):
                if rel.get("op") != "add":
                    continue
                record = {k: rel[k] for k in ("subject", "predicate", "object")}
                if record not in current["relations"]:
                    current["relations"].append(record)
                    patch.append({"op": "add_relation", **record})

            patches.append({
                "event_id": event["id"],
                "event_type": event["type"],
                "state_before": f"S{i-1}",
                "state_after": f"S{i}",
                "patch": patch,
            })
            snapshots.append({"id": f"S{i}", "after_event": event["id"], "state": copy.deepcopy(current)})

        return {
            "version": self.VERSION,
            "initial_state_id": "S0",
            "snapshots": snapshots,
            "patches": patches,
            "conflicts": conflicts,
            "diagnostics": [],
        }
