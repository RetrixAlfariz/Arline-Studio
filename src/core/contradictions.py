from __future__ import annotations

from typing import Any


class ContradictionResolver:
    """Classify semantic conflicts instead of treating every value change alike."""

    def classify_claim_conflicts(
        self,
        conflicts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        out = []
        for conflict in conflicts or []:
            temporal = str(conflict.get("temporal_scope", "current_or_unspecified"))
            values = conflict.get("values", [])
            source_kinds = set(conflict.get("source_kinds", []) or [])
            explicit_correction = bool(conflict.get("explicit_correction"))
            perspective_scoped = bool(conflict.get("perspective_scoped"))

            if explicit_correction:
                kind = "correction"
            elif perspective_scoped or {"belief", "attributed_statement"} & source_kinds:
                kind = "perspective_disagreement"
            elif temporal in {
                "historical_to_current",
                "current_after_transition",
                "historical",
            }:
                kind = "temporal_replacement"
            elif temporal in {"possible", "hypothetical", "conditional"}:
                kind = "uncertain_conflict"
            else:
                kind = "hard_contradiction"

            out.append({
                **conflict,
                "class": kind,
                "values": values,
            })
        return out

    def classify_transition_replacements(
        self,
        patches: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        out = []
        for patch in patches or []:
            for op in patch.get("patch", []) or []:
                if op.get("op") == "replace":
                    out.append({
                        "class": "temporal_replacement",
                        "path": op.get("path"),
                        "from": op.get("from"),
                        "to": op.get("value", op.get("to")),
                        "event_id": patch.get("event_id"),
                    })
        return out
