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
- optional LM Studio `multilingual-e5-base` embedding provider;
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

## Explicit v1.2.0 boundary

Dense retrieval remains optional and reranking is not required. Full world-time
interval reconstruction, mature POV knowledge continuity, autonomous summary
refresh, consequence simulation, and semantic branch merge remain later
v1.2.x/v1.3 work according to the research specification.
