# Arline v1.2 implementation status

**Development branch:** `develop/v1.2`  
**Package version:** `1.2.0a1` (v1.2.1 development extension reports `1.2.1a1`)  
**Merge policy:** do not merge into `main` until the repository owner explicitly approves the complete v1.2 line.

## v1.2.0 milestone — complete foundation

The v1.2.0 milestone is the Evidence & Retrieval Foundation. It deliberately
stops before full temporal reconstruction, epistemic continuity productization,
and advanced summary/trust workflows planned for later v1.2.x milestones.

Implemented:

- source-backed MemoryStore with revision/checksum/provenance metadata;
- split SQLite FTS5 domains with structured/FTS fallback;
- optional LM Studio BGE-M3 embedding provider (`lm-kit/bge-m3-gguf`, 1024 dimensions);
- deterministic Query Compiler and specialized retrieval lanes;
- hard Scope Gate applied before rank fusion;
- RRF fusion, authority boosts, source diversity and abstention;
- retrieval-run traces with admitted and excluded evidence;
- MemoryService wired into Analyze, streamed generation and normal generation;
- Context Stack receives selected memory as a separately labelled evidence block;
- generation continues with the v1.1 Workspace Context if retrieval fails;
- multi-chunk source revisions supersede atomically at the source level;
- document and completed-chat indexing hooks with debounced refresh;
- deleted document/session evidence is removed from automatic retrieval;
- full and Project-scoped backfill jobs with progress/status API;
- Developer Context panel for memory status, backfill and query debugging;
- eight isolated generative task contracts using the same primary model weights;
- every task contract forbids hidden cross-profile history and `may_commit_canon`;
- strict `memory_proposals_v1` schema for Structure Extractor proposals;
- strict `memory_summary_v1` schema requiring source chunk provenance;
- Developer API exposes task contracts and JSON Schemas for inspection;
- README model recommendations; Arline does not download model weights;
- permanent CI covers the v1.2 memory modules, profile/schema contracts, and frontend assets.

### Retrieval model baseline

The original research draft named `intfloat/multilingual-e5-base`, but the
runtime architecture for v1.2 delegates model serving to LM Studio. The current
recommended dense-retrieval baseline is therefore **BGE-M3 GGUF** from
`lm-kit/bge-m3-gguf`, with a 1024-dimensional embedding contract and no
E5-specific `query:` / `passage:` prefixes. The configured model string is a
local LM Studio key; use the exact embedding key reported by LM Studio if it
differs from `text-embedding-bge-m3`.

Changing the embedding model or dimension requires a new derived index
generation. Existing vectors from another embedding model/dimension must not be
reinterpreted as BGE-M3 vectors.

## v1.2.1 — temporal/hybrid + Character Rails development

v1.2.1 development continues on the same `develop/v1.2` line. The goal is a
meaningful upgrade of narrative-time recall and writer steering rather than a
separate release branch.

Implemented in the current v1.2.1 pass:

- dual-axis temporal-state lookup using both story/discourse order and comparable world time;
- atomic temporal state transitions that supersede the previous interval and current-state projection together;
- conservative fictional-time comparison: ISO date/time and numeric axes may be ordered, while unrelated opaque labels are never lexically invented into chronology;
- Scope Gate extension that blocks comparable future world-time evidence outside an allowed Author lens;
- temporal query traces carry exact world-time and story-order request bounds;
- accepted/canon Timeline `state_patch` data is projected into rebuildable temporal intervals while Timeline remains authoritative history;
- Timeline projection is idempotent, branch-aware, uses conservative ancestor recorded-time cutoffs, and refuses to overwrite state keys controlled by non-Timeline authoritative projections;
- normal Memory backfill also refreshes the derived Timeline temporal projection;
- MemoryService exposes targeted Timeline projection refresh and `/api/memory/refresh` accepts `world_id` + optional `branch_id` without changing Timeline truth;
- the current Workspace Timeline mutation surface (`add_timeline_event`) is instance-wrapped when the Memory router is created so a successful Timeline add automatically rebuilds the affected derived temporal projection; refresh failure never rolls back authoritative Timeline truth and is surfaced through Memory refresh diagnostics;
- Character Rails route as story-continuation requests so existing structured + FTS + optional dense hybrid retrieval can provide character context;
- resolved character variants contribute canonical shared identity, summary, attributes, voice, current/temporal state, and first-class relationship evidence to the structured lane;
- shared Library character sheets remain usable from story Projects without being misclassified as Project-owned evidence;
- `/mono`, `/dia`, `/ambience`, and `/intimacy` rail grammar with shared pacing, intensity, intensity-curve, delivery, target, length, and termination concepts;
- `/dia` is explicitly beat-driven rather than an alternating-speaker or fixed-turn generator;
- `/mono` defaults to private internal thought, while audible delivery such as `whisper`, `murmur`, or `mutter` becomes speech;
- deterministic Scene Dynamics planning converts pacing/length into soft min/target/max beat budgets, allowed expression channels, adaptive speaker-order policy, internal-access policy, and termination boundaries while leaving prose authorship to the writer model;
- slow/lingering and fast/immediate modes have different reaction/processing requirements rather than being aliases for more/fewer words;
- rail seeds are writer-only semantic steering: they are stripped before semantic extraction and before chat Memory evidence indexing;
- prior rail command lines are stripped from session-continuity steering so a one-generation rail does not silently persist;
- accepted/generated prose remains eligible for the normal extractor/review/Memory path; the command itself never commits canon;
- dedicated Character Rails documentation records the command grammar and isolation contract;
- synthetic tests cover rail parsing/isolation, compact `@vian@fano` participants, Scene Dynamics budgets/channels, optional hybrid dense routing, Library profile + relationship retrieval, world-time Scope Gate behavior, dual-axis state reconstruction, Timeline projection/backfill idempotency, Timeline add auto-refresh failure isolation, supersession, and chat-index rail leakage.

### Validation

Temporary validation PRs target `develop/v1.2` only and are never merged; they
exist solely because the connector exposes PR-triggered workflow runs more
reliably than push-triggered runs. Validation run `32079202074` completed
successfully across the Python regression suite, Python compilation, JavaScript
syntax checks, executable Memory runtime scope smoke, and repository hygiene for
the current source feature set. The temporary PR was closed without merging.

No feature code is merged into `main` by this validation process.

Still external or deferred before calling the v1.2.1 milestone fully closed:

- controlled real LM Studio BGE-M3 smoke/backfill on a local corpus/model runtime;
- larger-corpus retrieval quality benchmarking beyond deterministic synthetic regression fixtures;
- future Timeline update/delete APIs must bind the same derived-refresh rule when those mutation surfaces are introduced (the current Workspace API exposes Timeline add only);
- package/lock metadata remains on `1.2.0a1` until a synchronized `pyproject.toml` + `uv.lock` version bump is performed at milestone close.

## Explicit v1.2.0 boundary

Dense retrieval remains optional and reranking is not required. Full mature POV
knowledge continuity, autonomous summary refresh, consequence simulation, and
semantic branch merge remain later v1.2.x/v1.3 work according to the research
specification.

## v1.2.0 correctness hardening

- Memory frontend scope is read through the explicit `ArlineRuntime` bridge; a missing active project can no longer silently turn a UI backfill into a global backfill.
- Production document/chat chunks carry story-order/world-time metadata when the active Scene Card provides it; parent-chat fork cutoffs and ancestor-branch recorded-time cutoffs are enforced by ScopeGate.
- Source revision replacement is transactional: old evidence remains active until every new chunk/link/vector is ready and the source revision guard still matches.
- Dense generation activation verifies vector coverage, including unchanged chunks during generation rollover; dense rebuild generations are global snapshots.
- Memory receives an explicit remaining-token allocation and packs evidence inside that allocation rather than appending an unbounded block after the v1.1 context boundary.
- Background refresh failures create a visible issue/activity record, pending refreshes are cancelled on delete, and source guards prevent a late timer from resurrecting deleted/stale evidence.
- `enabled`, `fts_enabled`, `trace_enabled`, and `reranker.enabled` now control their advertised runtime behavior.
- Query routing no longer treats the mere words “scene” or “dialogue” as a continuation command; deterministic routes abstain when their required evidence lanes are empty after ScopeGate.
