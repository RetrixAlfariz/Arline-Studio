from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable


AIF_VERSION = "0.3"
VALID_PROFILES = {"writer", "teacher", "memory", "debug"}


@dataclass(slots=True)
class CompiledContext:
    profile: str
    text: str
    metadata: dict[str, Any]


class AIFCompiler:
    VERSION = AIF_VERSION

    KEY_MAP = {
        "identity.name": "name",
        "identity.nickname": "nick",
        "identity.age": "age",
        "identity.presentation_name": "present",
        "identity.birth.day": "born.d",
        "identity.birth.month": "born.m",
        "physical.height_cm": "h",
        "physical.morphology.frame": "frame",
        "physical.morphology.presentation": "body",
        "physical.morphology.leg_proportion": "legs",
        "physical.morphology.hand_build": "hands",
        "physical.morphology.gluteal_fullness": "glute",
        "physical.morphology.hip_descriptor": "hips",
        "physical.sensitivity.skin": "skin.sens",
        "physical.chest.reference_cup": "chest",
        "physical.chest.softness": "chest.soft",
        "physical.chest.compliance": "chest.comp",
        "hair.baseline.length_class": "hair0.len",
        "hair.current.length_cm": "hair.len",
        "hair.current.length_relative": "hair.len",
        "hair.current.density": "hair.density",
        "skills.voice_acting": "skill.voice",
        "skills.feminine_voice_imitation": "skill.femvoice",
        "transformations.wig_integrated_as_hair": "x.wig_hair",
        "transformations.fictional_anatomical_transformation": "x.anatomy",
        "endocrine.feminizing_hormone_production": "hormone.fem",
        "biological_context.baseline_sex": "sex0",
        "scene_state.thermal_comfort": "comfort.thermal",
        "gender": "gender",
        "city": "city",
        "floor": "floor",
        "area_m2": "area",
        "color": "col",
        "material": "mat",
        "length": "len",
        "length_cm": "len",
        "front_length": "front",
        "back_length": "back",
        "flowiness": "flow",
        "size_class": "size",
        "construction": "construction",
    }

    PREFIX = {
        "character": "C",
        "garment": "G",
        "item": "X",
        "location": "L",
        "family": "FAM",
        "relationship": "REL",
    }

    def compile(self, extracted_state, events, analysis, *, profile="writer"):
        if profile not in VALID_PROFILES:
            raise ValueError(f"Unknown AIF profile {profile!r}")
        active_entities = self._active_entities(extracted_state, events) if profile == "writer" else None
        aliases = self._aliases(extracted_state, active_entities=active_entities)
        lines = [
            f"@AIF-CORE {self.VERSION} profile={profile}",
            f"@ARLINE {extracted_state.get('system_version', '?')}",
        ]

        focus = analysis.get("scene_focus", {}) or {}
        if focus:
            lines.append("F " + " ".join(f"{self._atom(k)}={self._number(v)}" for k, v in sorted(focus.items())))

        self._entities(lines, extracted_state, aliases, profile, active_entities=active_entities)
        self._relations(lines, extracted_state, aliases, profile)
        self._experience(lines, extracted_state, aliases, profile)
        self._relationship_timeline(lines, extracted_state, aliases, profile)
        self._norms(lines, extracted_state, aliases, profile)
        self._knowledge(lines, extracted_state, aliases, profile)
        self._wearing(lines, events, aliases)

        if profile in {"teacher", "debug"}:
            self._claims(lines, extracted_state, aliases, profile)

        if profile != "memory":
            self._scenario_events(lines, events, aliases, profile)
            self._runtime_events(lines, events, aliases, profile)

        if profile in {"writer", "teacher", "debug"}:
            self._derived(lines, analysis, profile, aliases)
            self._surface(lines, analysis, profile)

        if profile == "debug":
            self._blocked(lines, analysis)
            self._coverage(lines, analysis)

        text = "\n".join(lines).rstrip() + "\n"
        return CompiledContext(
            profile=profile,
            text=text,
            metadata={
                "aif_core_version": self.VERSION,
                "profile": profile,
                "characters": len(text),
                "lines": len(lines),
                "aliases": aliases,
            },
        )

    def _aliases(self, state, active_entities=None):
        entities = [
            e for e in state.get("entities", [])
            if active_entities is None or e.get("id") in active_entities
        ]
        canonical_self = None
        for a in state.get("entity_aliases", []) or []:
            if a.get("alias") == "char:self":
                canonical_self = a.get("canonical")
        if not canonical_self and any(e.get("id") == "char:self" for e in entities):
            canonical_self = "char:self"
        if not canonical_self:
            chars = [e for e in entities if e.get("type") == "character" and e.get("label") not in {"fano", "self_mother", "fano_mother"}]
            if chars:
                canonical_self = chars[0]["id"]

        aliases, used = {}, set()
        counters = {"garment": 0, "item": 0, "location": 0, "family": 0, "relationship": 0}
        for e in entities:
            eid, etype = e.get("id", ""), e.get("type", "entity")
            label = self._atom(e.get("label") or eid.split(":")[-1])
            if eid == canonical_self:
                alias = "self"
            elif etype == "character":
                alias = label
            elif etype == "garment":
                counters[etype] += 1; alias = f"g{counters[etype]}"
            elif etype == "item":
                counters[etype] += 1; alias = f"x{counters[etype]}"
            elif etype == "location":
                counters[etype] += 1; alias = f"loc{counters[etype]}"
            elif etype == "family":
                if eid == "family:self": alias = "fam.self"
                elif eid == "family:fano": alias = "fam.fano"
                else: counters[etype] += 1; alias = f"fam{counters[etype]}"
            elif etype == "relationship":
                counters[etype] += 1; alias = f"rel{counters[etype]}"
            else:
                alias = label
            base, n = alias, 2
            while alias in used:
                alias = f"{base}{n}"; n += 1
            used.add(alias); aliases[eid] = alias
        return aliases

    def _active_entities(self, state, events):
        active = set()
        # Self/canonical character is always useful.
        for a in state.get("entity_aliases", []) or []:
            if a.get("alias") == "char:self": active.add(a.get("canonical"))
        if not active:
            for e in state.get("entities", []):
                if e.get("id") == "char:self": active.add("char:self")

        def add_ref(value):
            if not isinstance(value, str): return
            for e in state.get("entities", []):
                eid = e.get("id")
                if value == eid or value.startswith(eid + "."):
                    active.add(eid)

        for r in state.get("relations", []) or []:
            add_ref(r.get("subject")); add_ref(r.get("object"))
        for h in state.get("experience", []) or []:
            add_ref(h.get("subject")); add_ref(h.get("object"))
        for k in state.get("knowledge", []) or []:
            add_ref(k.get("knower")); add_ref(k.get("known_object"))
        for n in state.get("norms", []) or []:
            add_ref(n.get("subject")); add_ref(n.get("object"))
        for rt in state.get("relationship_timeline", []) or []:
            add_ref(rt.get("relationship"))
            for x in rt.get("participants", []) or []: add_ref(x)
        for e in events.get("events", []) or []:
            for key in ("actor", "target", "cause"): add_ref(e.get(key))
        for e in events.get("scenario_events", []) or []:
            for key in ("causer", "patient", "target"): add_ref(e.get(key))
        snaps = events.get("state_snapshots", []) or []
        if snaps:
            for actor, data in snaps[-1].get("state", {}).get("runtime", {}).items():
                add_ref(actor)
                for gid, enabled in data.get("wearing", {}).items():
                    if enabled: add_ref(gid)
        # Location setting is cheap and usually useful.
        for e in state.get("entities", []):
            if e.get("type") == "location": active.add(e.get("id"))
        return active

    def _entities(self, lines, state, aliases, profile, active_entities=None):
        for e in state.get("entities", []):
            if active_entities is not None and e.get("id") not in active_entities:
                continue
            eid, etype = e.get("id", ""), e.get("type", "entity")
            alias = aliases.get(eid, self._atom(eid))
            prefix = self.PREFIX.get(etype, "O")
            label = self._atom(e.get("label") or etype)
            fields = []

            # Character names are identity, not categorical "type".
            if etype == "garment":
                fields.append(f"kind={label}")
                ontology = e.get("attributes", {}).get("ontology", {})
                if ontology.get("garment_family"):
                    fields.append(f"family={self._atom(ontology['garment_family'])}")
            elif etype in {"item", "location", "family", "relationship"}:
                fields.append(f"kind={label}")

            for path, fact in self._flatten(e.get("attributes", {})):
                if path.startswith("ontology."):
                    continue
                key = self.KEY_MAP.get(path, self._compact_path(path))
                tok = self._field(key, fact.get("value"), fact.get("epistemic", "explicit"))
                if profile in {"teacher", "debug"} and fact.get("confidence") is not None:
                    tok += f"@{self._number(fact['confidence'])}"
                if profile == "debug" and fact.get("source_segment"):
                    tok += f"#{self._atom(fact['source_segment'])}"
                fields.append(tok)
            if e.get("provisional") and profile in {"teacher", "debug"}:
                fields.append("provisional")
            lines.append(f"{prefix} {alias}" + ((" " + " ".join(fields)) if fields else ""))

    def _flatten(self, obj, prefix="") -> Iterable[tuple[str, dict]]:
        if not isinstance(obj, dict):
            return
        if "value" in obj and ("epistemic" in obj or "confidence" in obj or "source_segment" in obj):
            yield prefix, obj
            return
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                yield from self._flatten(v, path)

    def _relations(self, lines, state, aliases, profile):
        rels = state.get("relations", []) or []
        historical_friend = {
            (r.get("subject"), r.get("object"))
            for r in rels
            if r.get("predicate") == "relationship.friend_of"
            and r.get("temporal_scope") == "historical"
        }
        for r in rels:
            raw_pred = r.get("predicate", "related")
            # Dedicated records and final-state W are less ambiguous.
            if raw_pred.startswith("knowledge.") or raw_pred == "relationship.transition":
                continue
            if profile == "writer" and raw_pred == "wearing":
                continue
            if (
                raw_pred == "relationship.friend_of"
                and r.get("temporal_scope") == "unspecified"
                and (r.get("subject"), r.get("object")) in historical_friend
            ):
                continue
            pred = self._atom(raw_pred)
            subj = self._ref(r.get("subject"), aliases)
            args = [subj]
            if r.get("object") is not None:
                args.append(self._ref(r.get("object"), aliases))
            if r.get("value") not in (None, True):
                args.append(self._value_refaware(r.get("value"), aliases))
            line = f"R {pred}({','.join(args)})"
            temporal = r.get("temporal_scope")
            if temporal and temporal not in {"current", "current_or_unspecified"}:
                line += f" t={self._atom(temporal)}"
            if profile in {"teacher", "debug"} and r.get("confidence") is not None:
                line += f" @{self._number(r['confidence'])}"
            lines.append(line)

    def _experience(self, lines, state, aliases, profile):
        for h in state.get("experience", []) or []:
            value = h.get("value")
            if isinstance(value, dict) and "with" in value:
                value = {k: v for k, v in value.items() if k != "with"}
            line = f"H {self._atom(h.get('predicate'))}({self._ref(h.get('subject'), aliases)})={self._value_refaware(value, aliases)}"
            if h.get("object"):
                line += f" with={self._ref(h['object'], aliases)}"
            if h.get("temporal_scope"):
                line += f" t={self._atom(h['temporal_scope'])}"
            if profile in {"teacher", "debug"}:
                line += f" @{self._number(h.get('confidence', .9))}"
            lines.append(line)

    def _relationship_timeline(self, lines, state, aliases, profile):
        for rt in state.get("relationship_timeline", []) or []:
            tr = rt.get("transition", {})
            line = (
                f"RT {self._ref(rt.get('relationship'), aliases)} "
                f"{self._atom(tr.get('from','?'))}->{self._atom(tr.get('to','?'))}"
            )
            if tr.get("progression"):
                line += f" progression={self._atom(tr['progression'])}"
            lines.append(line)

    def _norms(self, lines, state, aliases, profile):
        for n in state.get("norms", []) or []:
            line = f"N {self._atom(n.get('predicate'))} subject={self._ref(n.get('subject'), aliases)} value={self._value_refaware(n.get('value'), aliases)}"
            if profile in {"teacher", "debug"}:
                line += f" @{self._number(n.get('confidence', .9))}"
            lines.append(line)

    def _knowledge(self, lines, state, aliases, profile):
        for k in state.get("knowledge", []) or []:
            line = f"K {self._ref(k.get('knower'), aliases)} aware={self._ref(k.get('known_object'), aliases)}"
            if profile in {"teacher", "debug"}:
                line += f" @{self._number(k.get('confidence', .9))}"
            lines.append(line)

    def _wearing(self, lines, events, aliases):
        snaps = events.get("state_snapshots", []) or []
        if not snaps:
            return
        runtime = snaps[-1].get("state", {}).get("runtime", {})
        for entity_id, data in runtime.items():
            worn = [self._ref(g, aliases) for g, active in data.get("wearing", {}).items() if active]
            if worn:
                lines.append(f"W {self._ref(entity_id, aliases)}:{','.join(worn)}")

    def _claims(self, lines, state, aliases, profile):
        for c in state.get("claims", []) or []:
            subject = self._ref(c.get("subject"), aliases)
            line = f"CL {self._atom(c.get('kind','fact'))} {self._atom(c.get('predicate'))}({subject})={self._value(c.get('value'))}"
            if c.get("object"):
                line += f" obj={self._ref(c['object'], aliases)}"
            temporal = c.get("scope", {}).get("temporal")
            if temporal and temporal != "current_or_unspecified":
                line += f" t={self._atom(temporal)}"
            line += f" @{self._number(c.get('confidence', .9))}"
            if profile == "debug" and c.get("source_segment"):
                line += f" #{self._atom(c['source_segment'])}"
            lines.append(line)

    def _scenario_events(self, lines, events, aliases, profile):
        for e in events.get("scenario_events", []) or []:
            args = []
            for key in ("causer", "patient", "target"):
                if e.get(key): args.append(f"{key}={self._ref(e[key], aliases)}")
            if e.get("recurrence"): args.append(f"rec={self._atom(e['recurrence'])}")
            args.append(f"status={self._atom(e.get('realization_status','requested'))}")
            lines.append(f"Q {self._atom(e.get('id'))} {self._atom(e.get('type'))} " + " ".join(args))

    def _runtime_events(self, lines, events, aliases, profile):
        for e in events.get("events", []) or []:
            args = []
            for key in ("actor", "target", "cause"):
                if e.get(key): args.append(f"{key}={self._ref(e[key], aliases)}")
            if e.get("order") is not None: args.append(f"ord={e['order']}")
            if profile in {"teacher", "debug"}:
                args.append(f"eh={self._number(e.get('eventhood_score',1))}")
                for eff in e.get("effects", []) or []:
                    path = self._path_ref(eff.get("path", ""), aliases)
                    if eff.get("op") == "delete": args.append(f"Δdel:{path}")
                    else: args.append(f"Δ{self._atom(eff.get('op','set'))}:{path}={self._value(eff.get('value'))}")
            lines.append(f"E {self._atom(e.get('id'))} {self._atom(e.get('type'))}" + ((" " + " ".join(args)) if args else ""))

    def _derived(self, lines, analysis, profile, aliases):
        focus = analysis.get("scene_focus", {}) or {}
        for d in analysis.get("derived_facts", []) or []:
            if profile == "writer":
                if not d.get("writer_relevant"):
                    continue
                tags = d.get("focus_tags", [])
                # If no scene focus is available, keep explicitly writer-relevant facts.
                # Otherwise retain facts whose domain is active or generally appearance/clothing relevant.
                if focus and tags and not any(focus.get(t, 0) > .25 for t in tags) and not any(t in {"appearance", "clothing", "relationship", "familiarity"} for t in tags):
                    continue
            op = "≈" if d.get("name", "").startswith("estimated_") else "="
            raw_name = str(d.get("name"))
            compact_name = raw_name
            for eid, alias in sorted(aliases.items(), key=lambda kv: len(kv[0]), reverse=True):
                if compact_name.startswith(eid + "."):
                    compact_name = alias + compact_name[len(eid):]
                    break
            line = f"D {self._atom(compact_name)}{op}{self._value(d.get('value'))}"
            if profile in {"teacher", "debug"}: line += f" @{self._number(d.get('confidence', .9))}"
            lines.append(line)

    def _surface(self, lines, analysis, profile):
        plan = analysis.get("surface_plan", {}) or {}
        for s in plan.get("writer_context", []) or []:
            line = f"S {self._atom(s.get('surface_policy'))} {self._atom(s.get('effect'))} event={self._atom(s.get('event_id'))} score={self._number(s.get('score',0))}"
            if s.get("why_relevant"): line += " why=" + self._list(s["why_relevant"])
            if s.get("avoid"): line += " avoid=" + self._list(s["avoid"])
            lines.append(line)
        if profile == "debug":
            for s in plan.get("suppressed", []) or []:
                lines.append(f"S- {self._atom(s.get('surface_policy'))} {self._atom(s.get('effect'))} score={self._number(s.get('score',0))}")

    def _blocked(self, lines, analysis):
        for u in analysis.get("blocked_inferences", []) or []:
            lines.append(f"U blocked {self._atom(u.get('candidate'))} reason={self._quoted(u.get('reason'))}")

    def _coverage(self, lines, analysis):
        cov = analysis.get("coverage", {}) or {}
        if cov:
            layers = cov.get("coverage_by_layer", {})
            bits = [f"overall={self._number(cov.get('semantic_coverage_score',0))}"]
            bits += [f"{self._atom(k)}={self._number(v)}" for k, v in sorted(layers.items())]
            lines.append("COV " + " ".join(bits))

    def _field(self, key, value, epistemic):
        op = {"explicit": "=", "inferred": "~", "estimated": "≈", "assumed": "?", "hypothetical": "??"}.get(epistemic, "=")
        return f"{key}{op}{self._value(value)}"

    def _value(self, value):
        if value is True: return "true"
        if value is False: return "false"
        if value is None: return "null"
        if isinstance(value, (int, float)): return self._number(value)
        if isinstance(value, dict):
            # Measurement compression.
            if value.get("frame") == "body_relative" and value.get("anchor"):
                return f"{self._atom(value['anchor'])}@body"
            if value.get("unit") and value.get("value") is not None:
                return f"{self._number(value['value'])}{self._atom(value['unit'])}"
            return "{" + ",".join(f"{self._atom(k)}:{self._value(v)}" for k, v in value.items() if v is not None) + "}"
        if isinstance(value, list): return "[" + ",".join(self._value(v) for v in value) + "]"
        text = str(value)
        if re.fullmatch(r"[A-Za-z0-9_.:+@/-]+", text): return text
        return json.dumps(text, ensure_ascii=False, separators=(",", ":"))

    def _value_refaware(self, value, aliases):
        if isinstance(value, dict):
            return "{" + ",".join(
                f"{self._atom(k)}:{self._value_refaware(v, aliases)}"
                for k, v in value.items() if v is not None
            ) + "}"
        if isinstance(value, list):
            return "[" + ",".join(self._value_refaware(v, aliases) for v in value) + "]"
        if isinstance(value, str):
            return self._ref(value, aliases) if value.startswith(("char:", "garment:", "item:", "family:", "relationship:", "loc:")) else self._value(value)
        return self._value(value)

    def _ref(self, value, aliases):
        if value is None: return "?"
        text = str(value)
        if text in aliases: return aliases[text]
        for eid, alias in sorted(aliases.items(), key=lambda kv: len(kv[0]), reverse=True):
            if text.startswith(eid + "."): return alias + text[len(eid):]
        return self._atom(text)

    def _path_ref(self, path, aliases):
        text = path.removeprefix("runtime.")
        for eid, alias in sorted(aliases.items(), key=lambda kv: len(kv[0]), reverse=True):
            if text.startswith(eid): return alias + text[len(eid):]
        return self._compact_path(text)

    def _compact_path(self, path):
        out = path
        for a, b in (("physical.", "phys."), ("morphology.", "morph."), ("current.", ""), ("baseline.", "0."), ("transformations.", "x."), ("biological_context.", "bio.")):
            out = out.replace(a, b)
        return out

    def _atom(self, value):
        text = str(value).strip().lower()
        text = re.sub(r"\s+", "_", text)
        return re.sub(r"[^a-z0-9_./:+@~-]", "", text) or "?"

    def _number(self, value):
        try: f = float(value)
        except Exception: return self._atom(value)
        return f"{f:.4f}".rstrip("0").rstrip(".") or "0"

    def _quoted(self, value):
        return json.dumps(str(value), ensure_ascii=False, separators=(",", ":"))

    def _list(self, values):
        return "[" + ",".join(self._quoted(v) for v in values) + "]"
