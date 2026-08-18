from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.discovery import DiscoveryService, DiscoveryStore, install_discovery_memory_bridge
from src.history import HistoryStore
from src.memory import MemoryConfig, MemoryQueryContext, MemoryQueryEngine, MemoryStore
from src.workspace import FoundationStore, WorkspaceStore
from src.workspace.store import WORLD_BIBLE_BRANCH_ID, WORLD_BIBLE_WORLD_ID


class DiscoveryHarness:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "arline.db"
        self.workspace = WorkspaceStore(self.path)
        self.foundation = FoundationStore(self.path)
        self.history = HistoryStore(self.path)
        self.store = DiscoveryStore(self.path, backup_before_migration=False)
        self.service = DiscoveryService(
            store=self.store, workspace=self.workspace, history=self.history, foundation=self.foundation
        )
        self.project = self.workspace.create_project("Discovery Test")

    def close(self):
        self.tmp.cleanup()

    def session(self, title="Root"):
        return self.history.create_session(
            prompt="start", title=title, project_id=self.project["id"],
            world_id=WORLD_BIBLE_WORLD_ID, branch_id=WORLD_BIBLE_BRANCH_ID,
        )

    def turn(self, session_id, prompt="CharacterA has a blue notebook."):
        return self.history.add_turn(
            session_id, run_id=f"RUN-{prompt[:8]}", user_prompt=prompt, story="",
            model="test", mode="smart_hybrid", reasoning="off", projection_mode="balanced",
            workspace_scope={}, lineage={},
        )

    def proposition(self, label="CharacterA", predicate="likes", value="tea"):
        return self.store.upsert_proposition(
            project_id=self.project["id"], world_id=WORLD_BIBLE_WORLD_ID,
            subject_type="character", subject_key=f"char:{label.lower()}", subject_label=label,
            predicate=predicate, value=value, operation="update",
        )

    def support(self, prop, session, turn, *, source_kind="user_prompt", qualifies=True):
        return self.store.add_instance(
            prop["id"], source_kind=source_kind,
            source_session_id=session["id"], source_turn_id=turn["id"],
            origin_session_id=session["id"], origin_turn_id=turn["id"],
            source_revision=f"rev-{turn['id']}-{source_kind}",
            project_id=self.project["id"], world_id=WORLD_BIBLE_WORLD_ID,
            branch_id=WORLD_BIBLE_BRANCH_ID, source_segment="seg",
            span_start=0, span_end=10, span_text=turn.get("user_prompt") or "evidence",
            extraction_confidence=1.0, explicitness="explicit", qualifies_review=qualifies,
        )

    def context(self, session_id=None):
        return MemoryQueryContext(
            project_id=self.project["id"], world_id=WORLD_BIBLE_WORLD_ID,
            branch_id=WORLD_BIBLE_BRANCH_ID, session_id=session_id,
        )


class V121DiscoveryProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.h = DiscoveryHarness()

    def tearDown(self):
        self.h.close()

    def test_one_support_is_detected_two_user_sources_are_reviewed(self):
        session = self.h.session()
        first = self.h.turn(session["id"], "CharacterA likes tea.")
        prop = self.h.proposition()
        self.h.support(prop, session, first)
        item = self.h.service.get(prop["id"], self.h.context(session["id"]))
        self.assertEqual(item["knowledge_state"], "detected")
        second = self.h.turn(session["id"], "CharacterA again chooses tea.")
        self.h.support(prop, session, second)
        item = self.h.service.get(prop["id"], self.h.context(session["id"]))
        self.assertEqual(item["knowledge_state"], "reviewed")
        self.assertEqual(item["qualified_support_count"], 2)

    def test_child_fork_only_sees_parent_through_cutoff(self):
        parent = self.h.session()
        first = self.h.turn(parent["id"], "CharacterA likes tea.")
        prop = self.h.proposition()
        self.h.support(prop, parent, first)
        child = self.h.history.fork_session(parent["id"], through_turn_id=first["id"], title="Child")
        second = self.h.turn(parent["id"], "CharacterA still chooses tea.")
        self.h.support(prop, parent, second)

        parent_state = self.h.service.get(prop["id"], self.h.context(parent["id"]))
        child_state = self.h.service.get(prop["id"], self.h.context(child["id"]))
        self.assertEqual(parent_state["knowledge_state"], "reviewed")
        self.assertEqual(child_state["knowledge_state"], "detected")
        self.assertEqual(child_state["qualified_support_count"], 1)

    def test_fork_copy_does_not_create_independent_discovery_support(self):
        parent = self.h.session()
        first = self.h.turn(parent["id"], "CharacterA likes tea.")
        prop = self.h.proposition()
        self.h.support(prop, parent, first)
        before = len(self.h.store.list_instances(prop["id"]))
        self.h.history.fork_session(parent["id"], through_turn_id=first["id"], title="Child")
        after = len(self.h.store.list_instances(prop["id"]))
        self.assertEqual(before, after)

    def test_reviewed_degrades_when_support_is_invalidated(self):
        session = self.h.session()
        first = self.h.turn(session["id"], "CharacterA likes tea.")
        second = self.h.turn(session["id"], "CharacterA again chooses tea.")
        prop = self.h.proposition()
        self.h.support(prop, session, first)
        self.h.support(prop, session, second)
        self.assertEqual(self.h.service.get(prop["id"], self.h.context(session["id"]))["knowledge_state"], "reviewed")
        self.h.store.set_source_active(turn_id=second["id"], active=False, reason="source_deleted")
        item = self.h.service.get(prop["id"], self.h.context(session["id"]))
        self.assertEqual(item["knowledge_state"], "detected")
        self.assertEqual(item["provenance_state"], "partial")

    def test_canon_survives_source_invalidation(self):
        session = self.h.session()
        turn = self.h.turn(session["id"], "CharacterA likes tea.")
        prop = self.h.proposition()
        self.h.support(prop, session, turn)
        self.h.store.set_authority(prop["id"], "canon", note="explicit user decision")
        self.h.service.set_session_active(session["id"], active=False, reason="source_deleted")
        item = self.h.service.get(prop["id"], self.h.context(session["id"]))
        self.assertEqual(item["knowledge_state"], "canon")
        self.assertEqual(item["provenance_state"], "orphaned")

    def test_accepted_generation_cannot_self_promote_to_reviewed(self):
        session = self.h.session()
        user_turn = self.h.turn(session["id"], "CharacterA likes tea.")
        generated_turn = self.h.turn(session["id"], "continue")
        prop = self.h.proposition()
        self.h.support(prop, session, user_turn, source_kind="user_prompt", qualifies=True)
        self.h.support(prop, session, generated_turn, source_kind="accepted_generation", qualifies=False)
        item = self.h.service.get(prop["id"], self.h.context(session["id"]))
        self.assertEqual(item["knowledge_state"], "detected")
        self.assertEqual(item["qualified_support_count"], 1)
        self.h.support(prop, session, generated_turn, source_kind="user_edited_prose", qualifies=True)
        self.assertEqual(self.h.service.get(prop["id"], self.h.context(session["id"]))["knowledge_state"], "reviewed")

    def test_rail_seed_is_not_discovery_evidence(self):
        session = self.h.session()
        turn = self.h.turn(session["id"], '/dia @characterA@characterB "marriage"')
        report = self.h.service.capture_turn(turn["id"])
        self.assertEqual(report.instances, 0)
        self.assertEqual(report.propositions, 0)

    def test_capture_can_emit_multiple_components_and_is_idempotent(self):
        session = self.h.session()
        turn = self.h.turn(
            session["id"],
            "Namaku CharacterA. Aku tinggal di sebuah apartemen luas di Surabaya, lantai 3, luas 56m.",
        )
        first = self.h.service.capture_turn(turn["id"])
        before = self.h.store.status()["instances"]
        second = self.h.service.capture_turn(turn["id"])
        after = self.h.store.status()["instances"]
        self.assertGreaterEqual(first.propositions, 2)
        self.assertGreaterEqual(first.instances, 2)
        self.assertEqual(before, after)
        self.assertEqual(first.propositions, second.propositions)

    def test_memory_labels_discoveries_as_non_canon(self):
        session = self.h.session()
        first = self.h.turn(session["id"], "CharacterA likes tea.")
        second = self.h.turn(session["id"], "CharacterA again chooses tea.")
        prop = self.h.proposition()
        self.h.support(prop, session, first)
        self.h.support(prop, session, second)

        install_discovery_memory_bridge()
        memory_store = MemoryStore(self.h.path)
        config = MemoryConfig()
        config.fts_enabled = False
        config.dense_enabled = False
        engine = MemoryQueryEngine(
            store=memory_store, workspace=self.h.workspace, history=self.h.history,
            foundation=self.h.foundation, config=config,
        )
        engine.discovery = self.h.service
        engine.compiler.discovery = self.h.service
        result = engine.execute("continue the scene", self.h.context(session["id"]))
        self.assertIn("[DISCOVERED NON-CANON]", result.packed_text)
        self.assertNotIn("[ACCEPTED STATE]\n- [REVIEWED NON-CANON]", result.packed_text)


if __name__ == "__main__":
    unittest.main()
