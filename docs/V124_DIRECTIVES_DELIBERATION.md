# v1.2.4 — Narrative Directives, Semantic References & Deliberation

v1.2.4 adds one top-down control/intelligence layer above v1.2.3 context planning.

```text
user input
  ├─ / typed directive     = explicit user intent
  ├─ @ semantic reference = explicit grounding
  └─ prose                 = semantic request
        ↓
DirectiveEngine
        ↓
NarrativeContextPlanner
        ↓
Memory / Continuity / ScopeGate
        ↓
authoritative writer context
        ↓
NarrativeDeliberator       = soft possibilities, never authority
        ↓
Writer                     = realization
```

## Authority rule

- `/` changes what the user is asking Arline to do. It is not a story fact.
- `@` binds a stable or dynamic story resource into the request. It does not change Canon.
- Context/Continuity decide what evidence is allowed and what is currently derivable.
- Deliberation proposes plausible beats, intentions, emotional motion, opportunities, alternatives, and uncertainty.
- Deliberation is explicitly `soft_non_canon` and cannot resolve UNKNOWN/conflicts or create character knowledge.
- Only accepted/reviewed story/world workflows may later change authoritative state.

## Reference expressions

Stable references may be selector-qualified:

`@Fila.voice`, `@Fila.state`, `@Fila.appearance`, `@Fila.knowledge`, `@Fila.beliefs`, `@Fila.relationships`, `@Fila.timeline`, `@Fila.evidence`, `@Fila.conflicts`.

Dynamic references are resolved on every request rather than persisted as stale IDs:

`@scene`, `@pov`, `@location`, `@cast`, `@world`, `@branch`, `@threads`, `@recent`.

## Deliberation commands

`/intuition` exposes author-facing narrative intuition. `/alternatives` asks for several possible next beats. Normal writing commands use the same deliberation internally before prose realization.

The same selected local LM Studio writer model performs deliberation using a bounded JSON-only call. Deliberation failure is fail-soft: generation continues with conservative context-only guidance.
