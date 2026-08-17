from __future__ import annotations

from datetime import date, datetime, timezone
import json
from typing import Any

from src.narrative.rails import CharacterRailParser

from .index import MemoryIndexer
from .models import (
    Authority,
    ContextLens,
    MemoryCandidate,
    QueryRoute,
    RetrievalLane,
    ScopeDecision,
    TrustLevel,
)
from .query import MemoryQueryEngine, QueryCompiler
from .scope import ScopeGate
from .store import MemoryStore, dumps, loads, make_id, utc_now
from .temporal import TemporalMemory


V121_EXTENSION_VERSION = "1.2.1a1"
_INSTALLED = False


def _as_datetime(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        pass
    try:
        parsed_date = date.fromisoformat(text)
        return datetime(parsed_date.year, parsed_date.month, parsed_date.day, tzinfo=timezone.utc)
    except ValueError:
        return None


def normalize_world_time(value: Any) -> tuple[str, Any] | None:
    """Normalize comparable fictional time values without inventing order for labels."""
    if value is None:
        return None
    if isinstance(value, bool):
        return ("text", str(value).lower())
    if isinstance(value, (int, float)):
        return ("number", float(value))
    if isinstance(value, datetime):
        parsed = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return ("datetime", parsed.astimezone(timezone.utc).timestamp())
    if isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
        return ("datetime", parsed.timestamp())
    if isinstance(value, dict):
        for key in ("iso", "datetime", "date", "timestamp", "value"):
            if key in value:
                nested = normalize_world_time(value[key])
                if nested is not None:
                    return nested
        return ("text", json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    text = str(value).strip()
    parsed_dt = _as_datetime(text)
    if parsed_dt is not None:
        return ("datetime", parsed_dt.timestamp())
    try:
        return ("number", float(text))
    except ValueError:
        return ("text", text.casefold())


def compare_world_time(left: Any, right: Any) -> int | None:
    a = normalize_world_time(left)
    b = normalize_world_time(right)
    if a is None or b is None or a[0] != b[0]:
        return None
    # Named fictional epochs are intentionally opaque. Exact equality is valid;
    # lexical ordering ("Day Ten" > "Day Two") would fabricate chronology.
    if a[0] == "text":
        return 0 if a[1] == b[1] else None
    if a[1] < b[1]:
        return -1
    if a[1] > b[1]:
        return 1
    return 0


def world_time_in_interval(point: Any, start: Any = None, end: Any = None) -> bool:
    """Start-inclusive, end-exclusive membership on a comparable world-time axis."""
    if point is None:
        return True
    if start is not None:
        cmp_start = compare_world_time(point, start)
        if cmp_start is None or cmp_start < 0:
            return False
    if end is not None:
        cmp_end = compare_world_time(point, end)
        if cmp_end is None or cmp_end >= 0:
            return False
    return True


def _state_at_v121(
    self: MemoryStore,
    *,
    world_id: str,
    branch_id: str | None,
    owner_type: str,
    owner_id: str,
    story_order: float | None = None,
    world_time: Any = None,
) -> list[dict[str, Any]]:
    where = ["world_id=?", "branch_id IS ?", "owner_type=?", "owner_id=?", "status='accepted'"]
    params: list[Any] = [world_id, branch_id, owner_type, owner_id]
    with self.connection() as con:
        rows = con.execute(
            f"SELECT id FROM state_intervals WHERE {' AND '.join(where)} ORDER BY created_at DESC, rowid DESC",
            params,
        ).fetchall()

    matching: list[dict[str, Any]] = []
    for raw in rows:
        row = self.get_state_interval(raw["id"])
        if story_order is not None:
            start = row.get("story_order_from")
            end = row.get("story_order_to")
            if start is not None and float(start) > float(story_order):
                continue
            if end is not None and float(end) <= float(story_order):
                continue
        if world_time is not None and not world_time_in_interval(
            world_time,
            row.get("valid_from_world_time"),
            row.get("valid_to_world_time"),
        ):
            continue
        matching.append(row)

    by_key: dict[str, list[dict[str, Any]]] = {}
    for row in matching:
        by_key.setdefault(str(row["state_key"]), []).append(row)

    result: list[dict[str, Any]] = []
    for state_key in sorted(by_key):
        def rank(row: dict[str, Any]) -> tuple[int, float, str]:
            specificity = 0
            if story_order is not None and (
                row.get("story_order_from") is not None or row.get("story_order_to") is not None
            ):
                specificity += 1
            if world_time is not None and (
                row.get("valid_from_world_time") is not None or row.get("valid_to_world_time") is not None
            ):
                specificity += 2
            start_order = float(row.get("story_order_from")) if row.get("story_order_from") is not None else float("-inf")
            return specificity, start_order, str(row.get("created_at") or "")

        result.append(max(by_key[state_key], key=rank))
    return result


def _transition_state_v121(
    self: MemoryStore,
    *,
    world_id: str,
    branch_id: str | None,
    owner_type: str,
    owner_id: str,
    state_key: str,
    value: Any,
    story_order: float | None = None,
    world_time: Any = None,
    source_type: str = "manual",
    source_id: str | None = None,
    authority: str = Authority.USER_ACCEPTED_WORLD_CANON.value,
) -> dict[str, Any]:
    """Atomically supersede a state interval and its current-state projection."""
    if story_order is None and world_time is None:
        raise ValueError("Temporal transition requires story_order and/or world_time")

    interval_id = make_id("STATEINT")
    now = utc_now()
    previous_id: str | None = None
    with self._lock, self.connection() as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            previous = con.execute(
                "SELECT * FROM state_intervals WHERE world_id=? AND branch_id IS ? AND owner_type=? AND owner_id=? "
                "AND state_key=? AND status='accepted' ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (world_id, branch_id, owner_type, owner_id, state_key),
            ).fetchone()
            if previous is not None:
                previous_id = str(previous["id"])
                if story_order is not None and previous["story_order_from"] is not None:
                    if float(story_order) < float(previous["story_order_from"]):
                        raise ValueError("State transition cannot move backward in story order")
                previous_world_time = loads(previous["valid_from_world_time_json"], None)
                if world_time is not None and previous_world_time is not None:
                    comparison = compare_world_time(world_time, previous_world_time)
                    if comparison is not None and comparison < 0:
                        raise ValueError("State transition cannot move backward in world time")

                updates: list[str] = []
                update_params: list[Any] = []
                if story_order is not None and previous["story_order_to"] is None:
                    updates.append("story_order_to=?")
                    update_params.append(float(story_order))
                if world_time is not None and previous["valid_to_world_time_json"] is None:
                    updates.append("valid_to_world_time_json=?")
                    update_params.append(dumps(world_time))
                if updates:
                    update_params.append(previous_id)
                    con.execute(f"UPDATE state_intervals SET {','.join(updates)} WHERE id=?", update_params)

            con.execute(
                "INSERT INTO state_intervals(id,world_id,branch_id,owner_type,owner_id,state_key,value_json,"
                "valid_from_event_id,valid_to_event_id,valid_from_world_time_json,valid_to_world_time_json,"
                "story_order_from,story_order_to,source_type,source_id,authority,status,created_at) "
                "VALUES(?,?,?,?,?,?,?,NULL,NULL,?,NULL,?,NULL,?,?,?,'accepted',?)",
                (
                    interval_id,
                    world_id,
                    branch_id,
                    owner_type,
                    owner_id,
                    state_key,
                    dumps(value),
                    dumps(world_time) if world_time is not None else None,
                    float(story_order) if story_order is not None else None,
                    source_type,
                    source_id,
                    authority,
                    now,
                ),
            )

            updated = con.execute(
                "UPDATE current_state_projection SET value_json=?,source_type=?,source_id=?,authority=?,updated_at=? "
                "WHERE world_id=? AND branch_id IS ? AND owner_type=? AND owner_id=? AND state_key=?",
                (
                    dumps(value), source_type, source_id, authority, now,
                    world_id, branch_id, owner_type, owner_id, state_key,
                ),
            )
            if updated.rowcount == 0:
                con.execute(
                    "INSERT INTO current_state_projection(world_id,branch_id,owner_type,owner_id,state_key,value_json,"
                    "source_type,source_id,authority,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        world_id, branch_id, owner_type, owner_id, state_key, dumps(value),
                        source_type, source_id, authority, now,
                    ),
                )
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise

    current = self.query_current_state(world_id, branch_id, owner_type, owner_id, state_key)
    return {
        "interval": self.get_state_interval(interval_id),
        "superseded_interval_id": previous_id,
        "current": current[0] if current else None,
    }


def _temporal_state_v121(self: MemoryQueryEngine, plan) -> list[MemoryCandidate]:
    if not plan.scope.world_id:
        return []
    output: list[MemoryCandidate] = []
    for variant in self._variant_targets(plan):
        rows = self.store.state_at(
            world_id=plan.scope.world_id,
            branch_id=plan.scope.branch_id,
            owner_type="entity_variant",
            owner_id=variant["id"],
            story_order=plan.scope.story_order,
            world_time=plan.scope.world_time,
        )
        for row in rows:
            output.append(MemoryCandidate(
                id=row["id"],
                lane=RetrievalLane.TEMPORAL_STATE,
                text=(
                    f"At the requested narrative time, "
                    f"{variant.get('display_name', variant['id'])}.{row['state_key']} = {row.get('value')!r}"
                ),
                source_type=row.get("source_type") or "state_interval",
                source_id=row.get("source_id") or row["id"],
                world_id=row.get("world_id"),
                branch_id=row.get("branch_id"),
                world_time=row.get("valid_from_world_time"),
                story_order=row.get("story_order_from"),
                authority=row.get("authority") or Authority.USER_ACCEPTED_WORLD_CANON.value,
                trust_level=TrustLevel.TRUSTED_LOCAL.value,
                importance=0.95,
                metadata={"structured": True, "interval": row},
            ))
    return output


def _profile_and_relationship_state(self: MemoryQueryEngine, plan, lane: RetrievalLane) -> list[MemoryCandidate]:
    output = list(_ORIGINAL_STRUCTURED_STATE(self, plan, lane))
    if not plan.scope.world_id:
        return output

    variants = self._variant_targets(plan)
    seen_profiles: set[str] = set()
    seen_relationships: set[str] = set()
    for variant in variants:
        variant_id = str(variant["id"])
        if variant_id not in seen_profiles:
            seen_profiles.add(variant_id)
            try:
                family = self.workspace.get_entity_family(variant["family_id"])
            except Exception:
                family = {}
            profile = {
                "identity": family.get("shared_core") or {},
                "summary": variant.get("summary") or "",
                "attributes": variant.get("attributes") or {},
                "voice": variant.get("voice") or {},
            }
            if any(bool(value) for value in profile.values()):
                label = variant.get("display_name") or family.get("name") or variant_id
                output.append(MemoryCandidate(
                    id=f"PROFILE:{variant_id}",
                    lane=lane,
                    text=f"Character profile for {label}: {json.dumps(profile, ensure_ascii=False, default=str)}",
                    source_type="entity_variant",
                    source_id=variant_id,
                    project_id=None,  # Library sheets are shared across story projects.
                    world_id=variant.get("world_id") or plan.scope.world_id,
                    branch_id=variant.get("branch_id"),
                    authority=Authority.USER_ACCEPTED_WORLD_CANON.value,
                    trust_level=TrustLevel.TRUSTED_LOCAL.value,
                    importance=1.0,
                    metadata={
                        "structured": True,
                        "character_profile": True,
                        "source_recorded_at": variant.get("updated_at") or variant.get("created_at"),
                    },
                ))

        relationship_rows: list[dict[str, Any]] = []
        for branch_value in (None, plan.scope.branch_id):
            if branch_value is None and plan.scope.branch_id is None and relationship_rows:
                continue
            try:
                relationship_rows.extend(self.workspace.list_relationships(
                    world_id=plan.scope.world_id,
                    branch_id=branch_value,
                    variant_id=variant_id,
                ))
            except Exception:
                continue
        for relationship in relationship_rows:
            rel_id = str(relationship.get("id") or "")
            if not rel_id or rel_id in seen_relationships:
                continue
            seen_relationships.add(rel_id)
            subject_id = relationship.get("subject_variant_id")
            object_id = relationship.get("object_variant_id")
            try:
                subject = self.workspace.get_variant(subject_id) if subject_id else {}
            except Exception:
                subject = {}
            try:
                obj = self.workspace.get_variant(object_id) if object_id else {}
            except Exception:
                obj = {}
            subject_name = subject.get("display_name") or subject_id or "unknown"
            object_name = obj.get("display_name") or object_id or "unknown"
            relation_type = relationship.get("relation_type") or "related_to"
            attributes = relationship.get("attributes") or {}
            output.append(MemoryCandidate(
                id=f"RELATIONSHIP:{rel_id}",
                lane=lane,
                text=(
                    f"Relationship: {subject_name} {relation_type} {object_name}; "
                    f"status={relationship.get('status') or 'current'}; "
                    f"attributes={json.dumps(attributes, ensure_ascii=False, default=str)}"
                ),
                source_type="relationship",
                source_id=rel_id,
                world_id=relationship.get("world_id") or plan.scope.world_id,
                branch_id=relationship.get("branch_id"),
                authority=Authority.USER_ACCEPTED_WORLD_CANON.value,
                trust_level=TrustLevel.TRUSTED_LOCAL.value,
                importance=0.95,
                metadata={
                    "structured": True,
                    "relationship": relationship,
                    "source_recorded_at": relationship.get("updated_at") or relationship.get("created_at"),
                },
            ))
    return output


def _scope_evaluate_v121(self: ScopeGate, candidate: MemoryCandidate, context) -> ScopeDecision:
    decision = _ORIGINAL_SCOPE_EVALUATE(self, candidate, context)
    if not decision.allowed:
        return decision
    if context.world_time is None or candidate.world_time is None:
        return decision
    comparison = compare_world_time(candidate.world_time, context.world_time)
    if comparison is None or comparison <= 0:
        return decision
    explicit = self._explicitly_allowed(candidate, context)
    if explicit or (context.context_lens == ContextLens.AUTHOR and context.allow_future_author_knowledge):
        return decision
    return ScopeDecision(False, "future world-time evidence blocked by active lens", "world_time")


def _index_turn_v121(self: MemoryIndexer, turn: dict[str, Any], *args, **kwargs):
    raw_prompt = str(turn.get("user_prompt") or "")
    compilation = CharacterRailParser.parse(raw_prompt)
    if not compilation.active:
        return _ORIGINAL_INDEX_TURN(self, turn, *args, **kwargs)
    scoped = dict(turn)
    # Slash rails steer one generation. They are deliberately absent from
    # Memory evidence; accepted generated prose can still be indexed normally.
    scoped["user_prompt"] = compilation.evidence_prompt
    return _ORIGINAL_INDEX_TURN(self, scoped, *args, **kwargs)


def _compile_v121(self: QueryCompiler, query: str, scope):
    plan = _ORIGINAL_COMPILE(self, query, scope)
    if CharacterRailParser.parse(query).active:
        plan.route = QueryRoute.STORY_CONTINUE
        if "character_rails" not in plan.predicates:
            plan.predicates.append("character_rails")
    if scope.world_time is not None:
        plan.world_time_range = {"at": scope.world_time}
    if scope.story_order is not None:
        plan.story_order_range = (scope.story_order, scope.story_order)
    return plan


def _route_v121(cls, query: str) -> QueryRoute:
    if CharacterRailParser.parse(query).active:
        return QueryRoute.STORY_CONTINUE
    return _ORIGINAL_ROUTE(query)


def _temporal_memory_state_at(self: TemporalMemory, *, world_id: str, branch_id: str | None,
                              owner_type: str, owner_id: str, story_order: float | None = None,
                              world_time: Any = None):
    return self.store.state_at(
        world_id=world_id,
        branch_id=branch_id,
        owner_type=owner_type,
        owner_id=owner_id,
        story_order=story_order,
        world_time=world_time,
    )


def _temporal_memory_transition(self: TemporalMemory, **kwargs):
    return self.store.transition_state(**kwargs)


_ORIGINAL_ROUTE = QueryCompiler.route
_ORIGINAL_COMPILE = QueryCompiler.compile
_ORIGINAL_STRUCTURED_STATE = MemoryQueryEngine._structured_state
_ORIGINAL_TEMPORAL_STATE = MemoryQueryEngine._temporal_state
_ORIGINAL_SCOPE_EVALUATE = ScopeGate.evaluate
_ORIGINAL_INDEX_TURN = MemoryIndexer.index_turn
_ORIGINAL_STATE_AT = MemoryStore.state_at
_ORIGINAL_TEMPORAL_MEMORY_STATE_AT = TemporalMemory.state_at


def install_v121() -> None:
    """Install the v1.2.1 extension once over the stable v1.2.0 foundation."""
    global _INSTALLED
    if _INSTALLED:
        return
    QueryCompiler.route = classmethod(_route_v121)
    QueryCompiler.compile = _compile_v121
    MemoryQueryEngine._structured_state = _profile_and_relationship_state
    MemoryQueryEngine._temporal_state = _temporal_state_v121
    ScopeGate.evaluate = _scope_evaluate_v121
    MemoryIndexer.index_turn = _index_turn_v121
    MemoryStore.state_at = _state_at_v121
    MemoryStore.transition_state = _transition_state_v121
    TemporalMemory.state_at = _temporal_memory_state_at
    TemporalMemory.transition = _temporal_memory_transition
    _INSTALLED = True
