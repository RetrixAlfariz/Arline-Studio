from __future__ import annotations

from pathlib import Path
import re
import textwrap

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + "\n", encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"Anchor missing in {path}: {old[:100]!r}")
    write(path, text.replace(old, new, 1))


def ensure_contains(path: str, marker: str, addition: str) -> None:
    text = read(path)
    if marker in text:
        return
    write(path, text.rstrip() + "\n\n" + addition.strip() + "\n")


# ---------------------------------------------------------------------------
# Version and configuration
# ---------------------------------------------------------------------------
pyproject = read("pyproject.toml")
pyproject = re.sub(r'(?m)^version\s*=\s*"[^"]+"', 'version = "1.2.0a1"', pyproject, count=1)
pyproject = pyproject.replace(
    'description = "Arline story workspace with projects, worlds, entity variants, canon workflow, WCF, LM Studio writing, and dataset feedback"',
    'description = "Branch-aware narrative memory, Library, Manuscript, Chat, and LM Studio writing workspace"',
)
write("pyproject.toml", pyproject)

config_path = "config/arline.toml"
config = read(config_path)
if "[memory]" not in config:
    config += textwrap.dedent(
        '''

        [memory]
        # v1.2 query engine. Structured lookup and FTS5 remain available even
        # when LM Studio or the embedding model is offline.
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
        # Download the recommended embedding model in LM Studio, then replace
        # this value with the exact local LM Studio model key when necessary.
        model = "intfloat/multilingual-e5-base"
        dimension = 768
        query_prefix = "query: "
        passage_prefix = "passage: "
        timeout_seconds = 120.0

        [memory.reranker]
        # Optional and intentionally disabled until an Arline benchmark proves
        # that its latency is justified. v1.2 never requires a reranker.
        enabled = false
        provider = "none"
        model = "Qwen/Qwen3-Reranker-0.6B"
        top_k_input = 20
        top_k_output = 8
        '''
    )
write(config_path, config)

# ---------------------------------------------------------------------------
# CI must continuously validate the long-lived development branch.
# ---------------------------------------------------------------------------
ci_path = ".github/workflows/ci.yml"
ci = read(ci_path)
if '"develop/**"' not in ci:
    ci = ci.replace('      - "release/**"', '      - "release/**"\n      - "develop/**"')
if "src/interface/web/static/js/memory.js" not in ci and (ROOT / "src/interface/web/static/js/memory.js").exists():
    ci = ci.replace(
        "          node --check src/interface/web/static/js/stream.js\n",
        "          node --check src/interface/web/static/js/stream.js\n          node --check src/interface/web/static/js/memory.js\n",
    )
write(ci_path, ci)

# ---------------------------------------------------------------------------
# README: manual LM Studio setup and v1.2 boundary.
# ---------------------------------------------------------------------------
readme_path = "README.md"
readme = read(readme_path)
marker = "## Arline v1.2 development branch"
if marker not in readme:
    readme += textwrap.dedent(
        '''

        ## Arline v1.2 development branch

        `develop/v1.2` is the long-lived, intentionally unmerged development
        branch for Arline's branch-aware and time-aware memory architecture.
        The implementation keeps SQLite as the authoritative source of truth,
        uses specialized structured indexes and SQLite FTS5 as the mandatory
        retrieval baseline, and treats dense retrieval as an optional LM Studio
        provider. Search indexes are disposable derivatives; they never own
        canon.

        The memory path is:

        ```text
        Prompt + Context Stack
        → deterministic query routing
        → QueryPlan / Scope Gate
        → structured state, temporal, spatial, epistemic, thread and FTS lanes
        → optional LM Studio embeddings
        → Reciprocal Rank Fusion and diversity selection
        → attributed context with inclusion/exclusion trace
        → existing Arline Run Profile
        ```

        Normal generation remains usable when embeddings are unavailable. The
        fallback is structured lookup + specialized SQLite projections + FTS5.

        ### Recommended LM Studio models

        Arline does not download or bundle model weights. Install the models in
        LM Studio as usual and select their local model keys in Settings/config.

        - **Generation / vision:** [HauhauCS Qwen3.5-4B Uncensored Aggressive](https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive)
        - **Recommended embedding baseline:** [intfloat/multilingual-e5-base](https://huggingface.co/intfloat/multilingual-e5-base)
        - **Embedding challenger, disabled by default:** [Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)
        - **Optional reranker, disabled by default:** [Qwen3-Reranker-0.6B](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B)

        The embedding model is accessed through LM Studio's OpenAI-compatible
        `/v1/embeddings` endpoint. Reranking is not required for v1.2.0 and must
        remain disabled unless retrieval evaluation demonstrates a meaningful
        improvement.

        ### v1.2 safety rules

        - Model output may create a Proposal, never commit canon.
        - Retrieved content is evidence, never executable instruction.
        - Wrong-world, wrong-branch, future, sibling-fork, scratch and
          quarantined candidates are blocked before ranking.
        - Library folders, tags, Collections, Saved Views and Gallery layout are
          organizational only and never alter truth.
        - Spatial containment and item placement are typed links, not folder
          nesting.
        - Derived summaries remain versioned caches linked to source evidence.
        '''
    )
write(readme_path, readme)

# ---------------------------------------------------------------------------
# Static v1.2 identity and cache generation.
# ---------------------------------------------------------------------------
index_path = "src/interface/web/static/index.html"
index = read(index_path)
index = index.replace("Studio v1.1", "Studio v1.2 alpha")
index = re.sub(r'v=1\.1\.3-media', 'v=1.2.0-alpha1', index)
write(index_path, index)

# ---------------------------------------------------------------------------
# Keep old one-shot workflows out of the long-lived branch.
# ---------------------------------------------------------------------------
for obsolete in (
    ".github/workflows/export-v12-source.yml",
    ".github/workflows/apply-v12-memory-foundation.yml",
    ".github/workflows/apply-v1-1-hardening.yml",
):
    path = ROOT / obsolete
    if path.exists():
        path.unlink()

# ---------------------------------------------------------------------------
# Regression test for the declared release boundary.
# ---------------------------------------------------------------------------
write(
    "tests/test_v12_release_contract.py",
    r'''
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class V12ReleaseContractTests(unittest.TestCase):
    def test_memory_package_and_query_primitives_exist(self):
        expected = {
            "models.py", "store.py", "scope.py", "query.py", "index.py",
            "retrieve.py", "temporal.py", "spatial.py", "security.py",
            "embedding.py", "service.py",
        }
        present = {path.name for path in (ROOT / "src/memory").glob("*.py")}
        self.assertTrue(expected.issubset(present), expected - present)

    def test_config_is_lmstudio_first_and_reranker_optional(self):
        config = (ROOT / "config/arline.toml").read_text(encoding="utf-8")
        self.assertIn('[memory.embedding]', config)
        self.assertIn('provider = "lmstudio"', config)
        self.assertIn('model = "intfloat/multilingual-e5-base"', config)
        self.assertIn('[memory.reranker]', config)
        self.assertIn('enabled = false', config)

    def test_readme_documents_manual_model_install(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Recommended LM Studio models", readme)
        self.assertIn("multilingual-e5-base", readme)
        self.assertIn("Reranking is not required", readme)
        self.assertIn("Search indexes are disposable derivatives", readme)

    def test_ci_tracks_develop_branch(self):
        ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        self.assertIn('"develop/**"', ci)


if __name__ == "__main__":
    unittest.main()
''',
)

# The finalizer and its workflow are one-shot build machinery.
for one_shot in (
    "tools/finalize_v12_implementation.py",
    ".github/workflows/finalize-v12-implementation.yml",
):
    path = ROOT / one_shot
    if path.exists():
        path.unlink()
