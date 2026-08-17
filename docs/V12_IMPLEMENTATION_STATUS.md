# Arline v1.2 implementation status

**Development branch:** `develop/v1.2`  
**Package version:** `1.2.0a1`  
**Merge policy:** do not merge into `main` until the repository owner explicitly approves v1.2.

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

## Explicit v1.2.0 boundary

Dense retrieval remains optional and reranking is not required. Full world-time
interval reconstruction, mature POV knowledge continuity, autonomous summary
refresh, consequence simulation, and semantic branch merge remain later
v1.2.x/v1.3 work according to the research specification.


## v1.2.0 correctness hardening

- Memory frontend scope is read through the explicit `ArlineRuntime` bridge; a missing active project can no longer silently turn a UI backfill into a global backfill.
- Production document/chat chunks carry story-order/world-time metadata when the active Scene Card provides it; parent-chat fork cutoffs and ancestor-branch recorded-time cutoffs are enforced by ScopeGate.
- Source revision replacement is transactional: old evidence remains active until every new chunk/link/vector is ready and the source revision guard still matches.
- Dense generation activation verifies vector coverage, including unchanged chunks during generation rollover; dense rebuild generations are global snapshots.
- Memory receives an explicit remaining-token allocation and packs evidence inside that allocation rather than appending an unbounded block after the v1.1 context boundary.
- Background refresh failures create a visible issue/activity record, pending refreshes are cancelled on delete, and source guards prevent a late timer from resurrecting deleted/stale evidence.
- `enabled`, `fts_enabled`, `trace_enabled`, and `reranker.enabled` now control their advertised runtime behavior.
- Query routing no longer treats the mere words “scene” or “dialogue” as a continuation command; deterministic routes abstain when their required evidence lanes are empty after ScopeGate.
