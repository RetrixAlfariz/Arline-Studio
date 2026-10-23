from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
from threading import RLock
from typing import Any, Callable


log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """A post-commit application event emitted by an authoritative store."""

    name: str
    database_path: str
    payload: dict[str, Any]


class DomainEventBus:
    """Small synchronous event bus for one Arline database.

    Authoritative writes never depend on derived handlers succeeding. Handlers
    run after the source transaction commits, and one failing handler cannot
    prevent later handlers from observing the same event.
    """

    def __init__(self, database_path: str):
        self.database_path = database_path
        self._lock = RLock()
        self._handlers: dict[str, dict[str, Callable[[DomainEvent], None]]] = {}

    def subscribe(
        self,
        name: str,
        handler: Callable[[DomainEvent], None],
        *,
        key: str | None = None,
    ) -> None:
        subscription_key = key or (
            f"{handler.__module__}.{getattr(handler, '__qualname__', handler.__name__)}"
        )
        with self._lock:
            # A stable key makes repeated application/router construction
            # idempotent instead of stacking duplicate side effects.
            self._handlers.setdefault(name, {})[subscription_key] = handler

    def emit(
        self,
        name: str,
        payload: dict[str, Any] | None = None,
    ) -> list[Exception]:
        event = DomainEvent(name, self.database_path, dict(payload or {}))
        with self._lock:
            handlers = list(self._handlers.get(name, {}).items())

        errors: list[Exception] = []
        for key, handler in handlers:
            try:
                handler(event)
            except Exception as exc:  # derived work must not break authority
                errors.append(exc)
                log.exception("Domain event handler %s failed for %s", key, name)
        return errors


def _database_key(database_path: Path | str) -> str:
    return str(Path(database_path).expanduser().resolve())


_registry_lock = RLock()
_registry: dict[str, DomainEventBus] = {}


def get_domain_event_bus(database_path: Path | str) -> DomainEventBus:
    key = _database_key(database_path)
    with _registry_lock:
        if key not in _registry:
            _registry[key] = DomainEventBus(key)
        return _registry[key]


def emit_domain_event(
    database_path: Path | str,
    name: str,
    payload: dict[str, Any] | None = None,
) -> list[Exception]:
    return get_domain_event_bus(database_path).emit(name, payload)


def clear_domain_event_bus(database_path: Path | str) -> None:
    """Drop subscriptions for one database (primarily useful for test teardown)."""

    with _registry_lock:
        _registry.pop(_database_key(database_path), None)
