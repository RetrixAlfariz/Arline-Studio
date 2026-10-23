from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.history.store import HistoryStore
from src.memory import MemoryConfig, MemoryService, MemoryStore
from src.memory.web import create_memory_router
from src.workspace import FoundationStore
from src.workspace.store import WorkspaceStore


class V121DiscoveryHotPathTests(unittest.TestCase):
    def fixture(self, root: str):
        path = Path(root) / "arline.db"
        workspace = WorkspaceStore(path, backup_before_migration=False)
        history = HistoryStore(path, backup_before_migration=False)
        foundation = FoundationStore(path)
        project = workspace.create_project("Hot-path fixture")
        world_id = project["default_world_id"]
        branch = next(
            item for item in workspace.get_world(world_id)["branches"]
            if item["kind"] == "main"
        )
        store = MemoryStore(path)
        config = MemoryConfig()
        config.dense_enabled = False
        memory = MemoryService(
            store=store,
            workspace=workspace,
            history=history,
            foundation=foundation,
            config=config,
            lmstudio_base_url="http://127.0.0.1:1234",
        )
        app = FastAPI()
        app.include_router(create_memory_router(service=memory, store=store, foundation=foundation))
        session = history.create_session(
            prompt="fixture",
            project_id=project["id"],
            world_id=world_id,
            branch_id=branch["id"],
        )
        return history, memory, app, session

    def test_history_add_turn_captures_once_and_report_does_not_recapture(self):
        with tempfile.TemporaryDirectory() as td:
            history, memory, app, session = self.fixture(td)
            original = memory.discovery.capture_turn
            calls = 0

            def counted(*args, **kwargs):
                nonlocal calls
                calls += 1
                return original(*args, **kwargs)

            memory.discovery.capture_turn = counted
            turn = history.add_turn(
                session["id"], run_id="RUN-HOT-1",
                user_prompt="Namaku Alex. Aku punya dress hitam.",
                story="Generated.", model="fixture-model",
                mode="smart_hybrid", reasoning="off", projection_mode="off",
            )
            self.assertEqual(calls, 1)
            self.assertGreater(turn["_discovery_report"]["propositions"], 0)

            def forbidden(*args, **kwargs):
                raise AssertionError("report-only compatibility route recaptured the turn")

            memory.discovery.capture_turn = forbidden
            client = TestClient(app)
            response = client.post(
                f"/api/memory/discoveries/capture-turn/{turn['id']}"
            )
            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertTrue(payload["persisted"])
            self.assertGreater(payload["propositions"], 0)

            report = client.get(
                f"/api/memory/discoveries/turn/{turn['id']}/report"
            )
            self.assertEqual(report.status_code, 200)
            self.assertEqual(report.json()["instances"], payload["instances"])

    def test_force_flag_remains_available_for_explicit_repair(self):
        with tempfile.TemporaryDirectory() as td:
            history, memory, app, session = self.fixture(td)
            turn = history.add_turn(
                session["id"], run_id="RUN-HOT-2",
                user_prompt="Namaku Alex.", story="Generated.",
                model="fixture-model", mode="smart_hybrid",
                reasoning="off", projection_mode="off",
            )
            original = memory.discovery.capture_turn
            calls = 0

            def counted(*args, **kwargs):
                nonlocal calls
                calls += 1
                return original(*args, **kwargs)

            memory.discovery.capture_turn = counted
            client = TestClient(app)
            response = client.post(
                f"/api/memory/discoveries/capture-turn/{turn['id']}?force=true"
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(calls, 1)


if __name__ == "__main__":
    unittest.main()
