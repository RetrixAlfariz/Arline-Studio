from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.memory import MemoryStore


class MemoryStoreTests(unittest.TestCase):
    def test_source_chunks_are_searchable_and_replaceable(self):
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(Path(td) / "memory.db")
            first = store.upsert_chunk(
                source_type="document", source_id="DOC-1", source_revision="1",
                text="Vian keeps the black dress inside the bedroom wardrobe.",
                project_id="P", world_id="W", branch_id="B",
            )
            self.assertEqual(store.get_chunk(first["id"])["semantic_status"], "active")
            results = store.search_fts("black dress wardrobe", domains=["manuscript"])
            self.assertTrue(any(item["id"] == first["id"] for item in results))
            # Source-level lifecycle is explicit so multi-chunk revisions can be
            # inserted atomically without each chunk invalidating its siblings.
            store.mark_source_status("document", "DOC-1", "stale")
            second = store.upsert_chunk(
                source_type="document", source_id="DOC-1", source_revision="2",
                text="Vian moved the black dress into the storage room.",
                project_id="P", world_id="W", branch_id="B",
            )
            self.assertNotEqual(first["id"], second["id"])
            self.assertEqual(store.get_chunk(first["id"])["semantic_status"], "stale")

    def test_spatial_graph_and_temporal_state(self):
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(Path(td) / "memory.db")
            room = store.create_spatial_edge(
                world_id="W", branch_id="B", subject_type="entity_family", subject_id="APARTMENT",
                relation="contains", object_type="entity_family", object_id="BEDROOM",
            )
            store.create_spatial_edge(
                world_id="W", branch_id="B", subject_type="entity_family", subject_id="BEDROOM",
                relation="contains", object_type="entity_family", object_id="WARDROBE",
            )
            store.create_spatial_edge(
                world_id="W", branch_id="B", subject_type="entity_family", subject_id="WARDROBE",
                relation="contains", object_type="entity_family", object_id="DRESS",
            )
            graph = store.spatial_neighborhood(
                world_id="W", branch_id="B", resource_type="entity_family", resource_id="APARTMENT", depth=4
            )
            self.assertEqual(len(graph["edges"]), 3)
            self.assertEqual(room["relation"], "contains")

            store.upsert_current_state(
                world_id="W", branch_id="B", owner_type="entity_variant", owner_id="V",
                state_key="location", value="BEDROOM", source_type="event", source_id="E1", authority="accepted_event",
            )
            self.assertEqual(store.query_current_state("W", "B", "entity_variant", "V")[0]["value"], "BEDROOM")
            store.add_state_interval(
                world_id="W", branch_id="B", owner_type="entity_variant", owner_id="V",
                state_key="location", value="APARTMENT", story_order_from=1, story_order_to=4,
                source_type="event", source_id="E0", authority="accepted_event",
            )
            self.assertEqual(store.state_at(world_id="W", branch_id="B", owner_type="entity_variant", owner_id="V", story_order=2)[0]["value"], "APARTMENT")

    def test_epistemic_and_threads(self):
        with tempfile.TemporaryDirectory() as td:
            store = MemoryStore(Path(td) / "memory.db")
            store.upsert_epistemic_interval(
                world_id="W", branch_id="B", character_variant_id="FANO",
                topic_type="fact", topic_id="SECRET", state_type="belief_formed",
                value={"believes": False}, confidence=0.7, story_order_from=3,
                source_type="event", source_id="E3",
            )
            state = store.query_epistemic(
                world_id="W", branch_id="B", character_variant_id="FANO",
                topic_type="fact", topic_id="SECRET", story_order=5,
            )
            self.assertEqual(state[0]["value"], {"believes": False})
            thread = store.create_thread(
                world_id="W", branch_id="B", thread_type="promise",
                title="Return Dawnblade", links=[{"resource_type": "entity_family", "resource_id": "FANO"}],
            )
            self.assertEqual(store.list_threads(world_id="W", branch_id="B", status="open")[0]["id"], thread["id"])


if __name__ == "__main__":
    unittest.main()
