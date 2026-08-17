from __future__ import annotations

from pathlib import Path
import ast
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def save(path: str, value: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value, encoding="utf-8")


# Ensure the primary integration was applied, even if an earlier workflow raced.
app_path = ROOT / "src/interface/web/app.py"
if "/api/memory/status" not in app_path.read_text(encoding="utf-8"):
    applicator = ROOT / "tools/apply_v12_memory_foundation.py"
    if not applicator.exists():
        raise RuntimeError("Memory modules exist but the FastAPI integration was not applied")
    subprocess.run(["python", str(applicator)], cwd=ROOT, check=True)

# Re-apply idempotent finalizer if needed.
finalizer = ROOT / "tools/finalize_v12_memory_foundation.py"
if finalizer.exists():
    subprocess.run(["python", str(finalizer)], cwd=ROOT, check=True)

# Known SQL invariant: five placeholders remain after active/ready constants.
store_path = "src/memory/store.py"
store = text(store_path).replace(
    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'active','ready',?,?,?,?,?,?)",
    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'active','ready',?,?,?,?,?)",
)
save(store_path, store)

# Make eval exports safe whether the old package declared __all__ or not.
eval_path = "src/eval/__init__.py"
eval_text = text(eval_path)
if "from .memory import" in eval_text and "__all__ +=" in eval_text and "__all__ =" not in eval_text:
    eval_text = eval_text.replace("from .memory import", "__all__ = []\n\nfrom .memory import", 1)
save(eval_path, eval_text)

# FoundationStore.create_job does not need to accept presentation text at creation.
app = text("src/interface/web/app.py")
app = app.replace(
    '            payload={"project_id": payload.project_id}, message="Indexing source-backed evidence",\n',
    '            payload={"project_id": payload.project_id},\n',
)
# Pydantic v1 compatibility is cheap and keeps older environments usable.
app = app.replace("payload.model_dump()", "payload.model_dump() if hasattr(payload, 'model_dump') else payload.dict()")
save("src/interface/web/app.py", app)

# The source package must parse before dependency installation obscures syntax errors.
for source in sorted((ROOT / "src").rglob("*.py")):
    ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
for source in sorted((ROOT / "tests").rglob("*.py")):
    ast.parse(source.read_text(encoding="utf-8"), filename=str(source))

# Keep one permanent implementation note that doubles as a release checklist.
save("docs/V12_ALPHA_FOUNDATION.md", """# Arline Studio v1.2 Alpha Foundation

This document describes the first implementation milestone on `develop/v1.2`.
It is not a claim that the complete v1.2 specification is finished.

## Implemented

- SQLite source-backed `memory_chunks` and immutable provenance metadata.
- Entity/resource links from memory evidence.
- Separate FTS5 domains for manuscript, chat, summaries, and imports.
- Deterministic `QueryCompiler` and explicit `QueryPlan` execution contracts.
- Specialized routes for current state, historical state, events, spatial
  lookup, character knowledge/beliefs, story threads, causal questions,
  continuity, branch comparison, summaries, recall, and story continuation.
- Shared Scope Gate for project, world, branch ancestry, chat-fork ancestry,
  story order, Context Lens, scratch, trust, and explicit cross-scope evidence.
- Current-state and temporal-interval projections.
- Linked spatial graph for rooms, containers, items, surfaces, and placement.
- Epistemic intervals for knowledge, beliefs, suspicions, and misinformation.
- First-class story threads and resource links.
- Retrieval generations, trace records, RRF fusion, diversity limits, and
  abstention when no allowed evidence exists.
- Optional LM Studio `/v1/embeddings` provider with structured + FTS fallback.
- Incremental document/turn indexing plus explicit full-workspace backfill.
- Context Stack augmentation with selected sources and exclusion diagnostics.
- FastAPI endpoints and Developer Settings memory debugger.
- Retrieval metrics and branch/scratch/security regression tests.

## Deliberately not automatic

- No retrieved text, model result, summary, vision description, or extraction
  can commit canon.
- No sibling branch/chat fork is admitted without explicit comparison scope.
- No reranker is enabled by default.
- Dense retrieval is optional and never required for startup or correctness.
- Deep consequence simulation and autonomous branch simulation remain future
  reasoning layers.

## Required before merging to `main`

- User acceptance of UX and memory behavior.
- Real-corpus retrieval benchmarks and zero-leakage branch fixtures.
- Temporal fork-cutoff metadata beyond basic ancestor visibility.
- Production-scale index profiling and checkpoint/rebuild recovery tests.
- Remaining v1.2.1–v1.2.3 work from the research specification.
""")

print("v1.2 alpha source invariants verified")
