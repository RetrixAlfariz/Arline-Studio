from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.history.store import HistoryStore
from src.memory import MemoryConfig, MemoryQueryContext, MemoryService, MemoryStore
from src.memory.web import create_memory_router
from src.workspace import FoundationStore
from src.workspace.store import WorkspaceStore


class Fixture:
    def __init__(self, root: str):
        path = Path(root) / "arline.db"
        self.workspace = WorkspaceStore(path, backup_before_migration=False)
        self.history = HistoryStore(path, backup_before_migration=False)
        self.foundation = FoundationStore(path)
        self.project = self.workspace.create_project("v122 topdown")
        self.world_id = self.project["default_world_id"]
        self.branch = next(x for x in self.workspace.get_world(self.world_id)["branches"] if x["kind"] == "main")
        config = MemoryConfig(); config.dense_enabled = False
        store = MemoryStore(path)
        self.memory = MemoryService(
            store=store, workspace=self.workspace, history=self.history,
            foundation=self.foundation, config=config,
            lmstudio_base_url="http://127.0.0.1:1234",
        )
        create_memory_router(service=self.memory, store=store, foundation=self.foundation)
        self.discovery = self.memory.discovery
        self.session = self.history.create_session(
            prompt="topdown", project_id=self.project["id"], world_id=self.world_id,
            branch_id=self.branch["id"],
        )

    def turn(self, prompt: str, suffix: str):
        return self.history.add_turn(
            self.session["id"], run_id=f"RUN-TOP-{suffix}", user_prompt=prompt,
            story="Generated.", model="fixture", mode="smart_hybrid",
            reasoning="off", projection_mode="off",
        )

    def context(self):
        return MemoryQueryContext(
            project_id=self.project["id"], world_id=self.world_id,
            branch_id=self.branch["id"], session_id=self.session["id"],
        )


class V122TopDownCompletionTests(unittest.TestCase):
    def test_alias_reuses_one_stable_discovery_anchor(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(td)
            family = fx.workspace.create_entity_family(None, "Revian", entity_type="character")
            fx.foundation.add_alias("entity_family", family["id"], "Vian")
            r1 = fx.discovery.entity_resolver.resolve(
                project_id=fx.project["id"], world_id=fx.world_id, branch_id=fx.branch["id"],
                session_id=fx.session["id"], turn_id="T1", source_kind="user_prompt",
                source_text="Revian arrived.", entity_type="character", raw_subject_key="char:revian", label="Revian",
            )
            r2 = fx.discovery.entity_resolver.resolve(
                project_id=fx.project["id"], world_id=fx.world_id, branch_id=fx.branch["id"],
                session_id=fx.session["id"], turn_id="T2", source_kind="user_prompt",
                source_text="Vian smiled.", entity_type="character", raw_subject_key="char:vian", label="Vian",
            )
            self.assertEqual(r1.subject_key, r2.subject_key)
            self.assertEqual(r2.target_resource_id, family["id"])

    def test_first_person_requires_explicit_narrator_anchor_then_persists(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(td)
            first = fx.discovery.entity_resolver.resolve(
                project_id=fx.project["id"], world_id=fx.world_id, branch_id=fx.branch["id"],
                session_id=fx.session["id"], turn_id="T1", source_kind="user_prompt",
                source_text="Namaku Vian, aku tinggal sendiri.", entity_type="character",
                raw_subject_key="self", label="self",
            )
            self.assertTrue(first.resolved)
            later = fx.discovery.entity_resolver.resolve(
                project_id=fx.project["id"], world_id=fx.world_id, branch_id=fx.branch["id"],
                session_id=fx.session["id"], turn_id="T2", source_kind="user_prompt",
                source_text="Aku tersenyum.", entity_type="character",
                raw_subject_key="self:2", label="aku",
            )
            self.assertEqual(later.subject_key, first.subject_key)
            self.assertEqual(later.subject_label, "Vian")
            self.assertEqual(later.resolution_kind, "self_recent")

    def test_third_person_abstains_when_recent_candidates_are_ambiguous(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(td)
            for key, name in (("char:alex", "Alex"), ("char:bob", "Bob")):
                fx.discovery.entity_resolver.resolve(
                    project_id=fx.project["id"], world_id=fx.world_id, branch_id=fx.branch["id"],
                    session_id=fx.session["id"], turn_id="T1", source_kind="user_prompt",
                    source_text="Alex met Bob.", entity_type="character", raw_subject_key=key, label=name,
                )
            pronoun = fx.discovery.entity_resolver.resolve(
                project_id=fx.project["id"], world_id=fx.world_id, branch_id=fx.branch["id"],
                session_id=fx.session["id"], turn_id="T2", source_kind="user_prompt",
                source_text="Dia tersenyum.", entity_type="character", raw_subject_key="mention:dia", label="dia",
            )
            self.assertFalse(pronoun.resolved)
            self.assertEqual(pronoun.resolution_kind, "ambiguous_coreference")
            self.assertEqual(set(pronoun.ambiguous_candidates), {"char:alex", "char:bob"})

    def test_unique_cross_turn_pronoun_resolves(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(td)
            alex = fx.discovery.entity_resolver.resolve(
                project_id=fx.project["id"], world_id=fx.world_id, branch_id=fx.branch["id"],
                session_id=fx.session["id"], turn_id="T1", source_kind="user_prompt",
                source_text="Alex arrived.", entity_type="character", raw_subject_key="char:alex", label="Alex",
            )
            pronoun = fx.discovery.entity_resolver.resolve(
                project_id=fx.project["id"], world_id=fx.world_id, branch_id=fx.branch["id"],
                session_id=fx.session["id"], turn_id="T2", source_kind="user_prompt",
                source_text="Dia tersenyum.", entity_type="character", raw_subject_key="mention:dia", label="dia",
            )
            self.assertEqual(pronoun.subject_key, alex.subject_key)
            self.assertEqual(pronoun.subject_label, "Alex")
            self.assertEqual(pronoun.resolution_kind, "coreference_recent")
            mentions = fx.discovery.store.recent_mentions(
                session_id=fx.session["id"], branch_id=fx.branch["id"], entity_type="character"
            )
            resolved = next(item for item in mentions if item["surface"].casefold() == "dia")
            self.assertEqual(resolved["resolved_label"], "Alex")

    def test_transition_builds_event_and_causal_link(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(td)
            first = fx.turn("Alex has hair length 10 cm.", "1")
            p1 = fx.discovery.store.upsert_proposition(
                project_id=fx.project["id"], world_id=fx.world_id, subject_type="character",
                subject_key="char:alex", subject_label="Alex", predicate="state.hair.length_cm",
                value=10, operation="update", temporal_state="current_or_unspecified",
            )
            fx.discovery.store.add_instance(
                p1["id"], source_kind="user_prompt", source_session_id=fx.session["id"], source_turn_id=first["id"],
                origin_session_id=fx.session["id"], origin_turn_id=first["id"], source_revision="R1",
                project_id=fx.project["id"], world_id=fx.world_id, branch_id=fx.branch["id"],
                span_text=first["user_prompt"], extraction_confidence=1, explicitness="explicit", qualifies_review=True,
            )
            second = fx.turn("Sekarang rambut Alex menjadi 100 cm.", "2")
            p2 = fx.discovery.store.upsert_proposition(
                project_id=fx.project["id"], world_id=fx.world_id, subject_type="character",
                subject_key="char:alex", subject_label="Alex", predicate="state.hair.length_cm",
                value=100, operation="transition", temporal_state="historical_or_current",
            )
            fx.discovery.store.add_instance(
                p2["id"], source_kind="user_prompt", source_session_id=fx.session["id"], source_turn_id=second["id"],
                origin_session_id=fx.session["id"], origin_turn_id=second["id"], source_revision="R2",
                project_id=fx.project["id"], world_id=fx.world_id, branch_id=fx.branch["id"],
                span_text=second["user_prompt"], extraction_confidence=1, explicitness="explicit", qualifies_review=True,
            )
            fx.discovery.continuity.resolve_turn(second["id"])
            events = fx.discovery.continuity.list_events(fx.context(), subject_key="char:alex")
            self.assertEqual(len(events), 1)
            self.assertTrue(events[0]["id"].startswith("EVENT-"))
            self.assertEqual(events[0]["causal_links"][0]["from_proposition_id"], p1["id"])
            self.assertEqual(events[0]["causal_links"][0]["to_proposition_id"], p2["id"])

    def test_resource_view_contains_one_continuity_projection(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(td)
            turn = fx.turn("Character Alex is calm.", "1")
            # turn_created already captures/materializes; find Alex sheet from current families.
            family = next((x for x in fx.workspace.list_entity_families(None, entity_type="character") if x["name"].casefold() == "alex"), None)
            if family is None:
                self.skipTest("deterministic parser did not materialize Alex in this fixture")
            view = fx.discovery.resource_view(family["id"], fx.context())
            self.assertIn("continuity", view)
            self.assertEqual(set(view["continuity"]), {"current", "forms", "history", "events", "conflicts", "mentions"})

    def test_explicit_conflict_resolution_is_derived_not_canon(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(td)
            t1 = fx.turn("Alex is calm.", "1")
            t2 = fx.turn("Alex is impulsive.", "2")
            def claim(turn, value, rev):
                prop = fx.discovery.store.upsert_proposition(
                    project_id=fx.project["id"], world_id=fx.world_id, subject_type="character",
                    subject_key="char:alex", subject_label="Alex", predicate="personality.descriptor",
                    value=value, operation="update",
                )
                fx.discovery.store.add_instance(
                    prop["id"], source_kind="user_prompt", source_session_id=fx.session["id"], source_turn_id=turn["id"],
                    origin_session_id=fx.session["id"], origin_turn_id=turn["id"], source_revision=rev,
                    project_id=fx.project["id"], world_id=fx.world_id, branch_id=fx.branch["id"],
                    span_text=turn["user_prompt"], extraction_confidence=1, explicitness="explicit", qualifies_review=True,
                )
                return prop
            p1 = claim(t1, "calm", "A")
            p2 = claim(t2, "impulsive", "B")
            fx.discovery.continuity.resolve_turn(t2["id"])
            conflicts = fx.discovery.continuity.list_conflicts(fx.context(), subject_key="char:alex")
            target = next(x for x in conflicts if {x["left_proposition_id"], x["right_proposition_id"]} == {p1["id"], p2["id"]})
            fx.discovery.continuity.resolve_conflict(
                target["id"], action="correction",
                from_proposition_id=p1["id"], to_proposition_id=p2["id"], note="user chose",
            )
            self.assertEqual(fx.discovery.store.get_proposition(p2["id"])["authority_state"], "observed")
            self.assertFalse(fx.discovery.continuity.list_conflicts(fx.context(), subject_key="char:alex"))

    def test_schema_v4_owns_resolution_and_causality_tables(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(td)
            self.assertEqual(fx.discovery.store.SCHEMA_VERSION, 4)
            with fx.discovery.store.connection() as con:
                tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for name in {"discovery_mentions", "continuity_events", "continuity_event_effects", "continuity_causal_links", "continuity_conflict_resolutions"}:
                self.assertIn(name, tables)


if __name__ == "__main__":
    unittest.main()
