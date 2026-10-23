from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.history.store import HistoryStore
from src.memory import MemoryConfig, MemoryQueryContext, MemoryService, MemoryStore
from src.memory.web import create_memory_router
from src.workspace import FoundationStore
from src.workspace.store import WorkspaceStore


class Fixture:
    def __init__(self, root: str):
        path = Path(root) / "arline.db"
        self.workspace = WorkspaceStore(path, backup_before_migration=False)
        self.history = HistoryStore(path, backup_before_migration=False)
        self.foundation = FoundationStore(path)
        self.project = self.workspace.create_project("Physical item fixture")
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
        self.session = self.history.create_session(
            prompt="fixture",
            project_id=self.project["id"],
            world_id=self.world_id,
            branch_id=self.branch["id"],
        )

    def turn(self, prompt: str, suffix: str):
        return self.history.add_turn(
            self.session["id"], run_id=f"RUN-PHYSICAL-{suffix}",
            user_prompt=prompt, story="Generated.", model="fixture-model",
            mode="smart_hybrid", reasoning="off", projection_mode="off",
        )

    def context(self):
        return MemoryQueryContext(
            project_id=self.project["id"], world_id=self.world_id,
            branch_id=self.branch["id"], session_id=self.session["id"],
        )

    def physical_garments(self):
        output = []
        for family in self.workspace.list_entity_families(None, entity_type="item"):
            core = family.get("shared_core") or {}
            meta = core.get("_discovery") or {}
            if core.get("kind") == "garment" and meta.get("physical_item_id"):
                output.append(family)
        return output

    @staticmethod
    def item_id(family):
        return family["shared_core"]["_discovery"]["physical_item_id"]

    @staticmethod
    def subject_key(family):
        return family["shared_core"]["_discovery"]["subject_key"]

    def color(self, family):
        view = self.memory.discovery.resource_view(family["id"], self.context())
        colors = [item for item in view["claims"] if item["predicate"] == "garment.color"]
        return [item["value"] for item in colors]


class V121PhysicalItemIdentityTests(unittest.TestCase):
    def test_two_dresses_are_two_physical_items_not_one_type_sheet(self):
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td)
            f.turn("Namaku Alex. Aku punya dress hitam dan dress lavender.", "1")
            garments = f.physical_garments()
            self.assertEqual(len(garments), 2)
            ids = {f.item_id(item) for item in garments}
            self.assertEqual(len(ids), 2)
            self.assertTrue(all(item_id.startswith("ITEM-") for item_id in ids))
            self.assertEqual(
                {item["shared_core"]["garment"]["type"] for item in garments},
                {"dress"},
            )
            colors = {value for item in garments for value in f.color(item)}
            self.assertEqual(colors, {"black", "lavender"})

    def test_explicit_quantity_creates_multiple_identical_physical_items(self):
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td)
            f.turn("Namaku Alex. Aku punya dua dress hitam.", "1")
            garments = f.physical_garments()
            self.assertEqual(len(garments), 2)
            self.assertEqual(len({f.item_id(item) for item in garments}), 2)
            self.assertTrue(all("black" in f.color(item) for item in garments))
            self.assertTrue(any("#2" in item["name"] for item in garments))

    def test_explicit_anaphora_keeps_same_item_and_records_change(self):
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td)
            f.turn("Namaku Alex. Aku memakai dress hitam. Dressnya sekarang merah.", "1")
            garments = f.physical_garments()
            self.assertEqual(len(garments), 1)
            family = garments[0]
            view = f.memory.discovery.resource_view(family["id"], f.context())
            colors = [item["value"] for item in view["claims"] if item["predicate"] == "garment.color"]
            self.assertIn("black", colors)
            self.assertIn("red", colors)
            color_changes = [item for item in view["changes"] if item["predicate"] == "garment.color"]
            self.assertTrue(color_changes)
            identity_claims = [
                item for item in view["claims"]
                if item["predicate"] == "entity.exists"
            ]
            physical_ids = {
                item["value"].get("physical_item_id")
                for item in identity_claims if isinstance(item.get("value"), dict)
            }
            self.assertEqual(physical_ids, {f.item_id(family)})

    def test_new_purchase_gets_new_item_but_later_unique_reference_reuses_it(self):
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td)
            f.turn("Namaku Alex. Aku punya dress hitam.", "1")
            f.turn("Aku membeli dress biru.", "2")
            garments = f.physical_garments()
            self.assertEqual(len(garments), 2)
            blue = next(item for item in garments if "blue" in f.color(item))
            blue_key = f.subject_key(blue)

            f.turn("Aku memakai dress biru.", "3")
            self.assertEqual(len(f.physical_garments()), 2)
            alex = next(
                item for item in f.workspace.list_entity_families(None, entity_type="character")
                if item["name"].casefold() == "alex"
            )
            view = f.memory.discovery.resource_view(alex["id"], f.context())
            wearing = [
                item for item in view["relations"]
                if item["predicate"] == "wearing" and item.get("object_key") == blue_key
            ]
            self.assertTrue(wearing)

    def test_ambiguous_reference_abstains_without_generic_or_new_item(self):
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td)
            f.turn("Namaku Alex. Aku punya dua dress hitam.", "1")
            before = {f.item_id(item) for item in f.physical_garments()}
            f.turn("Aku memakai dress hitamku.", "2")
            after = {f.item_id(item) for item in f.physical_garments()}
            self.assertEqual(after, before)
            legacy = [
                item for item in f.workspace.list_entity_families(None, entity_type="item")
                if not (item.get("shared_core") or {}).get("_discovery", {}).get("physical_item_id")
                and (item.get("shared_core") or {}).get("kind") == "garment"
            ]
            self.assertFalse(legacy)


if __name__ == "__main__":
    unittest.main()
