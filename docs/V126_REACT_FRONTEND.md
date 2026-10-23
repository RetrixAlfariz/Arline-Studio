# v1.2.6 React frontend overhaul

## Decision

Arline Studio now treats the browser UI as a first-class TypeScript application:

```text
React + TypeScript + Vite
          │
          │ HTTP / SSE
          ▼
      FastAPI / Python
          │
   ┌──────┼───────────────┐
   │      │               │
Memory  Workspace      Inference
   │      │               │
SQLite / native Rust adapters where useful
```

The migration is a frontend-framework overhaul, not a backend rewrite.

## Why

The v1.2 static frontend had grown into a large DOM-contract surface with manual
`getElementById`, event binding, state synchronization, and CSS layering. That
made each visual change increasingly coupled to runtime behavior. React/TSX
provides component ownership, typed API boundaries, composable state, and a
clear place to grow Studio without further expanding the monolithic static
runtime.

## Current React surfaces

- application shell, scope selectors, theme, and local UI state
- Home dashboard
- Chat with real SSE generation, cancellation, forks, references, slash command
  discovery, mention lookup, and context analysis
- Manuscript binder/editor with local recovery plus backend checkpoints
- Shared Library browser for entity families, variants, and relationships
- Quick Create preview/create through the existing Python inference endpoint
- Command Center driven by the backend directive registry
- Settings drawer for LM Studio/runtime, generation, context, and storage
- structured Inspector for selected resources and analysis output

## Compatibility strategy

`src/interface/react_app.py` wraps the existing FastAPI application. A built
`frontend/dist` is preferred. If it is absent, the legacy static root remains
available. This makes the migration reversible during v1.2 development while
ensuring no API or canonical data behavior is duplicated in TypeScript.

The old static UI remains only as a compatibility/recovery fallback. New UI
feature work should target `frontend/src`.

## Development contract

```powershell
# terminal 1
uv run python app.py

# terminal 2
cd frontend
npm install
npm run dev
```

Production/local integrated UI:

```powershell
cd frontend
npm install
npm run build
cd ..
uv run python app.py
```

## Repository hygiene

The following are intentionally untracked:

- `node_modules/`
- `frontend/node_modules/`
- `frontend/dist/`
- `frontend/.vite/`
- frontend coverage output
- `*.tsbuildinfo`
- npm/yarn/pnpm debug logs

CI builds from source rather than relying on generated frontend artifacts in Git.
