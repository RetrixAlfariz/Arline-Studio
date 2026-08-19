from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import tomllib
import unittest

from src.discovery.store import DiscoveryStore
from src.domain_events import clear_domain_event_bus, get_domain_event_bus
from src.history import HistoryStore
from src.version import __version__


ROOT = Path(__file__).resolve().parents[1]


class ArchitectureHardeningTests(unittest.TestCase):
    def test_domain_event_bus_isolates_derived_handler_failure(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "events.db"
            clear_domain_event_bus(db)
            bus = get_domain_event_bus(db)
            calls: list[str] = []

            def broken(_event):
                raise RuntimeError("derived failure")

            def healthy(event):
                calls.append(event.name)

            bus.subscribe("example", broken, key="broken")
            bus.subscribe("example", healthy, key="healthy")
            errors = bus.emit("example", {"value": 1})
            self.assertEqual(len(errors), 1)
            self.assertEqual(calls, ["example"])
            clear_domain_event_bus(db)

    def test_history_emits_only_after_authoritative_turn_and_feedback_commit(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "history.db"
            clear_domain_event_bus(db)
            history = HistoryStore(db)
            session = history.create_session(prompt="A scene")
            events: list[tuple[str, str]] = []
            bus = get_domain_event_bus(db)
            bus.subscribe(
                "history.turn_created",
                lambda event: events.append((event.name, event.payload["turn"]["id"])),
                key="test.turn",
            )
            bus.subscribe(
                "history.feedback_changed",
                lambda event: events.append((event.name, event.payload["turn"]["id"])),
                key="test.feedback",
            )

            turn = history.add_turn(
                session["id"],
                run_id="RUN-1",
                user_prompt="Continue",
                story="Done",
                model="local-model",
                mode="smart_hybrid",
                reasoning="off",
                projection_mode="balanced",
            )
            self.assertEqual(events, [("history.turn_created", turn["id"])])
            history.set_feedback(turn["id"], status="accepted")
            self.assertEqual(
                events,
                [
                    ("history.turn_created", turn["id"]),
                    ("history.feedback_changed", turn["id"]),
                ],
            )
            clear_domain_event_bus(db)

    def test_discovery_store_owns_continuity_schema(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "discovery.db"
            store = DiscoveryStore(db)
            self.assertEqual(store.SCHEMA_VERSION, 2)
            with sqlite3.connect(db) as con:
                tables = {
                    row[0]
                    for row in con.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                version = con.execute(
                    "SELECT value FROM discovery_meta WHERE key='continuity_version'"
                ).fetchone()[0]
            self.assertTrue(
                {"continuity_edges", "continuity_conflicts", "continuity_forms"}
                <= tables
            )
            self.assertEqual(version, "1.2.2a1")

        resolver = (ROOT / "src/discovery/continuity.py").read_text(encoding="utf-8")
        self.assertNotIn("def _ensure_schema", resolver)
        self.assertNotIn("CREATE TABLE IF NOT EXISTS continuity_", resolver)

    def test_derived_systems_use_source_specific_event_buses_not_method_replacement(self):
        memory_web = (ROOT / "src/memory/web.py").read_text(encoding="utf-8")
        discovery_web = (ROOT / "src/discovery/web.py").read_text(encoding="utf-8")

        self.assertNotIn("workspace.add_timeline_event =", memory_web)
        for assignment in (
            "history.add_turn =",
            "history.set_feedback =",
            "history.delete_session =",
            "history.delete_sessions_by_scope =",
            "foundation_store.trash =",
            "foundation_store.restore =",
        ):
            self.assertNotIn(assignment, discovery_web)

        self.assertIn("workspace_path = getattr(workspace,", memory_web)
        self.assertIn("history_bus = get_domain_event_bus(memory_service.history.path)", discovery_web)
        self.assertIn("workspace_bus = get_domain_event_bus(discovery.store.path)", discovery_web)

    def test_model_discovery_never_accepts_api_key_in_get_query(self):
        app = (ROOT / "src/interface/web/app.py").read_text(encoding="utf-8")
        start = app.index('    @app.get("/api/models")')
        end = app.index('    @app.post("/api/models/query")', start)
        legacy_get = app[start:end]
        self.assertNotIn("api_key", legacy_get)
        self.assertIn("ModelsPayload", app)
        self.assertIn('api_key: str | None = None', app)

    def test_combined_migration_backup_covers_derived_stores_once(self):
        app = (ROOT / "src/interface/web/app.py").read_text(encoding="utf-8")
        discovery_web = (ROOT / "src/discovery/web.py").read_text(encoding="utf-8")
        self.assertIn('["memory_meta"] = MemoryStore.SCHEMA_VERSION', app)
        self.assertIn('["discovery_meta"] = DiscoveryStore.SCHEMA_VERSION', app)
        self.assertIn(
            "MemoryStore(initial_cfg.workspace.database_path, backup_before_migration=False)",
            app,
        )
        self.assertIn("memory_service._combined_migration_backup_complete = True", app)
        self.assertIn(
            'getattr(memory_service, "_combined_migration_backup_complete", False)',
            discovery_web,
        )

    def test_remote_ui_bind_requires_explicit_override(self):
        app = (ROOT / "src/interface/web/app.py").read_text(encoding="utf-8")
        self.assertIn("ARLINE_ALLOW_UNAUTHENTICATED_REMOTE_UI", app)
        self.assertIn("Refusing unauthenticated remote UI bind", app)

    def test_package_and_source_versions_are_one_contract(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(project["project"]["version"], __version__)
        self.assertEqual(__version__, "1.2.2a1")

    def test_frontend_has_no_runtime_compatibility_shim(self):
        compat = ROOT / "src/interface/web/static/js/compat.js"
        html = (ROOT / "src/interface/web/static/index.html").read_text(encoding="utf-8")
        self.assertFalse(compat.exists())
        self.assertNotIn("compat.js", html)
        self.assertIn("quick-create.js", html)
        self.assertIn("discovery-sheets.js", html)


if __name__ == "__main__":
    unittest.main()
