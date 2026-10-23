from __future__ import annotations

import re
import sqlite3
import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from src.interface.web.app import create_app
from src.history.store import HistoryStore
from src.workspace import FoundationStore, WORLD_BIBLE_PROJECT_ID, WorkspaceStore


ROOT = Path(__file__).resolve().parents[1]


class FolderIntegrityTests(unittest.TestCase):
    @contextmanager
    def _db(self):
        con = sqlite3.connect(self.db)
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "data" / "studio.db"
        source = (ROOT / "config" / "arline.toml").read_text(encoding="utf-8")
        source = re.sub(r'(?m)^database_path\s*=.*$', f'database_path = "{self.db.as_posix()}"', source)
        source = re.sub(r'(?m)^dataset_root\s*=.*$', f'dataset_root = "{(self.root / "datasets").as_posix()}"', source)
        source = re.sub(r'(?m)^output_root\s*=.*$', f'output_root = "{(self.root / "output").as_posix()}"', source)
        source = re.sub(r'(?m)^saved_root\s*=.*$', f'saved_root = "{(self.root / "output" / "saved").as_posix()}"', source)
        self.config = self.root / "arline.toml"
        self.config.write_text(source, encoding="utf-8")
        self.store = WorkspaceStore(self.db, backup_before_migration=False)
        self.project = self.store.create_project("One")
        self.other = self.store.create_project("Two")
        self.clients = []

    def _client(self):
        client = TestClient(create_app(self.config))
        self.clients.append(client)
        return client

    def tearDown(self):
        for client in self.clients:
            client.close()
        self.temp.cleanup()

    def test_create_and_move_reject_invalid_parents_and_roll_back(self):
        root = self.store.create_folder(self.project["id"], "Root")
        child = self.store.create_folder(self.project["id"], "Child", parent_id=root["id"])
        with self.assertRaises(ValueError):
            self.store.create_folder(self.project["id"], "Missing", parent_id="missing")
        with self.assertRaises(ValueError):
            self.store.create_folder(self.project["id"], "Cross", parent_id=self.store.create_folder(self.other["id"], "Other")["id"])
        with self.assertRaises(ValueError):
            self.store.update_folder(root["id"], parent_id=root["id"])
        with self.assertRaises(ValueError):
            self.store.update_folder(root["id"], parent_id=child["id"])
        self.assertIsNone(self.store.get_folder(root["id"])["parent_id"])
        self.store.update_folder(child["id"], parent_id=None)
        self.assertIsNone(self.store.get_folder(child["id"])["parent_id"])

    def test_tree_preserves_healthy_rows_and_terminates_on_corrupt_cycle_or_orphan(self):
        healthy = self.store.create_folder(self.project["id"], "Healthy")
        with self._db() as con:
            con.execute("PRAGMA foreign_keys=OFF")
            now = "2026-01-01T00:00:00Z"
            con.execute(
                "INSERT INTO workspace_folders VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("ORPHAN", self.project["id"], None, None, "NO_PARENT", "Orphan", "mixed", 0, now, now),
            )
            con.execute(
                "INSERT INTO workspace_folders VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("CYCLE_A", self.project["id"], None, None, "CYCLE_B", "A", "mixed", 0, now, now),
            )
            con.execute(
                "INSERT INTO workspace_folders VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("CYCLE_B", self.project["id"], None, None, "CYCLE_A", "B", "mixed", 0, now, now),
            )
        tree = self.store.folder_tree(self.project["id"])
        ids = {row["id"] for row in tree}
        self.assertIn(healthy["id"], ids)
        self.assertNotIn("ORPHAN", ids)
        self.assertNotIn("CYCLE_A", ids)
        self.assertNotIn("CYCLE_B", ids)
        rows = {row["id"] for row in self.store.list_folders(self.project["id"])}
        self.assertTrue({"ORPHAN", "CYCLE_A", "CYCLE_B"}.issubset(rows))

    def test_delete_legacy_cycle_terminates_and_does_not_cross_project(self):
        root = self.store.create_folder(self.project["id"], "Root")
        foreign = self.store.create_folder(self.other["id"], "Foreign")
        with self._db() as con:
            con.execute("PRAGMA foreign_keys=OFF")
            now = "2026-01-01T00:00:00Z"
            con.execute(
                "INSERT INTO workspace_folders VALUES(?,?,?,?,?,?,?,?,?,?)",
                ("BAD_CHILD", self.project["id"], None, None, "BAD_CHILD", "Bad", "mixed", 0, now, now),
            )
            con.execute("UPDATE workspace_folders SET parent_id=? WHERE id=?", (root["id"], "BAD_CHILD"))
            con.execute("UPDATE workspace_folders SET parent_id=? WHERE id=?", (root["id"], root["id"]))
            # A corrupt cross-project child must be detached and preserved.
            con.execute("UPDATE workspace_folders SET parent_id=? WHERE id=?", (root["id"], foreign["id"]))
        deleted = self.store.delete_folder(root["id"])
        self.assertIn(root["id"], deleted)
        self.assertIsNone(self.store.get_folder(foreign["id"])["parent_id"])
        with self.assertRaises(KeyError):
            self.store.get_folder("BAD_CHILD")

    def test_delete_rolls_back_parent_detach_and_resource_refs_on_cleanup_error(self):
        root = self.store.create_folder(self.project["id"], "Rollback")
        foreign = self.store.create_folder(self.other["id"], "Foreign")
        document = self.store.create_document(self.project["id"], "Keep", folder_id=root["id"])
        with self._db() as con:
            con.execute("PRAGMA foreign_keys=OFF")
            con.execute("UPDATE workspace_folders SET parent_id=? WHERE id=?", (root["id"], foreign["id"]))

        def fail_cleanup(*args, **kwargs):
            raise RuntimeError("injected cleanup failure")

        original = self.store._purge_resource_refs_tx
        self.store._purge_resource_refs_tx = fail_cleanup
        try:
            with self.assertRaises(RuntimeError):
                self.store.delete_folder(root["id"])
        finally:
            self.store._purge_resource_refs_tx = original
        self.assertEqual(self.store.get_folder(foreign["id"])["parent_id"], root["id"])
        self.assertEqual(self.store.get_document(document["id"])["folder_id"], root["id"])
        self.assertIsNotNone(self.store.get_folder(root["id"]))

    def test_api_rejects_bad_parents_and_invalid_folder_ownership(self):
        client = self._client()
        a = client.post("/api/projects", json={"name": "API One"}).json()
        b = client.post("/api/projects", json={"name": "API Two"}).json()
        parent = client.post("/api/folders", json={"project_id": a["id"], "name": "Parent"}).json()
        foreign = client.post("/api/folders", json={"project_id": b["id"], "name": "Foreign"}).json()
        self.assertEqual(client.patch(f"/api/folders/{parent['id']}", json={"parent_id": foreign["id"]}).status_code, 400)
        self.assertEqual(client.patch(f"/api/folders/{parent['id']}", json={"parent_id": "missing"}).status_code, 400)
        self.assertEqual(client.patch("/api/folders/missing", json={"name": "x"}).status_code, 404)
        doc = client.post("/api/documents", json={"project_id": a["id"], "title": "Doc", "folder_id": foreign["id"]})
        self.assertEqual(doc.status_code, 400)

    def test_api_null_parent_and_folder_clear(self):
        client = self._client()
        project = client.post("/api/projects", json={"name": "API"}).json()
        folder = client.post("/api/folders", json={"project_id": project["id"], "name": "Folder"}).json()
        child = client.post("/api/folders", json={"project_id": project["id"], "name": "Child", "parent_id": folder["id"]}).json()
        detached = client.patch(f"/api/folders/{child['id']}", json={"parent_id": None})
        self.assertEqual(detached.status_code, 200)
        self.assertIsNone(detached.json()["parent_id"])
        document = client.post("/api/documents", json={"project_id": project["id"], "title": "Doc", "folder_id": folder["id"]}).json()
        cleared = client.patch(f"/api/documents/{document['id']}", json={"folder_id": None})
        self.assertEqual(cleared.status_code, 200)
        self.assertIsNone(cleared.json()["folder_id"])
        invalid = client.patch(f"/api/documents/{document['id']}", json={"content": "changed", "folder_id": "missing"})
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(client.get(f"/api/documents/{document['id']}").json()["content"], "")

    def test_deep_chain_reads_are_bounded(self):
        now = "2026-01-01T00:00:00Z"
        with self._db() as con:
            con.execute("PRAGMA foreign_keys=OFF")
            parent = None
            for index in range(1005):
                ident = f"DEEP_{index}"
                con.execute(
                    "INSERT INTO workspace_folders VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (ident, self.project["id"], None, None, parent, ident, "mixed", 0, now, now),
                )
                parent = ident
        tree = self.store.folder_tree(self.project["id"])
        self.assertEqual(len(tree), 1)
        depth = 0
        current = tree
        while current:
            depth += 1
            current = current[0].get("children", [])
        self.assertLessEqual(depth, 100)

    def test_create_depth_limit_and_move_subtree_rollback(self):
        parent = self.store.create_folder(self.project["id"], "Parent")
        parent_child = self.store.create_folder(self.project["id"], "Parent child", parent_id=parent["id"])
        chain_root = self.store.create_folder(self.project["id"], "Chain")
        current = chain_root
        for index in range(99):
            current = self.store.create_folder(self.project["id"], str(index), parent_id=current["id"])
        with self.assertRaises(ValueError):
            self.store.update_folder(chain_root["id"], parent_id=parent_child["id"])
        self.assertIsNone(self.store.get_folder(chain_root["id"])["parent_id"])
        with self.assertRaises(ValueError):
            self.store.create_folder(self.project["id"], "Too deep", parent_id=current["id"])

    def test_deep_legacy_delete_finishes(self):
        now = "2026-01-01T00:00:00Z"
        with self._db() as con:
            con.execute("PRAGMA foreign_keys=OFF")
            parent = None
            for index in range(1005):
                ident = f"DELETE_DEEP_{index}"
                con.execute(
                    "INSERT INTO workspace_folders VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (ident, self.project["id"], None, None, parent, ident, "mixed", 0, now, now),
                )
                parent = ident
        deleted = self.store.delete_folder("DELETE_DEEP_0")
        self.assertEqual(len(deleted), 1005)
        self.assertEqual(self.store.list_folders(self.project["id"]), [])

    def test_deep_chain_project_tree_is_bounded_and_serializable(self):
        now = "2026-01-01T00:00:00Z"
        with self._db() as con:
            con.execute("PRAGMA foreign_keys=OFF")
            parent = None
            for index in range(1005):
                ident = f"API_DEEP_{index}"
                con.execute(
                    "INSERT INTO workspace_folders VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (ident, self.project["id"], None, None, parent, ident, "mixed", 0, now, now),
                )
                parent = ident
        client = self._client()
        response = client.get(f"/api/projects/{self.project['id']}/tree")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(response.json()["folders"]), 100)

    def test_corrupt_project_and_library_paths_are_safe_and_repairable(self):
        healthy = self.store.create_folder(self.project["id"], "Healthy")
        library_healthy = self.store.create_folder(WORLD_BIBLE_PROJECT_ID, "Library healthy")
        now = "2026-01-01T00:00:00Z"
        with self._db() as con:
            con.execute("PRAGMA foreign_keys=OFF")
            for prefix, project_id in (("P", self.project["id"]), ("L", WORLD_BIBLE_PROJECT_ID)):
                con.execute(
                    "INSERT INTO workspace_folders VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (f"{prefix}_ORPHAN", project_id, None, None, f"{prefix}_MISSING", f"{prefix} orphan", "mixed", 0, now, now),
                )
                con.execute(
                    "INSERT INTO workspace_folders VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (f"{prefix}_A", project_id, None, None, f"{prefix}_B", f"{prefix} A", "mixed", 0, now, now),
                )
                con.execute(
                    "INSERT INTO workspace_folders VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (f"{prefix}_B", project_id, None, None, f"{prefix}_A", f"{prefix} B", "mixed", 0, now, now),
                )
        client = self._client()
        project_tree = client.get(f"/api/projects/{self.project['id']}/tree")
        bible_tree = client.get("/api/world-bible")
        self.assertEqual(project_tree.status_code, 200, project_tree.text)
        self.assertEqual(bible_tree.status_code, 200, bible_tree.text)
        self.assertIn(healthy["id"], {row["id"] for row in project_tree.json()["folders"]})
        self.assertIn(library_healthy["id"], {row["id"] for row in bible_tree.json()["folders"]})
        self.assertNotIn("P_A", {row["id"] for row in project_tree.json()["folders"]})
        self.assertNotIn("L_A", {row["id"] for row in bible_tree.json()["folders"]})
        repaired = client.patch("/api/folders/P_A", json={"parent_id": None})
        self.assertEqual(repaired.status_code, 200, repaired.text)
        self.assertIn("P_A", {row["id"] for row in client.get(f"/api/projects/{self.project['id']}/tree").json()["folders"]})
        with self._db() as con:
            self.assertIsNotNone(con.execute("SELECT 1 FROM workspace_folders WHERE id='P_ORPHAN'").fetchone())
            self.assertIsNotNone(con.execute("SELECT 1 FROM workspace_folders WHERE id='L_ORPHAN'").fetchone())

    def test_library_family_folder_ownership_and_null_clear(self):
        client = self._client()
        story_folder = self.store.create_folder(self.project["id"], "Story")
        library_folder = self.store.create_folder(WORLD_BIBLE_PROJECT_ID, "Library")
        payload = {"name": "Library sheet", "folder_id": story_folder["id"], "entity_type": "character"}
        self.assertEqual(client.post("/api/entities/families", json=payload).status_code, 400)
        payload["folder_id"] = library_folder["id"]
        family = client.post("/api/entities/families", json=payload)
        self.assertEqual(family.status_code, 200, family.text)
        family_id = family.json()["id"]
        self.assertEqual(client.patch(f"/api/entities/families/{family_id}", json={"folder_id": story_folder["id"]}).status_code, 400)
        cleared = client.patch(f"/api/entities/families/{family_id}", json={"folder_id": None})
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertIsNone(cleared.json()["folder_id"])

    def test_trash_restore_hides_and_reveals_healthy_subtree(self):
        client = self._client()
        project = client.post("/api/projects", json={"name": "Visibility"}).json()
        folder = client.post("/api/folders", json={"project_id": project["id"], "name": "Hidden"}).json()
        child = client.post("/api/folders", json={"project_id": project["id"], "name": "Child", "parent_id": folder["id"]}).json()
        self.assertIn(child["id"], {row["id"] for row in client.get(f"/api/projects/{project['id']}/tree").json()["folders"]})
        payload = {"resource_type": "folder", "resource_id": folder["id"]}
        self.assertEqual(client.post("/api/lifecycle/trash", json=payload).status_code, 200)
        self.assertNotIn(child["id"], {row["id"] for row in client.get(f"/api/projects/{project['id']}/tree").json()["folders"]})
        self.assertEqual(client.post("/api/lifecycle/restore", json=payload).status_code, 200)
        self.assertIn(child["id"], {row["id"] for row in client.get(f"/api/projects/{project['id']}/tree").json()["folders"]})

    def test_direct_and_lifecycle_delete_clear_chat_and_foundation_metadata(self):
        client = self._client()
        project = client.post("/api/projects", json={"name": "Delete"}).json()
        folder = client.post("/api/folders", json={"project_id": project["id"], "name": "Delete Me"}).json()
        history = HistoryStore(self.db, backup_before_migration=False)
        foundation = FoundationStore(self.db)
        session = history.create_session(title="Folder chat", project_id=project["id"], folder_id=folder["id"])
        foundation.add_alias("folder", folder["id"], "old folder")
        self.assertEqual(client.post("/api/lifecycle/trash", json={"resource_type": "folder", "resource_id": folder["id"]}).status_code, 200)
        self.assertEqual(client.delete(f"/api/trash/folder/{folder['id']}").status_code, 200)
        self.assertIsNone(history.get_session_meta(session["id"])["folder_id"])
        with self._db() as con:
            self.assertIsNone(con.execute("SELECT 1 FROM resource_lifecycle WHERE resource_type='folder' AND resource_id=?", (folder["id"],)).fetchone())
            self.assertIsNone(con.execute("SELECT 1 FROM resource_aliases WHERE resource_type='folder' AND resource_id=?", (folder["id"],)).fetchone())

        direct = client.post("/api/folders", json={"project_id": project["id"], "name": "Direct"}).json()
        direct_session = history.create_session(title="Direct chat", project_id=project["id"], folder_id=direct["id"])
        foundation.add_alias("folder", direct["id"], "direct folder")
        self.assertEqual(client.delete(f"/api/folders/{direct['id']}").status_code, 200)
        self.assertIsNone(history.get_session_meta(direct_session["id"])["folder_id"])


if __name__ == "__main__":
    unittest.main()
