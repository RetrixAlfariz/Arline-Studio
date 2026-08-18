from __future__ import annotations

from dataclasses import dataclass
from threading import Lock, Timer
from typing import Any, Callable


@dataclass(slots=True)
class BackgroundMaterializationState:
    scheduled: bool = False
    running: bool = False
    completed: bool = False
    rounds: int = 0
    processed: int = 0
    pending: int = 0
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scheduled": self.scheduled,
            "running": self.running,
            "completed": self.completed,
            "rounds": self.rounds,
            "processed": self.processed,
            "pending": self.pending,
            "last_error": self.last_error,
        }


def install_background_materialization(service) -> None:
    """Drain old provisional projections incrementally after startup.

    New turns are projected synchronously by their turn-local materializer. This
    worker exists only for upgrade/backfill residue, so startup never blocks on
    thousands of historical propositions. Work is rate-limited and daemonized;
    source truth and the HTTP server remain usable while the derived sheets catch
    up in small deterministic batches.
    """

    if getattr(service, "_background_materialization_installed", False):
        return

    original: Callable[..., dict[str, Any]] = service.materialize_existing
    state = BackgroundMaterializationState()
    lock = Lock()
    timer: Timer | None = None
    max_rounds = 256
    interval_seconds = 0.35
    batch_limit = 256

    def publish() -> None:
        metrics = dict(getattr(service, "_performance_metrics", {}) or {})
        metrics["background_materialization"] = state.to_dict()
        service._performance_metrics = metrics

    def schedule(delay: float = interval_seconds) -> None:
        nonlocal timer
        with lock:
            if state.scheduled or state.running or state.completed:
                return
            state.scheduled = True
            publish()
            timer = Timer(delay, run_batch)
            timer.daemon = True
            timer.start()

    def run_batch() -> None:
        with lock:
            state.scheduled = False
            if state.running or state.completed:
                return
            state.running = True
            state.rounds += 1
            publish()
        try:
            report = original(limit=batch_limit)
            processed = int(report.get("processed") or report.get("claims") or 0)
            pending = int(report.get("pending") or 0)
            with lock:
                state.processed += processed
                state.pending = pending
                state.last_error = None
                state.completed = pending <= 0 or state.rounds >= max_rounds
        except Exception as exc:  # derived projection must never stop the app
            with lock:
                state.last_error = str(exc)
                state.completed = state.rounds >= max_rounds
        finally:
            with lock:
                state.running = False
                done = state.completed
                publish()
            if not done:
                schedule()

    def materialize_existing_with_schedule(*, limit: int = 5000):
        report = original(limit=limit)
        pending = int(report.get("pending") or 0)
        with lock:
            state.pending = pending
            if pending <= 0:
                state.completed = True
            elif state.completed and state.rounds < max_rounds:
                state.completed = False
            publish()
        if pending > 0:
            schedule()
        return report

    service.materialize_existing = materialize_existing_with_schedule
    service.schedule_materialization_drain = schedule
    service.background_materialization_status = lambda: state.to_dict()
    service._background_materialization_installed = True

    # The bounded startup pass already ran before this installer. Check the
    # remaining dirty set once without delaying application readiness.
    try:
        first = original(limit=1)
        state.pending = int(first.get("pending") or 0)
        state.processed += int(first.get("processed") or first.get("claims") or 0)
        state.completed = state.pending <= 0
        publish()
        if state.pending > 0:
            schedule(delay=0.08)
    except Exception as exc:
        state.last_error = str(exc)
        publish()
