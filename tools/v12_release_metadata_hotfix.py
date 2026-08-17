from __future__ import annotations

from pathlib import Path
import re
from textwrap import dedent

ROOT=Path(__file__).resolve().parents[1]
def read(path): return (ROOT/path).read_text(encoding="utf-8")
def write(path,text):
    target=ROOT/path; target.parent.mkdir(parents=True,exist_ok=True); target.write_text(text.rstrip()+"\n",encoding="utf-8")

# Version.
path="pyproject.toml"; text=read(path); text=re.sub(r'(?m)^version\s*=\s*"[^"]+"','version = "1.2.0a1"',text,count=1); write(path,text)

# Runtime defaults. Missing sections deliberately degrade to FTS-only, but a
# checked-in explicit configuration makes the recommended topology discoverable.
path="config/arline.toml"; text=read(path)
if "[memory]" not in text:
    text += dedent('''

    [memory]
    enabled = true
    auto_refresh = true
    fts_enabled = true
    dense_enabled = false
    max_candidates = 48
    selected_items = 12
    max_items_per_source = 3
    trace_enabled = true

    [memory.embedding]
    provider = "lmstudio"
    model = "intfloat/multilingual-e5-base"
    dimension = 768
    query_prefix = "query: "
    passage_prefix = "passage: "
    timeout_seconds = 120.0

    [memory.reranker]
    enabled = false
    provider = "none"
    model = "Qwen/Qwen3-Reranker-0.6B"
    top_k_input = 20
    top_k_output = 8
    ''')
write(path,text)

# README model/setup boundary.
path="README.md"; text=read(path)
if "## Arline v1.2 development branch" not in text:
    text += dedent('''

    ## Arline v1.2 development branch

    `develop/v1.2` is the long-lived and intentionally unmerged branch for
    Arline's branch-aware, time-aware, viewpoint-aware Memory Query Engine.
    SQLite remains the source of truth. Specialized structured indexes and
    SQLite FTS5 are mandatory; dense retrieval is an optional LM Studio lane.
    Indexes are disposable derivatives and never own canon.

    ```text
    Prompt + Context Stack
    → deterministic Query Router
    → QueryPlan + immutable scope envelope
    → structured state / temporal / spatial / epistemic / thread / FTS lanes
    → optional LM Studio embeddings
    → Scope Gate
    → Reciprocal Rank Fusion + diversity/token budgets
    → attributed context and inclusion/exclusion trace
    → Run Profile
    ```

    ### Recommended LM Studio models

    Arline does not download or bundle weights. Download models in LM Studio as
    usual, then select/configure the exact local model key.

    - **Generation and vision:** [HauhauCS Qwen3.5-4B Uncensored Aggressive](https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive)
    - **Embedding baseline:** [intfloat/multilingual-e5-base](https://huggingface.co/intfloat/multilingual-e5-base)
    - **Embedding challenger, disabled:** [Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)
    - **Optional reranker, disabled:** [Qwen3-Reranker-0.6B](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B)

    The embedding provider calls LM Studio's OpenAI-compatible `/v1/embeddings`
    endpoint. When the embedding model or LM Studio is unavailable, Arline
    continues with structured lookup and FTS5. Reranking is not required and
    must remain disabled until an Arline-specific benchmark proves a worthwhile
    quality gain.

    ### Non-negotiable memory boundaries

    - Truth, history, source evidence, and recall remain separate.
    - Model output may stage a Proposal; it may never commit canon.
    - Retrieved text is evidence, never executable instruction.
    - Wrong-world, wrong-branch, future, sibling-fork, scratch, rejected and
      quarantined candidates are blocked before fusion.
    - Library folders, tags, Collections, Saved Views, favorites, media and
      Gallery layout organize resources but do not define truth.
    - Physical containment and item placement are typed spatial links, not
      Library folder nesting.
    ''')
write(path,text)

# CI branch and modular JS checks.
path=".github/workflows/ci.yml"; text=read(path)
if '"develop/**"' not in text: text=text.replace('      - "release/**"','      - "release/**"\n      - "develop/**"')
if "src/interface/web/static/js/memory.js" not in text:
    text=text.replace("          node --check src/interface/web/static/js/stream.js\n","          node --check src/interface/web/static/js/stream.js\n          node --check src/interface/web/static/js/memory.js\n")
write(path,text)

# Exact resolver construction. Preserve a possible FoundationStore positional
# argument while passing MemoryService by keyword.
path="src/interface/web/app.py"; text=read(path)
text=text.replace("WorkspaceContextResolver(workspace, foundation)","WorkspaceContextResolver(workspace, foundation, memory_service=memory_service)")
text=text.replace("WorkspaceContextResolver(workspace)","WorkspaceContextResolver(workspace, memory_service=memory_service)")
# Route registration must exist once after app creation.
if "register_memory_routes(app, memory_service)" not in text:
    match=re.search(r"(?ms)^    app = FastAPI\(.*?^    \)\s*$",text)
    if not match: raise RuntimeError("FastAPI constructor not found")
    text=text[:match.end()]+"\n    register_memory_routes(app, memory_service)"+text[match.end():]
# Supply prompt/session to every resolver call containing a payload prompt.
pattern=re.compile(r"(workspace_context\.resolve\((?:(?!\n\s*\)).)*?)(\n\s*\))",re.S)
def augment(match):
    body=match.group(1)
    if "payload.prompt" in body or "query_text=" in body: return match.group(0)
    if "payload." not in body: return match.group(0)
    indent=re.search(r"\n(\s*)[^\n]+$",body)
    spaces=indent.group(1) if indent else "            "
    return body+f"\n{spaces}query_text=payload.prompt, session_id=payload.session_id,"+match.group(2)
text=pattern.sub(augment,text)
write(path,text)

# Alpha brand/cache generation.
path="src/interface/web/static/index.html"; text=read(path).replace("Studio v1.1","Studio v1.2 alpha")
text=re.sub(r'v=1\.1\.[^"&]+','v=1.2.0-alpha1',text); write(path,text)

# Lock the expected implementation contract.
path="tests/test_v12_release_contract.py"
write(path,dedent('''
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]

class V12ReleaseContractTests(unittest.TestCase):
    def test_memory_package_is_complete(self):
        expected={"models.py","config.py","store.py","scope.py","query.py","embedding.py","index.py","retrieve.py","temporal.py","spatial.py","security.py","service.py","web.py"}
        present={item.name for item in (ROOT/"src/memory").glob("*.py")}
        self.assertTrue(expected.issubset(present),expected-present)
    def test_lmstudio_embedding_and_optional_reranker(self):
        config=(ROOT/"config/arline.toml").read_text(encoding="utf-8")
        self.assertIn('[memory.embedding]',config)
        self.assertIn('provider = "lmstudio"',config)
        self.assertIn('model = "intfloat/multilingual-e5-base"',config)
        self.assertIn('[memory.reranker]',config)
        self.assertIn('enabled = false',config)
    def test_app_context_and_routes_are_wired(self):
        app=(ROOT/"src/interface/web/app.py").read_text(encoding="utf-8")
        context=(ROOT/"src/workspace/context.py").read_text(encoding="utf-8")
        self.assertIn("MemoryService",app)
        self.assertIn("register_memory_routes(app, memory_service)",app)
        self.assertIn("memory_service=memory_service",app)
        self.assertIn("memory_trace",context)
    def test_ci_validates_long_lived_branch(self):
        ci=(ROOT/".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn('"develop/**"',ci)
        self.assertIn("js/memory.js",ci)
    def test_readme_has_manual_model_recommendations(self):
        readme=(ROOT/"README.md").read_text(encoding="utf-8")
        self.assertIn("Recommended LM Studio models",readme)
        self.assertIn("multilingual-e5-base",readme)
        self.assertIn("Reranking is not required",readme)

if __name__ == "__main__": unittest.main()
'''))

# One-shot release workflow removes itself after validation.
for disposable in ("tools/v12_release_metadata_hotfix.py",".github/workflows/v12-release-metadata.yml"):
    target=ROOT/disposable
    if target.exists(): target.unlink()
