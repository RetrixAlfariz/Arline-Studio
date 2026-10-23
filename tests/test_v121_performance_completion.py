from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.discovery.performance import DiscoveryExtractionPipeline
from src.discovery import physical_items as physical_items_module
from src.history.store import HistoryStore
from src.memory import MemoryConfig, MemoryQueryContext, MemoryService, MemoryStore
from src.memory.web import create_memory_router
from src.workspace import FoundationStore
from src.workspace.store import WorkspaceStore


class PerformanceFixture:
    def __init__(self, root: str):
        path = Path(root) / "arline.db"
        self.workspace = WorkspaceStore(path, backup_before_migration=False)
        self.history = HistoryStore(path, backup_before_migration=False)
        self.foundation = FoundationStore(path)
        self.project = self.workspace.create_project("Performance fixture")
        self.world_id = self.project["default_world_id"]
        self.branch = next(
            item for item in self.workspace.get_world(self.world_id)["branches"]
            if item["kind"] == "main"
        )
        store = MemoryStore(path)
        config = MemoryConfig()
        config.dense_enabled = False
        self.memory = MemoryService(
            store=store,
            workspace=self.workspace,
            history=self.history,
            foundation=self.foundation,
            config=config,
            lmstudio_base_url="http://127.0.0.1:1234",
        )
        create_memory_router(service=self.memory, store=store, foundation=self.foundation)
        self.discovery = self.memory.discovery
        self.session = self.history.create_session(
            prompt="fixture",
            project_id=self.project["id"],
            world_id=self.world_id,
            branch_id=self.branch["id"],
        )

    def context(self):
        return MemoryQueryContext(
            project_id=self.project["id"],
            world_id=self.world_id,
            branch_id=self.branch["id"],
            session_id=self.session["id"],
        )

    def turn(self, prompt: str, suffix: str = "1"):
        return self.history.add_turn(
            self.session["id"],
            run_id=f"RUN-PERF-{suffix}",
            user_prompt=prompt,
            story="Generated.",
            model="fixture-model",
            mode="smart_hybrid",
            reasoning="off",
            projection_mode="off",
        )


class V121PerformanceCompletionTests(unittest.TestCase):
    def test_discovery_uses_lightweight_extraction_not_full_reasoner(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = PerformanceFixture(td)
            self.assertIsInstance(fixture.discovery.pipeline, DiscoveryExtractionPipeline)

            def forbidden(*_args, **_kwargs):
                raise AssertionError("full analytical reasoner must not run for Discovery capture")

            fixture.discovery.pipeline.base.reasoner.analyze = forbidden
            turn = fixture.turn("Namaku Alex. Aku tinggal di Nova City.")
            report = turn.get("_discovery_report") or {}
            self.assertGreater(report.get("propositions", 0), 0)

    def test_duplicate_capture_and_materialization_are_revision_cache_hits(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = PerformanceFixture(td)
            turn = fixture.turn("Namaku Alex. Aku memakai dress hitam.")
            discovery = fixture.discovery

            def forbidden(_text):
                raise AssertionError("unchanged source must not re-run extraction")

            discovery.pipeline.run = forbidden
            report = discovery.capture_turn(turn["id"], source_kind="user_prompt")
            self.assertGreater(report.instances, 0)

            materialized = discovery.materialize_turn(turn["id"])
            self.assertTrue(materialized.get("cached"))
            metrics = discovery.performance_status()["metrics"]
            self.assertGreaterEqual(metrics["capture_hits"], 1)
            self.assertGreaterEqual(metrics["materialization_hits"], 1)

    def test_discovery_list_batches_instances_instead_of_n_plus_one(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = PerformanceFixture(td)
            fixture.turn("Namaku Alex. Alex adalah pemalu. Alex tinggal di Nova City.")

            def forbidden(*_args, **_kwargs):
                raise AssertionError("list_instances N+1 path must not be used")

            fixture.discovery.store.list_instances = forbidden
            items = fixture.discovery.list(fixture.context(), limit=100)
            self.assertTrue(items)
            self.assertTrue(all("semantics" in item for item in items))

    def test_physical_item_lookup_uses_discovery_index_not_workspace_scan(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = PerformanceFixture(td)
            fixture.turn("Namaku Alex. Aku punya dress hitam dan dress lavender.")

            def forbidden(*_args, **_kwargs):
                raise AssertionError("physical item lookup must not scan all Workspace Item families")

            fixture.workspace.list_entity_families = forbidden
            items = physical_items_module._existing_items(fixture.discovery, fixture.context())
            self.assertEqual(len(items), 2)
            self.assertEqual({item.garment_type for item in items}, {"dress"})
            self.assertEqual(
                {item.attributes.get("color") for item in items},
                {"black", "lavender"},
            )

    def test_resource_view_prefetch_avoids_per_claim_instance_queries(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = PerformanceFixture(td)
            fixture.turn("Namaku Alex. Aku memakai dress hitam. Dressnya panjang 138cm dan bahan rayon.")
            dress = next(
                family for family in fixture.workspace.list_entity_families(None, entity_type="item")
                if (family.get("shared_core") or {}).get("_discovery", {}).get("physical_item_id")
            )

            def forbidden(*_args, **_kwargs):
                raise AssertionError("resource view must use prefetched batch instances")

            fixture.discovery.store.list_instances = forbidden
            view = fixture.discovery.resource_view(dress["id"], fixture.context())
            predicates = {item["predicate"] for item in view["claims"]}
            self.assertIn("garment.color", predicates)
            self.assertIn("garment.length", predicates)
            self.assertIn("garment.material", predicates)

    def test_status_exposes_bounded_incremental_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = PerformanceFixture(td)
            status = fixture.memory.status()
            performance = status["discovery"]["performance"]
            self.assertEqual(performance["pipeline"], "lightweight_extraction")
            self.assertLessEqual(performance["startup_budget_ms"], 250)
            self.assertIn("capture_hits", performance["metrics"])
            self.assertIn("physical_item_cache_entries", performance)


if __name__ == "__main__":
    unittest.main()
