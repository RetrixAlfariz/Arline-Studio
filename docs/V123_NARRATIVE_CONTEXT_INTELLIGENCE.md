# Arline v1.2.3 — Narrative Context Intelligence

v1.2.3 sits above the v1.2.2 continuity model. It does not invent a second
memory system and it does not ask an LLM to decide what is true. Its job is to
make the existing sources agree on **what matters for this scene**.

## Top-down contract

```text
Current request + active Scene Card
              ↓
      NarrativeContextPlan
       ├ intent
       ├ focus resources
       ├ POV / time / location anchors
       ├ narrative dimensions
       ├ lane weights
       └ token allocation
              ↓
 Workspace + Memory + Continuity + ScopeGate
              ↓
 @ARLINE-NARRATIVE-CONTEXT 1.2.3
       ├ unresolved continuity
       ├ active continuity
       ├ accepted/current state
       ├ POV knowledge & beliefs
       ├ relationships
       ├ events & causes
       ├ spatial context
       ├ open threads
       └ source evidence
              ↓
             Writer
```

The planner is deterministic and rebuildable. Canon authority, branch/fork
visibility, temporal visibility and POV access remain enforced by the layers
below it.

## Narrative intents

The first implementation distinguishes continuation, dialogue, action,
description, transition, causal lookup, recall, summary, continuity review and
branch comparison. The intent changes *priority and budget*, never truth.

Examples:

- dialogue prioritizes POV + relationships + continuity;
- action prioritizes events + state + continuity + spatial anchors;
- description prioritizes state + spatial detail;
- transition prioritizes continuity + before/after events;
- causal questions prioritize events/causes and supporting source evidence.

## Active-scene focus

Explicit `@` references are always first-class focus resources. When the prompt
is terse (`Continue.`), the planner also uses the active scene POV, location and
participants as focus anchors. This prevents the retrieval layer from requiring
the user to repeat names that the workspace already knows.

## Continuity retrieval lane

v1.2.2 continuity is now a real Memory lane. It can surface:

- current derived heads;
- FORM snapshots;
- EVENT/CAUSE history;
- unresolved ambiguity/conflict diagnostics.

Ambiguous state is rendered as an explicit abstention. The planner never chooses
one competing value merely to make the writer prompt look cleaner.

## Relationships lane

Relationships connected to focused variants are retrieved structurally rather
than rediscovered through text search. Canon relationships retain stronger
authority scoring while draft/non-canon relationships remain clearly lower
authority context.

## POV boundary

POV is a planning dimension, not a prompt decoration. POV/scene lenses preserve
the epistemic lane and continue to rely on ScopeGate to block inaccessible or
future knowledge. Author lens may see author-only future context only when the
existing scope explicitly allows it.

## Semantic token budgeting

The planner allocates the Memory token allowance across lanes. Under pressure,
important lanes receive one protected slot before verbose source evidence can
consume the remainder. Unused allocations may be reused afterward, so the plan
is a priority system rather than a rigid quota system.

The global token budget remains the hard ceiling.

## Authority rule

```text
Context relevance ≠ truth
Continuity reconstruction ≠ Canon
High retrieval score ≠ Canon
```

v1.2.3 may decide that a piece of evidence is important enough to show the
writer. It may not upgrade that evidence's authority.

## Deliberate non-goals

- no LLM context router;
- no fuzzy identity merge;
- no automatic Canon promotion;
- no autonomous retcon;
- no semantic branch merge;
- no second vector/database subsystem.

Those remain separate later milestones.
