from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.history.store import HistoryStore
from src.memory import MemoryConfig, MemoryQueryContext, MemoryService, MemoryStore
from src.memory.web import create_memory_router
from src.workspace import FoundationStore
from src.workspace.store import WorkspaceStore


class V121GarmentDiscoveryTests(unittest.TestCase):
    def fixture(self, root: str):
        path = Path(root) / "arline.db"
        workspace = WorkspaceStore(path, backup_before_migration=False)
        history = HistoryStore(path, backup_before_migration=False)
        foundation = FoundationStore(path)
        project = workspace.create_project("Garment fixture")
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
        create_memory_router(service=memory, store=store, foundation=foundation)
        session = history.create_session(
            prompt="fixture",
            project_id=project["id"],
            world_id=world_id,
            branch_id=branch["id"],
        )
        context = MemoryQueryContext(
            project_id=project["id"], world_id=world_id,
            branch_id=branch["id"], session_id=session["id"],
        )
        return workspace, history, memory, project, world_id, branch, session, context

    @staticmethod
    def physical_garments(workspace):
        result = []
        for item in workspace.list_entity_families(None, entity_type="item"):
            core = item.get("shared_core") or {}
            discovery = core.get("_discovery") or {}
            if core.get("kind") == "garment" and discovery.get("physical_item_id"):
                result.append(item)
        return result

    def test_detected_garment_materializes_as_physical_item_sheet_with_garment_ontology(self):
        with tempfile.TemporaryDirectory() as td:
            workspace, history, memory, project, world_id, branch, session, context = self.fixture(td)
            history.add_turn(
                session["id"],
                run_id="RUN-GARMENT-1",
                user_prompt="Aku memakai dress hitam. Dressnya panjang 138cm dan bahan rayon.",
                story="Generated.", model="fixture-model", mode="smart_hybrid",
                reasoning="off", projection_mode="off",
            )

            garments = self.physical_garments(workspace)
            self.assertEqual(len(garments), 1)
            dress = garments[0]
            core = dress.get("shared_core") or {}
            discovery = core.get("_discovery") or {}
            self.assertEqual(core.get("kind"), "garment")
            self.assertEqual((core.get("garment") or {}).get("type"), "dress")
            self.assertEqual(discovery.get("semantic_type"), "garment")
            self.assertEqual(discovery.get("identity_model"), "physical_instance_v1")
            self.assertTrue(str(discovery.get("physical_item_id") or "").startswith("ITEM-"))
            self.assertEqual(discovery.get("subject_key"), f"item:{discovery['physical_item_id']}")

            view = memory.discovery.resource_view(dress["id"], context)
            claims = {item["predicate"]: item for item in view["claims"]}
            self.assertIn("item.kind", claims)
            self.assertIn("garment.type", claims)
            self.assertIn("garment.color", claims)
            self.assertIn("garment.length", claims)
            self.assertIn("garment.material", claims)
            self.assertEqual(claims["garment.color"]["semantics"]["group"], "garment")
            self.assertEqual(claims["garment.type"]["semantics"]["group"], "identity")
            self.assertEqual(claims["garment.material"]["value"], "rayon")

    def test_wearing_relation_points_to_physical_garment_item(self):
        with tempfile.TemporaryDirectory() as td:
            workspace, history, memory, project, world_id, branch, session, context = self.fixture(td)
            history.add_turn(
                session["id"],
                run_id="RUN-GARMENT-2",
                user_prompt="Namaku Alex. Aku memakai dress hitam.",
                story="Generated.", model="fixture-model", mode="smart_hybrid",
                reasoning="off", projection_mode="off",
            )

            garments = self.physical_garments(workspace)
            self.assertEqual(len(garments), 1)
            dress = garments[0]
            subject_key = (dress.get("shared_core") or {}).get("_discovery", {}).get("subject_key")
            characters = workspace.list_entity_families(None, entity_type="character")
            alex = next(item for item in characters if item["name"].casefold() == "alex")
            view = memory.discovery.resource_view(alex["id"], context)
            wearing = [
                item for item in view["relations"]
                if item.get("object_key") == subject_key
                and item.get("predicate") in {"wearing", "garment.wearing"}
            ]
            self.assertTrue(wearing)
            self.assertEqual(wearing[0].get("object_type"), "garment")
            self.assertTrue(str(wearing[0].get("object_key") or "").startswith("item:ITEM-"))
            self.assertEqual(dress.get("entity_type"), "item")


if __name__ == "__main__":
    unittest.main()
