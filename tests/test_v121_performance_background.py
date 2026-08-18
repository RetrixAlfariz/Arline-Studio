from __future__ import annotations

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


class V121PerformanceBackgroundTests(unittest.TestCase):
    def test_no_backlog_finishes_without_long_lived_worker(self):
        service = _Service([0])
        install_background_materialization(service)
        status = service.background_materialization_status()
        self.assertTrue(status["completed"])
        self.assertEqual(status["pending"], 0)
        self.assertEqual(service.calls, 1)

    def test_backlog_is_drained_after_startup_in_daemon_batches(self):
        service = _Service([2, 0])
        install_background_materialization(service)
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            status = service.background_materialization_status()
            if status["completed"]:
                break
            time.sleep(0.02)
        status = service.background_materialization_status()
        self.assertTrue(status["completed"])
        self.assertEqual(status["pending"], 0)
        self.assertGreaterEqual(service.calls, 2)
        self.assertGreaterEqual(status["processed"], 2)
        self.assertIn("background_materialization", service._performance_metrics)

    def test_explicit_backfill_restarts_a_pending_drain(self):
        service = _Service([0])
        install_background_materialization(service)
        service.pending_sequence = [3, 0]
        report = service.materialize_existing(limit=64)
        self.assertEqual(report["pending"], 3)
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            if service.background_materialization_status()["completed"]:
                break
            time.sleep(0.02)
        self.assertTrue(service.background_materialization_status()["completed"])
        self.assertEqual(service.background_materialization_status()["pending"], 0)


if __name__ == "__main__":
    unittest.main()
