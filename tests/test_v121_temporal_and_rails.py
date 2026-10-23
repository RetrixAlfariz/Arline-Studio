from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.history.store import HistoryStore
from src.memory import (
    EmbeddingConfig,
    MemoryConfig,
    MemoryQueryContext,
    MemoryQueryEngine,
    MemoryStore,
    QueryCompiler,
    QueryRoute,
    RetrievalLane,
    TimelineStateProjector,
    compare_world_time,
)
from src.memory.index import MemoryIndexer
from src.narrative.rails import CharacterRailParser, ExpressionChannel, RailKind, RailPacing
from src.service.v121_rails import _strip_persisted_rail_lines
from src.workspace.store import WorkspaceStore


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

    def test_rail_query_keeps_dense_as_optional_hybrid_lane(self):
        config = MemoryConfig(
            dense_enabled=True,
            embedding=EmbeddingConfig(enabled=True, provider="lmstudio", model="text-embedding-bge-m3", dimension=1024),
        )
        plan = QueryCompiler(_NoEntities(), config=config).compile('/dia @vian@fano "main game"', MemoryQueryContext())
        self.assertEqual(plan.route, QueryRoute.STORY_CONTINUE)
        self.assertIn(RetrievalLane.STRUCTURED_STATE, plan.optional_lanes)
        self.assertIn(RetrievalLane.FTS_MANUSCRIPT, plan.optional_lanes)
        self.assertIn(RetrievalLane.DENSE, plan.optional_lanes)

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

    def test_timeline_projector_is_idempotent_and_backfill_integrated(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "arline.db"
            workspace = WorkspaceStore(db, backup_before_migration=False)
            history = HistoryStore(db, backup_before_migration=False)
            project = workspace.create_project("Temporal fixture")
            world_id = project["default_world_id"]
            branch = next(item for item in workspace.get_world(world_id)["branches"] if item["kind"] == "main")
            family = workspace.create_entity_family(None, "Vian", shared_core={"role": "protagonist"})
            variant = workspace.create_variant(family["id"], world_id, branch_id=branch["id"], canon_status="canon")
            workspace.add_timeline_event(
                world_id=world_id, branch_id=branch["id"], owner_type="entity_variant", owner_id=variant["id"],
                time_label="2026-01-01T20:00:00Z", order_key=1, summary="Vian is at the apartment.",
                state_patch={"location": "apartment"}, status="canon",
            )
            workspace.add_timeline_event(
                world_id=world_id, branch_id=branch["id"], owner_type="entity_variant", owner_id=variant["id"],
                time_label="2026-01-02T08:00:00Z", order_key=2, summary="Vian reaches campus.",
                state_patch={"location": "campus"}, status="canon",
            )

            store = MemoryStore(db)
            projector = TimelineStateProjector(store=store, workspace=workspace)
            first = projector.project_world(world_id, branch_id=branch["id"])
            second = projector.project_world(world_id, branch_id=branch["id"])
            self.assertEqual(first.intervals, 2)
            self.assertEqual(second.intervals, 2)
            with store.connection() as con:
                count = con.execute(
                    "SELECT COUNT(*) FROM state_intervals WHERE world_id=? AND branch_id=? AND owner_id=? "
                    "AND state_key='location' AND source_type='timeline_event' AND status='accepted'",
                    (world_id, branch["id"], variant["id"]),
                ).fetchone()[0]
            self.assertEqual(count, 2)
            at_first = store.state_at(
                world_id=world_id, branch_id=branch["id"], owner_type="entity_variant", owner_id=variant["id"],
                story_order=1, world_time="2026-01-01T21:00:00Z",
            )
            at_second = store.state_at(
                world_id=world_id, branch_id=branch["id"], owner_type="entity_variant", owner_id=variant["id"],
                story_order=2, world_time="2026-01-02T09:00:00Z",
            )
            self.assertEqual(at_first[0]["value"], "apartment")
            self.assertEqual(at_second[0]["value"], "campus")

            indexer = MemoryIndexer(store=store, workspace=workspace, history=history, config=MemoryConfig())
            backfill = indexer.backfill(project["id"])
            self.assertIn("timeline_state", backfill)
            self.assertGreaterEqual(backfill["timeline_state"]["intervals"], 2)

    def test_character_rail_retrieval_uses_library_profiles_and_relationships(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "arline.db"
            workspace = WorkspaceStore(db, backup_before_migration=False)
            project = workspace.create_project("Character rail fixture")
            world_id = project["default_world_id"]
            branch = next(item for item in workspace.get_world(world_id)["branches"] if item["kind"] == "main")

            vian_family = workspace.create_entity_family(
                None, "Vian", shared_core={"personality": "talkative but withdrawn while sulking"}
            )
            fano_family = workspace.create_entity_family(
                None, "Fano", shared_core={"personality": "calm and observant"}
            )
            vian = workspace.create_variant(
                vian_family["id"], world_id, branch_id=branch["id"], canon_status="canon",
                summary="Usually casual around Fano.", voice={"dialogue": "casual and reactive"},
                current_state={"mood": "sulking"},
            )
            fano = workspace.create_variant(
                fano_family["id"], world_id, branch_id=branch["id"], canon_status="canon",
                summary="Notices when Vian withdraws.", voice={"dialogue": "calm, concise"},
            )
            relationship = workspace.create_relationship(
                world_id, vian["id"], fano["id"], "close_friend",
                branch_id=branch["id"], canon_status="canon", attributes={"dynamic": "teasing but attentive"},
            )

            engine = MemoryQueryEngine(store=MemoryStore(db), workspace=workspace, config=MemoryConfig())
            result = engine.execute(
                '/dia @Vian@Fano slow "main game"',
                MemoryQueryContext(
                    project_id=project["id"], world_id=world_id, branch_id=branch["id"], story_order=1,
                ),
            )
            profile_sources = {
                item.source_id for item in result.selected if item.metadata.get("character_profile")
            }
            relationship_sources = {
                item.source_id for item in result.selected if item.metadata.get("relationship")
            }
            self.assertIn(vian["id"], profile_sources)
            self.assertIn(fano["id"], profile_sources)
            self.assertIn(relationship["id"], relationship_sources)
            self.assertFalse(result.abstain)

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
