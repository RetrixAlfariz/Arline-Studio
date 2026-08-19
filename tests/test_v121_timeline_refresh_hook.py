from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.domain_events import clear_domain_event_bus, emit_domain_event
from src.memory.web import create_memory_router


class _Workspace:
    def __init__(self, path: Path):
        self.path = path
        self.created: list[dict] = []

    def add_timeline_event(self, **kwargs):
        event = {
            "id": "EVENT-1",
            "world_id": kwargs["world_id"],
            "branch_id": kwargs.get("branch_id"),
            "summary": kwargs.get("summary", ""),
        }
        self.created.append(event)
        emit_domain_event(
            self.path,
            "workspace.timeline_event_created",
            {"event": event},
        )
        return event


class _Store:
    def __init__(self, path: Path):
        self.path = path


class _Service:
    def __init__(self, path: Path, *, fail_refresh: bool = False):
        self.workspace = _Workspace(path)
        self.fail_refresh = fail_refresh
        self.refreshes: list[tuple[str, str | None]] = []
        self.failures: list[tuple[str, str]] = []

    def refresh_timeline_state(self, world_id, branch_id=None):
        self.refreshes.append((world_id, branch_id))
        if self.fail_refresh:
            raise RuntimeError("projection failed")
        return {"worlds": 1}

    def _report_refresh_failure(self, key, exc):
        self.failures.append((key, str(exc)))


class V121TimelineRefreshHookTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "arline.db"
        clear_domain_event_bus(self.path)

    def tearDown(self):
        clear_domain_event_bus(self.path)
        self.tmp.cleanup()

    def test_router_subscribes_timeline_refresh_without_replacing_workspace_method(self):
        service = _Service(self.path)
        original = service.workspace.add_timeline_event
        create_memory_router(service=service, store=_Store(self.path))

        # The authoritative Workspace method remains the method it was before
        # Memory attached; Memory observes the post-commit domain event instead.
        self.assertEqual(service.workspace.add_timeline_event, original)
        event = service.workspace.add_timeline_event(
            world_id="WORLD", branch_id="BRANCH", summary="state changed"
        )
        self.assertEqual(event["id"], "EVENT-1")
        self.assertEqual(service.refreshes, [("WORLD", "BRANCH")])
        self.assertTrue(service._v121_timeline_refresh_hook_bound)

    def test_projection_failure_does_not_roll_back_authoritative_timeline_event(self):
        service = _Service(self.path, fail_refresh=True)
        create_memory_router(service=service, store=_Store(self.path))
        event = service.workspace.add_timeline_event(
            world_id="WORLD", summary="authoritative event"
        )
        self.assertEqual(event["summary"], "authoritative event")
        self.assertEqual(len(service.workspace.created), 1)
        self.assertEqual(service.failures[0][0], "timeline:WORLD")
        self.assertIn("projection failed", service.failures[0][1])

    def test_subscription_is_idempotent(self):
        service = _Service(self.path)
        create_memory_router(service=service, store=_Store(self.path))
        create_memory_router(service=service, store=_Store(self.path))
        service.workspace.add_timeline_event(world_id="WORLD", summary="one event")
        self.assertEqual(service.refreshes, [("WORLD", None)])


if __name__ == "__main__":
    unittest.main()
