# Arline Architecture Hardening

This document records the integration boundaries introduced during the v1.2.2 hardening pass. The goal is not to redesign Arline's narrative model; it is to make the existing Canon, Memory, Discovery, and Continuity model easier to reason about and safer to extend.

## 1. Authority first, derived state second

Workspace, History, and explicit Canon workflows own authoritative user state. Memory indexes, Discovery propositions, temporal projections, and Continuity graphs are derived and rebuildable.

An authoritative operation follows this order:

```text
validate
  ↓
authoritative transaction
  ↓
COMMIT
  ↓
DomainEvent
  ↓
Memory / Discovery / Continuity / Activity handlers
```

A derived handler failure must never roll back a committed user edit. Derived failures are reported through their subsystem diagnostics and may be rebuilt later.

## 2. Domain events instead of method replacement

Derived subsystems must not replace methods on `HistoryStore`, `WorkspaceStore`, or `FoundationStore` at runtime. Cross-domain reactions use the per-database event bus in `src/domain_events.py`.

Current post-commit events include:

- `history.turn_created`
- `history.feedback_changed`
- `history.session_deleted`
- `history.scope_deleted`
- `foundation.resource_trashed`
- `foundation.resource_restored`
- `workspace.timeline_event_created`

Subscriptions use stable keys so repeated application/router construction replaces the same subscription instead of multiplying side effects. History and Workspace may use different database files, so consumers subscribe to the bus that owns each authoritative source rather than assuming the default single-database layout.

## 3. Persistence ownership

Schema creation belongs to stores, not reasoners or resolvers.

- `WorkspaceStore` owns Workspace schema.
- `HistoryStore` owns History schema.
- `MemoryStore` owns Memory schema.
- `DiscoveryStore` owns Discovery and derived Continuity tables.
- `ContinuityResolver` reads/writes continuity state but does not create tables.

Application startup computes one pre-migration SQLite backup boundary for every schema family sharing the configured database. Stores that initialize through that application boundary skip duplicate backups; the same stores retain their standalone backup hooks when used independently.

## 4. Frontend module boundary

`stream.js` is transport-only. It parses the streaming response and exports `ArlineStream.consume`; it does not repair UI state, fabricate DOM nodes, load feature scripts, or provide missing lexical variables.

There is no runtime compatibility prelude. Bulk Library Trash/Undo belongs to the main Library UI owner, while Quick Create and Discovery sheets are explicit deferred scripts in `index.html`.

Feature modules obtain the active workspace scope through the read-only `window.ArlineRuntime` bridge rather than reaching into the main script's lexical `state` object or depending on hidden compatibility controls.

## 5. Credential transport and remote bind safety

Transient LM Studio credentials are accepted through `POST /api/models/query`, not URL query parameters. The legacy `GET /api/models` route may use server location information but does not accept an API key.

Arline remains local-first. `launch_ui()` accepts loopback hosts by default. Binding the unauthenticated UI to a non-loopback address requires the explicit environment override:

```text
ARLINE_ALLOW_UNAUTHENTICATED_REMOTE_UI=1
```

This override is intentionally noisy: it acknowledges that the current FastAPI surface is not an authenticated multi-user service.

## 6. Version contract

`src/version.py`, `pyproject.toml`, and `uv.lock` represent one development version contract. The v1.2.2 hardening baseline is `1.2.2a1`.

## 7. CI contract

Permanent CI validates two environments:

1. Python 3.11 with floating compatible dependencies, to detect upstream compatibility regressions.
2. Python 3.13 with the frozen `uv.lock`, to prove the declared local environment is reproducible.

Both run the full regression suite, Python compilation, JavaScript syntax checks, the Memory runtime smoke test, and diff hygiene. Temporary applicators/workflows, frontend compatibility shims, and stale v1.1 hardening workflows are rejected by repository hygiene.

## 8. What this does not change

The following architectural principles remain intact:

- retrieved evidence is not Canon;
- Discovery is provenance, not authority;
- Continuity is a derived interpretation and may abstain;
- sibling branch and chat-fork scope isolation remains enforced;
- explicit user promotion is required for Canon;
- derived indexes may be rebuilt from authoritative source state.

Future v1.2.2 entity resolution, cross-turn coreference, event causality, and Continuity UI work should build through these boundaries rather than reintroducing lifecycle monkey patches.
