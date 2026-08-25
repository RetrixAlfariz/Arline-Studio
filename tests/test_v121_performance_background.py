from __future__ import annotations

from threading import RLock
from time import monotonic
import time
import unittest

from src.discovery.performance_background import install_background_materialization


class _Service:
    def __init__(self, pending_sequence):
        self.pending_sequence = list(pending_sequence)
        self.calls = 0
        self._performance_metrics = {}

    def materialize_existing(self, *, limit=5000):
        self.calls += 1
        pending = self.pending_sequence.pop(0) if self.pending_sequence else 0
        return {"processed": 1, "pending": pending, "limit": limit}


class _GuardedService(_Service):
    def __init__(self, pending_sequence):
        super().__init__(pending_sequence)
        self._provisional_materialization_lock = RLock()
        self._provisional_last_turn_materialized_at = 0.0


def _wait_done(service, timeout: float = 1.5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = service.background_materialization_status()
        if status["completed"]:
            return status
        time.sleep(0.01)
    return service.background_materialization_status()


class V121PerformanceBackgroundTests(unittest.TestCase):
    def test_install_does_zero_database_work_before_app_ready(self):
        service = _Service([0])
        install_background_materialization(service)
        status = service.background_materialization_status()
        self.assertEqual(service.calls, 0)
        self.assertEqual(status["pending"], -1)
        self.assertFalse(status["completed"])
        self.assertTrue(status["scheduled"])

        # Tests can accelerate the already-scheduled daemon without changing the
        # production startup contract.
        service.schedule_materialization_drain(delay=0.01)
        status = _wait_done(service)
        self.assertTrue(status["completed"])
        self.assertEqual(status["pending"], 0)
        self.assertEqual(service.calls, 1)

    def test_backlog_is_drained_after_startup_in_daemon_batches(self):
        service = _Service([2, 0])
        install_background_materialization(service)
        self.assertEqual(service.calls, 0)
        service.schedule_materialization_drain(delay=0.01)
        status = _wait_done(service)
        self.assertTrue(status["completed"])
        self.assertEqual(status["pending"], 0)
        self.assertGreaterEqual(service.calls, 2)
        self.assertGreaterEqual(status["processed"], 2)
        self.assertIn("background_materialization", service._performance_metrics)

    def test_explicit_backfill_restarts_a_pending_drain(self):
        service = _Service([0])
        install_background_materialization(service)
        self.assertEqual(service.calls, 0)

        # Explicit work is allowed to run now; any residue returns to the daemon.
        service.pending_sequence = [3, 0]
        report = service.materialize_existing(limit=64)
        self.assertEqual(report["pending"], 3)
        service.schedule_materialization_drain(delay=0.01)
        status = _wait_done(service)
        self.assertTrue(status["completed"])
        self.assertEqual(status["pending"], 0)

    def test_background_yields_after_foreground_materialization(self):
        service = _GuardedService([0])
        install_background_materialization(service)
        service._provisional_last_turn_materialized_at = monotonic()
        service.schedule_materialization_drain(delay=0.01)
        time.sleep(0.08)
        self.assertEqual(service.calls, 0)
        status = service.background_materialization_status()
        self.assertTrue(status["scheduled"])
        self.assertFalse(status["running"])

        # Once the foreground quiet marker is old, the same daemon may proceed.
        service._provisional_last_turn_materialized_at = 0.0
        service.schedule_materialization_drain(delay=0.01)
        status = _wait_done(service)
        self.assertTrue(status["completed"])
        self.assertEqual(service.calls, 1)


if __name__ == "__main__":
    unittest.main()
