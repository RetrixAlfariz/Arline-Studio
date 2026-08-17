from __future__ import annotations

from pathlib import Path
import re
from textwrap import dedent

ROOT=Path(__file__).resolve().parents[1]
def read(path): return (ROOT/path).read_text(encoding="utf-8")
def write(path,text):
    target=ROOT/path; target.parent.mkdir(parents=True,exist_ok=True); target.write_text(text.rstrip()+"\n",encoding="utf-8")

required_memory={"__init__.py","models.py","config.py","store.py","scope.py","query.py","embedding.py","index.py","retrieve.py","temporal.py","spatial.py","security.py","service.py","web.py"}
present={item.name for item in (ROOT/"src/memory").glob("*.py")}
missing=required_memory-present
if missing: raise RuntimeError(f"v1.2 memory package incomplete: {sorted(missing)}")

# Keep the branch clearly identified as an alpha implementation.
path="pyproject.toml"; text=read(path); text=re.sub(r'(?m)^version\s*=\s*"[^"]+"','version = "1.2.0a1"',text,count=1); write(path,text)

# Permanent CI only.
path=".github/workflows/ci.yml"; text=read(path)
if '"develop/**"' not in text: text=text.replace('      - "release/**"','      - "release/**"\n      - "develop/**"')
if "src/interface/web/static/js/memory.js" not in text: text=text.replace("          node --check src/interface/web/static/js/stream.js\n","          node --check src/interface/web/static/js/stream.js\n          node --check src/interface/web/static/js/memory.js\n")
write(path,text)

# Ensure manual LM Studio model recommendations remain visible.
path="README.md"; text=read(path)
if "Recommended LM Studio models" not in text:
    text += dedent('''

    ## Arline v1.2 development branch

    `develop/v1.2` contains the unmerged narrative Memory Query Engine. SQLite
    owns truth; FTS5 and specialized projections are mandatory; dense retrieval
    is an optional LM Studio lane.

    ### Recommended LM Studio models

    Download models in LM Studio normally. Arline does not bundle weights.

    - [HauhauCS Qwen3.5-4B Uncensored Aggressive](https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive) — generation and vision
    - [intfloat/multilingual-e5-base](https://huggingface.co/intfloat/multilingual-e5-base) — recommended embedding baseline
    - [Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) — disabled challenger
    - [Qwen3-Reranker-0.6B](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B) — optional and disabled

    Arline calls LM Studio's `/v1/embeddings` endpoint. If dense retrieval is
    unavailable it continues with structured lookup and SQLite FTS5.
    ''')
write(path,text)

write("docs/V12_IMPLEMENTATION_STATUS.md",dedent('''
# Arline v1.2 implementation status

This document records the implementation boundary of the long-lived
`develop/v1.2` branch. It is not a release declaration and the branch must not
be merged until the owner explicitly approves it.

## Implemented foundation

- immutable `MemoryQueryContext` with project/world/branch/chat/time/POV lens;
- deterministic Query Router and Query Compiler;
- hard Scope Gate with branch, chat-fork, future, scratch and quarantine rules;
- source-backed chunks with authority, trust, provenance and semantic status;
- split FTS5 domains for Manuscript, Chat, Summary and Import evidence;
- optional LM Studio embedding provider with FTS-only fallback;
- RRF fusion, authority boosts, source diversity and token budgets;
- retrieval run traces with admitted and excluded candidates;
- specialized current-state and historical-interval projections;
- typed spatial nodes/links for rooms, containers, objects and placement;
- epistemic intervals for character knowledge/belief state;
- story-thread storage and links;
- summary, event-participant and causal-edge schema foundation;
- incremental document/chat backfill with revision checksums;
- memory API, Developer inspector, entity spatial-link section and Context
  Resolver integration;
- SQLite schema migration backup through Workspace schema v8;
- CI and regression coverage for the long-lived branch.

## Runtime topology

- Generative/vision model: LM Studio.
- Embedding model: LM Studio `/v1/embeddings`.
- Authoritative data and specialized indexes: SQLite.
- Reranker: disabled and non-required until benchmark admission.

## Still iterative inside v1.2

The foundation intentionally leaves quality tuning, benchmark admission,
complete temporal event projection, full POV continuity rules, summary
invalidation policy and large-corpus optimization for subsequent commits on the
same branch. None of those require replacing the query/scope/storage contract.

## Explicitly not v1.2

Autonomous canon writes, autonomous retcons, automatic branch merge,
consequence simulation and predictive character planning remain out of scope.
'''))

# Final contract checks.
write("tests/test_v12_reconciled_branch.py",dedent('''
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

class ReconciledBranchTests(unittest.TestCase):
    def test_status_document_and_alpha_version(self):
        self.assertTrue((ROOT/"docs/V12_IMPLEMENTATION_STATUS.md").exists())
        self.assertIn('version = "1.2.0a1"',(ROOT/"pyproject.toml").read_text(encoding="utf-8"))
    def test_no_one_shot_workflows_remain(self):
        names={item.name for item in (ROOT/".github/workflows").glob("*.yml")}
        forbidden={name for name in names if any(token in name for token in ("rebuild-v12","finalize-v12","v12-release-metadata","export-v12","apply-v12"))}
        self.assertEqual(forbidden,set())
    def test_memory_contract_is_wired(self):
        app=(ROOT/"src/interface/web/app.py").read_text(encoding="utf-8")
        html=(ROOT/"src/interface/web/static/index.html").read_text(encoding="utf-8")
        self.assertIn("register_memory_routes",app)
        self.assertIn('data-inspector-tab="memory"',html)

if __name__ == "__main__": unittest.main()
'''))

# Remove every one-shot script/workflow, including this reconciler.
for pattern in (
    "tools/rebuild_v12_memory_core.py","tools/rebuild_v12_memory_integration.py","tools/v12_memory_preflight_hotfix.py",
    "tools/v12_release_metadata_hotfix.py","tools/v12_reconcile_branch.py","tools/finalize_v12_implementation.py",
    ".github/workflows/rebuild-v12-memory.yml",".github/workflows/rebuild-v12-memory-v2.yml",
    ".github/workflows/v12-release-metadata.yml",".github/workflows/v12-reconcile.yml",
    ".github/workflows/finalize-v12-implementation.yml",".github/workflows/export-v12-source.yml",
    ".github/workflows/apply-v12-memory-foundation.yml",
):
    target=ROOT/pattern
    if target.exists(): target.unlink()
