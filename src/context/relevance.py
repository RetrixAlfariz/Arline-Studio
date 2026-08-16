from __future__ import annotations

from src.core import RelevanceDecision, SemanticCore


class RelevanceSelector:
    """Select writer facts by semantic role, not by raw string truncation."""

    VERSION = "0.1"

    def select(self, core: SemanticCore, pipeline_result, narrative) -> list[RelevanceDecision]:
        state = pipeline_result.extracted_state
        events = pipeline_result.events
        focus = pipeline_result.analysis.get("scene_focus", {}) or {}
        active_entities: set[str] = set()

        # Canonical self and location are cheap scene anchors.
        for alias in state.get("entity_aliases", []) or []:
            if alias.get("alias") == "char:self" and alias.get("canonical"):
                active_entities.add(alias["canonical"])
        for e in state.get("entities", []) or []:
            if e.get("type") == "location":
                active_entities.add(e.get("id"))

        # Current wearing and active event references get top priority.
        snaps = events.get("state_snapshots", []) or []
        if snaps:
            runtime = snaps[-1].get("state", {}).get("runtime", {}) or {}
            for actor, data in runtime.items():
                active_entities.add(actor)
                for gid, enabled in (data.get("wearing", {}) or {}).items():
                    if enabled:
                        active_entities.add(gid)
        for event in (events.get("events", []) or []) + (events.get("scenario_events", []) or []):
            for key in ("actor", "target", "cause", "causer", "patient"):
                value = event.get(key)
                if isinstance(value, str):
                    root = value.split(".", 1)[0] if ":" not in value.split(".", 1)[0] else value
                    # Match full entity id by prefix.
                    for entity in state.get("entities", []) or []:
                        eid = entity.get("id")
                        if value == eid or value.startswith(str(eid) + "."):
                            active_entities.add(eid)

        # Relation participants become active if one end is already active,
        # especially for relationship/social context.
        for r in state.get("relations", []) or []:
            subject, obj = r.get("subject"), r.get("object")
            pred = str(r.get("predicate") or "")
            if subject in active_entities or obj in active_entities or pred.startswith(("relationship.", "social.")):
                if isinstance(subject, str): active_entities.add(subject)
                if isinstance(obj, str): active_entities.add(obj)

        decisions: list[RelevanceDecision] = []
        for fact in core.facts:
            p = 3
            reason = "latent canonical fact"
            include = True
            score = .4
            domain = fact.category

            if fact.entity_id in active_entities and fact.temporal_scope == "current":
                p, reason, score = 0, "current state of an active scene entity", 1.0
            elif fact.entity_id in active_entities and fact.category in {"identity", "location", "garment", "transformation"}:
                p, reason, score = 1, "active entity fact needed for continuity", .9
            elif fact.entity_id in active_entities and fact.category in {"physical", "appearance"}:
                p, reason, score = 1, "active character/appearance fact", .82
            elif fact.category == "physical" and any(focus.get(k, 0) > .45 for k in ("physical_detail", "appearance", "clothing_fit")):
                p, reason, score = 2, "matches active physical-detail focus", .72
            elif fact.category == "skill":
                p, reason, score = 3, "stable character capability; usually latent", .45
            elif fact.authority in {"estimate", "analytical_inference"}:
                p, reason, score = 4, "derived/estimated source fact not directly needed", .2
                include = False

            decisions.append(RelevanceDecision(
                key=fact.id,
                priority=p,
                include=include,
                reason=reason,
                score=score,
                domain=domain,
            ))

        # Derived facts get explicit relevance reasons too.
        for d in pipeline_result.analysis.get("derived_facts", []) or []:
            name = str(d.get("name"))
            writer_relevant = bool(d.get("writer_relevant"))
            tags = d.get("focus_tags", []) or []
            match = max([float(focus.get(t, 0)) for t in tags if isinstance(focus.get(t, 0), (int, float))] or [0.0])
            include = writer_relevant and (match > .2 or any(t in {"appearance", "clothing", "relationship", "familiarity"} for t in tags))
            decisions.append(RelevanceDecision(
                key="derived:" + name,
                priority=2 if include else 4,
                include=include,
                reason=("writer-relevant analytical consequence matches scene" if include else "analytical fact has no active scene reason"),
                score=round(max(.2, match), 3),
                domain="derived",
            ))
        return decisions
