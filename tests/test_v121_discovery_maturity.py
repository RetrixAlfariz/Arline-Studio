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
        self.project = self.workspace.create_project("Discovery maturity fixture")
        self.world_id = self.project["default_world_id"]
        self.main_branch = next(
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
        router = create_memory_router(
            service=self.memory, store=memory_store, foundation=self.foundation
        )
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)
        self.discovery = self.memory.discovery

    def session(self, branch_id: str | None = None):
        return self.history.create_session(
            prompt="fixture",
            project_id=self.project["id"],
            world_id=self.world_id,
            branch_id=branch_id or self.main_branch["id"],
        )

    def turn(self, session_id: str, prompt: str, suffix: str = "1"):
        return self.history.add_turn(
            session_id,
            run_id=f"RUN-MATURE-{suffix}",
            user_prompt=prompt,
            story="Generated.",
            model="fixture-model",
            mode="smart_hybrid",
            reasoning="off",
            projection_mode="off",
        )

    def context(self, session_id: str | None = None, branch_id: str | None = None):
        return MemoryQueryContext(
            project_id=self.project["id"],
            world_id=self.world_id,
            branch_id=branch_id or self.main_branch["id"],
            session_id=session_id,
        )

    def family(self, name: str, entity_type: str):
        return next(
            item for item in self.workspace.list_entity_families(None, entity_type=entity_type)
            if item["name"] == name
        )


class V121DiscoveryMaturityTests(unittest.TestCase):
    def test_alias_identity_is_reused_without_duplicate_family(self):
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td)
            family = f.workspace.create_entity_family(
                None, "Revian", entity_type="character",
                create_variant_in_world=f.world_id,
            )
            f.foundation.add_alias("entity_family", family["id"], "Vian")
            session = f.session()
            f.turn(session["id"], "Character Vian lives in Nova City.")

            names = [
                item["name"] for item in f.workspace.list_entity_families(None, entity_type="character")
            ]
            self.assertIn("Revian", names)
            self.assertNotIn("Vian", names)
            view = f.discovery.resource_view(family["id"], f.context(session["id"]))
            self.assertTrue(any(item["subject_label"] == "Vian" for item in view["claims"]))

    def test_fact_promotion_is_idempotent_main_scoped_and_projects_to_sheet(self):
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td)
            session = f.session()
            f.turn(session["id"], "Character Alex is shy.")
            alex = f.family("Alex", "character")
            view = f.discovery.resource_view(alex["id"], f.context(session["id"]))
            claim = next(item for item in view["claims"] if item["predicate"] == "personality.descriptor")
            self.assertEqual(claim["semantics"]["group"], "personality")
            self.assertEqual(claim["semantics"]["canon_target"], "fact")

            first = f.discovery.promote_canon(claim["id"], f.context(session["id"]), note="test")
            second = f.discovery.promote_canon(claim["id"], f.context(session["id"]), note="test again")
            self.assertEqual(first["materialized_resource_id"], second["materialized_resource_id"])

            with f.workspace._connection() as con:
                facts = con.execute(
                    "SELECT * FROM canon_facts WHERE source_type='discovery_proposition' AND source_id=?",
                    (claim["id"],),
                ).fetchall()
            self.assertEqual(len(facts), 1)
            self.assertIsNone(facts[0]["branch_id"])

            with f.discovery.store.connection() as con:
                decisions = con.execute(
                    "SELECT COUNT(*) FROM discovery_decisions WHERE proposition_id=? AND action='canon'",
                    (claim["id"],),
                ).fetchone()[0]
            self.assertEqual(decisions, 1)

            variant = f.workspace.resolve_variant(alex["id"], f.world_id)
            self.assertEqual(
                (variant.get("attributes") or {}).get("personality", {}).get("descriptor"),
                claim["value"],
            )
            with self.assertRaises(ValueError):
                f.discovery.dismiss(claim["id"], f.context(session["id"]))
            with self.assertRaises(ValueError):
                f.discovery.reset_decision(claim["id"], f.context(session["id"]))

    def test_failed_materialization_never_grants_canon_authority(self):
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td)
            session = f.session()
            f.turn(session["id"], "Character Mira is calm.")
            mira = f.family("Mira", "character")
            view = f.discovery.resource_view(mira["id"], f.context(session["id"]))
            claim = next(item for item in view["claims"] if item["predicate"] == "personality.descriptor")

            original_add_fact = f.workspace.add_fact
            def fail_add_fact(*args, **kwargs):
                raise RuntimeError("simulated canon materialization failure")
            f.workspace.add_fact = fail_add_fact
            try:
                with self.assertRaises(RuntimeError):
                    f.discovery.promote_canon(claim["id"], f.context(session["id"]))
            finally:
                f.workspace.add_fact = original_add_fact

            proposition = f.discovery.store.get_proposition(claim["id"])
            self.assertEqual(proposition["authority_state"], "observed")
            self.assertIsNone(proposition["materialized_resource_id"])
            with f.discovery.store.connection() as con:
                decisions = con.execute(
                    "SELECT COUNT(*) FROM discovery_decisions WHERE proposition_id=? AND action='canon'",
                    (claim["id"],),
                ).fetchone()[0]
            self.assertEqual(decisions, 0)

    def test_relation_promotion_is_idempotent_and_main_branch_is_null(self):
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td)
            session = f.session()
            f.turn(session["id"], "Character Alex lives in Nova City.")
            alex = f.family("Alex", "character")
            view = f.discovery.resource_view(alex["id"], f.context(session["id"]))
            relation = next(item for item in view["relations"] if item["predicate"] == "resides_at")
            self.assertEqual(relation["semantics"]["canon_target"], "relationship")

            first = f.discovery.promote_canon(relation["id"], f.context(session["id"]))
            second = f.discovery.promote_canon(relation["id"], f.context(session["id"]))
            self.assertEqual(first["materialized_resource_id"], second["materialized_resource_id"])
            rel = f.workspace.get_relationship(first["materialized_resource_id"])
            self.assertIsNone(rel["branch_id"])
            self.assertEqual(rel["attributes"].get("source_proposition_id"), relation["id"])

    def test_sibling_branch_cannot_promote_hidden_discovery(self):
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td)
            branch_a = f.workspace.create_branch(
                f.world_id, "A", parent_branch_id=f.main_branch["id"], kind="what_if"
            )
            branch_b = f.workspace.create_branch(
                f.world_id, "B", parent_branch_id=f.main_branch["id"], kind="what_if"
            )
            session_a = f.session(branch_a["id"])
            f.turn(session_a["id"], "Character BranchAlex is shy.")
            family = f.family("BranchAlex", "character")
            view_a = f.discovery.resource_view(
                family["id"], f.context(session_a["id"], branch_a["id"])
            )
            claim = next(item for item in view_a["claims"] if item["predicate"] == "personality.descriptor")
            with self.assertRaises(ValueError):
                f.discovery.promote_canon(claim["id"], f.context(None, branch_b["id"]))
            self.assertEqual(f.discovery.store.get_proposition(claim["id"])["authority_state"], "observed")

    def test_generic_building_floor_room_uses_same_containment_grammar(self):
        with tempfile.TemporaryDirectory() as td:
            f = Fixture(td)
            session = f.session()
            f.turn(
                session["id"],
                "location Gedung Teknik lantai 4 ruang R401 [luas 32m], Surabaya",
            )
            names = {
                item["name"] for item in f.workspace.list_entity_families(None, entity_type="location")
            }
            self.assertIn("Gedung Teknik", names)
            self.assertIn("Ruang R401", names)
            self.assertIn("Surabaya", names)
            self.assertNotIn("Floor 4", names)

            room = f.family("Ruang R401", "location")
            view = f.discovery.resource_view(room["id"], f.context(session["id"]))
            self.assertEqual(
                [node["label"] for node in view["spatial_path"]],
                ["Surabaya", "Gedung Teknik", "Floor 4", "Ruang R401"],
            )
            values = {item["predicate"]: item["value"] for item in view["claims"]}
            self.assertEqual(values["floor_number"], 4)
            self.assertEqual(values["area_m2"], 32)
            zone_edge = next(
                item for item in view["relations"]
                if item["predicate"] == "located_on" and item.get("object_type") == "spatial_zone"
            )
            self.assertFalse(zone_edge["semantics"]["canonizable"])
            self.assertEqual(zone_edge["semantics"]["canon_target"], "none")


if __name__ == "__main__":
    unittest.main()
