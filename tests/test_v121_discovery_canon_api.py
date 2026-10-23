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


class V121DiscoveryCanonAPITests(unittest.TestCase):
    def test_canonized_discovery_reset_and_dismiss_are_client_errors(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "arline.db"
            workspace = WorkspaceStore(path, backup_before_migration=False)
            history = HistoryStore(path, backup_before_migration=False)
            foundation = FoundationStore(path)
            project = workspace.create_project("Canon API fixture")
            world_id = project["default_world_id"]
            branch = next(
                item for item in workspace.get_world(world_id)["branches"]
                if item["kind"] == "main"
            )
            memory_store = MemoryStore(path)
            config = MemoryConfig()
            config.dense_enabled = False
            service = MemoryService(
                store=memory_store,
                workspace=workspace,
                history=history,
                foundation=foundation,
                config=config,
                lmstudio_base_url="http://127.0.0.1:1234",
            )
            app = FastAPI()
            app.include_router(
                create_memory_router(service=service, store=memory_store, foundation=foundation)
            )
            client = TestClient(app)

            session = history.create_session(
                prompt="fixture", project_id=project["id"],
                world_id=world_id, branch_id=branch["id"],
            )
            history.add_turn(
                session["id"], run_id="RUN-CANON-API",
                user_prompt="Character Alex is shy.", story="Generated.",
                model="fixture-model", mode="smart_hybrid",
                reasoning="off", projection_mode="off",
            )
            alex = next(
                item for item in workspace.list_entity_families(None, entity_type="character")
                if item["name"] == "Alex"
            )
            context = {
                "project_id": project["id"], "world_id": world_id,
                "branch_id": branch["id"], "session_id": session["id"],
            }
            view = client.get(
                f"/api/memory/discoveries/resource/entity_family/{alex['id']}",
                params=context,
            )
            self.assertEqual(view.status_code, 200)
            claim = next(
                item for item in view.json()["claims"]
                if item["predicate"] == "personality.descriptor"
            )

            promoted = client.post(
                f"/api/memory/discoveries/{claim['id']}/canon", json=context
            )
            self.assertEqual(promoted.status_code, 200)
            self.assertEqual(promoted.json()["knowledge_state"], "canon")

            for action in ("dismiss", "reset"):
                response = client.post(
                    f"/api/memory/discoveries/{claim['id']}/{action}", json=context
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("canonical", response.json()["detail"].casefold())

            self.assertEqual(
                service.discovery.store.get_proposition(claim["id"])["authority_state"],
                "canon",
            )


if __name__ == "__main__":
    unittest.main()
