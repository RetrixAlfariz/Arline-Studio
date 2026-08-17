from __future__ import annotations

from pathlib import Path
import re
import sqlite3
import tempfile
import tomllib
import unittest

from fastapi.testclient import TestClient

from src.history import HistoryStore
from src.interface.web.app import create_app
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

    def test_model_discovery_does_not_put_api_key_in_query_string(self):
        js = (ROOT / "src/interface/web/static/arline.js").read_text(encoding="utf-8")
        app = (ROOT / "src/interface/web/app.py").read_text(encoding="utf-8")
        self.assertIn('/api/models/query', js)
        self.assertNotIn('/api/models?server_url=', js)
        self.assertIn('"api_key_configured": bool(cfg.lmstudio.api_key)', app)
        self.assertNotIn('"api_key": cfg.lmstudio.api_key', app)

    def test_permanent_delete_cleans_history_scope(self):
        app = (ROOT / "src/interface/web/app.py").read_text(encoding="utf-8")
        start = app.index("    def _permanent_delete(resource_type: str, resource_id: str) -> None:")
        end = app.index("\n    @app.", start)
        block = app[start:end]
        self.assertIn("history.delete_sessions_by_scope(project_id=resource_id)", block)
        self.assertIn("history.delete_sessions_by_scope(world_id=resource_id)", block)
        self.assertIn("history.delete_sessions_by_scope(branch_id=resource_id)", block)
        self.assertIn("foundation.forget_resource(resource_type, resource_id)", block)

    def test_package_versions_match(self):
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        version = pyproject["project"]["version"]
        lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
        match = re.search(r'\[\[package\]\]\nname = "arline-studio"\nversion = "([^"]+)"', lock)
        self.assertIsNotNone(match)
        self.assertEqual(version, "1.1.0")
        self.assertEqual(match.group(1), version)

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
            con.commit()
            con.close()
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
            con.commit()
            con.close()
            store = HistoryStore(db)
            self.assertIsNotNone(store.last_migration_backup)

    def test_fastapi_startup_public_config_and_tab_context_smoke(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = root / "arline.db"
            config_text = (ROOT / "config/arline.toml").read_text(encoding="utf-8")
            config_text = config_text.replace('auto_load = true', 'auto_load = false')
            config_text = config_text.replace(
                'database_path = "data\\\\arline_history.db"',
                f'database_path = "{db.as_posix()}"',
            )
            config_text = config_text.replace(
                'dataset_root = "data\\\\datasets"',
                f'dataset_root = "{(root / "datasets").as_posix()}"',
            )
            config_text = config_text.replace(
                'output_root = "output"',
                f'output_root = "{(root / "output").as_posix()}"',
            )
            config_text = config_text.replace(
                'saved_root = "output\\\\saved"',
                f'saved_root = "{(root / "saved").as_posix()}"',
            )
            config_path = root / "arline.toml"
            config_path.write_text(config_text, encoding="utf-8")

            client = TestClient(create_app(config_path))
            public = client.get("/api/config")
            self.assertEqual(public.status_code, 200)
            payload = public.json()
            self.assertNotIn("api_key", payload)
            self.assertFalse(payload["api_key_configured"])
            self.assertEqual(payload["studio_version"], "1.1.0")

            bootstrap = client.get("/api/workspace/bootstrap", params={"stack_id": "smoke-a"})
            self.assertEqual(bootstrap.status_code, 200)
            project_id = bootstrap.json()["active"]["project"]["id"]
            saved = client.put(
                "/api/context-stack",
                json={"stack_id": "smoke-a", "project_id": project_id, "references": []},
            )
            self.assertEqual(saved.status_code, 200)
            other = client.get("/api/context-stack", params={"stack_id": "smoke-b"})
            self.assertEqual(other.status_code, 200)
            self.assertNotEqual(other.json().get("project_id"), project_id)


if __name__ == "__main__":
    unittest.main()
