from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.history.store import HistoryStore
from src.memory import MemoryQueryContext, MemoryStore, ScopeGate
from src.memory.models import MemoryCandidate, RetrievalLane


class _Workspace:
    def get_branch(self, branch_id):
        raise KeyError(branch_id)


class NestedForkCutoffTests(unittest.TestCase):
    def test_nested_chat_forks_keep_each_parent_cutoff(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "arline.db"
            history = HistoryStore(db, backup_before_migration=False)
            root = history.create_session(prompt="root", project_id="P")
            root_turns = [
                history.add_turn(root["id"], run_id=f"ROOT-{i}", user_prompt=f"u{i}", story=f"root {i}", model="m", mode="smart_hybrid", reasoning="off", projection_mode="off")
                for i in range(1, 4)
            ]
            child = history.fork_session(root["id"], through_turn_id=root_turns[1]["id"], title="child")
            child_turn = history.add_turn(child["id"], run_id="CHILD-NEW", user_prompt="child", story="child new", model="m", mode="smart_hybrid", reasoning="off", projection_mode="off")
            grandchild = history.fork_session(child["id"], through_turn_id=child_turn["id"], title="grandchild")

            gate = ScopeGate(_Workspace(), history)
            cutoffs = gate.session_cutoffs(grandchild["id"])
            self.assertIn(grandchild["id"], cutoffs)
            self.assertIn(child["id"], cutoffs)
            self.assertIn(root["id"], cutoffs)
            self.assertEqual(cutoffs[child["id"]], child_turn["id"])
            self.assertEqual(cutoffs[root["id"]], root_turns[1]["id"])

            after_root_fork = MemoryCandidate(
                id="late-root", lane=RetrievalLane.FTS_CHAT, source_type="chat_window",
                source_id=root_turns[2]["id"], text="root 3", session_id=root["id"], project_id="P",
            )
            decision = gate.evaluate(after_root_fork, MemoryQueryContext(project_id="P", session_id=grandchild["id"]))
            self.assertFalse(decision.allowed)
            self.assertEqual(decision.rule, "session_cutoff")


if __name__ == "__main__":
    unittest.main()
