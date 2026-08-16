from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any

from .writer_context import WriterContext


@dataclass(slots=True)
class WCFValidationReport:
    valid: bool
    errors: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self): return asdict(self)


class WCFValidator:
    VERSION="0.2"
    INTERNAL_ID_PATTERNS=(
        r"\b(?:char|garment|item|family|relationship|loc):[A-Za-z0-9_.-]+\b",
        r"\bevt_\d+\b", r"\binf_\d+\b", r"\bseg_\d+\b",
        r"(?<![A-Za-z0-9])(?:g|x)\d+(?![A-Za-z0-9])",
    )

    @classmethod
    def default(cls): return cls()

    def validate(self, context: WriterContext, rendered_text: str) -> WCFValidationReport:
        errors=[]; warnings=[]
        for pattern in self.INTERNAL_ID_PATTERNS:
            found=re.findall(pattern,rendered_text)
            if found:
                errors.append({"type":"internal_id_leak", "pattern":pattern, "examples":found[:8]})

        lock_values={x.key:repr(x.value) for x in context.locked}
        current_values={x.key:repr(x.value) for x in context.current}
        for key,value in current_values.items():
            if key in lock_values and lock_values[key] != value:
                errors.append({"type":"conflicting_current_and_lock", "key":key, "locked":lock_values[key], "current":value})

        # Unknown names should not duplicate an exact locked key verbatim.
        for unknown in context.unknown:
            for lock in context.locked:
                if lock.label.lower() in unknown.lower() and str(lock.value).lower() in unknown.lower():
                    warnings.append({"type":"unknown_mentions_locked_value", "unknown":unknown, "lock":lock.key})

        known_labels = {x.label.lower() for x in context.locked}
        for tr in context.transitions:
            changes={str(x.get("path")) for x in tr.get("changes",[]) if isinstance(x,dict) and x.get("path")}
            preserves=set(map(str,tr.get("preserves",[]) or []))
            overlap=changes & preserves
            if overlap:
                errors.append({"type":"change_preserve_overlap", "event":tr.get("event"), "paths":sorted(overlap)})
            for preserve in preserves:
                normalized = preserve.lower().replace(" › ", " ").replace("_", " ")
                if not any(normalized in label.replace(" › ", " ").replace("_", " ") or label.replace(" › ", " ").replace("_", " ") in normalized for label in known_labels):
                    warnings.append({"type":"preserve_path_not_visible_in_locked_facts", "event":tr.get("event"), "path":preserve})
            if not tr.get("event"):
                errors.append({"type":"transition_without_event_label"})

        # Projections are allowed to approximate an UNKNOWN, but they must
        # remain explicitly non-canonical and traceable to canonical facts.
        for projection in context.projections:
            if projection.canonical:
                errors.append({
                    "type": "projection_marked_canonical",
                    "projection": projection.key,
                })
            if not 0.0 <= float(projection.confidence) <= 1.0:
                errors.append({
                    "type": "projection_confidence_out_of_range",
                    "projection": projection.key,
                    "confidence": projection.confidence,
                })
            if not projection.basis_trace_ids:
                warnings.append({
                    "type": "projection_without_canonical_basis",
                    "projection": projection.key,
                })
            missing_basis = [
                trace_id for trace_id in projection.basis_trace_ids
                if trace_id not in context.trace_index
            ]
            if missing_basis:
                warnings.append({
                    "type": "projection_basis_trace_missing",
                    "projection": projection.key,
                    "trace_ids": missing_basis,
                })
            if projection.target_unknown:
                target_words = {
                    word for word in re.findall(r"[a-z]+", projection.target_unknown.lower())
                    if len(word) > 3 and word not in {"exact", "unknown", "relative"}
                }
                unknown_text = " ".join(context.unknown).lower()
                if target_words and not any(word in unknown_text for word in target_words):
                    warnings.append({
                        "type": "projection_target_unknown_not_visible",
                        "projection": projection.key,
                        "target_unknown": projection.target_unknown,
                    })

        current_keys=[x.key for x in context.current]
        if len(current_keys)!=len(set(current_keys)):
            warnings.append({"type":"duplicate_current_keys"})

        if not context.scene_goal:
            warnings.append({"type":"missing_scene_goal"})
        if not context.surface:
            warnings.append({"type":"missing_surface_guidance"})
        return WCFValidationReport(valid=not errors, errors=errors, warnings=warnings)
