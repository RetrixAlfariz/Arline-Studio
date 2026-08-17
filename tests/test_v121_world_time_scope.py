from __future__ import annotations

import unittest

from src.memory import ContextLens, MemoryCandidate, MemoryQueryContext, RetrievalLane, ScopeGate


class _Workspace:
    def get_branch(self, branch_id):
        raise KeyError(branch_id)


class V121WorldTimeScopeTests(unittest.TestCase):
    def test_scene_lens_blocks_comparable_future_world_time(self):
        candidate = MemoryCandidate(
            id="FUTURE", lane=RetrievalLane.FTS_MANUSCRIPT,
            text="future evidence", source_type="document", source_id="DOC",
            world_id="WORLD", branch_id=None, world_time="2026-01-03T00:00:00Z",
        )
        context = MemoryQueryContext(
            world_id="WORLD", branch_id=None, world_time="2026-01-02T00:00:00Z",
            context_lens=ContextLens.SCENE,
        )
        decision = ScopeGate(_Workspace()).evaluate(candidate, context)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.rule, "world_time")

    def test_author_lens_can_explicitly_allow_future_world_time(self):
        candidate = MemoryCandidate(
            id="FUTURE", lane=RetrievalLane.FTS_MANUSCRIPT,
            text="future evidence", source_type="document", source_id="DOC",
            world_id="WORLD", branch_id=None, world_time="2026-01-03T00:00:00Z",
        )
        context = MemoryQueryContext(
            world_id="WORLD", branch_id=None, world_time="2026-01-02T00:00:00Z",
            context_lens=ContextLens.AUTHOR, allow_future_author_knowledge=True,
        )
        decision = ScopeGate(_Workspace()).evaluate(candidate, context)
        self.assertTrue(decision.allowed)

    def test_opaque_world_time_labels_do_not_invent_future_order(self):
        candidate = MemoryCandidate(
            id="OPAQUE", lane=RetrievalLane.FTS_MANUSCRIPT,
            text="opaque evidence", source_type="document", source_id="DOC",
            world_id="WORLD", branch_id=None, world_time="Day Ten",
        )
        context = MemoryQueryContext(
            world_id="WORLD", branch_id=None, world_time="Day Two", context_lens=ContextLens.SCENE,
        )
        decision = ScopeGate(_Workspace()).evaluate(candidate, context)
        self.assertTrue(decision.allowed)


if __name__ == "__main__":
    unittest.main()
