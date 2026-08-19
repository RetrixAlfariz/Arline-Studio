from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"anchor missing in {path}: {old!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


patch(
    "src/discovery/resolution.py",
    "            ambiguous_candidates=list(result.ambiguous_candidates),\n            span_start=span_start, span_end=span_end,\n",
    "            ambiguous_candidates=list(result.ambiguous_candidates),\n            span_start=span_start, span_end=span_end,\n            resolved_label=result.subject_label,\n",
)

patch(
    "tests/test_v122_topdown_completion.py",
    "            self.assertEqual(later.subject_key, first.subject_key)\n            self.assertEqual(later.resolution_kind, \"self_recent\")\n",
    "            self.assertEqual(later.subject_key, first.subject_key)\n            self.assertEqual(later.subject_label, \"Vian\")\n            self.assertEqual(later.resolution_kind, \"self_recent\")\n",
)

patch(
    "tests/test_v122_topdown_completion.py",
    "            self.assertEqual(pronoun.subject_key, alex.subject_key)\n            self.assertEqual(pronoun.resolution_kind, \"coreference_recent\")\n",
    "            self.assertEqual(pronoun.subject_key, alex.subject_key)\n            self.assertEqual(pronoun.subject_label, \"Alex\")\n            self.assertEqual(pronoun.resolution_kind, \"coreference_recent\")\n            mentions = fx.discovery.store.recent_mentions(\n                session_id=fx.session[\"id\"], branch_id=fx.branch[\"id\"], entity_type=\"character\"\n            )\n            resolved = next(item for item in mentions if item[\"surface\"].casefold() == \"dia\")\n            self.assertEqual(resolved[\"resolved_label\"], \"Alex\")\n",
)

status = ROOT / "docs/V12_IMPLEMENTATION_STATUS.md"
text = status.read_text(encoding="utf-8")
anchor = "## Explicit v1.2.0 boundary\n"
if "## v1.2.2 — Narrative State & Continuity" not in text:
    block = '''## v1.2.2 — Narrative State & Continuity\n\nThe v1.2.2 continuity milestone is implemented on `develop/v1.2` using a\ntop-down narrative-state pipeline rather than extractor-local identity patches.\n\nImplemented:\n\n- one conservative `NarrativeEntityResolver` sits before proposition persistence;\n- exact Library identity, aliases and unique variants reuse stable entity anchors;\n- same-turn and bounded cross-turn coreference resolve only when the candidate is unique;\n- unresolved, plural or ambiguous references abstain and remain auditable as `MENTION-*` diagnostics;\n- mention diagnostics retain both the literal surface form and the resolved identity label;\n- Discovery schema v4 owns mention, event, event-effect, causal-link and conflict-resolution derived tables;\n- state transitions create or reuse `EVENT-*` records and connect visible before/after propositions through causal links;\n- `SUPER-*`, `CONFLICT-*` and `FORM-*` reconstruction remains derived and cannot grant Canon;\n- conflict resolution is an explicit user action choosing correction, story change direction or leave-unresolved;\n- Library resources expose one continuity payload for Current State, Forms, Change History, Events & Causes, Conflicts and mention provenance;\n- the Library UI renders those continuity views without creating a second interpretation of narrative truth;\n- the v1.2.2 regression layer covers stable aliases, narrator/self resolution, ambiguous abstention, unique pronoun resolution, event causality, resource projection, conflict resolution and schema ownership.\n\nThe milestone deliberately keeps fuzzy auto-merge, autonomous Canon promotion,\nsemantic branch merge and model-generated retcons out of scope. Those remain\nlater v1.2.x/v1.3 work.\n\n'''
    if anchor not in text:
        raise RuntimeError("V12 status insertion anchor missing")
    status.write_text(text.replace(anchor, block + anchor, 1), encoding="utf-8")

print("v1.2.2 final polish applied")
