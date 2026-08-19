from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.discovery.coreference import CrossTurnCoreferenceResolver
from src.discovery.entity_resolver import NarrativeEntityResolver
from src.history.store import HistoryStore
from src.memory import MemoryConfig, MemoryQueryContext, MemoryService, MemoryStore
from src.memory.web import create_memory_router
from src.workspace import FoundationStore
from src.workspace.store import WorkspaceStore


class TopDownFixture:
    def __init__(self, root: str):
        path = Path(root) / "arline.db"
        self.workspace = WorkspaceStore(path, backup_before_migration=False)
        self.history = HistoryStore(path, backup_before_migration=False)
        self.foundation = FoundationStore(path)
        self.project = self.workspace.create_project("v1.2.2 top-down")
        self.world_id = self.project["default_world_id"]
        self.branch = next(x for x in self.workspace.get_world(self.world_id)["branches"] if x["kind"] == "main")
        config = MemoryConfig(); config.dense_enabled = False
        store = MemoryStore(path)
        self.memory = MemoryService(
            store=store, workspace=self.workspace, history=self.history,
            foundation=self.foundation, config=config, lmstudio_base_url="http://127.0.0.1:1234",
        )
        create_memory_router(service=self.memory, store=store, foundation=self.foundation)
        self.discovery = self.memory.discovery
        self.session = self.history.create_session(
            prompt="v122", project_id=self.project["id"], world_id=self.world_id, branch_id=self.branch["id"]
        )

    def turn(self, prompt: str, suffix: str):
        return self.history.add_turn(
            self.session["id"], run_id=f"V122-TOP-{suffix}", user_prompt=prompt,
            story="Generated.", model="fixture", mode="smart_hybrid", reasoning="off", projection_mode="off",
        )

    def context(self, turn_id=None):
        return MemoryQueryContext(
            project_id=self.project["id"], world_id=self.world_id, branch_id=self.branch["id"],
            session_id=self.session["id"], current_turn_id=turn_id,
        )

    def source(self, turn, text: str):
        return {
            "source_kind": "user_prompt", "session_id": self.session["id"], "turn_id": turn["id"],
            "revision": f"REV-{turn['id']}", "project_id": self.project["id"], "world_id": self.world_id,
            "branch_id": self.branch["id"], "world_time": None, "story_order": float(turn.get("ordinal") or 0),
            "segments": {}, "base_qualifies": True,
        }

    def claim(self, turn, *, value, operation="update", predicate="state.hair.length_cm"):
        prop = self.discovery.store.upsert_proposition(
            project_id=self.project["id"], world_id=self.world_id, subject_type="character",
            subject_key="char:alex", subject_label="Alex", predicate=predicate, value=value,
            operation=operation, temporal_state="historical_or_current" if operation == "transition" else "current_or_unspecified",
        )
        self.discovery.store.add_instance(
            prop["id"], source_kind="user_prompt", source_session_id=self.session["id"],
            source_turn_id=turn["id"], origin_session_id=self.session["id"], origin_turn_id=turn["id"],
            source_revision=f"R-{turn['id']}-{prop['id']}", project_id=self.project["id"], world_id=self.world_id,
            branch_id=self.branch["id"], story_order=float(turn.get("ordinal") or 0), span_text=turn["user_prompt"],
            extraction_confidence=1.0, explicitness="explicit", qualifies_review=True,
        )
        return prop


class V122TopDownCompletionTests(unittest.TestCase):
    def test_schema_v4_owns_mentions_events_causality_and_conflict_resolution_columns(self):
        with tempfile.TemporaryDirectory() as td:
            fx = TopDownFixture(td)
            self.assertEqual(fx.discovery.store.SCHEMA_VERSION, 4)
            with fx.discovery.store.connection() as con:
                tables = {row["name"] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertTrue({"discovery_mentions", "narrative_events", "narrative_event_state_links"} <= tables)
                form_cols = {row["name"] for row in con.execute("PRAGMA table_info(continuity_forms)")}
                conflict_cols = {row["name"] for row in con.execute("PRAGMA table_info(continuity_conflicts)")}
            self.assertTrue({"event_id", "before_state_json", "after_state_json"} <= form_cols)
            self.assertTrue({"resolution_kind", "resolution_note", "chosen_proposition_id"} <= conflict_cols)

    def test_exact_library_alias_resolves_to_stable_family_anchor_without_fuzzy_merge(self):
        with tempfile.TemporaryDirectory() as td:
            fx = TopDownFixture(td)
            family = fx.workspace.create_entity_family(None, "Alexander", entity_type="character")
            fx.foundation.add_alias("entity_family", family["id"], "Alex")
            turn = fx.turn("Alex entered the room.", "alias")
            frame = fx.discovery.entity_resolver.resolve_entities(
                {"char:temp": {"id": "char:temp", "type": "character", "label": "Alex", "attributes": {}}},
                text="Alex entered the room.", source=fx.source(turn, "Alex entered the room."),
            )
            resolved = frame.resolutions["char:temp"]
            self.assertEqual(resolved.resource_id, family["id"])
            self.assertEqual(resolved.subject_key, f"entity:{family['id']}")
            self.assertEqual(resolved.reason, "exact_library_identity")

    def test_first_person_coreference_uses_unique_self_anchor_and_persists_mention(self):
        with tempfile.TemporaryDirectory() as td:
            fx = TopDownFixture(td)
            turn = fx.turn("My name is Alex. I am tired.", "self")
            entities = {
                "char:alex-local": {"id": "char:alex-local", "type": "character", "label": "Alex", "attributes": {}},
                "char:self": {"id": "char:self", "type": "character", "label": "self", "attributes": {}},
            }
            frame = fx.discovery.entity_resolver.resolve_entities(
                entities, text="My name is Alex. I am tired.", source=fx.source(turn, "My name is Alex. I am tired."),
            )
            self.assertEqual(frame.key_map["char:self"], frame.key_map["char:alex-local"])
            with fx.discovery.store.connection() as con:
                mentions = con.execute(
                    "SELECT surface,resolution_state,resolved_subject_key FROM discovery_mentions WHERE source_turn_id=? AND active=1",
                    (turn["id"],),
                ).fetchall()
            self.assertEqual(len(mentions), 2)
            self.assertTrue(all(row["resolution_state"] == "resolved" for row in mentions))

    def test_ambiguous_third_person_reference_abstains(self):
        with tempfile.TemporaryDirectory() as td:
            fx = TopDownFixture(td)
            turn = fx.turn("Alex met Fano. Dia smiled.", "amb")
            entities = {
                "a": {"id": "a", "type": "character", "label": "Alex", "attributes": {}},
                "f": {"id": "f", "type": "character", "label": "Fano", "attributes": {}},
                "p": {"id": "p", "type": "character", "label": "dia", "attributes": {}},
            }
            frame = fx.discovery.entity_resolver.resolve_entities(
                entities, text="Alex met Fano. Dia smiled.", source=fx.source(turn, "Alex met Fano. Dia smiled."),
            )
            self.assertEqual(frame.resolutions["p"].state, "ambiguous")
            self.assertEqual(frame.key_map["p"], "p")

    def test_event_state_causality_reconstructs_before_after_form(self):
        with tempfile.TemporaryDirectory() as td:
            fx = TopDownFixture(td)
            before = fx.turn("Alex has hair length 10 cm.", "1")
            p1 = fx.claim(before, value=10)
            after = fx.turn("Now Alex changed; his hair became 100 cm.", "2")
            p2 = fx.claim(after, value=100, operation="transition")
            source = fx.source(after, after["user_prompt"])
            event_map = fx.discovery.events.capture_events(
                {"events": [{"id": "ev-1", "event_type": "transformation", "summary": "Alex transforms"}]},
                source=source, key_map={"char:alex": "char:alex"},
            )
            fx.discovery.events.link_after(
                event_id=event_map["ev-1"], subject_key="char:alex",
                predicate="state.hair.length_cm", after_proposition_id=p2["id"],
            )
            fx.discovery.continuity.resolve_turn(after["id"])
            events = fx.discovery.events.list_for_subject(fx.context(after["id"]), subject_key="char:alex")
            forms = fx.discovery.continuity.list_forms(fx.context(after["id"]), subject_key="char:alex")
            self.assertEqual(events[0]["before"]["id"], p1["id"])
            self.assertEqual(events[0]["after"]["id"], p2["id"])
            self.assertEqual(forms[0]["event_id"], event_map["ev-1"])
            self.assertEqual(forms[0]["before_state"]["hair.length_cm"], 10)
            self.assertEqual(forms[0]["after_state"]["hair.length_cm"], 100)

    def test_conflict_resolution_changes_derived_view_but_never_canon(self):
        with tempfile.TemporaryDirectory() as td:
            fx = TopDownFixture(td)
            first = fx.turn("Alex's eyes are blue.", "1")
            p1 = fx.claim(first, value="blue", predicate="appearance.eye_color")
            second = fx.turn("Alex's eyes are green.", "2")
            p2 = fx.claim(second, value="green", predicate="appearance.eye_color")
            fx.discovery.continuity.resolve_turn(second["id"])
            conflicts = fx.discovery.continuity.list_conflicts(fx.context(second["id"]), subject_keys=["char:alex"])
            self.assertEqual(len(conflicts), 1)
            fx.discovery.continuity.resolve_conflict(
                conflicts[0]["id"], fx.context(second["id"]), resolution="story_change", note="explicit test resolution"
            )
            view = fx.discovery.continuity.current_view(fx.context(second["id"]), subject_key="char:alex")
            head = next(item for item in view["heads"] if item["predicate"] == "appearance.eye_color")
            self.assertEqual(head["id"], p2["id"])
            self.assertEqual(fx.discovery.store.get_proposition(p1["id"])["authority_state"], "observed")
            self.assertEqual(fx.discovery.store.get_proposition(p2["id"])["authority_state"], "observed")

    def test_resource_summary_exposes_current_forms_events_conflicts_mentions(self):
        with tempfile.TemporaryDirectory() as td:
            fx = TopDownFixture(td)
            turn = fx.turn("Alex is here.", "summary")
            fx.discovery.entity_resolver.resolve_entities(
                {"a": {"id": "a", "type": "character", "label": "Alex", "attributes": {}}},
                text="Alex is here.", source=fx.source(turn, "Alex is here."),
            )
            fx.claim(turn, value="calm", predicate="state.mood")
            summary = fx.discovery.continuity.resource_summary(fx.context(turn["id"]), subject_keys=["char:alex"])
            self.assertEqual(summary["version"], "1.2.2b1")
            self.assertIn("current_state", summary)
            self.assertIn("forms", summary)
            self.assertIn("events", summary)
            self.assertIn("conflicts", summary)
            self.assertIn("mentions", summary)

    def test_v122_runtime_is_explicit_not_capture_turn_monkey_patch(self):
        with tempfile.TemporaryDirectory() as td:
            fx = TopDownFixture(td)
            self.assertIs(fx.discovery.continuity, fx.discovery.narrative.continuity)
            self.assertIs(fx.discovery.entity_resolver, fx.discovery.narrative.entity_resolver)
            self.assertIs(fx.discovery.events, fx.discovery.narrative.events)
            self.assertFalse(hasattr(type(fx.discovery), "_identity_resolution_v2"))


if __name__ == "__main__":
    unittest.main()
