from __future__ import annotations

import unittest

from src.memory.web import create_memory_router


class _Workspace:
    def __init__(self):
        self.created = []

    def add_timeline_event(self, **kwargs):
        event = {
            "id": "EVENT-1",
            "world_id": kwargs["world_id"],
            "branch_id": kwargs.get("branch_id"),
            "summary": kwargs.get("summary", ""),
        }
        self.created.append(event)
        return event


class _Service:
    def __init__(self, *, fail_refresh: bool = False):
        self.workspace = _Workspace()
        self.fail_refresh = fail_refresh
        self.refreshes = []
        self.failures = []

    def refresh_timeline_state(self, world_id, branch_id=None):
        self.refreshes.append((world_id, branch_id))
        if self.fail_refresh:
            raise RuntimeError("projection failed")
        return {"worlds": 1}

    def _report_refresh_failure(self, key, exc):
        self.failures.append((key, str(exc)))


class _Store:
    pass


class V121TimelineRefreshHookTests(unittest.TestCase):
    def test_router_binds_timeline_add_to_derived_refresh(self):
        service = _Service()
        create_memory_router(service=service, store=_Store())
        event = service.workspace.add_timeline_event(
            world_id="WORLD", branch_id="BRANCH", summary="state changed"
        )
        self.assertEqual(event["id"], "EVENT-1")
        self.assertEqual(service.refreshes, [("WORLD", "BRANCH")])
        self.assertTrue(service._v121_timeline_refresh_hook_bound)

    def test_projection_failure_does_not_roll_back_authoritative_timeline_event(self):
        service = _Service(fail_refresh=True)
        create_memory_router(service=service, store=_Store())
        event = service.workspace.add_timeline_event(world_id="WORLD", summary="authoritative event")
        self.assertEqual(event["summary"], "authoritative event")
        self.assertEqual(len(service.workspace.created), 1)
        self.assertEqual(service.failures[0][0], "timeline:WORLD")
        self.assertIn("projection failed", service.failures[0][1])

    def test_binding_is_idempotent(self):
        service = _Service()
        create_memory_router(service=service, store=_Store())
        create_memory_router(service=service, store=_Store())
        service.workspace.add_timeline_event(world_id="WORLD", summary="one event")
        self.assertEqual(service.refreshes, [("WORLD", None)])


if __name__ == "__main__":
    unittest.main()
