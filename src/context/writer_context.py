from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any

from src.core import SemanticCore
from src.narrative import NarrativeRuntime
from .relevance import RelevanceSelector


@dataclass(slots=True)
class WriterContextItem:
    key: str
    label: str
    value: Any
    priority: int
    reason: str
    trace_id: str | None = None
    epistemic: str = "explicit"
    confidence: float = 1.0

    def to_dict(self): return asdict(self)


@dataclass(slots=True)
class WriterProjectionItem:
    key: str
    label: str
    value: Any
    confidence: float
    priority: int
    assumptions: list[str] = field(default_factory=list)
    target_unknown: str | None = None
    applies_after: str | None = None
    surface_policy: str = "visualize_naturally"
    language_hint: str | None = None
    exact_claim_forbidden: bool = True
    canonical: bool = False
    trace_id: str | None = None
    basis_trace_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self): return asdict(self)


@dataclass(slots=True)
class WriterContext:
    version: str
    scene: list[WriterContextItem] = field(default_factory=list)
    style: dict[str, Any] = field(default_factory=dict)
    characters: dict[str, list[WriterContextItem]] = field(default_factory=dict)
    world: list[WriterContextItem] = field(default_factory=list)
    current: list[WriterContextItem] = field(default_factory=list)
    relations: list[str] = field(default_factory=list)
    history: list[str] = field(default_factory=list)
    knowledge: list[str] = field(default_factory=list)
    beliefs: list[str] = field(default_factory=list)
    norms: list[str] = field(default_factory=list)
    locked: list[WriterContextItem] = field(default_factory=list)
    negative: list[str] = field(default_factory=list)
    transitions: list[dict[str, Any]] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    projections: list[WriterProjectionItem] = field(default_factory=list)
    derivable: list[str] = field(default_factory=list)
    freedom: dict[str, str] = field(default_factory=dict)
    scene_goal: dict[str, Any] = field(default_factory=dict)
    beat_state: dict[str, Any] = field(default_factory=dict)
    surface: list[str] = field(default_factory=list)
    relevance: list[dict[str, Any]] = field(default_factory=list)
    trace_index: dict[str, dict[str, Any]] = field(default_factory=dict)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self):
        return {
            "version": self.version,
            "scene": [x.to_dict() for x in self.scene],
            "style": self.style,
            "characters": {k: [x.to_dict() for x in v] for k, v in self.characters.items()},
            "world": [x.to_dict() for x in self.world],
            "current": [x.to_dict() for x in self.current],
            "relations": self.relations,
            "history": self.history,
            "knowledge": self.knowledge,
            "beliefs": self.beliefs,
            "norms": self.norms,
            "locked": [x.to_dict() for x in self.locked],
            "negative": self.negative,
            "transitions": self.transitions,
            "unknown": self.unknown,
            "projections": [x.to_dict() for x in self.projections],
            "derivable": self.derivable,
            "freedom": self.freedom,
            "scene_goal": self.scene_goal,
            "beat_state": self.beat_state,
            "surface": self.surface,
            "relevance": self.relevance,
            "trace_index": self.trace_index,
            "diagnostics": self.diagnostics,
        }


class WriterContextBuilder:
    VERSION = "0.2"

    def __init__(self):
        self.relevance = RelevanceSelector()

    @classmethod
    def default(cls): return cls()

    def build(
        self,
        raw_prompt: str,
        core: SemanticCore,
        pipeline_result,
        narrative: NarrativeRuntime,
        *,
        projections=None,
    ) -> WriterContext:
        state = pipeline_result.extracted_state
        events = pipeline_result.events
        analysis = pipeline_result.analysis
        decisions = self.relevance.select(core, pipeline_result, narrative)
        decision_map = {d.key: d for d in decisions}
        entities = {e.get("id"): e for e in state.get("entities", []) or []}
        self_id = self._self_id(state, entities)
        labels = {eid: self._natural_entity_label(e, entities, self_id) for eid, e in entities.items()}

        ctx = WriterContext(
            version=self.VERSION,
            style={
                **narrative.style.to_dict(),
                "language_profile": narrative.language.to_dict(),
                "description_lens": narrative.description_lens.to_dict(),
                "scene_energy": narrative.scene_energy.to_dict(),
                "paragraph_functions": list(narrative.paragraph_functions),
            },
            freedom=narrative.freedom.to_dict(),
            scene_goal=narrative.scene_goal.to_dict(),
            beat_state=narrative.beat_state.to_dict(),
            relevance=[d.to_dict() for d in decisions],
            trace_index=dict(core.trace_index),
        )

        # Facts that are introduced by outlined transitions should not be
        # presented as already-current at the scene-start beat. Their exact
        # values remain available in TRANSITIONS/LOCKS.
        transition_target_paths = {
            str(change.get("path"))
            for tr in core.transitions
            for change in tr.changes
            if isinstance(change, dict) and change.get("path")
        }
        # For generation from an outline/prompt, realized event candidates are
        # the sequence the writer is expected to dramatize. Start from S0 and
        # let TRANSITIONS advance the scene rather than leaking the final
        # snapshot into the opening paragraph.
        scene_starts_before_events = bool(events.get("events"))

        # Canonical facts, selected and re-labeled for the writer.
        for fact in sorted(core.facts, key=lambda f: (f.priority, f.entity_id or "", f.path)):
            decision = decision_map.get(fact.id)
            if decision and not decision.include and decision.priority >= 4:
                continue
            entity = entities.get(fact.entity_id, {})
            entity_label = labels.get(fact.entity_id, self._clean_id(fact.entity_id))
            base_label = self._human_path(fact.path)
            visible_label = base_label if fact.entity_id == self_id else f"{entity_label} — {base_label}"
            item = WriterContextItem(
                key=self._writer_key(fact.entity_id, fact.path, labels),
                label=visible_label,
                value=self._human_value(fact.value),
                priority=decision.priority if decision else fact.priority,
                reason=decision.reason if decision else "canonical fact",
                trace_id=fact.id,
                epistemic=fact.epistemic,
                confidence=fact.confidence,
            )
            if fact.id in ctx.trace_index:
                ctx.trace_index[fact.id]["writer_fact"] = item.key

            if fact.category == "location":
                ctx.scene.append(item)
            elif fact.entity_id == self_id:
                # Don't leak the end-state of an outlined transition into the
                # opening beat. The transition contract carries those values.
                if not (scene_starts_before_events and (
                    fact.path in transition_target_paths
                    or fact.path.startswith("transformations.")
                    or (fact.path.startswith("hair.current.") and any(p.startswith("hair.") for p in transition_target_paths))
                )):
                    ctx.characters.setdefault(labels.get(self_id, "Protagonist"), []).append(item)
            elif entity.get("type") == "character":
                ctx.characters.setdefault(labels.get(fact.entity_id, "Character"), []).append(item)
            elif entity.get("type") in {"garment", "item"}:
                ctx.world.append(item)
            elif fact.temporal_scope == "current":
                ctx.current.append(item)

            if self._is_lockable(fact, entity, decision):
                ctx.locked.append(item)

        # Current runtime state (latest snapshot) is higher authority than baseline.
        snaps = events.get("state_snapshots", []) or []
        if snaps:
            snapshot = snaps[0] if scene_starts_before_events else snaps[-1]
            runtime = snapshot.get("state", {}).get("runtime", {}) or {}
            for actor, data in sorted(runtime.items()):
                actor_label = labels.get(actor, self._clean_id(actor))
                worn = [labels.get(g, self._clean_id(g)) for g, active in (data.get("wearing") or {}).items() if active]
                if worn:
                    ctx.current.append(WriterContextItem(
                        key=f"{actor_label}.currently_wearing",
                        label="currently wearing",
                        value=worn,
                        priority=0,
                        reason="latest runtime state",
                        epistemic="runtime",
                    ))
                hair = data.get("hair", {}) or {}
                for key, value in sorted(hair.items()):
                    ctx.current.append(WriterContextItem(
                        key=f"{actor_label}.current_hair.{key}",
                        label=f"current hair {key.replace('_',' ')}",
                        value=self._human_value(value),
                        priority=0,
                        reason="latest runtime state after transitions",
                        epistemic="runtime",
                    ))
                comfort = data.get("comfort", {}) or {}
                for key, value in sorted(comfort.items()):
                    ctx.current.append(WriterContextItem(
                        key=f"{actor_label}.comfort.{key}",
                        label=f"current {key} comfort",
                        value=value,
                        priority=0,
                        reason="scene-local current state",
                        epistemic="runtime",
                    ))

        ctx.relations = self._relations(state, labels)
        ctx.history = self._history(core, labels)
        ctx.knowledge = self._knowledge(core, labels)
        ctx.beliefs = self._beliefs(core, labels)
        ctx.norms = self._norms(core, labels)
        ctx.negative = self._negative(core, labels)
        ctx.transitions = self._transitions(core, labels)
        ctx.unknown = self._unknowns(core, state, entities, events, labels)
        ctx.projections = self._projections(projections or [], labels, ctx)
        ctx.derivable = self._derivable(analysis, decision_map, labels)
        ctx.surface = self._surface(analysis, narrative)
        ctx.diagnostics = self._diagnostics(ctx)
        return ctx

    def _relations(self, state, labels):
        # Prefer a temporally-scoped duplicate over an unspecified duplicate.
        selected = {}
        temporal_rank = {
            "historical_to_current": 5,
            "current_after_transition": 5,
            "current": 4,
            "historical": 4,
            "habitual": 3,
            "conditional": 3,
            "current_or_unspecified": 1,
            None: 0,
        }
        for r in state.get("relations", []) or []:
            key = (r.get("subject"), r.get("predicate"), r.get("object"), repr(r.get("value")))
            current = selected.get(key)
            if current is None or temporal_rank.get(r.get("temporal_scope"), 2) > temporal_rank.get(current.get("temporal_scope"), 2):
                selected[key] = r

        out = []
        for r in selected.values():
            # Explicit false relations are represented in NEGATIVE instead of
            # being repeated as a positive-looking relation with `(no)`.
            if r.get("value") is False:
                continue
            pred = str(r.get("predicate") or "related to").replace(".", " ").replace("_", " ")
            subject = self._human_ref(r.get("subject"), labels)
            obj = self._human_ref(r.get("object"), labels)
            value = r.get("value")
            temporal = r.get("temporal_scope")
            if obj is None:
                text = f"{subject} — {pred}"
                if value not in (None, True):
                    text += f" = {self._human_value_refaware(value, labels)}"
            else:
                text = f"{subject} — {pred} → {obj}"
                if value not in (None, True):
                    text += f" ({self._human_value_refaware(value, labels)})"
            if temporal and temporal not in {"current", "current_or_unspecified"}:
                text += f" [{temporal}]"
            out.append(text)
        return sorted(dict.fromkeys(out))

    def _history(self, core, labels):
        out = []
        for e in core.experience:
            subj = labels.get(e.get("subject"), self._clean_id(e.get("subject")))
            pred = str(e.get("predicate") or "experience").replace("experience.", "").replace("_", " ")
            out.append(f"{subj}: {pred} = {self._human_value_refaware(e.get('value'), labels)} [{e.get('temporal_scope','history')}]" )
        for rt in core.relationship_timeline:
            tr = rt.get("transition", {}) or {}
            out.append(f"Relationship history: {tr.get('from','?')} → {tr.get('to','?')} ({tr.get('progression','unspecified progression')})")
        return sorted(dict.fromkeys(out))

    def _knowledge(self, core, labels):
        out=[]
        for k in core.knowledge:
            knower=labels.get(k.get("knower"), self._clean_id(k.get("knower")))
            obj=labels.get(k.get("known_object"), self._clean_id(k.get("known_object")))
            out.append(f"{knower} knows/is aware of: {obj}")
        return sorted(dict.fromkeys(out))

    def _beliefs(self, core, labels):
        out=[]
        for b in core.beliefs:
            believer=labels.get(b.get("believer"), self._clean_id(b.get("believer")))
            belief = self._human_value_refaware(b.get("belief"), labels)
            out.append(f"{believer} believes: {belief} (truth status: {b.get('truth_status','unknown')})")
        return sorted(dict.fromkeys(out))

    def _norms(self, core, labels):
        out=[]
        for n in core.norms:
            subject=self._human_ref(n.get("subject"), labels)
            pred=str(n.get("predicate") or "norm").replace(".", " ").replace("_", " ")
            obj=self._human_ref(n.get("object"), labels)
            value=self._human_value_refaware(n.get("value"), labels)
            temporal=n.get("temporal_scope")
            text=f"{subject}: {pred}"
            if obj: text += f" for {obj}"
            if value not in (None, True, "yes"): text += f" = {value}"
            if temporal: text += f" [{temporal}]"
            out.append(text)
        return sorted(dict.fromkeys(out))

    def _negative(self, core, labels):
        out=[]
        for n in core.negative_facts:
            subject=labels.get(n.subject, self._clean_id(n.subject))
            obj=labels.get(n.object, self._clean_id(n.object)) if isinstance(n.object,str) else self._human_value(n.object)
            pred=str(n.predicate)
            for eid, label in sorted(labels.items(), key=lambda kv: len(kv[0]), reverse=True):
                pred=pred.replace(eid, label)
            pred=pred.replace(".", " ").replace("_", " ")
            if obj not in (None, "None", "null"):
                out.append(f"NOT: {subject} — {pred} → {obj} [{n.temporal_scope}]")
            else:
                out.append(f"NOT: {subject} — {pred} [{n.temporal_scope}]")
        return sorted(dict.fromkeys(out))

    def _transitions(self, core, labels):
        out=[]
        for tr in sorted(core.transitions, key=lambda x: x.order or 9999):
            out.append({
                "event": self._human_event(tr.event_type),
                "actor": labels.get(tr.actor, self._clean_id(tr.actor)),
                "target": labels.get(tr.target, self._human_ref(tr.target, labels)),
                "cause": labels.get(tr.cause, self._human_ref(tr.cause, labels)),
                "order": tr.order,
                "preconditions": [self._human_ref(x, labels) for x in tr.preconditions],
                "changes": [self._human_transition_change(x, labels) for x in tr.changes],
                "invalidates": [self._human_transition_change(x, labels) for x in tr.invalidates],
                "preserves": [self._human_path(x) for x in tr.preserves],
                "side_effects": tr.side_effects,
            })
        return out

    def _unknowns(self, core, state, entities, events, labels):
        unknown = []
        for item in state.get("unknowns", []) or []:
            candidate = str(item.get("candidate") or "unknown fact")
            unknown.append(self._human_path(candidate))
        # Domain-specific anti-hallucination unknowns. These are intentionally
        # explicit when a relevant entity exists but the canonical state does
        # not define the value.
        active = self._active_entity_ids(events)
        for eid, entity in entities.items():
            if eid not in active and entity.get("type") not in {"character", "location"}:
                continue
            attrs = entity.get("attributes", {}) or {}
            label = labels.get(eid, self._clean_id(eid))
            if entity.get("type") == "garment":
                lexical = (attrs.get("ontology") or {}).get("lexical_type") or entity.get("label")
                if lexical in {"dress", "gamis"}:
                    if "length" not in attrs and "length_cm" not in attrs:
                        unknown.append(f"{label}: exact garment length")
                    unknown.extend([
                        f"{label}: waist circumference",
                        f"{label}: shoulder width",
                        f"{label}: sleeve length unless explicitly specified",
                    ])
                    length = attrs.get("length") or attrs.get("length_cm")
                    basis = attrs.get("measurement_basis")
                    if length and (basis is None or self._fact_value(basis) in {None, "unspecified"}):
                        unknown.append(f"{label}: measurement origin/basis for the known length")
                        unknown.append(f"{label}: exact body-relative hem endpoint of the known garment length")
                if lexical == "bra":
                    unknown.extend([f"{label}: band size", f"{label}: exact garment measurements"])
            if entity.get("type") == "item" and entity.get("label") == "wig":
                if "material" not in attrs:
                    unknown.append(f"{label}: material/fiber type")
                unknown.append(f"{label}: exact width unless explicitly specified")
                # A known absolute hair length does not by itself establish the
                # exact body landmark reached by the hair. That requires body-
                # relative geometry/anchors which many prompts do not provide.
                for char_id, char_entity in entities.items():
                    if char_entity.get("type") != "character":
                        continue
                    char_attrs = char_entity.get("attributes", {}) or {}
                    hair = char_attrs.get("hair", {}) or {}
                    current = hair.get("current", {}) or {}
                    length = current.get("length_cm") or current.get("length")
                    relative = current.get("length_relative") or current.get("relative_length")
                    if length and not relative:
                        char_label = labels.get(char_id, self._clean_id(char_id))
                        unknown.append(
                            f"{char_label} hair: exact body-relative endpoint of the known hair length"
                        )
            if entity.get("type") == "item" and entity.get("label") == "transformation_item":
                unknown.append(f"{label}: activation mechanism or technology beyond source description")
        return sorted(dict.fromkeys(unknown))

    def _projections(self, projections, labels, ctx):
        out=[]
        for projection in projections:
            subject_label = labels.get(
                projection.subject, self._clean_id(projection.subject)
            ) if projection.subject else "scene"
            label = str(projection.name).replace("_", " ")
            if projection.subject:
                label = f"{subject_label} — {label}"
            target_unknown = projection.target_unknown
            if target_unknown:
                target_unknown = self._human_ref(target_unknown, labels)
            item = WriterProjectionItem(
                key=f"projection.{subject_label}.{projection.name}",
                label=label,
                value=self._human_value_refaware(projection.value, labels),
                confidence=float(projection.confidence),
                priority=int(projection.priority),
                assumptions=[self._human_ref(x, labels) for x in projection.assumptions],
                target_unknown=target_unknown,
                applies_after=projection.applies_after,
                surface_policy=projection.surface_policy,
                language_hint=projection.language_hint,
                exact_claim_forbidden=bool(projection.exact_claim_forbidden),
                canonical=False,
                trace_id=projection.id,
                basis_trace_ids=list(projection.basis_fact_ids),
                metadata=self._human_value_refaware(dict(projection.metadata), labels),
            )
            out.append(item)
            basis=[]
            for fact_id in projection.basis_fact_ids:
                trace=ctx.trace_index.get(fact_id)
                if trace:
                    basis.append({
                        "trace_id": fact_id,
                        "canonical_path": trace.get("canonical_path"),
                        "value": trace.get("value"),
                        "confidence": trace.get("confidence"),
                        "source_segment": trace.get("source_segment"),
                        "source_text": trace.get("source_text"),
                    })
            ctx.trace_index[projection.id] = {
                "type": "projection",
                "writer_fact": item.key,
                "projection_name": projection.name,
                "subject": subject_label,
                "value": item.value,
                "confidence": projection.confidence,
                "canonical": False,
                "assumptions": list(item.assumptions),
                "target_unknown": target_unknown,
                "applies_after": projection.applies_after,
                "language_hint": projection.language_hint,
                "basis_fact_ids": list(projection.basis_fact_ids),
                "basis": basis,
            }
        return sorted(out, key=lambda x: (x.priority, x.label, x.key))

    def _derivable(self, analysis, decision_map, labels):
        out=[]
        for d in analysis.get("derived_facts", []) or []:
            dec=decision_map.get("derived:"+str(d.get("name")))
            if dec and dec.include:
                raw_name=str(d.get("name"))
                for eid, label in sorted(labels.items(), key=lambda kv: len(kv[0]), reverse=True):
                    raw_name=raw_name.replace(eid, label)
                name=raw_name.replace("_", " ").replace(".", " — ")
                out.append(f"{name}: {self._human_value(d.get('value'))} (confidence {float(d.get('confidence',0)):.2f}; use as behavior guidance, not a required sentence)")
        return out

    def _surface(self, analysis, narrative):
        out=[]
        history=narrative.surface_history
        for item in analysis.get("surface_plan", {}).get("writer_context", []) or []:
            concept=str(item.get("effect"))
            novelty=history.novelty(concept)
            line=f"{item.get('surface_policy','imply')}: {concept.replace('_',' ')}"
            if item.get("why_relevant"):
                line += " — " + "; ".join(item["why_relevant"])
            if novelty < .6:
                line += f" [novelty {novelty:.2f}; avoid restating it explicitly]"
            if item.get("avoid"):
                line += " | avoid: " + "; ".join(item["avoid"])
            out.append(line)
        # General anti-recitation principle stays visible even with no consequence.
        out.append("Do not restate a specification merely because it is present; let it influence behavior when relevant.")
        return out

    def _diagnostics(self, ctx):
        diagnostics=[]
        lock_keys={x.key for x in ctx.locked}
        if len(lock_keys) != len(ctx.locked):
            diagnostics.append({"type":"duplicate_lock_keys"})
        return diagnostics

    @staticmethod
    def _self_id(state, entities):
        for a in state.get("entity_aliases", []) or []:
            if a.get("alias") == "char:self": return a.get("canonical")
        if "char:self" in entities: return "char:self"
        for eid,e in entities.items():
            if e.get("type")=="character" and e.get("label") not in {"fano","self_mother","fano_mother"}: return eid
        return "char:self"

    def _natural_entity_label(self, entity, entities, self_id):
        if not entity: return "Unknown entity"
        eid=entity.get("id")
        attrs=entity.get("attributes",{}) or {}
        label=str(entity.get("label") or "entity")
        if eid == self_id:
            identity=attrs.get("identity",{}) or {}
            name=self._fact_value(identity.get("name"))
            nick=self._fact_value(identity.get("nickname"))
            if name and nick: return f"{str(name).title()} ({str(nick).title()})"
            return str(nick or name or "Protagonist").title()
        if entity.get("type")=="character":
            if label=="fano": return "Fano"
            if label=="self_mother": return "the protagonist's mother"
            if label=="fano_mother": return "Fano's mother"
            return label.replace("_"," ").title()
        if entity.get("type")=="location":
            city=self._fact_value(attrs.get("city"))
            return f"{city} apartment" if city else label.replace("_"," ")
        if entity.get("type")=="garment":
            color=self._fact_value(attrs.get("color"))
            material=self._fact_value(attrs.get("material"))
            parts=[str(color).replace("hitam","black").replace("lavender","lavender") if color else None, str(material) if material else None, label.replace("_"," ")]
            return " ".join(x for x in parts if x)
        if entity.get("type")=="item":
            if label=="transformation_item": return "fictional transformation prosthetic"
            if label=="wig": return "integrating wig"
        if entity.get("type")=="family":
            return "the protagonist's family" if eid=="family:self" else "Fano's family" if eid=="family:fano" else label.replace("_"," ")
        if entity.get("type")=="relationship": return "the relationship between the protagonist and Fano"
        return label.replace("_"," ")

    @staticmethod
    def _is_lockable(fact, entity, decision):
        if fact.epistemic != "explicit": return False
        if fact.temporal_scope == "historical_baseline": return False
        if entity.get("type") in {"character","garment","location"}:
            if fact.category in {"identity","physical","garment","location","transformation","appearance"}:
                return True
        return False

    @staticmethod
    def _writer_key(entity_id, path, labels):
        prefix=labels.get(entity_id, WriterContextBuilder._clean_id(entity_id))
        return f"{prefix}.{path}"

    @staticmethod
    def _human_path(path):
        if path is None: return "unknown"
        text=str(path).replace("_"," ").replace(".", " › ")
        replacements={"cm":"cm", "m2":"m²", "reference cup":"cup reference", "length relative":"relative length"}
        for a,b in replacements.items(): text=text.replace(a,b)
        return text

    @staticmethod
    def _human_event(event_type):
        return str(event_type or "event").replace("_"," ")

    def _human_transition_change(self, item, labels):
        if "relation" in item:
            r=item["relation"]
            return {
                "relation": f"{self._human_ref(r.get('subject'), labels)} {str(r.get('predicate')).replace('_',' ')} {self._human_ref(r.get('object'), labels)}"
            }
        raw_path = str(item.get("path") or "")
        for eid, label in sorted(labels.items(), key=lambda kv: len(kv[0]), reverse=True):
            raw_path = raw_path.replace(eid, label)
        return {
            "path": self._human_path(raw_path),
            **({"from": self._human_value(item.get("from"))} if "from" in item else {}),
            **({"to": self._human_value(item.get("to"))} if "to" in item else {}),
            **({"semantic_scope": item.get("semantic_scope")} if item.get("semantic_scope") else {}),
        }

    def _human_ref(self, value, labels):
        if value is None: return None
        text=str(value)
        for eid,label in sorted(labels.items(),key=lambda kv:len(kv[0]), reverse=True):
            if text==eid: return label
            if text.startswith(eid+"."): return label+" — "+self._human_path(text[len(eid)+1:])
        # precondition prose can contain ids inside larger sentence
        for eid,label in sorted(labels.items(),key=lambda kv:len(kv[0]), reverse=True):
            text=text.replace(eid,label)
        return text.replace("_"," ")

    @staticmethod
    def _human_value(value):
        if isinstance(value,dict):
            if value.get("unit") and value.get("value") is not None:
                n=value["value"]
                n=int(n) if isinstance(n,float) and n.is_integer() else n
                return f"{n} {value['unit']}"
            if value.get("frame")=="body_relative" and value.get("anchor"):
                return f"reaches the {str(value['anchor']).replace('_',' ')}"
            return {str(k).replace("_"," "):WriterContextBuilder._human_value(v) for k,v in value.items() if v is not None}
        if isinstance(value,list): return [WriterContextBuilder._human_value(v) for v in value]
        if value is True: return "yes"
        if value is False: return "no"
        return value

    @classmethod
    def _human_value_refaware(cls, value, labels):
        if isinstance(value, dict):
            return {str(k).replace("_", " "): cls._human_value_refaware(v, labels) for k, v in value.items() if v is not None}
        if isinstance(value, list):
            return [cls._human_value_refaware(v, labels) for v in value]
        if isinstance(value, str):
            text=value
            for eid, label in sorted(labels.items(), key=lambda kv: len(kv[0]), reverse=True):
                if text == eid:
                    return label
                text=text.replace(eid, label)
            return text
        return cls._human_value(value)

    @staticmethod
    def _fact_value(value):
        return value.get("value") if isinstance(value,dict) and "value" in value else value

    @staticmethod
    def _clean_id(value):
        if value is None: return "unknown"
        text=str(value)
        text=re.sub(r"^(?:char|garment|item|family|relationship|loc):", "", text)
        return text.replace("_"," ")

    @staticmethod
    def _active_entity_ids(events):
        active=set()
        snaps=events.get("state_snapshots",[]) or []
        if snaps:
            for actor,data in snaps[-1].get("state",{}).get("runtime",{}).items():
                active.add(actor)
                for gid,enabled in (data.get("wearing",{}) or {}).items():
                    if enabled: active.add(gid)
        for e in events.get("events",[]) or []:
            for key in ("actor","target","cause"):
                v=e.get(key)
                if isinstance(v,str): active.add(v.split(".",1)[0] if ":" in v.split(".",1)[0] else v)
        return active
