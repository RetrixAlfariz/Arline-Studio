from __future__ import annotations

from pathlib import Path
import re
import sqlite3
import tempfile
import unittest

from src.history import HistoryStore
from src.storage_backup import backup_sqlite_before_migrations
from src.workspace import DOCUMENT_TYPES, FoundationStore, WorkspaceStore


ROOT = Path(__file__).resolve().parents[1]


class HardeningTests(unittest.TestCase):
    def test_frontend_has_one_top_level_definition_per_name(self):
        js = (ROOT / "src/interface/web/static/arline.js").read_text(encoding="utf-8")
        names = re.findall(r"(?m)^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(", js)
        duplicates = sorted({name for name in names if names.count(name) > 1})
        self.assertEqual(duplicates, [])

    def test_frontend_uses_backend_context_contract(self):
        js = (ROOT / "src/interface/web/static/arline.js").read_text(encoding="utf-8")
        self.assertIn("estimated_input_tokens", js)
        self.assertIn("semantic_coverage", js)
        self.assertNotIn("contextBreakdown?.estimated_total_tokens", js)
        self.assertIn("x.id || x.trace_id", js)

    def test_composer_overlay_does_not_activate_for_every_plain_text(self):
        js = (ROOT / "src/interface/web/static/arline.js").read_text(encoding="utf-8")
        css = (ROOT / "src/interface/web/static/arline.css").read_text(encoding="utf-8")
        self.assertNotIn('classList.toggle("has-highlight", Boolean(text))', js)
        self.assertIn('shell?.classList.toggle("has-highlight", decorated)', js)
        self.assertIn('padding:7px 5px', css)
        self.assertIn('.composer-editor-shell:not(.has-highlight) .prompt-highlight{display:none}', css)

    def test_draft_is_compatibility_input_not_canonical_type(self):
        self.assertNotIn("draft", DOCUMENT_TYPES)
        with tempfile.TemporaryDirectory() as td:
            store = WorkspaceStore(Path(td) / "workspace.db")
            project = store.create_project("Test")
            doc = store.create_document(project["id"], "Legacy", document_type="draft", status="draft")
            self.assertEqual(doc["document_type"], "scene")
            self.assertEqual(doc["status"], "writing")

    def test_preversioned_database_is_backed_up(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "legacy.db"
            con = sqlite3.connect(db)
            con.execute("CREATE TABLE sessions(id TEXT PRIMARY KEY)")
            con.commit(); con.close()
            backup = backup_sqlite_before_migrations(db, {"meta": 4, "workspace_meta": 6})
            self.assertIsNotNone(backup)
            self.assertTrue(backup.exists())

    def test_context_stacks_are_isolated(self):
        with tempfile.TemporaryDirectory() as td:
            store = FoundationStore(Path(td) / "foundation.db")
            store.set_context_stack(stack_id="tab-a", project_id="P-A")
            store.set_context_stack(stack_id="tab-b", project_id="P-B")
            self.assertEqual(store.get_context_stack("tab-a")["project_id"], "P-A")
            self.assertEqual(store.get_context_stack("tab-b")["project_id"], "P-B")

    def test_history_store_standalone_backup_hook(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "history.db"
            con = sqlite3.connect(db)
            con.execute("CREATE TABLE sessions(id TEXT PRIMARY KEY)")
            con.commit(); con.close()
            store = HistoryStore(db)
            self.assertIsNotNone(store.last_migration_backup)


if __name__ == "__main__":
    unittest.main()
