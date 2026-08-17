from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .index import MemoryIndexer
from .service import MemoryService
from .store import dumps, make_id, utc_now
from .v121 import compare_world_time


ACCEPTED_TIMELINE_STATUSES = {"canon", "accepted"}
_INSTALLED = False


@dataclass(slots=True)
class TimelineProjectionReport:
    worlds: int = 0
    branches: int = 0
    owners: int = 0
    keys: int = 0
    intervals: int = 0
    skipped_keys: int = 0
    skipped_events: int = 0
    diagnostics: list[str] = field(default_factory=list)

    def merge(self, other: "TimelineProjectionReport") -> None:
        self.worlds += other.worlds
        self.branches += other.branches
        self.owners += other.owners
        self.keys += other.keys
        self.intervals += other.intervals
        self.skipped_keys += other.skipped_keys
        self.skipped_events += other.skipped_events
        self.diagnostics.extend(other.diagnostics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "worlds": self.worlds,
            "branches": self.branches,
            "owners": self.owners,
            "keys": self.keys,
            "intervals": self.intervals,
            "skipped_keys": self.skipped_keys,
            "skipped_events": self.skipped_events,
            "diagnostics": self.diagnostics,
        }


class TimelineStateProjector:
    """Build disposable temporal state intervals from accepted Timeline events.

    Timeline events remain the authoritative history. The interval rows and current
    projection are derived caches that can be rebuilt without mutating the source.
    A projector never overwrites a state key controlled by a non-timeline interval
    or current-state projection; that conflict is surfaced as a diagnostic instead.
    """

    def __init__(self, *, store, workspace):
        self.store = store
        self.workspace = workspace

    @staticmethod
    def _recorded_before_or_equal(recorded_at: str | None, cutoff: str | None) -> bool:
        if cutoff is None:
            return True
        if not recorded_at:
            return False
        try:
            left = datetime.fromisoformat(str(recorded_at).replace("Z", "+00:00"))
            right = datetime.fromisoformat(str(cutoff).replace("Z", "+00:00"))
            return left <= right
        except ValueError:
            return str(recorded_at) <= str(cutoff)

    def _visible_branch_cutoffs(self, target_branch_id: str | None) -> dict[str | None, str | None]:
        # World-global events remain globally visible. Branch-local inheritance is
        # conservative: an ancestor contributes only events recorded before the
        # immediate child branch was created, matching the v1.2.0 fallback cutoff.
        cutoffs: dict[str | None, str | None] = {None: None}
        if target_branch_id is None:
            return cutoffs
        current_id = target_branch_id
        child_creation: str | None = None
        seen: set[str] = set()
        while current_id and current_id not in seen:
            seen.add(current_id)
            try:
                branch = self.workspace.get_branch(current_id)
            except Exception:
                break
            cutoffs[current_id] = child_creation
            child_creation = branch.get("created_at")
            current_id = branch.get("parent_branch_id")
        return cutoffs

    def _visible_events(self, world_id: str, target_branch_id: str | None) -> list[dict[str, Any]]:
        try:
            events = self.workspace.list_timeline_events(world_id)
        except Exception:
            return []
        cutoffs = self._visible_branch_cutoffs(target_branch_id)
        visible: list[dict[str, Any]] = []
        for event in events:
            if str(event.get("status") or "").casefold() not in ACCEPTED_TIMELINE_STATUSES:
                continue
            owner_type = event.get("owner_type")
            owner_id = event.get("owner_id")
            patch = event.get("state_patch") or {}
            if not owner_type or not owner_id or not isinstance(patch, dict) or not patch:
                continue
            event_branch = event.get("branch_id")
            if event_branch not in cutoffs:
                continue
            if not self._recorded_before_or_equal(event.get("created_at"), cutoffs[event_branch]):
                continue
            visible.append(event)
        visible.sort(key=lambda event: (float(event.get("order_key") or 0.0), str(event.get("created_at") or ""), str(event.get("id") or "")))
        return visible

    def _non_timeline_conflict(
        self,
        *,
        world_id: str,
        branch_id: str | None,
        owner_type: str,
        owner_id: str,
        state_key: str,
    ) -> str | None:
        with self.store.connection() as con:
            interval = con.execute(
                "SELECT source_type,source_id FROM state_intervals WHERE world_id=? AND branch_id IS ? "
                "AND owner_type=? AND owner_id=? AND state_key=? AND status='accepted' "
                "AND source_type!='timeline_event' ORDER BY created_at DESC,rowid DESC LIMIT 1",
                (world_id, branch_id, owner_type, owner_id, state_key),
            ).fetchone()
            if interval is not None:
                return f"accepted interval from {interval['source_type']}:{interval['source_id'] or ''}"
            current = con.execute(
                "SELECT source_type,source_id FROM current_state_projection WHERE world_id=? AND branch_id IS ? "
                "AND owner_type=? AND owner_id=? AND state_key=? AND source_type!='timeline_event' LIMIT 1",
                (world_id, branch_id, owner_type, owner_id, state_key),
            ).fetchone()
            if current is not None:
                return f"current projection from {current['source_type']}:{current['source_id'] or ''}"
        return None

    def _rebuild_key(
        self,
        *,
        world_id: str,
        branch_id: str | None,
        owner_type: str,
        owner_id: str,
        state_key: str,
        occurrences: list[dict[str, Any]],
    ) -> int:
        now = utc_now()
        rows: list[dict[str, Any]] = []
        for index, event in enumerate(occurrences):
            patch = event.get("state_patch") or {}
            next_event = occurrences[index + 1] if index + 1 < len(occurrences) else None
            start_world_time = str(event.get("time_label") or "").strip() or None
            end_world_time = str(next_event.get("time_label") or "").strip() or None if next_event else None
            # If opaque labels cannot be ordered, story_order still safely closes
            # the interval. Leaving world-time open avoids inventing chronology.
            if start_world_time is not None and end_world_time is not None:
                comparison = compare_world_time(start_world_time, end_world_time)
                if comparison is None:
                    end_world_time = None
            rows.append({
                "id": make_id("STATEINT"),
                "value": patch[state_key],
                "story_order_from": float(event.get("order_key") or 0.0),
                "story_order_to": float(next_event.get("order_key") or 0.0) if next_event else None,
                "world_time_from": start_world_time,
                "world_time_to": end_world_time,
                "source_id": event.get("id"),
            })

        with self.store._lock, self.store.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            try:
                con.execute(
                    "DELETE FROM state_intervals WHERE world_id=? AND branch_id IS ? AND owner_type=? AND owner_id=? "
                    "AND state_key=? AND source_type='timeline_event'",
                    (world_id, branch_id, owner_type, owner_id, state_key),
                )
                con.execute(
                    "DELETE FROM current_state_projection WHERE world_id=? AND branch_id IS ? AND owner_type=? AND owner_id=? "
                    "AND state_key=? AND source_type='timeline_event'",
                    (world_id, branch_id, owner_type, owner_id, state_key),
                )
                for row in rows:
                    con.execute(
                        "INSERT INTO state_intervals(id,world_id,branch_id,owner_type,owner_id,state_key,value_json,"
                        "valid_from_event_id,valid_to_event_id,valid_from_world_time_json,valid_to_world_time_json,"
                        "story_order_from,story_order_to,source_type,source_id,authority,status,created_at) "
                        "VALUES(?,?,?,?,?,?,?, ?,NULL, ?,?, ?,?, 'timeline_event',?, 'accepted_event','accepted',?)",
                        (
                            row["id"], world_id, branch_id, owner_type, owner_id, state_key, dumps(row["value"]),
                            row["source_id"],
                            dumps(row["world_time_from"]) if row["world_time_from"] is not None else None,
                            dumps(row["world_time_to"]) if row["world_time_to"] is not None else None,
                            row["story_order_from"], row["story_order_to"], row["source_id"], now,
                        ),
                    )
                if rows:
                    latest = rows[-1]
                    con.execute(
                        "INSERT INTO current_state_projection(world_id,branch_id,owner_type,owner_id,state_key,value_json,"
                        "source_type,source_id,authority,updated_at) VALUES(?,?,?,?,?,?, 'timeline_event',?,'accepted_event',?)",
                        (
                            world_id, branch_id, owner_type, owner_id, state_key,
                            dumps(latest["value"]), latest["source_id"], now,
                        ),
                    )
                con.execute("COMMIT")
            except Exception:
                con.execute("ROLLBACK")
                raise
        return len(rows)

    def project_branch(self, world_id: str, branch_id: str | None) -> TimelineProjectionReport:
        report = TimelineProjectionReport(worlds=1, branches=1)
        events = self._visible_events(world_id, branch_id)
        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        owners: set[tuple[str, str]] = set()
        for event in events:
            owner = (str(event["owner_type"]), str(event["owner_id"]))
            owners.add(owner)
            patch = event.get("state_patch") or {}
            for state_key in patch:
                grouped.setdefault((owner[0], owner[1], str(state_key)), []).append(event)
        report.owners = len(owners)

        for (owner_type, owner_id, state_key), occurrences in grouped.items():
            conflict = self._non_timeline_conflict(
                world_id=world_id, branch_id=branch_id, owner_type=owner_type,
                owner_id=owner_id, state_key=state_key,
            )
            if conflict:
                report.skipped_keys += 1
                report.diagnostics.append(
                    f"Skipped {owner_type}:{owner_id}.{state_key} in branch {branch_id or '<global>'}: {conflict}."
                )
                continue
            report.keys += 1
            report.intervals += self._rebuild_key(
                world_id=world_id, branch_id=branch_id, owner_type=owner_type,
                owner_id=owner_id, state_key=state_key, occurrences=occurrences,
            )
        return report

    def project_world(self, world_id: str, branch_id: str | None = None) -> TimelineProjectionReport:
        if branch_id is not None:
            return self.project_branch(world_id, branch_id)
        report = TimelineProjectionReport()
        # Keep a global projection for branch-less queries and one derived view
        # per real branch so ordinary scoped state lookup stays exact/fast.
        report.merge(self.project_branch(world_id, None))
        try:
            branches = (self.workspace.get_world(world_id) or {}).get("branches") or []
        except Exception:
            branches = []
        for branch in branches:
            if branch.get("id"):
                report.merge(self.project_branch(world_id, branch["id"]))
        report.worlds = 1
        return report

    def project_project(self, project_id: str | None = None) -> TimelineProjectionReport:
        report = TimelineProjectionReport()
        try:
            worlds = self.workspace.list_worlds(project_id)
        except Exception:
            worlds = []
        seen: set[str] = set()
        for world in worlds:
            world_id = world.get("id")
            if not world_id or world_id in seen:
                continue
            seen.add(world_id)
            report.merge(self.project_world(world_id))
        report.worlds = len(seen)
        return report


def _project_timeline_state(self: MemoryIndexer, *, world_id: str | None = None,
                            branch_id: str | None = None, project_id: str | None = None) -> dict[str, Any]:
    projector = TimelineStateProjector(store=self.store, workspace=self.workspace)
    if world_id:
        return projector.project_world(world_id, branch_id=branch_id).to_dict()
    return projector.project_project(project_id).to_dict()


_ORIGINAL_BACKFILL = MemoryIndexer.backfill
_ORIGINAL_SERVICE_BACKFILL = MemoryService.backfill


def _backfill_v121(self: MemoryIndexer, project_id: str | None = None) -> dict[str, Any]:
    result = _ORIGINAL_BACKFILL(self, project_id)
    if result.get("disabled"):
        return result
    effective_project_id = None if self.config.dense_enabled else project_id
    result["timeline_state"] = self.project_timeline_state(project_id=effective_project_id)
    return result


def _refresh_timeline_state(self: MemoryService, world_id: str, branch_id: str | None = None) -> dict[str, Any]:
    if not self.config.enabled:
        return {"disabled": True, "worlds": 0, "branches": 0, "owners": 0, "keys": 0, "intervals": 0}
    return self.indexer.project_timeline_state(world_id=world_id, branch_id=branch_id)


def install_v121_event_projection() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    MemoryIndexer.project_timeline_state = _project_timeline_state
    MemoryIndexer.backfill = _backfill_v121
    MemoryService.refresh_timeline_state = _refresh_timeline_state
    _INSTALLED = True
