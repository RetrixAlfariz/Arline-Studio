from __future__ import annotations

from pathlib import Path
from textwrap import dedent
import re

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content.rstrip() + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Lock the alpha identity without declaring the branch merged or released.
# ---------------------------------------------------------------------------
pyproject = read("pyproject.toml")
pyproject = re.sub(
    r'(?m)^version\s*=\s*"[^"]+"',
    'version = "1.2.0a1"',
    pyproject,
    count=1,
)
write("pyproject.toml", pyproject)

# Permanent CI must validate the long-lived development branch and every
# independent JavaScript module used by the memory UI.
ci_path = ".github/workflows/ci.yml"
ci = read(ci_path)
if '"develop/**"' not in ci:
    ci = ci.replace(
        '      - "release/**"',
        '      - "release/**"\n      - "develop/**"',
    )
if "src/interface/web/static/js/memory.js" not in ci:
    ci = ci.replace(
        "          node --check src/interface/web/static/js/stream.js\n",
        "          node --check src/interface/web/static/js/stream.js\n"
        "          node --check src/interface/web/static/js/memory.js\n",
    )
write(ci_path, ci)

# ---------------------------------------------------------------------------
# Canonical implementation checkpoint.
# ---------------------------------------------------------------------------
write(
    "docs/V12_IMPLEMENTATION_STATUS.md",
    dedent(
        '''
        # Arline v1.2 alpha implementation checkpoint

        **Branch:** `develop/v1.2`  
        **Version:** `1.2.0a1`  
        **Merge policy:** intentionally unmerged until the repository owner
        explicitly approves the complete v1.2 experience.

        This branch implements the functional alpha foundation described by the
        research-grounded memory specification. It does not describe Arline as
        generic RAG. SQLite owns accepted truth and history; search indexes are
        disposable evidence-selection derivatives.

        ## Implemented architecture

        ### Narrative query contract

        - immutable `MemoryQueryContext` carrying Project, World, branch, Chat
          lineage, world time, manuscript order, POV, Context Lens, explicit
          references, scratch policy, and cross-scope permissions;
        - deterministic Query Router and Query Compiler;
        - query routes for current and temporal state, events, epistemic state,
          spatial lookup, causal questions, text recall, summaries, continuity,
          branch comparison, story threads, and story continuation;
        - hard Scope Gate that rejects wrong-world, sibling-branch,
          post-fork-ancestor, sibling-chat, future, scratch, deleted, stale, and
          quarantined evidence before fusion;
        - Author, Scene, and POV lens foundations;
        - admitted and excluded candidate traces for every retrieval run.

        ### Authoritative and derived storage

        - SQLite remains the source of truth;
        - source-backed `memory_chunks` with revision, checksum, source span,
          authority, trust, semantic class/status, scope, time, and provenance;
        - `memory_links` between evidence and immutable Library resources;
        - split FTS5 domains for Manuscript, Chat, Summary, Import, Event, and
          Thread evidence, with a non-FTS fallback;
        - optional LM Studio embedding provider through `/v1/embeddings`;
        - disposable embedding vectors and verified index generations;
        - building → verified → active → retired/failed index lifecycle, where
          an incomplete generation cannot retire the active one;
        - RRF fusion, bounded authority boosts, source-diversity limits, and
          semantic/token budgets;
        - background, cancellable memory backfill jobs.

        ### Specialized indexes and Library integration

        - branch-visibility projection with manuscript-order and world-time fork
          cutoffs;
        - current-state and historical state-interval projections;
        - Project overlay projection and effective-state precedence;
        - accepted canon facts, entity-variant state, relationships, timeline
          events, participants, causal links, and story threads projected from
          the Library into specialized query lanes;
        - typed spatial nodes and edges for locations, rooms, zones, containers,
          items, surfaces, and placement;
        - spatial containment-cycle prevention, neighborhood lookup, and
          ancestor/path reconstruction;
        - epistemic intervals for what a character knows, believes, suspects,
          or falsely believes at a point in time;
        - world-time comparison that preserves incomparable or intentionally
          vague fictional time instead of guessing;
        - deterministic branch-state comparison.

        Library folders, tags, Collections, Saved Views, favorites, media, and
        Gallery layout remain organizational. They never define truth. Physical
        containment and item placement use typed spatial links instead of folder
        nesting.

        ### Safe write and review path

        - isolated LM Studio task contracts for Story Writer, Dialogue Writer,
          Structure Extractor, Memory Summarizer, Evidence Analyst, Continuity
          Explainer, Branch Comparison, and Ambiguous Query Router;
        - every task contract has `may_commit_canon = false`;
        - schema-constrained memory proposal extraction;
        - explicit Proposal → Review/Edit/Reject → Commit lifecycle;
        - reviewed commit adapters for state, accepted event, character
          knowledge/belief, story thread, and derived summary changes;
        - rejected and merely proposed records cannot commit;
        - evidence-linked summaries and stale-summary invalidation;
        - quarantine inspection and explicit trust promotion;
        - retrieved text wrapped as evidence rather than executable instruction;
        - retcon-impact preview across later state intervals, events, summaries,
          and snapshots.

        ### Continuity and analysis

        - deterministic checks for conflicting accepted facts, impossible
          simultaneous spatial placement, dangling spatial edges, and future POV
          knowledge;
        - LLM Continuity Explainer that explains an existing deterministic issue
          but cannot create, dismiss, or commit it;
        - Evidence Analyst that separates facts, inference, uncertainty, source
          IDs, and abstention;
        - evidence-backed summary proposals;
        - causal-edge and accepted-event retrieval.

        ### UI and API

        - memory status, backfill, query, trace, state-at-order,
          state-at-world-time, spatial, epistemic, thread, event, causal,
          summary, continuity, quarantine, proposal, job, retcon-impact,
          branch-compare, search, evaluation, and index-generation APIs;
        - Context Resolver integration with complete fallback to the v1.1 path if
          retrieval is disabled or fails;
        - Developer → Memory & Retrieval panel;
        - query trace, proposal review, quarantine review, index refresh, and
          benchmark controls;
        - entity Inspector sections for linked space, admitted evidence,
          accepted events, and open threads.

        ### Evaluation and safety

        - retrieval metrics for Recall@k, MRR, forbidden-source leakage,
          temporal validity, and branch isolation;
        - Arline-specific benchmark fixtures for branch, scratch, and POV/future
          isolation;
        - LongMemEval and LoCoMo case-adapter hooks;
        - large-corpus FTS smoke coverage;
        - pre-migration SQLite backup coordinated through Workspace schema 12;
        - permanent CI on `develop/**`;
        - FastAPI startup and memory-endpoint smoke tests.

        ## Runtime topology

        ```text
        LM Studio
        ├── Qwen3.5 generation / vision
        └── multilingual-e5-base embeddings

        Arline
        ├── SQLite authoritative truth/history
        ├── specialized structured projections
        ├── SQLite FTS5 evidence indexes
        ├── optional derived vectors
        ├── Scope Gate / Query Compiler / RRF
        └── Context Stack and review workflow
        ```

        Dense retrieval defaults to **disabled**. Structured lookup and FTS5 are
        always the baseline. The reranker remains optional and disabled until an
        Arline-specific benchmark demonstrates a meaningful gain within the
        configured latency/resource budget.

        ## Recommended LM Studio models

        Arline does not bundle or download model weights. Users install models in
        LM Studio normally and select the exact local key in Settings/config.

        - Generation and vision: HauhauCS Qwen3.5-4B Uncensored Aggressive
        - Embedding baseline: intfloat/multilingual-e5-base
        - Disabled embedding challenger: Qwen3-Embedding-0.6B
        - Optional disabled reranker: Qwen3-Reranker-0.6B

        ## Explicit non-goals

        The alpha does not autonomously commit canon, perform automatic retcons,
        merge branches without review, run consequence simulation, or predict
        character plans. Those remain outside this implementation boundary.

        ## Remaining work before merge

        The architecture and vertical slices are implemented. Work remaining on
        this branch is product validation and quality tuning: populate real
        long-form fixtures, benchmark candidate budgets and optional embeddings,
        refine issue rules against actual stories, profile large workspaces,
        and iterate UI wording/ergonomics. These tasks do not require replacing
        the identity/scope/time/authority/provenance contract.
        '''
    ),
)

# ---------------------------------------------------------------------------
# Permanent API smoke test. It intentionally runs with LM Studio unavailable;
# structured lookup and FTS must still start and answer safely.
# ---------------------------------------------------------------------------
write(
    "tests/test_v12_memory_api_smoke.py",
    dedent(
        r'''
        from __future__ import annotations

        from pathlib import Path
        import tempfile
        import textwrap
        import unittest

        from fastapi.testclient import TestClient

        from src.interface.web.app import create_app


        class V12MemoryApiSmokeTests(unittest.TestCase):
            def test_memory_endpoints_start_without_lmstudio(self) -> None:
                with tempfile.TemporaryDirectory() as td:
                    root = Path(td)
                    database = root / "arline.db"
                    config = root / "arline.toml"
                    config.write_text(
                        textwrap.dedent(
                            f"""
                            [lmstudio]
                            base_url = "http://127.0.0.1:1"
                            model = "missing-test-model"
                            api_key = ""
                            timeout_seconds = 0.25
                            auto_load = false

                            [model_load]
                            gpu_ratio = 1.0
                            context_length = 32768
                            flash_attention = false

                            [generation]
                            temperature = 0.8
                            top_p = 0.95
                            top_k = 40
                            min_p = 0.0
                            repeat_penalty = 1.05
                            reasoning = "off"
                            visible_output_tokens = 1024
                            reasoning_reserve_tokens = 1024
                            generation_mode = "single"
                            beat_count = 4
                            beat_tokens = 1024
                            total_story_target_tokens = 4096
                            seed = -1
                            [generation.extra]

                            [writer]
                            input_mode = "smart_hybrid"
                            system_prompt_file = "writer_system.txt"
                            story_filename = "story.txt"
                            save_request_packet = false
                            post_validate = false

                            [context_budget]
                            safety_margin = 1024
                            minimum_writer_context_tokens = 1024
                            system_prompt_token_estimate = 512

                            [reasoning_budget]
                            max_depth = 4
                            max_nodes = 200
                            min_confidence = 0.35
                            min_relevance = 0.25

                            [projection]
                            mode = "balanced"
                            min_confidence = 0.5
                            max_items = 12

                            [reasoning_runtime]
                            enforce_model_capabilities = false
                            guard_prompt_file = "reasoning_guard.txt"
                            dominance_ratio_warn = 2.0
                            reasoning_share_warn = 0.65
                            story_target_ratio_warn = 0.35

                            [artifacts]
                            output_root = "{(root / 'output').as_posix()}"
                            saved_root = "{(root / 'saved').as_posix()}"

                            [history]
                            database_path = "{database.as_posix()}"
                            dataset_root = "{(root / 'datasets').as_posix()}"
                            recent_limit = 100
                            continuity_turns = 2
                            continuity_chars = 12000
                            smart_hybrid_continuity = true

                            [workspace]
                            database_path = "{database.as_posix()}"
                            default_project_id = ""
                            context_enabled = true
                            mention_limit = 20
                            pinned_context_limit = 24
                            autosave_drafts = true
                            language_mode = "follow_prompt"

                            [memory]
                            enabled = true
                            auto_refresh = true
                            fts_enabled = true
                            dense_enabled = false
                            max_candidates = 32
                            selected_items = 8
                            max_items_per_source = 3
                            trace_enabled = true

                            [memory.embedding]
                            provider = "lmstudio"
                            model = "intfloat/multilingual-e5-base"
                            dimension = 768
                            query_prefix = "query: "
                            passage_prefix = "passage: "
                            timeout_seconds = 0.25

                            [memory.reranker]
                            enabled = false
                            provider = "none"
                            model = "Qwen/Qwen3-Reranker-0.6B"
                            top_k_input = 20
                            top_k_output = 8

                            [ui]
                            host = "127.0.0.1"
                            port = 7860
                            show_reasoning = true
                            """
                        ).strip()
                        + "\n",
                        encoding="utf-8",
                    )
                    (root / "writer_system.txt").write_text("writer", encoding="utf-8")
                    (root / "reasoning_guard.txt").write_text("guard", encoding="utf-8")

                    client = TestClient(create_app(config))
                    bootstrap = client.get("/api/workspace/bootstrap")
                    self.assertEqual(bootstrap.status_code, 200, bootstrap.text)

                    status = client.get("/api/memory/status")
                    self.assertEqual(status.status_code, 200, status.text)
                    status_data = status.json()
                    self.assertTrue(status_data["enabled"])
                    self.assertFalse(status_data["dense_enabled"])

                    profiles = client.get("/api/memory/profiles")
                    self.assertEqual(profiles.status_code, 200, profiles.text)
                    self.assertIn("structure_extractor", profiles.json()["profiles"])

                    generations = client.get("/api/memory/index-generations")
                    self.assertEqual(generations.status_code, 200, generations.text)

                    query = client.post(
                        "/api/memory/query",
                        json={
                            "query": "Where is Vian?",
                            "retrieval_mode": "debug",
                            "refresh": True,
                        },
                    )
                    self.assertEqual(query.status_code, 200, query.text)
                    query_data = query.json()
                    self.assertIn("selected", query_data)
                    self.assertIn("excluded", query_data)
                    self.assertIn("run_id", query_data)

                    trace = client.get(
                        f"/api/memory/retrieval/{query_data['run_id']}"
                    )
                    self.assertEqual(trace.status_code, 200, trace.text)

                    node = client.post(
                        "/api/memory/spatial/nodes",
                        json={
                            "resource_type": "entity_family",
                            "resource_id": "APT-TEST",
                            "label": "A0325",
                            "spatial_kind": "unit",
                        },
                    )
                    self.assertEqual(node.status_code, 200, node.text)

                    thread = client.post(
                        "/api/memory/threads",
                        json={
                            "thread_type": "promise",
                            "title": "Return the key",
                        },
                    )
                    self.assertEqual(thread.status_code, 200, thread.text)

                    proposals = client.get("/api/memory/proposals?status=proposed")
                    self.assertEqual(proposals.status_code, 200, proposals.text)

                    continuity = client.get("/api/memory/continuity")
                    self.assertEqual(continuity.status_code, 200, continuity.text)


        if __name__ == "__main__":
            unittest.main()
        '''
    ),
)

# ---------------------------------------------------------------------------
# Final source/schema/hygiene contract.
# ---------------------------------------------------------------------------
write(
    "tests/test_v12_final_checkpoint.py",
    dedent(
        r'''
        from __future__ import annotations

        from pathlib import Path
        import unittest

        from src.memory.store import MEMORY_SCHEMA_VERSION
        from src.workspace.foundation import FoundationStore
        from src.workspace.store import WORKSPACE_SCHEMA_VERSION


        ROOT = Path(__file__).resolve().parents[1]


        class V12FinalCheckpointTests(unittest.TestCase):
            def test_version_and_schema_contract(self) -> None:
                pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
                self.assertIn('version = "1.2.0a1"', pyproject)
                self.assertEqual(WORKSPACE_SCHEMA_VERSION, 12)
                self.assertEqual(FoundationStore.SCHEMA_VERSION, 12)
                self.assertEqual(MEMORY_SCHEMA_VERSION, 5)

            def test_required_memory_modules_exist(self) -> None:
                required = {
                    "analysis.py",
                    "config.py",
                    "continuity.py",
                    "embedding.py",
                    "index.py",
                    "inference.py",
                    "jobs.py",
                    "models.py",
                    "profiles.py",
                    "proposals.py",
                    "query.py",
                    "retcon.py",
                    "retrieve.py",
                    "scope.py",
                    "security.py",
                    "service.py",
                    "spatial.py",
                    "store.py",
                    "temporal.py",
                    "time.py",
                    "web.py",
                }
                present = {
                    path.name for path in (ROOT / "src" / "memory").glob("*.py")
                }
                self.assertTrue(required.issubset(present), required - present)

            def test_only_permanent_workflows_remain(self) -> None:
                names = {
                    path.name
                    for path in (ROOT / ".github" / "workflows").glob("*.yml")
                }
                forbidden_tokens = (
                    "apply-v12",
                    "export-v12",
                    "finalize-v12",
                    "rebuild-v12",
                    "v12-complete",
                    "v12-final",
                    "v12-project",
                    "v12-reconcile",
                    "v12-release",
                )
                temporary = {
                    name
                    for name in names
                    if any(token in name for token in forbidden_tokens)
                }
                self.assertEqual(temporary, set())
                self.assertIn("ci.yml", names)

            def test_no_one_shot_v12_tools_remain(self) -> None:
                temporary = {
                    path.name
                    for path in (ROOT / "tools").glob("*v12*.py")
                }
                self.assertEqual(temporary, set())

            def test_documentation_records_unmerged_alpha_boundary(self) -> None:
                status = (ROOT / "docs" / "V12_IMPLEMENTATION_STATUS.md").read_text(
                    encoding="utf-8"
                )
                self.assertIn("intentionally unmerged", status)
                self.assertIn("Proposal → Review/Edit/Reject → Commit", status)
                self.assertIn("Structured lookup and FTS5", status)
                self.assertIn("reranker remains optional and disabled", status)


        if __name__ == "__main__":
            unittest.main()
        '''
    ),
)

# Remove every known one-shot v1.2 script and workflow, including this one.
for disposable in (
    "tools/finalize_v12_implementation.py",
    "tools/rebuild_v12_memory_core.py",
    "tools/rebuild_v12_memory_integration.py",
    "tools/v12_complete_eval_performance.py",
    "tools/v12_complete_review_pipeline.py",
    "tools/v12_complete_temporal_analysis.py",
    "tools/v12_complete_vertical_slice.py",
    "tools/v12_final_checkpoint.py",
    "tools/v12_memory_preflight_hotfix.py",
    "tools/v12_project_library_truth.py",
    "tools/v12_reconcile_branch.py",
    "tools/v12_release_metadata_hotfix.py",
    ".github/workflows/apply-v12-memory-foundation.yml",
    ".github/workflows/export-v12-source.yml",
    ".github/workflows/finalize-v12-implementation.yml",
    ".github/workflows/rebuild-v12-memory-v2.yml",
    ".github/workflows/rebuild-v12-memory.yml",
    ".github/workflows/v12-complete-eval-performance.yml",
    ".github/workflows/v12-complete-review-pipeline.yml",
    ".github/workflows/v12-complete-temporal-analysis.yml",
    ".github/workflows/v12-complete-vertical-slice.yml",
    ".github/workflows/v12-final-checkpoint.yml",
    ".github/workflows/v12-project-library-truth.yml",
    ".github/workflows/v12-reconcile.yml",
    ".github/workflows/v12-release-metadata.yml",
):
    target = ROOT / disposable
    if target.exists():
        target.unlink()
