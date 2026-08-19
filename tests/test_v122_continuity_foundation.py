from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.history.store import HistoryStore
from src.memory import MemoryConfig, MemoryQueryContext, MemoryService, MemoryStore
from src.memory.web import create_memory_router
from src.workspace import FoundationStore
from src.workspace.store import WorkspaceStore


class ContinuityFixture:
    def __init__(self, root: str):
        path = Path(root) / "arline.db"
        self.workspace = WorkspaceStore(path, backup_before_migration=False)
        self.history = HistoryStore(path, backup_before_migration=False)
        self.foundation = FoundationStore(path)
        self.project = self.workspace.create_project("Continuity fixture")
        self.world_id = self.project["default_world_id"]
        self.branch = next(
            item for item in self.workspace.get_world(self.world_id)["branches"]
            if item["kind"] == "main"
        )
        config = MemoryConfig()
        config.dense_enabled = False
        store = MemoryStore(path)
        self.memory = MemoryService(
            store=store,
            workspace=self.workspace,
            history=self.history,
            foundation=self.foundation,
            config=config,
            lmstudio_base_url="http://127.0.0.1:1234",
        )
        create_memory_router(service=self.memory, store=store, foundation=self.foundation)
        self.discovery = self.memory.discovery
        self.session = self.history.create_session(
            prompt="continuity",
            project_id=self.project["id"],
            world_id=self.world_id,
            branch_id=self.branch["id"],
        )

    def turn(self, prompt: str, suffix: str):
        return self.history.add_turn(
            self.session["id"],
            run_id=f"RUN-V122-{suffix}",
            user_prompt=prompt,
            story="Generated.",
            model="fixture-model",
            mode="smart_hybrid",
            reasoning="off",
            projection_mode="off",
        )

    def context(self, turn_id: str | None = None):
        return MemoryQueryContext(
            project_id=self.project["id"],
            world_id=self.world_id,
            branch_id=self.branch["id"],
            session_id=self.session["id"],
            current_turn_id=turn_id,
        )

    def add_claim(self, turn, *, value, operation="update", predicate="state.hair.length_cm"):
        prop = self.discovery.store.upsert_proposition(
            project_id=self.project["id"],
            world_id=self.world_id,
            subject_type="character",
            subject_key="char:alex",
            subject_label="Alex",
            predicate=predicate,
            value=value,
            operation=operation,
            temporal_state="historical_or_current" if operation == "transition" else "current_or_unspecified",
        )
        self.discovery.store.add_instance(
            prop["id"],
            source_kind="user_prompt",
            source_session_id=self.session["id"],
            source_turn_id=turn["id"],
            origin_session_id=self.session["id"],
            origin_turn_id=turn["id"],
            source_revision=f"REV-{turn['id']}-{prop['id']}",
            project_id=self.project["id"],
            world_id=self.world_id,
            branch_id=self.branch["id"],
            story_order=float(turn.get("ordinal") or 0),
            source_segment="manual-fixture",
            span_text=turn.get("user_prompt") or "",
            extraction_confidence=1.0,
            explicitness="explicit",
            qualifies_review=True,
        )
        return prop


class V122ContinuityFoundationTests(unittest.TestCase):
    def test_explicit_story_change_supersedes_previous_visible_value(self):
        with tempfile.TemporaryDirectory() as td:
            fx = ContinuityFixture(td)
            before = fx.turn("Alex has hair length 10 cm.", "1")
            p1 = fx.add_claim(before, value=10)
            after = fx.turn("Sekarang rambut Alex menjadi 100 cm.", "2")
            p2 = fx.add_claim(after, value=100, operation="transition")

            report = fx.discovery.continuity.resolve_turn(after["id"])
            self.assertGreaterEqual(report["story_changes"], 1)
            view = fx.discovery.continuity.current_view(fx.context(after["id"]), subject_key="char:alex")
            head = next(item for item in view["heads"] if item["predicate"] == "state.hair.length_cm")
            self.assertEqual(head["id"], p2["id"])
            self.assertIn(p1["id"], view["superseded_proposition_ids"])

    def test_correction_is_distinct_from_story_change(self):
        with tempfile.TemporaryDirectory() as td:
            fx = ContinuityFixture(td)
            before = fx.turn("Alex has hair length 100 cm.", "1")
            p1 = fx.add_claim(before, value=100)
            corrected = fx.turn("Koreksi, maksudku panjang rambut Alex 80 cm.", "2")
            p2 = fx.add_claim(corrected, value=80)

            report = fx.discovery.continuity.resolve_turn(corrected["id"])
            self.assertGreaterEqual(report["corrections"], 1)
            with fx.discovery.store.connection() as con:
                edge = con.execute(
                    "SELECT kind FROM continuity_edges WHERE from_proposition_id=? AND to_proposition_id=?",
                    (p1["id"], p2["id"]),
                ).fetchone()
            self.assertEqual(edge["kind"], "correction")

    def test_uncued_competing_values_abstain_instead_of_overwriting(self):
        with tempfile.TemporaryDirectory() as td:
            fx = ContinuityFixture(td)
            first = fx.turn("The garment color is black.", "1")
            p1 = fx.add_claim(first, value="black", predicate="garment.color")
            second = fx.turn("The garment color is red.", "2")
            p2 = fx.add_claim(second, value="red", predicate="garment.color")

            report = fx.discovery.continuity.resolve_turn(second["id"])
            self.assertGreaterEqual(report["conflicts"], 1)
            view = fx.discovery.continuity.current_view(fx.context(second["id"]), subject_key="char:alex")
            ambiguous = next(item for item in view["ambiguous"] if item["predicate"] == "garment.color")
            self.assertEqual(set(ambiguous["proposition_ids"]), {p1["id"], p2["id"]})

    def test_state_transition_creates_form_without_creating_another_character(self):
        with tempfile.TemporaryDirectory() as td:
            fx = ContinuityFixture(td)
            first = fx.turn("Alex has hair length 10 cm.", "1")
            fx.add_claim(first, value=10)
            second = fx.turn("Alex sekarang berubah; rambutnya menjadi 100 cm.", "2")
            p2 = fx.add_claim(second, value=100, operation="transition")

            report = fx.discovery.continuity.resolve_turn(second["id"])
            self.assertGreaterEqual(report["forms"], 1)
            forms = fx.discovery.continuity.list_forms(fx.context(second["id"]), subject_key="char:alex")
            self.assertEqual(len(forms), 1)
            self.assertEqual(forms[0]["anchor_proposition_id"], p2["id"])
            self.assertEqual(forms[0]["state"]["hair.length_cm"], 100)
            self.assertEqual(forms[0]["subject_key"], "char:alex")

    def test_continuity_is_derived_and_does_not_grant_canon(self):
        with tempfile.TemporaryDirectory() as td:
            fx = ContinuityFixture(td)
            before = fx.turn("Alex has hair length 10 cm.", "1")
            fx.add_claim(before, value=10)
            after = fx.turn("Sekarang rambut Alex menjadi 100 cm.", "2")
            p2 = fx.add_claim(after, value=100, operation="transition")
            fx.discovery.continuity.resolve_turn(after["id"])
            self.assertEqual(fx.discovery.store.get_proposition(p2["id"])["authority_state"], "observed")
            self.assertEqual(fx.discovery.continuity.status()["version"], "1.2.2b1")


if __name__ == "__main__":
    unittest.main()
