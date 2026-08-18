# Arline v1.2.2 — Narrative State & Continuity

v1.2.2 continues on `develop/v1.2`. It is not a release branch and it must not
be merged to `main` without an explicit owner decision.

## Goal

v1.2.1 made narrative evidence usable: scoped Memory, temporal retrieval,
Narrative Discovery, provisional Library sheets, physical ITEM identity,
relations, spatial containment, and explicit Canon authority. v1.2.2 turns those
pieces into a continuity model capable of answering a harder question:

> Given everything visible in this narrative lineage, what is true about this
> entity **now**, what used to be true, what changed it, and what remains
> ambiguous?

The central rule remains unchanged:

> Derived continuity is not authority. Arline may reconstruct, compare, and
> abstain; only the user may grant Canon.

## Architecture

```text
SOURCE TURN
    ↓
Discovery instances (DISC-*)
    ↓
Propositions (PROP-*)
    ↓
Narrative Continuity Resolver
    ├── explicit story change → SUPER-* edge
    ├── explicit correction   → SUPER-* edge
    ├── unclear contradiction → CONFLICT-* (abstain)
    └── state transition      → FORM-* snapshot
    ↓
Current-view reconstruction
    ↓
Memory / Library / Character Rails
```

### Stable identity vs mutable state

Entity identity is stable. A new value never creates another character merely
because the character changed.

```text
Character A
  PROP-10 hair.length_cm = 10
  PROP-31 hair.length_cm = 100

  SUPER-8
    from = PROP-10
    to   = PROP-31
    kind = story_change
```

For physical items the same rule applies:

```text
ITEM-A81F
  color = black
    ↓ story change
  color = red
```

The ITEM id stays the same. Buying another object creates another ITEM id.

## Change classes

### Story change

Used only when the evidence explicitly describes a temporal transition. Examples
include `sekarang`, `kini`, `menjadi`, `berubah`, `setelah`, `now`, `became`,
`changed to`, or an extractor-generated state transition.

The previous proposition remains historical and the new proposition becomes the
current derived head in that lineage.

### Correction

Used only when the source explicitly corrects a previous observation, for
example `koreksi`, `maksudku`, `ralat`, `I meant`, or equivalent unambiguous
wording.

A correction and a story transition are not interchangeable: one repairs the
record while the other preserves a real before/after world state.

### Conflict / abstention

If two visible values compete and Arline cannot prove whether the new statement
is a correction or a story-world transition, neither value is silently chosen.
The resolver creates a `CONFLICT-*` record and current-view reconstruction marks
that predicate ambiguous.

This is intentionally conservative. A false abstention is recoverable; a silent
retcon is not.

## Character Forms

`FORM-*` is a derived state frame under one stable character identity. It is not
a second Character sheet.

```text
ENT-REV
  ├── FORM-A  first observed state frame
  ├── FORM-B  after transformation event
  └── FORM-C  later state frame
```

A form stores the visible `state.*` heads at that narrative point and points to
its parent form when one exists. The first implementation creates forms from
explicit state transitions. Later v1.2.2 passes will enrich form naming, event
causality, and before/after reconstruction.

## Current-view reconstruction

For a scoped `MemoryQueryContext`, the resolver:

1. applies the same project/world/branch/session Scope Gate used by Discovery;
2. collects only visible propositions (plus valid Canon);
3. removes propositions superseded by a visible `SUPER-*` edge;
4. gives Canon priority when it is the only authoritative head;
5. refuses to choose when multiple incompatible heads remain;
6. returns explicit `ambiguous` diagnostics instead of inventing chronology.

Sibling branches cannot alter one another's current view because a supersession
edge is effective only when both endpoint propositions are visible in the
requested lineage.

## v1.2.2 implementation phases

### Phase A — continuity graph foundation

- `SUPER-*` story-change/correction edges;
- `CONFLICT-*` abstention records;
- scoped current-view reconstruction;
- `FORM-*` derived state snapshots;
- no automatic Canon mutation;
- deterministic regression fixtures.

### Phase B — Narrative Entity Resolver

Replace hard-coded story identities in the analytical extractor with arbitrary
entity mentions and stable anchors. Resolve exact Library identity and aliases
before propositions are emitted. Fuzzy merging remains forbidden.

### Phase C — cross-turn coreference

Resolve narrator/self references, pronouns, possessives, demonstratives, and
recent mentions across turns. Examples include `aku`, `saya`, `dia`, `-ku`,
`-nya`, `itu`, and `tadi`. Ambiguous candidate sets remain unresolved rather
than guessed.

### Phase D — event/state causality

Connect state changes to their causing `EVENT-*` records and reconstruct explicit
before/after frames. Character Rails and Memory can then answer questions such as
"what was Character A like before the transformation?" without flattening the
history.

### Phase E — continuity UI

Library sheets gain Current State, Forms, Change History, and Conflicts sections.
Conflict resolution remains an explicit user action and does not silently grant
Canon.

## Non-goals

v1.2.2 does not add fuzzy identity auto-merge, autonomous Canon promotion,
semantic branch merging, or model-generated retcons. Those operations are too
authoritative to infer from narrative similarity alone.

## Performance boundary

Continuity tables are rebuildable derived state. No historical continuity scan is
required for application startup. New/edited turns resolve incrementally; old
content may be rebuilt explicitly or by a bounded background task later in the
milestone.
