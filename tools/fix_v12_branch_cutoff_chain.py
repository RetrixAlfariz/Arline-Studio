from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
scope_path = ROOT / "src/memory/scope.py"
scope = scope_path.read_text(encoding="utf-8")
old = '''    def branch_cutoffs(self, branch_id: str | None) -> dict[str | None, dict[str, Any]]:
        result: dict[str | None, dict[str, Any]] = {None: {"max_story_order": None, "fork_event_id": None}}
        current = branch_id
        inherited_cutoff: float | None = None
        guard = 0
        while current and guard < 128:
            metadata = self.memory_store.get_branch_fork_metadata(current) if self.memory_store is not None else None
            result[current] = {
                "max_story_order": inherited_cutoff,
                "fork_event_id": (metadata or {}).get("fork_event_id"),
                "fork_world_time": (metadata or {}).get("fork_world_time"),
            }
            try:
                branch = self.workspace.get_branch(current)
            except KeyError:
                break
            parent = branch.get("parent_branch_id")
            if metadata and metadata.get("fork_story_order") is not None:
                cutoff = float(metadata["fork_story_order"])
                inherited_cutoff = cutoff if inherited_cutoff is None else min(inherited_cutoff, cutoff)
            current = parent
            guard += 1
        return result
'''
new = '''    def branch_cutoffs(self, branch_id: str | None) -> dict[str | None, dict[str, Any]]:
        result: dict[str | None, dict[str, Any]] = {None: {"max_story_order": None, "fork_event_id": None}}
        current = branch_id
        if current:
            result[current] = {"max_story_order": None, "fork_event_id": None, "fork_world_time": None}
        guard = 0
        while current and guard < 128:
            metadata = self.memory_store.get_branch_fork_metadata(current) if self.memory_store is not None else None
            try:
                branch = self.workspace.get_branch(current)
            except KeyError:
                break
            parent = branch.get("parent_branch_id")
            if not parent:
                break
            # The fork metadata belongs to the edge current -> parent. Each
            # ancestor therefore receives its own cutoff, not a propagated min.
            result[parent] = {
                "max_story_order": (metadata or {}).get("fork_story_order"),
                "fork_event_id": (metadata or {}).get("fork_event_id"),
                "fork_world_time": (metadata or {}).get("fork_world_time"),
            }
            current = parent
            guard += 1
        return result
'''
if old in scope:
    scope = scope.replace(old, new, 1)
elif "def branch_cutoffs" not in scope:
    raise RuntimeError("Branch cutoff implementation missing")
scope_path.write_text(scope, encoding="utf-8")

test_path = ROOT / "tests/memory/test_scope_and_security.py"
test = test_path.read_text(encoding="utf-8")
if "story_order=30" not in test:
    test = test.replace(
        '        self.assertFalse(self.gate.evaluate(candidate(branch_id="MAIN", story_order=41), self.context).allowed)\n',
        '        self.assertFalse(self.gate.evaluate(candidate(branch_id="MAIN", story_order=41), self.context).allowed)\n        self.assertTrue(self.gate.evaluate(candidate(branch_id="MAIN", story_order=30), self.context).allowed)\n',
        1,
    )
test_path.write_text(test, encoding="utf-8")
print("Corrected nested branch cutoffs per ancestry edge")
