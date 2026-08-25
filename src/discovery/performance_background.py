from __future__ import annotations

from dataclasses import dataclass
from threading import Lock, Timer
from time import monotonic
from typing import Any, Callable


@dataclass(slots=True)
class BackgroundMaterializationState:
    scheduled: bool = False
    running: bool = False
    completed: bool = False
    rounds: int = 0
    processed: int = 0
    pending: int = -1
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
    """Drain old provisional projections strictly outside the startup path.

    New turns are projected synchronously by their turn-local materializer. This
    worker exists only for upgrade/backfill residue. Installing the worker must
    therefore perform *zero* discovery scans: even a one-row dirty check can be
    expensive on a large SQLite file because it still has to build/join the
    candidate set. The first check is delayed until after the HTTP application is
    already usable.

    Foreground projection owns priority. If a user turn just materialized, the
    historical daemon waits for a short quiet window and shares the service's
    re-entrant materialization guard. This prevents old-residue repair from
    racing a fresh turn for the same subject link/sheet.
    """

    if getattr(service, "_background_materialization_installed", False):
        return

    original: Callable[..., dict[str, Any]] = service.materialize_existing
    state = BackgroundMaterializationState()
    lock = Lock()
    timer: Timer | None = None
    max_rounds = 256
    interval_seconds = 0.55
    initial_delay_seconds = 1.25
    batch_limit = 192

    def publish() -> None:
        metrics = dict(getattr(service, "_performance_metrics", {}) or {})
        metrics["background_materialization"] = state.to_dict()
        service._performance_metrics = metrics

    def schedule(delay: float = interval_seconds, *, force: bool = False) -> None:
        nonlocal timer
        with lock:
            if state.running:
                return
            if state.scheduled:
                if not force:
                    return
                if timer is not None:
                    timer.cancel()
                state.scheduled = False
            if state.completed and not force:
                return
            if force and state.completed:
                state.completed = False
            state.scheduled = True
            publish()
            timer = Timer(max(0.01, float(delay)), run_batch)
            timer.daemon = True
            timer.start()

    def defer_after_foreground(delay: float) -> None:
        with lock:
            state.running = False
            publish()
        schedule(max(0.05, delay))

    def run_batch() -> None:
        with lock:
            state.scheduled = False
            if state.running or state.completed:
                return
            state.running = True
            state.rounds += 1
            publish()

        guard = getattr(service, "_provisional_materialization_lock", None)
        acquired = False
        try:
            if guard is not None:
                guard.acquire()
                acquired = True
                last_turn = float(getattr(service, "_provisional_last_turn_materialized_at", 0.0) or 0.0)
                quiet_remaining = interval_seconds - max(0.0, monotonic() - last_turn)
                if last_turn > 0.0 and quiet_remaining > 0.0:
                    # Release before rescheduling. A foreground turn that caused
                    # this delay has already done the user-visible projection.
                    guard.release()
                    acquired = False
                    defer_after_foreground(quiet_remaining)
                    return

            report = original(limit=batch_limit)
            branch_report = report.get("branch_repair") if isinstance(report.get("branch_repair"), dict) else {}
            processed = int(report.get("processed") or report.get("claims") or 0) + int(branch_report.get("processed") or 0)
            pending = int(bool(report.get("pending")))
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
            if acquired:
                guard.release()
            with lock:
                # defer_after_foreground already cleared running before return.
                if state.running:
                    state.running = False
                    done = state.completed
                    publish()
                else:
                    done = state.completed
            if not done and not state.scheduled:
                schedule()

    def materialize_existing_with_schedule(*, limit: int = 5000):
        # Explicit callers (backfill/repair) asked for work now, so run one
        # bounded pass synchronously and leave any residue to the daemon.
        guard = getattr(service, "_provisional_materialization_lock", None)
        if guard is None:
            report = original(limit=limit)
        else:
            with guard:
                report = original(limit=limit)
        pending = int(bool(report.get("pending")))
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
    service.schedule_materialization_drain = lambda delay=interval_seconds: schedule(delay, force=True)
    service.background_materialization_status = lambda: state.to_dict()
    service._background_materialization_installed = True

    # No DB read here. This is intentionally fire-and-forget so create_app() can
    # finish before any historical Discovery backlog is inspected.
    publish()
    schedule(delay=initial_delay_seconds)
