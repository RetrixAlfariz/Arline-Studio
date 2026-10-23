# Arline Studio v1.2.1 — Runtime Completion & Performance Architecture

**Development line:** `develop/v1.2`  
**Implementation milestone:** v1.2.1 development completion  
**Merge policy:** the v1.2 line remains isolated from `main` until the repository owner explicitly approves the complete update.

## Purpose

v1.2.1 originally proved the temporal Memory, Character Rails, Narrative Discovery, provisional Library, spatial hierarchy, and physical-item identity designs. As those systems became connected, several derived operations were still executed eagerly and repeatedly. The functionality was correct, but ordinary navigation, startup, and turn finalization could pay the cost of work that was only needed by the Discoveries view or by a one-time migration.

This completion pass keeps the same truth/provenance model while separating the runtime into **hot paths** and **cold/background paths**.

```text
HOT PATH
startup → project/chat navigation → write/generate → turn-local capture

COLD / DERIVED PATH
historical projection repair → large discovery listing → provenance detail
→ migration residue → explicit backfill / diagnostics
```

The source of truth remains unchanged:

```text
Source message / manuscript
        ↓
Discovery instances
        ↓
Propositions, relations, transitions
        ↓
Detected / Reviewed / Canon (user only)
        ↓
Derived Library / Timeline / Memory projections
```

## Completed runtime changes

### 1. Capture once, report many times

A new turn is captured exactly once by the History lifecycle hook. Turn-local materialization happens in that same incremental pipeline.

The compatibility endpoint:

```text
POST /api/memory/discoveries/capture-turn/{turn_id}
```

is now read-only/report-only by default. It returns persisted proposition and evidence counts without rerunning semantic extraction. An explicit diagnostic/repair caller may still request:

```text
?force=true
```

A dedicated read endpoint is also available:

```text
GET /api/memory/discoveries/turn/{turn_id}/report
```

This removes the old sequence where the backend captured and materialized a turn, built a second materialization report, and the frontend recaptured the same turn after generation.

### 2. Bounded startup work

Startup no longer synchronously walks thousands of historical propositions as one blocking operation.

The startup pass is bounded by both a small item batch and a short time budget. New turns remain synchronously usable because their own changed proposition IDs are materialized immediately. Historical migration or repair residue is treated as derived backlog.

### 3. Incremental background projection drain

Historical derived-projection residue is drained by a rate-limited daemon worker in small deterministic batches.

Properties of the worker:

- it never owns source truth;
- it does not block application readiness;
- it is restart-safe and idempotent;
- it publishes scheduled/running/completed, round, processed, pending, and error metrics;
- explicit backfill can restart the drain when new pending work is found;
- projection failure cannot roll back source messages, Canon, Timeline, or Library truth.

### 4. Capture and materialization fingerprints

Derived operations use source revision and proposition fingerprints to avoid repeating unchanged work.

Caches cover:

- turn/source capture revisions;
- turn-local materialization fingerprints;
- branch projection repair fingerprints;
- reusable branch/session cutoff information;
- evaluated Discovery lists by scope and revision;
- resource-view provenance prefetch;
- physical-item lookup projections.

Caches are derived and disposable. They never grant Canon authority.

### 5. Batch provenance evaluation

Discovery list and resource views no longer require an independent instance query for every proposition. Relevant proposition IDs and their evidence instances are prefetched in batches, then evaluated against ScopeGate using the same lineage/time/viewpoint rules.

The hard order remains:

```text
ScopeGate
  ↓
knowledge/provenance state
  ↓
ranking / presentation
```

Caching never admits sibling-fork, future-scene, future-world-time, or out-of-scope evidence.

### 6. Indexed physical-item resolution

Repeatable garment objects retain stable physical `ITEM-*` identities, but the resolver no longer needs to scan every Workspace item and then query every proposition independently for a simple reference.

The physical-item projection is keyed by stable identity and useful descriptors such as garment type, color, material, owner, and branch-visible evidence. Resolution still follows the conservative rules:

```text
unique compatible candidate → reuse ITEM
explicit new/purchase/quantity → create new ITEM identity
multiple equally compatible candidates → abstain
same physical object changes → same ITEM + PROP/CHANGE
```

### 7. Lazy Discoveries UI

The complete Discovery proposition list is no longer part of the ordinary Chat, Manuscript, or project-navigation critical path.

During boot and project switching, hidden Discovery-list requests are deferred and answered from the current in-memory snapshot. Opening the Discoveries tab always performs the real scoped request. After a completed turn, the existing persisted report and compact counters remain available without forcing a large list during unrelated navigation.

The full list is loaded when it provides user-visible value:

- the user opens Library → Discoveries;
- the user runs an explicit scan/backfill;
- the user opens a proposition or provisional sheet;
- a diagnostic tool requests it.

### 8. Runtime observability

Discovery status includes performance diagnostics for:

- capture-cache behavior;
- materialization-cache behavior;
- bounded startup processing;
- batch evaluation/list caching;
- physical-item lookup behavior;
- background materialization backlog and errors.

These metrics are diagnostics only and do not alter retrieval or authority.

## v1.2.1 functional completion boundary

The development milestone now includes:

- temporal state reconstruction on story-order and comparable world-time axes;
- future/fork/branch/POV-aware ScopeGate behavior;
- Timeline-derived temporal projection and targeted refresh;
- hybrid structured + FTS + optional BGE-M3 retrieval;
- Character Rails (`/mono`, `/dia`, `/ambience`, `/intimacy`);
- deterministic Scene Dynamics planning with adaptive speaker order;
- source-backed Narrative Discovery with message/revision/branch provenance;
- Detected → Reviewed lifecycle and explicit user-only Canon promotion;
- provisional callable Library sheets and first-class relations;
- spatial containment hierarchy with lightweight zones;
- stable physical `ITEM-*` identities for repeatable garments;
- correction versus story-state transition semantics;
- hot-path/cold-path performance separation, bounded startup, background repair, batch evaluation, and lazy UI loading.

## Explicitly external or later work

The following are not hidden blockers in this code milestone:

- a controlled real LM Studio BGE-M3 benchmark requires the user's local model runtime and representative corpus;
- retrieval-quality tuning on a large novel-sized corpus remains empirical evaluation rather than a missing architecture primitive;
- full model-assisted free-form coreference/conflict resolution remains later semantic work and should not be introduced by weakening conservative identity rules;
- package metadata remains on the v1.2 alpha development line until the complete v1.2 branch is explicitly prepared for merge/release.

## Validation expectations

The permanent CI must cover:

- Python regression suite;
- Python compilation;
- JavaScript syntax;
- executable Memory runtime scope smoke;
- repository hygiene;
- capture-once/report-only hot path;
- bounded and background materialization behavior;
- batch/cached Discovery semantics;
- physical-item identity and ambiguity behavior;
- lazy Discovery UI without blocking explicit Discoveries navigation.

A temporary validation PR may target `develop/v1.2` only. It must never be merged and must differ from the exact development head only by a validation marker.
