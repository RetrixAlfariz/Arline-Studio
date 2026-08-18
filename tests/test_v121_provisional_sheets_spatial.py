from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.history.store import HistoryStore
from src.memory import MemoryConfig, MemoryQueryContext, MemoryService, MemoryStore
from src.memory.web import create_memory_router
from src.workspace import FoundationStore
from src.workspace.store import WorkspaceStore


class Fixture:
    def __init__(self, root: str):
        self.path = Path(root) / "arline.db"
        self.workspace = WorkspaceStore(self.path, backup_before_migration=False)
        self.history = HistoryStore(self.path, backup_before_migration=False)
        self.foundation = FoundationStore(self.path)
        self.project = self.workspace.create_project("Provisional sheet fixture")
        self.world_id = self.project["default_world_id"]
        self.branch = next(
            item for item in self.workspace.get_world(self.world_id)["branches"]
            if item["kind"] == "main"
        )
        memory_store = MemoryStore(self.path)
        config = MemoryConfig()
        config.dense_enabled = False
        self.memory = MemoryService(
            store=memory_store,
            workspace=self.workspace,
            history=self.history,
            foundation=self.foundation,
            config=config,
            lmstudio_base_url="http://127.0.0.1:1234",
        )
        router = create_memory_router(service=self.memory, store=memory_store, foundation=self.foundation)
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def session(self, *, branch_id: str | None = None):
        return self.history.create_session(
            prompt="fixture",
            project_id=self.project["id"],
            world_id=self.world_id,
            branch_id=branch_id or self.branch["id"],
        )

    def turn(self, session_id: str, prompt: str, suffix: str = "1"):
        return self.history.add_turn(
            session_id,
            run_id=f"RUN-{suffix}",
            user_prompt=prompt,
            story="Generated.",
            model="fixture-model",
            mode="smart_hybrid",
            reasoning="off",
            projection_mode="off",
        )

    def context(self, session_id: str | None = None, *, branch_id: str | None = None):
        return MemoryQueryContext(
            project_id=self.project["id"],
            world_id=self.world_id,
            branch_id=branch_id or self.branch["id"],
            session_id=session_id,
        )


class V121ProvisionalSheetSpatialTests(unittest.TestCase):
    def test_detected_entities_materialize_as_callable_draft_sheets(self):
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td)
            session = f.session()
            f.turn(session["id"], "Character Alex lives in Nova City.")

            characters = f.workspace.list_entity_families(None, entity_type="character")
            locations = f.workspace.list_entity_families(None, entity_type="location")
            alex = next(item for item in characters if item["name"] == "Alex")
            nova = next(item for item in locations if item["name"] == "Nova City")
            self.assertTrue((alex.get("shared_core") or {}).get("_discovery", {}).get("provisional"))
            self.assertTrue((nova.get("shared_core") or {}).get("_discovery", {}).get("provisional"))
            self.assertEqual(f.workspace.resolve_variant(alex["id"], f.world_id)["canon_status"], "draft")
            self.assertEqual(f.workspace.resolve_variant(nova["id"], f.world_id)["canon_status"], "draft")

            view = f.memory.discovery.resource_view(alex["id"], f.context(session["id"]))
            self.assertTrue(view["provisional"])
            self.assertTrue(any(item["operation"] == "relation" for item in view["relations"]))
            self.assertTrue(all(item["knowledge_state"] != "canon" for item in view["relations"]))

    def test_apartment_phrase_builds_type_zone_unit_and_city_without_apartment_node(self):
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td)
            session = f.session()
            prompt = "location Apartemen Puncak Dharmahusada lantai 3 unit A0325 [ukuran 56m dengan 2 kamar],surabaya"
            turn = f.turn(session["id"], prompt)
            self.assertGreater((turn.get("_discovery_report") or {}).get("propositions", 0), 0)

            locations = f.workspace.list_entity_families(None, entity_type="location")
            names = {item["name"] for item in locations}
            self.assertIn("Surabaya", names)
            self.assertIn("Puncak Dharmahusada", names)
            self.assertIn("Unit A0325", names)
            self.assertNotIn("Apartemen", names)
            self.assertNotIn("Floor 3", names)

            building = next(item for item in locations if item["name"] == "Puncak Dharmahusada")
            unit = next(item for item in locations if item["name"] == "Unit A0325")
            self.assertEqual((building.get("shared_core") or {}).get("kind"), "apartment_building")
            self.assertEqual((unit.get("shared_core") or {}).get("kind"), "apartment_unit")

            view = f.memory.discovery.resource_view(unit["id"], f.context(session["id"]))
            self.assertEqual(
                [item["label"] for item in view["spatial_path"]],
                ["Surabaya", "Puncak Dharmahusada", "Floor 3", "Unit A0325"],
            )
            values = {item["predicate"]: item["value"] for item in view["claims"]}
            self.assertEqual(values["floor_number"], 3)
            self.assertEqual(values["area_m2"], 56)
            self.assertEqual(values["room_count"], 2)
            relations = {(item["predicate"], item.get("object_label")) for item in view["relations"]}
            self.assertIn(("located_on", "Floor 3"), relations)
            self.assertIn(("part_of", "Puncak Dharmahusada"), relations)

            floor_edge = next(
                item for item in view["relations"]
                if item["predicate"] == "located_on" and item.get("object_type") == "spatial_zone"
            )
            blocked = f.client.post(
                f"/api/memory/discoveries/{floor_edge['id']}/canon",
                json={
                    "project_id": f.project["id"], "world_id": f.world_id,
                    "branch_id": f.branch["id"], "session_id": session["id"],
                },
            )
            self.assertEqual(blocked.status_code, 400)
            self.assertIn("spatial-zone", blocked.json()["detail"])

    def test_claim_values_get_change_ids_and_user_edit_is_reviewed_not_canon(self):
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td)
            session = f.session()
            f.turn(session["id"], "Character Alex became tall.", "A")
            f.turn(session["id"], "Alex became short.", "B")

            alex = next(item for item in f.workspace.list_entity_families(None, entity_type="character") if item["name"] == "Alex")
            view = f.memory.discovery.resource_view(alex["id"], f.context(session["id"]))
            state_claims = [item for item in view["claims"] if item["predicate"] == "state.form_description"]
            self.assertGreaterEqual(len(state_claims), 2)
            self.assertTrue(view["changes"])
            self.assertTrue(all(str(item["id"]).startswith("CHANGE-") for item in view["changes"]))

            latest = state_claims[-1]
            response = f.client.post(
                f"/api/memory/discoveries/{latest['id']}/edit",
                json={
                    "project_id": f.project["id"],
                    "world_id": f.world_id,
                    "branch_id": f.branch["id"],
                    "session_id": session["id"],
                    "value": "medium height",
                    "mode": "correction",
                },
            )
            self.assertEqual(response.status_code, 200)
            edited = response.json()
            self.assertEqual(edited["knowledge_state"], "reviewed")
            self.assertNotEqual(edited["knowledge_state"], "canon")

    def test_story_change_and_correction_are_distinct_operations(self):
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td)
            session = f.session()
            f.turn(session["id"], "Character Alex became tall.")
            alex = next(item for item in f.workspace.list_entity_families(None, entity_type="character") if item["name"] == "Alex")
            view = f.memory.discovery.resource_view(alex["id"], f.context(session["id"]))
            claim = next(item for item in view["claims"] if item["predicate"] == "state.form_description")

            response = f.client.post(
                f"/api/memory/discoveries/{claim['id']}/edit",
                json={
                    "project_id": f.project["id"], "world_id": f.world_id,
                    "branch_id": f.branch["id"], "session_id": session["id"],
                    "story_order": 7, "value": "short", "mode": "story_change",
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["operation"], "transition")
            refreshed = f.memory.discovery.resource_view(alex["id"], f.context(session["id"]))
            self.assertTrue(any(item["change_kind"] == "state_transition" for item in refreshed["changes"]))

    def test_branch_only_provisional_sheet_has_no_ghost_base_and_follows_lineage(self):
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td)
            branch_a = f.workspace.create_branch(
                f.world_id, "Branch A", parent_branch_id=f.branch["id"], kind="alternate"
            )
            branch_b = f.workspace.create_branch(
                f.world_id, "Branch B", parent_branch_id=f.branch["id"], kind="alternate"
            )
            branch_child = f.workspace.create_branch(
                f.world_id, "Branch A Child", parent_branch_id=branch_a["id"], kind="alternate"
            )
            session_a = f.session(branch_id=branch_a["id"])
            f.turn(session_a["id"], "Character BranchOnly lives in Nova Annex.")
            family = next(
                item for item in f.workspace.list_entity_families(None, entity_type="character")
                if item["name"] == "BranchOnly"
            )
            variants = f.workspace.list_variants(family_id=family["id"], world_id=f.world_id)
            self.assertTrue(any(item.get("branch_id") == branch_a["id"] for item in variants))
            self.assertFalse(any(item.get("branch_id") is None for item in variants))
            self.assertFalse(any(item.get("branch_id") == branch_b["id"] for item in variants))
            meta = (f.workspace.get_entity_family(family["id"]).get("shared_core") or {}).get("_discovery", {})
            self.assertEqual(meta.get("source_branch_ids"), [branch_a["id"]])

            view_a = f.memory.discovery.resource_view(family["id"], f.context(session_a["id"], branch_id=branch_a["id"]))
            self.assertTrue(view_a["claims"])
            view_child = f.memory.discovery.resource_view(family["id"], f.context(None, branch_id=branch_child["id"]))
            self.assertTrue(view_child["claims"])
            view_b = f.memory.discovery.resource_view(family["id"], f.context(None, branch_id=branch_b["id"]))
            self.assertFalse(view_b["claims"])
            self.assertFalse(view_b["relations"])


if __name__ == "__main__":
    unittest.main()
