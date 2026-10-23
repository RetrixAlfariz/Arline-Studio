from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.history.store import HistoryStore
from src.memory import MemoryConfig, MemoryQueryContext, MemoryQueryEngine, MemoryStore, QueryCompiler, QueryRoute, ScopeGate
from src.memory.config import EmbeddingConfig
from src.memory.index import MemoryIndexer
from src.memory.models import MemoryCandidate, RetrievalLane
from src.workspace.store import WorkspaceStore


class _NoEntities:
    path = Path("__different__.db")
    def list_entity_families(self, _project=None): return []
    def list_variants(self, **_kwargs): return []
    def get_scene_card(self, _document_id): raise KeyError(_document_id)
    def get_document(self, _document_id): raise KeyError(_document_id)
    def get_branch(self, branch_id): raise KeyError(branch_id)


class _FakeEmbedding:
    model_id = "fake-e5"
    dimension = 3
    def available(self): return True
    def embed_passages(self, texts): return [[float(len(text) % 7 + 1), 1.0, 0.5] for text in texts]
    def embed_query(self, text): return [float(len(text) % 7 + 1), 1.0, 0.5]


class V120CorrectnessHardeningTests(unittest.TestCase):
    def test_bge_m3_is_default_lmstudio_embedding_profile(self):
        config = EmbeddingConfig()
        self.assertEqual(config.provider, "lmstudio")
        self.assertEqual(config.model, "text-embedding-bge-m3")
        self.assertEqual(config.dimension, 1024)
        self.assertEqual(config.query_prefix, "")
        self.assertEqual(config.passage_prefix, "")

    def test_routing_does_not_treat_scene_word_as_continue(self):
        workspace = _NoEntities()
        self.assertEqual(QueryCompiler.route("Summarize this scene"), QueryRoute.GLOBAL_SUMMARY)
        self.assertEqual(QueryCompiler.route("Where did this scene happen?"), QueryRoute.SPATIAL_LOOKUP)
        self.assertEqual(QueryCompiler.route("Continue the current scene"), QueryRoute.STORY_CONTINUE)

    def test_atomic_source_replacement_rolls_back_on_failure(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "arline.db"
            workspace = WorkspaceStore(db)
            project = workspace.create_project("Atomic")
            document = workspace.create_document(project["id"], "Scene", content="old complete revision")
            store = MemoryStore(db)
            store.upsert_chunk(source_type="document", source_id=document["id"], source_revision="old:0", text="old complete revision")
            with self.assertRaises(ValueError):
                store.replace_source_revision(
                    source_type="document", source_id=document["id"],
                    source_guard={"table": "workspace_documents", "id": document["id"], "updated_at": document["updated_at"]},
                    prepared=[{"source_revision": "new:0", "text": "first new chunk"}, {"source_revision": "new:1", "text": ""}],
                )
            active = store.list_chunks(source_type="document", source_id=document["id"], status="active")
            self.assertEqual(len(active), 1)
            self.assertEqual(active[0]["text"], "old complete revision")

    def test_real_document_index_carries_scene_order_and_blocks_future_scene(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "arline.db"
            workspace = WorkspaceStore(db)
            history = HistoryStore(db, backup_before_migration=False)
            project = workspace.create_project("Temporal")
            world_id = project["default_world_id"]
            branch = next(item for item in workspace.get_world(world_id)["branches"] if item["kind"] == "main")
            earlier = workspace.create_document(project["id"], "Earlier", content="shared clue early", world_id=world_id, branch_id=branch["id"])
            later = workspace.create_document(project["id"], "Later", content="shared clue spoiler", world_id=world_id, branch_id=branch["id"])
            earlier = workspace.update_document(earlier["id"], sort_order=1, note="test order")
            later = workspace.update_document(later["id"], sort_order=2, note="test order")
            store = MemoryStore(db)
            indexer = MemoryIndexer(store=store, workspace=workspace, history=history, config=MemoryConfig())
            indexer.index_document(earlier); indexer.index_document(later)
            rows = store.search_fts("shared clue", domains=["manuscript"], limit=10)
            by_source = {row["source_id"]: row for row in rows}
            self.assertEqual(by_source[earlier["id"]]["story_order"], 1.0)
            self.assertEqual(by_source[later["id"]]["story_order"], 2.0)
            gate = ScopeGate(workspace, history)
            candidate = MemoryQueryEngine._candidate_from_chunk(by_source[later["id"]], RetrievalLane.FTS_MANUSCRIPT, 1)
            decision = gate.evaluate(candidate, MemoryQueryContext(project_id=project["id"], world_id=world_id, branch_id=branch["id"], story_order=1, context_lens="scene"))
            self.assertFalse(decision.allowed)
            self.assertEqual(decision.rule, "story_order")

    def test_parent_chat_after_fork_is_blocked_from_real_indexed_turn(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "arline.db"
            history = HistoryStore(db, backup_before_migration=False)
            parent = history.create_session(prompt="parent", project_id="P")
            turns = []
            for i, story in enumerate(("first", "fork point", "SECRET AFTER FORK"), 1):
                turns.append(history.add_turn(parent["id"], run_id=f"R{i}", user_prompt=f"u{i}", story=story,
                                              model="m", mode="smart_hybrid", reasoning="off", projection_mode="off"))
            child = history.fork_session(parent["id"], through_turn_id=turns[1]["id"])
            workspace = _NoEntities()
            store = MemoryStore(db)
            indexer = MemoryIndexer(store=store, workspace=workspace, history=history, config=MemoryConfig())
            parent_meta = history.get_session_meta(parent["id"])
            for turn in turns:
                indexer.index_turn({**turn, "project_id": "P", "session_id": parent["id"], "scratch_mode": False})
            row = next(item for item in store.search_fts("SECRET AFTER FORK", domains=["chat"], limit=10) if item["source_id"] == turns[2]["id"])
            candidate = MemoryQueryEngine._candidate_from_chunk(row, RetrievalLane.FTS_CHAT, 1)
            decision = ScopeGate(workspace, history).evaluate(candidate, MemoryQueryContext(project_id="P", session_id=child["id"]))
            self.assertFalse(decision.allowed)
            self.assertEqual(decision.rule, "session_cutoff")
            self.assertEqual(parent_meta["id"], parent["id"])

    def test_dense_rollover_embeds_unchanged_chunks_into_new_generation(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "memory.db"
            store = MemoryStore(db)
            workspace = _NoEntities()
            class _History: path = Path(td) / "other.db"
            config = MemoryConfig(dense_enabled=True, embedding=EmbeddingConfig(enabled=True, provider="fake", model="fake-e5", dimension=3))
            indexer = MemoryIndexer(store=store, workspace=workspace, history=_History(), config=config, embedding=_FakeEmbedding())
            document = {"id": "DOC-1", "project_id": "P", "world_id": None, "branch_id": None, "title": "Dense", "content": "unchanged dense evidence", "sort_order": 1, "created_at": "2026-01-01T00:00:00+00:00", "updated_at": "2026-01-01T00:00:00+00:00"}
            # Fake workspace cannot source-guard, so provide current document for revision check.
            workspace.get_document = lambda _id: dict(document)
            g1 = store.create_generation(provider="fake", embedding_model="fake-e5", dimension=3, chunker_version=1)
            rows = indexer.index_document(document, generation_id=g1["generation_id"])
            self.assertFalse(store.vector_coverage(g1["generation_id"], [r["id"] for r in rows])["missing"])
            g2 = store.create_generation(provider="fake", embedding_model="fake-e5", dimension=3, chunker_version=1)
            rows2 = indexer.index_document(document, generation_id=g2["generation_id"])
            self.assertEqual([r["id"] for r in rows2], [r["id"] for r in rows])
            self.assertFalse(store.vector_coverage(g2["generation_id"], [r["id"] for r in rows2])["missing"])

    def test_fts_and_trace_switches_and_required_lane_abstention(self):
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(Path(td) / "memory.db")
            workspace = _NoEntities()
            config = MemoryConfig(fts_enabled=False, trace_enabled=False, dense_enabled=False)
            engine = MemoryQueryEngine(store=store, workspace=workspace, config=config)
            result = engine.execute("remember this wording", MemoryQueryContext(project_id="P", token_budget=128))
            self.assertFalse(any(lane.value.startswith("fts_") for lane in result.plan.optional_lanes + result.plan.required_lanes))
            with self.assertRaises(KeyError):
                store.get_retrieval_run(result.run_id)

            config2 = MemoryConfig(fts_enabled=True, trace_enabled=False)
            engine2 = MemoryQueryEngine(store=store, workspace=workspace, config=config2)
            store.upsert_chunk(source_type="document", source_id="DOC", text="Whereabouts are mentioned in prose", project_id="P")
            spatial = engine2.execute("Where is Vian?", MemoryQueryContext(project_id="P"))
            self.assertTrue(spatial.abstain)
            self.assertIn("Required structured evidence", spatial.abstention_reason)


if __name__ == "__main__":
    unittest.main()
