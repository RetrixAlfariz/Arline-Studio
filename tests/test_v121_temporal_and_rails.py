from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.history.store import HistoryStore
from src.memory import (
    MemoryConfig,
    MemoryQueryContext,
    MemoryStore,
    QueryCompiler,
    QueryRoute,
    compare_world_time,
)
from src.memory.index import MemoryIndexer
from src.narrative.rails import CharacterRailParser, ExpressionChannel, RailKind, RailPacing
from src.service.v121_rails import _strip_persisted_rail_lines


class _NoEntities:
    path = Path("__different__.db")

    def list_entity_families(self, _project=None):
        return []

    def list_variants(self, **_kwargs):
        return []

    def get_scene_card(self, _document_id):
        raise KeyError(_document_id)

    def get_document(self, _document_id):
        raise KeyError(_document_id)

    def get_branch(self, branch_id):
        raise KeyError(branch_id)


class V121TemporalAndRailsTests(unittest.TestCase):
    def test_monologue_seed_is_internal_and_generation_only(self):
        compiled = CharacterRailParser.parse('/mono @vian "ihhh malu banget tau"')
        self.assertTrue(compiled.active)
        self.assertEqual(compiled.evidence_prompt, "")
        self.assertEqual(compiled.rails[0].kind, RailKind.MONOLOGUE)
        self.assertEqual(compiled.rails[0].participants, ["vian"])
        self.assertEqual(compiled.rails[0].channel, ExpressionChannel.INTERNAL)
        self.assertIn("canon_commit: forbidden", compiled.rendered_text)
        self.assertIn("seed: ihhh malu banget tau", compiled.rendered_text)

    def test_whisper_is_audible_speech_not_internal_thought(self):
        compiled = CharacterRailParser.parse('/mono @vian whisper "malu banget"')
        rail = compiled.rails[0]
        self.assertEqual(rail.channel, ExpressionChannel.SPEECH)
        self.assertEqual(rail.delivery, "whisper")

    def test_dialogue_is_beat_driven_and_parses_compact_mentions(self):
        compiled = CharacterRailParser.parse('/dia @vian@fano slow curve=wave "main game"')
        rail = compiled.rails[0]
        self.assertEqual(rail.kind, RailKind.DIALOGUE)
        self.assertEqual(rail.participants, ["vian", "fano"])
        self.assertEqual(rail.pacing, RailPacing.SLOW)
        self.assertEqual(rail.intensity_curve, "wave")
        self.assertEqual(rail.seed, "main game")
        self.assertIn("not alternating-turn quotas", compiled.rendered_text)

    def test_solo_intimacy_uses_shared_scene_dynamics(self):
        compiled = CharacterRailParser.parse('/intimacy @vian solo slow "vulnerability and aftermath"')
        rail = compiled.rails[0]
        self.assertEqual(rail.mode, "solo")
        self.assertEqual(rail.pacing, RailPacing.SLOW)
        self.assertEqual(rail.seed, "vulnerability and aftermath")

    def test_rail_lines_are_removed_from_semantic_evidence(self):
        compiled = CharacterRailParser.parse(
            '/dia @vian@fano "main game"\nFano is standing beside the apartment door.'
        )
        self.assertEqual(compiled.evidence_prompt, "Fano is standing beside the apartment door.")
        self.assertNotIn("main game", compiled.evidence_prompt)
        self.assertEqual(
            _strip_persisted_rail_lines('USER: /mono @vian "embarrassed"\nASSISTANT: previous prose'),
            "ASSISTANT: previous prose",
        )

    def test_rail_query_routes_to_story_continue_and_traces_time_axes(self):
        scope = MemoryQueryContext(world_time="2026-01-02T00:00:00Z", story_order=4)
        plan = QueryCompiler(_NoEntities()).compile('/dia @vian@fano "main game"', scope)
        self.assertEqual(plan.route, QueryRoute.STORY_CONTINUE)
        self.assertIn("character_rails", plan.predicates)
        self.assertEqual(plan.world_time_range, {"at": "2026-01-02T00:00:00Z"})
        self.assertEqual(plan.story_order_range, (4, 4))

    def test_world_time_only_orders_values_that_are_actually_comparable(self):
        self.assertEqual(compare_world_time("2026-01-01", "2026-01-02"), -1)
        self.assertEqual(compare_world_time(2, 1), 1)
        self.assertEqual(compare_world_time("Day Ten", "Day Ten"), 0)
        self.assertIsNone(compare_world_time("Day Ten", "Day Two"))

    def test_dual_axis_temporal_state_reconstructs_and_supersedes(self):
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(Path(td) / "memory.db")
            first = store.transition_state(
                world_id="WORLD", branch_id=None, owner_type="entity_variant", owner_id="VIAN",
                state_key="location", value="apartment", story_order=1,
                world_time="2026-01-01T20:00:00Z", source_type="timeline_event", source_id="E1",
            )
            second = store.transition_state(
                world_id="WORLD", branch_id=None, owner_type="entity_variant", owner_id="VIAN",
                state_key="location", value="campus", story_order=2,
                world_time="2026-01-02T08:00:00Z", source_type="timeline_event", source_id="E2",
            )
            self.assertEqual(second["superseded_interval_id"], first["interval"]["id"])

            at_first = store.state_at(
                world_id="WORLD", branch_id=None, owner_type="entity_variant", owner_id="VIAN",
                story_order=1, world_time="2026-01-01T21:00:00Z",
            )
            at_second = store.state_at(
                world_id="WORLD", branch_id=None, owner_type="entity_variant", owner_id="VIAN",
                story_order=2, world_time="2026-01-02T09:00:00Z",
            )
            self.assertEqual(at_first[0]["value"], "apartment")
            self.assertEqual(at_second[0]["value"], "campus")
            current = store.query_current_state("WORLD", None, "entity_variant", "VIAN", "location")
            self.assertEqual(current[0]["value"], "campus")

            with self.assertRaises(ValueError):
                store.transition_state(
                    world_id="WORLD", branch_id=None, owner_type="entity_variant", owner_id="VIAN",
                    state_key="location", value="impossible", story_order=1.5,
                    world_time="2026-01-03T00:00:00Z",
                )

    def test_chat_memory_does_not_index_rail_seed_as_user_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "arline.db"
            history = HistoryStore(db, backup_before_migration=False)
            session = history.create_session(prompt="start", project_id="P")
            turn = history.add_turn(
                session["id"], run_id="R1",
                user_prompt='/dia @vian@fano "secret game topic"\nThe apartment door is open.',
                story="Fano notices the open door.", model="m", mode="smart_hybrid",
                reasoning="off", projection_mode="off",
            )
            store = MemoryStore(db)
            indexer = MemoryIndexer(store=store, workspace=_NoEntities(), history=history, config=MemoryConfig())
            indexer.index_turn({
                **turn, "project_id": "P", "world_id": None, "branch_id": None,
                "scratch_mode": False, "parent_session_id": None, "forked_from_turn_id": None,
            })
            self.assertEqual(store.search_fts("secret game topic", domains=["chat"], limit=10), [])
            self.assertTrue(store.search_fts("apartment door", domains=["chat"], limit=10))
            self.assertTrue(store.search_fts("notices open door", domains=["chat"], limit=10))


if __name__ == "__main__":
    unittest.main()
