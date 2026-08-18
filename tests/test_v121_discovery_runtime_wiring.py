from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.discovery.backfill import backfill_discoveries
from src.discovery.general import detect_general
from src.history.store import HistoryStore
from src.memory import MemoryConfig, MemoryQueryContext, MemoryService, MemoryStore
from src.memory.web import create_memory_router
from src.workspace import FoundationStore
from src.workspace.store import WorkspaceStore


ROOT = Path(__file__).resolve().parents[1]
MEMORY_JS = ROOT / "src/interface/web/static/js/memory.js"
DISCOVERY_WEB = ROOT / "src/discovery/web.py"


class RuntimeFixture:
    def __init__(self, root: str):
        self.path = Path(root) / "arline.db"
        self.workspace = WorkspaceStore(self.path, backup_before_migration=False)
        self.history = HistoryStore(self.path, backup_before_migration=False)
        self.foundation = FoundationStore(self.path)
        self.project = self.workspace.create_project("Discovery runtime fixture")
        self.world_id = self.project["default_world_id"]
        self.branch = next(
            item for item in self.workspace.get_world(self.world_id)["branches"]
            if item["kind"] == "main"
        )

    def session(self):
        return self.history.create_session(
            prompt="fixture",
            project_id=self.project["id"],
            world_id=self.world_id,
            branch_id=self.branch["id"],
        )

    def add_raw_turn(self, session_id: str, prompt: str, *, suffix: str = "1"):
        return self.history.add_turn(
            session_id,
            run_id=f"RUN-{suffix}",
            user_prompt=prompt,
            story="Generated surface.",
            model="fixture-model",
            mode="smart_hybrid",
            reasoning="off",
            projection_mode="off",
        )

    def attach(self):
        store = MemoryStore(self.path)
        config = MemoryConfig()
        config.dense_enabled = False
        service = MemoryService(
            store=store,
            workspace=self.workspace,
            history=self.history,
            foundation=self.foundation,
            config=config,
            lmstudio_base_url="http://127.0.0.1:1234",
        )
        router = create_memory_router(service=service, store=store, foundation=self.foundation)
        app = FastAPI()
        app.include_router(router)
        return service, TestClient(app)


class V121DiscoveryRuntimeWiringTests(unittest.TestCase):
    def test_general_detector_handles_arbitrary_named_components(self):
        candidates = detect_general(
            "Character Alex lives in Nova City. Alex is shy. "
            "Alex became a silver-haired shapeshifter."
        )
        entity_pairs = {(item.subject_type, item.subject_label) for item in candidates if item.predicate == "entity.exists"}
        predicates = {(item.subject_label, item.predicate) for item in candidates}
        self.assertIn(("character", "Alex"), entity_pairs)
        self.assertIn(("location", "Nova City"), entity_pairs)
        self.assertIn(("Alex", "personality.descriptor"), predicates)
        self.assertIn(("Alex", "state.form_description"), predicates)
        self.assertIn(("Alex", "resides_at"), predicates)

    def test_general_detector_does_not_promote_incidental_lowercase_nouns(self):
        candidates = detect_general(
            "dia duduk di ruang kecil lalu menaruh gelas di meja dekat jendela."
        )
        self.assertEqual(candidates, [])

    def test_real_history_add_turn_hook_captures_without_manual_service_call(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = RuntimeFixture(td)
            service, client = fixture.attach()
            session = fixture.session()
            turn = fixture.add_raw_turn(
                session["id"],
                "Character Alex lives in Nova City. Alex is shy. "
                "Alex became a silver-haired shapeshifter.",
            )
            report = turn.get("_discovery_report") or {}
            self.assertGreaterEqual(report.get("propositions", 0), 4)
            self.assertGreaterEqual(report.get("instances", 0), 4)

            context = MemoryQueryContext(
                project_id=fixture.project["id"],
                world_id=fixture.world_id,
                branch_id=fixture.branch["id"],
                session_id=session["id"],
            )
            discoveries = service.discovery.list(context)
            labels = {item["subject_label"] for item in discoveries}
            self.assertIn("Alex", labels)
            self.assertIn("Nova City", labels)
            self.assertTrue(all(item["knowledge_state"] != "canon" for item in discoveries))

            # The frontend deliberately recaptures idempotently to obtain a live
            # report. The endpoint must report persisted evidence, not `0` merely
            # because the backend hook already captured the same turn.
            response = client.post(f"/api/memory/discoveries/capture-turn/{turn['id']}")
            self.assertEqual(response.status_code, 200)
            live_report = response.json()
            self.assertGreaterEqual(live_report["propositions"], 4)
            self.assertGreaterEqual(live_report["instances"], 4)

    def test_existing_chat_backfill_is_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            fixture = RuntimeFixture(td)
            session = fixture.session()
            old_turn = fixture.add_raw_turn(
                session["id"],
                "Character Mira lives in Lumen City. Mira is calm.",
                suffix="OLD",
            )

            service, _client = fixture.attach()
            before = service.discovery.store.status()["instances"]
            self.assertEqual(before, 0)
            first = backfill_discoveries(service.discovery, project_id=fixture.project["id"])
            after_first = service.discovery.store.status()["instances"]
            second = backfill_discoveries(service.discovery, project_id=fixture.project["id"])
            after_second = service.discovery.store.status()["instances"]

            self.assertGreater(first.turns, 0)
            self.assertGreater(after_first, 0)
            self.assertEqual(after_first, after_second)
            self.assertGreaterEqual(second.turns, 1)
            self.assertEqual(old_turn["id"], fixture.history.get_turn(old_turn["id"])["id"])

    def test_frontend_surfaces_live_and_existing_discoveries(self):
        source = MEMORY_JS.read_text(encoding="utf-8")
        web = DISCOVERY_WEB.read_text(encoding="utf-8")
        self.assertIn("discoverySidebarBtn", source)
        self.assertIn("discoveryTurnNotice", source)
        self.assertIn("wrapGenerationFinalize", source)
        self.assertIn("refreshAfterTurn", source)
        self.assertIn("Scan existing chats", source)
        self.assertIn("/api/memory/discoveries/backfill", source)
        self.assertIn("/api/memory/discoveries/capture-turn/", source)
        self.assertIn('@router.post("/discoveries/backfill")', web)
        self.assertIn("persisted_turn_report", web)


if __name__ == "__main__":
    unittest.main()
