from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.workspace.store import WorkspaceStore


class BranchRetconScopeTests(unittest.TestCase):
    """Regression coverage for the scope boundaries of branch and retcon writes."""

    @staticmethod
    def _fixture(root: str):
        store = WorkspaceStore(Path(root) / "arline.db", backup_before_migration=False)
        project = store.create_project("Scope safety")
        first = store.create_world(project["id"], "First world")
        second = store.create_world(project["id"], "Second world")
        first_main = next(b for b in store.list_branches(first["id"]) if b["kind"] == "main")
        second_main = next(b for b in store.list_branches(second["id"]) if b["kind"] == "main")
        return store, project, first, second, first_main, second_main

    def test_branch_creation_rejects_foreign_or_missing_parent(self):
        with tempfile.TemporaryDirectory() as td:
            store, _, first, _, first_main, second_main = self._fixture(td)
            before = len(store.list_branches(first["id"]))
            with self.assertRaisesRegex(ValueError, "same world"):
                store.create_branch(
                    first["id"], "Foreign parent",
                    parent_branch_id=second_main["id"],
                )
            with self.assertRaisesRegex(ValueError, "does not exist"):
                store.create_branch(
                    first["id"], "Missing parent",
                    parent_branch_id="BRANCH-NONEXISTENT",
                )
            self.assertEqual(len(store.list_branches(first["id"])), before)
            child = store.create_branch(
                first["id"], "Safe child", parent_branch_id=first_main["id"]
            )
            self.assertEqual(child["parent_branch_id"], first_main["id"])

    def test_main_identity_is_not_mutable_via_branch_api(self):
        with tempfile.TemporaryDirectory() as td:
            store, _, first, _, main, _ = self._fixture(td)
            child = store.create_branch(
                first["id"], "Sandbox", parent_branch_id=main["id"]
            )
            with self.assertRaisesRegex(ValueError, "created with worlds"):
                store.create_branch(first["id"], "Second main", kind="main")
            with self.assertRaisesRegex(ValueError, "to or from Main"):
                store.update_branch(main["id"], kind="sandbox")
            with self.assertRaisesRegex(ValueError, "to or from Main"):
                store.update_branch(child["id"], kind="main")
            updated = store.update_branch(child["id"], kind="what_if", name="What if")
            self.assertEqual(updated["kind"], "what_if")
            self.assertEqual(updated["name"], "What if")
            self.assertEqual(
                len([b for b in store.list_branches(first["id"]) if b["kind"] == "main"]),
                1,
            )
            self.assertEqual(store.get_branch(main["id"])["kind"], "main")

    def test_retcon_mutates_only_exact_branch_not_main_sibling_or_other_world(self):
        with tempfile.TemporaryDirectory() as td:
            store, project, first, second, first_main, _ = self._fixture(td)
            alt = store.create_branch(first["id"], "Alternate", parent_branch_id=first_main["id"])
            sibling = store.create_branch(first["id"], "Sibling", parent_branch_id=first_main["id"])
            family = store.create_entity_family(None, "Nafila", entity_type="character")
            common = dict(project_id=project["id"], owner_type="entity_family",
                          owner_id=family["id"], path="temperament")
            old_main = store.add_fact(project["id"], "entity_family", family["id"],
                                      "temperament", "quiet", world_id=first["id"], status="canon")
            old_alt = store.add_fact(project["id"], "entity_family", family["id"],
                                     "temperament", "curious", world_id=first["id"],
                                     branch_id=alt["id"], status="canon")
            old_sibling = store.add_fact(project["id"], "entity_family", family["id"],
                                         "temperament", "bold", world_id=first["id"],
                                         branch_id=sibling["id"], status="canon")
            old_other = store.add_fact(project["id"], "entity_family", family["id"],
                                       "temperament", "patient", world_id=second["id"],
                                       status="canon")
            new_fact = store.apply_retcon(
                project_id=project["id"], world_id=first["id"], branch_id=alt["id"],
                owner_type="entity_family", owner_id=family["id"],
                path="temperament", new_value="thoughtful",
            )
            self.assertEqual(new_fact["branch_id"], alt["id"])
            self.assertEqual(new_fact["status"], "canon")
            self.assertEqual(store.get_fact(old_alt["id"])["status"], "retconned")
            for fact in (old_main, old_sibling, old_other):
                self.assertEqual(store.get_fact(fact["id"])["status"], "canon")
            preview = store.retcon_preview(
                project_id=project["id"], world_id=first["id"], branch_id=alt["id"],
                owner_type="entity_family", owner_id=family["id"],
                path="temperament", new_value="kind",
            )
            visible = {fact["id"] for fact in preview["current_facts"]}
            self.assertIn(old_main["id"], visible)
            self.assertIn(new_fact["id"], visible)
            self.assertNotIn(old_sibling["id"], visible)
            self.assertNotIn(old_other["id"], visible)
            self.assertNotIn(old_alt["id"], visible)

    def test_main_retcon_normalizes_main_id_and_does_not_touch_alternate(self):
        with tempfile.TemporaryDirectory() as td:
            store, project, first, second, first_main, _ = self._fixture(td)
            alt = store.create_branch(first["id"], "Else", parent_branch_id=first_main["id"])
            family = store.create_entity_family(None, "Vian", entity_type="character")
            old_main = store.add_fact(project["id"], "entity_family", family["id"],
                                      "trait", "old", world_id=first["id"], status="canon")
            old_alt = store.add_fact(project["id"], "entity_family", family["id"],
                                     "trait", "other", world_id=first["id"],
                                     branch_id=alt["id"], status="canon")
            old_other_world = store.add_fact(project["id"], "entity_family", family["id"],
                                             "trait", "elsewhere", world_id=second["id"],
                                             status="canon")
            new_fact = store.apply_retcon(
                project_id=project["id"], world_id=first["id"], branch_id=first_main["id"],
                owner_type="entity_family", owner_id=family["id"],
                path="trait", new_value="new",
            )
            self.assertIsNone(new_fact["branch_id"])
            self.assertEqual(store.get_fact(old_main["id"])["status"], "retconned")
            self.assertEqual(store.get_fact(old_alt["id"])["status"], "canon")
            self.assertEqual(store.get_fact(old_other_world["id"])["status"], "canon")
            preview = store.retcon_preview(
                project_id=project["id"], world_id=first["id"],
                branch_id=first_main["id"], owner_type="entity_family",
                owner_id=family["id"], path="trait", new_value="newer",
            )
            self.assertEqual([item["id"] for item in preview["current_facts"]], [new_fact["id"]])

    def test_cross_world_retcon_branch_rejected_without_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            store, project, first, _, _, second_main = self._fixture(td)
            family = store.create_entity_family(None, "Alex", entity_type="character")
            initial = store.add_fact(project["id"], "entity_family", family["id"],
                                     "mood", "calm", world_id=first["id"], status="canon")
            request = dict(
                project_id=project["id"], world_id=first["id"],
                branch_id=second_main["id"], owner_type="entity_family",
                owner_id=family["id"], path="mood", new_value="angry",
            )
            with self.assertRaisesRegex(ValueError, "different world"):
                store.apply_retcon(**request)
            with self.assertRaisesRegex(ValueError, "different world"):
                store.retcon_preview(**request)
            self.assertEqual(store.get_fact(initial["id"])["status"], "canon")
            facts = store.list_facts(
                project_id=project["id"], world_id=first["id"],
                owner_type="entity_family", owner_id=family["id"],
            )
            self.assertEqual(len(facts), 1)


if __name__ == "__main__":
    unittest.main()
