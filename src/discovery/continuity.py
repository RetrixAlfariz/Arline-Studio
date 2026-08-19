from __future__ import annotations

from dataclasses import dataclass, asdict
from hashlib import sha256
import re
from typing import Any

from src.memory.models import MemoryQueryContext

from .store import dumps, loads, make_id, utc_now


CONTINUITY_VERSION = "1.2.2a1"

CORRECTION_CUES = re.compile(
    r"\b(?:koreksi|maksudku|ralat|sebenarnya\s+bukan|bukan\s+.+?\s+tapi|"
    r"correction|i\s+meant|actually\s+not|rather\s+than)\b",
    re.I | re.S,
)
TRANSITION_CUES = re.compile(
    r"\b(?:sekarang|kini|menjadi|berubah(?:\s+menjadi)?|setelah|kemudian|akhirnya|"
    r"now|became|becomes|turned\s+into|changed\s+to|after|then|eventually)\b",
    re.I,
)

# Identity/classification is not a mutable state head. Relations have their own
# temporal lifecycle and are deliberately excluded from this first resolver.
NON_HEAD_PREDICATES = {"entity.exists"}


@dataclass(slots=True)
class ContinuityResolutionReport:
    turn_id: str
    source_kind: str
    examined: int = 0
    story_changes: int = 0
    corrections: int = 0
    conflicts: int = 0
    forms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ContinuityResolver:
    """Derived narrative continuity graph over Discovery propositions.

    Discovery propositions and their source instances remain the evidence layer;
    Canon/Timeline remain authority. This resolver only records how visible
    observations supersede or conflict with one another and builds rebuildable
    form snapshots for state transitions.
    """

    def __init__(self, service):
        self.service = service
        self.store = service.store

    @staticmethod
    def _same_value(left: Any, right: Any) -> bool:
        return dumps(left) == dumps(right)

    def _turn_scope(self, turn_id: str) -> tuple[dict[str, Any], dict[str, Any], MemoryQueryContext, Any, float | None]:
        turn = self.service.history.get_turn(turn_id)
        session = self.service.history.get_session_meta(turn["session_id"])
        world_time, story_order = self.service._turn_time_scope(turn)
        context = MemoryQueryContext(
            project_id=session.get("project_id"),
            world_id=session.get("world_id"),
            branch_id=session.get("branch_id"),
            session_id=session.get("id"),
            current_turn_id=turn_id,
            world_time=world_time,
            story_order=story_order,
            context_lens="scene",
            retrieval_mode="continuity",
        )
        return turn, session, context, world_time, story_order

    @staticmethod
    def _source_text(turn: dict[str, Any], source_kind: str) -> str:
        if source_kind == "user_prompt":
            return str(turn.get("user_prompt") or "")
        if source_kind == "accepted_generation":
            return str(turn.get("story") or "")
        if source_kind == "user_edited_prose":
            return str(turn.get("edited_story") or "")
        return ""

    def _current_propositions(self, turn_id: str, source_kind: str) -> list[dict[str, Any]]:
        with self.store.connection() as con:
            rows = con.execute(
                "SELECT DISTINCT p.* FROM discovery_propositions p "
                "JOIN discovery_instances i ON i.proposition_id=p.id "
                "WHERE i.source_turn_id=? AND i.source_kind=? AND i.active=1 "
                "ORDER BY p.rowid",
                (turn_id, source_kind),
            ).fetchall()
        return [self.store._prop_row(row) for row in rows]

    def _visible_instances(self, proposition_id: str, context: MemoryQueryContext, *, exclude_turn_id: str | None = None) -> list[dict[str, Any]]:
        result = []
        for instance in self.store.list_instances(proposition_id, active=True):
            if exclude_turn_id and instance.get("source_turn_id") == exclude_turn_id:
                continue
            if self.service._instance_allowed(instance, context):
                result.append(instance)
        return result

    @staticmethod
    def _instance_order(instance: dict[str, Any]) -> tuple[float, str, str]:
        story_order = instance.get("story_order")
        try:
            order = float(story_order) if story_order is not None else float("-inf")
        except (TypeError, ValueError):
            order = float("-inf")
        return order, str(instance.get("updated_at") or instance.get("created_at") or ""), str(instance.get("id") or "")

    def _previous_candidate(self, current: dict[str, Any], context: MemoryQueryContext, turn_id: str) -> dict[str, Any] | None:
        with self.store.connection() as con:
            rows = con.execute(
                "SELECT * FROM discovery_propositions WHERE project_id IS ? AND world_id IS ? "
                "AND subject_key=? AND predicate=? AND id!=? AND authority_state!='dismissed'",
                (
                    current.get("project_id"), current.get("world_id"),
                    current.get("subject_key"), current.get("predicate"), current.get("id"),
                ),
            ).fetchall()
        candidates: list[tuple[tuple[float, str, str], dict[str, Any]]] = []
        for row in rows:
            prop = self.store._prop_row(row)
            visible = self._visible_instances(prop["id"], context, exclude_turn_id=turn_id)
            if prop.get("authority_state") == "canon" and not visible:
                # Explicit Canon survives source loss, but cross-scope Canon must
                # still not be guessed into an unrelated project/world query.
                if prop.get("project_id") not in {None, context.project_id} or prop.get("world_id") not in {None, context.world_id}:
                    continue
                candidates.append(((float("inf"), str(prop.get("updated_at") or ""), prop["id"]), prop))
                continue
            if not visible:
                continue
            candidates.append((max(self._instance_order(item) for item in visible), prop))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1]

    @staticmethod
    def _classify(current: dict[str, Any], source_text: str) -> str:
        if current.get("operation") == "transition":
            return "story_change"
        if CORRECTION_CUES.search(source_text):
            return "correction"
        if TRANSITION_CUES.search(source_text):
            return "story_change"
        return "conflict"

    def _insert_edge(self, *, previous: dict[str, Any], current: dict[str, Any], kind: str,
                     session: dict[str, Any], turn_id: str, source_kind: str,
                     story_order: float | None, world_time: Any) -> str:
        now = utc_now()
        edge_id = "SUPER-" + sha256(
            dumps([previous["id"], current["id"], kind, turn_id]).encode("utf-8")
        ).hexdigest()[:16].upper()
        with self.store._lock, self.store.connection() as con:
            con.execute(
                "INSERT OR IGNORE INTO continuity_edges(id,project_id,world_id,branch_id,session_id,subject_key,predicate,"
                "from_proposition_id,to_proposition_id,kind,source_turn_id,source_kind,story_order,world_time_json,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    edge_id, session.get("project_id"), session.get("world_id"), session.get("branch_id"), session.get("id"),
                    current["subject_key"], current["predicate"], previous["id"], current["id"], kind,
                    turn_id, source_kind, story_order, dumps(world_time) if world_time is not None else None, now,
                ),
            )
        return edge_id

    def _insert_conflict(self, *, previous: dict[str, Any], current: dict[str, Any],
                         session: dict[str, Any], turn_id: str) -> None:
        left, right = sorted([previous["id"], current["id"]])
        conflict_id = "CONFLICT-" + sha256(
            dumps([left, right, turn_id]).encode("utf-8")
        ).hexdigest()[:16].upper()
        with self.store._lock, self.store.connection() as con:
            con.execute(
                "INSERT OR IGNORE INTO continuity_conflicts(id,project_id,world_id,branch_id,session_id,subject_key,predicate,"
                "left_proposition_id,right_proposition_id,source_turn_id,reason,status,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,'open',?)",
                (
                    conflict_id, session.get("project_id"), session.get("world_id"), session.get("branch_id"), session.get("id"),
                    current["subject_key"], current["predicate"], left, right, turn_id,
                    "Competing visible values without an explicit correction or story-transition cue.", utc_now(),
                ),
            )

    def _visible_evaluated(self, context: MemoryQueryContext, *, subject_key: str | None = None) -> list[dict[str, Any]]:
        where = ["authority_state!='dismissed'"]
        params: list[Any] = []
        if context.project_id is not None:
            where.append("project_id IS ?")
            params.append(context.project_id)
        if context.world_id is not None:
            where.append("world_id IS ?")
            params.append(context.world_id)
        if subject_key is not None:
            where.append("subject_key=?")
            params.append(subject_key)
        with self.store.connection() as con:
            rows = con.execute(
                f"SELECT * FROM discovery_propositions WHERE {' AND '.join(where)} ORDER BY rowid",
                params,
            ).fetchall()
        props = [self.store._prop_row(row) for row in rows]
        evaluator = getattr(self.service, "evaluate_many", None)
        if callable(evaluator):
            evaluated = evaluator(props, context, include_instances=False)
        else:
            evaluated = [self.service.evaluate_proposition(prop, context) for prop in props]
        return [
            item for item in evaluated
            if item.get("knowledge_state") == "canon" or int(item.get("support_count") or 0) > 0
        ]

    def current_view(self, context: MemoryQueryContext, *, subject_key: str | None = None) -> dict[str, Any]:
        visible = self._visible_evaluated(context, subject_key=subject_key)
        visible_ids = {item["id"] for item in visible}
        superseded: set[str] = set()
        with self.store.connection() as con:
            edges = con.execute(
                "SELECT * FROM continuity_edges WHERE project_id IS ? AND world_id IS ?",
                (context.project_id, context.world_id),
            ).fetchall()
        for row in edges:
            edge = dict(row)
            if edge["from_proposition_id"] in visible_ids and edge["to_proposition_id"] in visible_ids:
                superseded.add(edge["from_proposition_id"])

        by_key: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for item in visible:
            if item.get("predicate") in NON_HEAD_PREDICATES or item.get("operation") == "relation":
                continue
            if item["id"] in superseded:
                continue
            by_key.setdefault((str(item["subject_key"]), str(item["predicate"])), []).append(item)

        heads: list[dict[str, Any]] = []
        ambiguous: list[dict[str, Any]] = []
        for (key, predicate), items in sorted(by_key.items()):
            canonical = [item for item in items if item.get("knowledge_state") == "canon"]
            pool = canonical or items
            values = {dumps(item.get("value")) for item in pool}
            if len(values) > 1:
                ambiguous.append({
                    "subject_key": key,
                    "predicate": predicate,
                    "proposition_ids": [item["id"] for item in pool],
                    "reason": "multiple_visible_heads",
                })
                continue
            chosen = max(
                pool,
                key=lambda item: (
                    int(item.get("knowledge_state") == "canon"),
                    int(item.get("qualified_support_count") or 0),
                    int(item.get("support_count") or 0),
                    str(item.get("updated_at") or ""),
                ),
            )
            heads.append(chosen)
        return {
            "version": CONTINUITY_VERSION,
            "heads": heads,
            "ambiguous": ambiguous,
            "superseded_proposition_ids": sorted(superseded),
        }

    def _form_id(self, subject_key: str, turn_id: str, source_kind: str) -> str:
        digest = sha256(dumps([subject_key, turn_id, source_kind]).encode("utf-8")).hexdigest()[:16].upper()
        return f"FORM-{digest}"

    def _build_form(self, *, subject_key: str, subject_label: str, anchor_prop_id: str,
                    context: MemoryQueryContext, session: dict[str, Any], turn_id: str,
                    source_kind: str, story_order: float | None, world_time: Any) -> bool:
        current = self.current_view(context, subject_key=subject_key)
        state = {
            item["predicate"].removeprefix("state."): item.get("value")
            for item in current["heads"]
            if str(item.get("predicate") or "").startswith("state.")
        }
        if not state:
            return False
        form_id = self._form_id(subject_key, turn_id, source_kind)
        with self.store.connection() as con:
            existing = con.execute("SELECT id FROM continuity_forms WHERE id=?", (form_id,)).fetchone()
            parent = con.execute(
                "SELECT id FROM continuity_forms WHERE project_id IS ? AND world_id IS ? AND subject_key=? AND id!=? "
                "ORDER BY COALESCE(story_order,-1e308) DESC,created_at DESC LIMIT 1",
                (session.get("project_id"), session.get("world_id"), subject_key, form_id),
            ).fetchone()
        if existing:
            return False
        with self.store._lock, self.store.connection() as con:
            con.execute(
                "INSERT INTO continuity_forms(id,project_id,world_id,branch_id,session_id,subject_key,subject_label,"
                "source_turn_id,source_kind,anchor_proposition_id,parent_form_id,reason,story_order,world_time_json,state_json,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    form_id, session.get("project_id"), session.get("world_id"), session.get("branch_id"), session.get("id"),
                    subject_key, subject_label, turn_id, source_kind, anchor_prop_id,
                    parent["id"] if parent else None, "state_transition" if parent else "baseline_observed",
                    story_order, dumps(world_time) if world_time is not None else None, dumps(state), utc_now(),
                ),
            )
        return True

    def resolve_turn(self, turn_id: str, *, source_kind: str = "user_prompt") -> dict[str, Any]:
        turn, session, context, world_time, story_order = self._turn_scope(turn_id)
        source_text = self._source_text(turn, source_kind)
        current_props = self._current_propositions(turn_id, source_kind)
        report = ContinuityResolutionReport(turn_id=turn_id, source_kind=source_kind)
        transitioned_characters: dict[str, tuple[str, str]] = {}

        for current in current_props:
            if current.get("predicate") in NON_HEAD_PREDICATES or current.get("operation") == "relation":
                continue
            report.examined += 1
            previous = self._previous_candidate(current, context, turn_id)
            if previous is not None and not self._same_value(previous.get("value"), current.get("value")):
                kind = self._classify(current, source_text)
                if kind == "conflict":
                    self._insert_conflict(previous=previous, current=current, session=session, turn_id=turn_id)
                    report.conflicts += 1
                else:
                    self._insert_edge(
                        previous=previous, current=current, kind=kind, session=session,
                        turn_id=turn_id, source_kind=source_kind,
                        story_order=story_order, world_time=world_time,
                    )
                    if kind == "story_change":
                        event = self.store.find_event_for_proposition(current["id"])
                        if event is None and current.get("operation") == "transition":
                            event = self.store.upsert_continuity_event(
                                project_id=session.get("project_id"), world_id=session.get("world_id"),
                                branch_id=session.get("branch_id"), session_id=session.get("id"),
                                source_turn_id=turn_id, source_kind=source_kind,
                                event_type="state_transition",
                                summary=(source_text.strip()[:240] or f"{current.get('subject_label')} changed"),
                                story_order=story_order, world_time=world_time,
                                stable_seed=[current["id"], "synthetic_transition"],
                            )
                            self.store.link_event_effect(
                                event["id"], current["id"], subject_key=current["subject_key"],
                                predicate=current["predicate"], role="after",
                            )
                        if event is not None:
                            link_id = "CAUSE-" + sha256(
                                dumps([event["id"], previous["id"], current["id"]]).encode("utf-8")
                            ).hexdigest()[:16].upper()
                            with self.store._lock, self.store.connection() as con:
                                con.execute(
                                    "INSERT OR IGNORE INTO continuity_causal_links(id,event_id,subject_key,predicate,"
                                    "from_proposition_id,to_proposition_id,kind,created_at) VALUES(?,?,?,?,?,?,?,?)",
                                    (link_id, event["id"], current["subject_key"], current["predicate"],
                                     previous["id"], current["id"], "state_transition", utc_now()),
                                )
                    if kind == "story_change":
                        report.story_changes += 1
                    elif kind == "correction":
                        report.corrections += 1

            if (
                current.get("subject_type") == "character"
                and str(current.get("predicate") or "").startswith("state.")
                and current.get("operation") == "transition"
            ):
                transitioned_characters[current["subject_key"]] = (current.get("subject_label") or current["subject_key"], current["id"])

        for subject_key, (label, anchor_prop_id) in transitioned_characters.items():
            if self._build_form(
                subject_key=subject_key, subject_label=label, anchor_prop_id=anchor_prop_id,
                context=context, session=session, turn_id=turn_id, source_kind=source_kind,
                story_order=story_order, world_time=world_time,
            ):
                report.forms += 1
        return report.to_dict()

    def list_forms(self, context: MemoryQueryContext, *, subject_key: str) -> list[dict[str, Any]]:
        with self.store.connection() as con:
            rows = con.execute(
                "SELECT * FROM continuity_forms WHERE project_id IS ? AND world_id IS ? AND subject_key=? "
                "ORDER BY COALESCE(story_order,-1e308),created_at,id",
                (context.project_id, context.world_id, subject_key),
            ).fetchall()
        forms = []
        for raw in rows:
            item = dict(raw)
            anchor = item.get("anchor_proposition_id")
            if anchor:
                try:
                    evaluated = self.service.evaluate_proposition(self.store.get_proposition(anchor), context)
                except KeyError:
                    continue
                if evaluated.get("knowledge_state") != "canon" and int(evaluated.get("support_count") or 0) <= 0:
                    continue
            item["world_time"] = loads(item.pop("world_time_json", None), None)
            item["state"] = loads(item.pop("state_json", None), {})
            forms.append(item)
        return forms

    def list_events(self, context: MemoryQueryContext, *, subject_key: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = [context.project_id, context.world_id]
        subject_join = ""
        subject_where = ""
        if subject_key:
            subject_join = " JOIN continuity_event_effects x ON x.event_id=e.id "
            subject_where = " AND x.subject_key=?"
            params.append(subject_key)
        with self.store.connection() as con:
            rows = con.execute(
                "SELECT DISTINCT e.* FROM continuity_events e" + subject_join +
                " WHERE e.project_id IS ? AND e.world_id IS ?" + subject_where +
                " ORDER BY COALESCE(e.story_order,-1e308),e.created_at,e.id",
                params,
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["world_time"] = loads(item.pop("world_time_json", None), None)
            with self.store.connection() as con:
                effects = con.execute(
                    "SELECT * FROM continuity_event_effects WHERE event_id=? ORDER BY created_at,proposition_id",
                    (item["id"],),
                ).fetchall()
                causes = con.execute(
                    "SELECT * FROM continuity_causal_links WHERE event_id=? ORDER BY created_at,id",
                    (item["id"],),
                ).fetchall()
            visible_effects = []
            for effect in effects:
                effect_item = dict(effect)
                try:
                    evaluated = self.service.evaluate_proposition(
                        self.store.get_proposition(effect_item["proposition_id"]), context
                    )
                except KeyError:
                    continue
                if evaluated.get("knowledge_state") == "canon" or int(evaluated.get("support_count") or 0) > 0:
                    visible_effects.append(effect_item)
            if not visible_effects:
                continue
            item["effects"] = visible_effects
            item["causal_links"] = [dict(row) for row in causes]
            output.append(item)
        return output

    def list_conflicts(self, context: MemoryQueryContext, *, subject_key: str | None = None,
                       include_resolved: bool = False) -> list[dict[str, Any]]:
        where = ["project_id IS ?", "world_id IS ?"]
        params: list[Any] = [context.project_id, context.world_id]
        if subject_key:
            where.append("subject_key=?")
            params.append(subject_key)
        if not include_resolved:
            where.append("status='open'")
        with self.store.connection() as con:
            rows = con.execute(
                f"SELECT * FROM continuity_conflicts WHERE {' AND '.join(where)} ORDER BY created_at,id",
                params,
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            try:
                left = self.service.evaluate_proposition(self.store.get_proposition(item["left_proposition_id"]), context)
                right = self.service.evaluate_proposition(self.store.get_proposition(item["right_proposition_id"]), context)
            except KeyError:
                continue
            if not any(x.get("knowledge_state") == "canon" or int(x.get("support_count") or 0) > 0 for x in (left, right)):
                continue
            item["left"] = left
            item["right"] = right
            output.append(item)
        return output

    def change_history(self, context: MemoryQueryContext, *, subject_key: str) -> list[dict[str, Any]]:
        with self.store.connection() as con:
            rows = con.execute(
                "SELECT * FROM continuity_edges WHERE project_id IS ? AND world_id IS ? AND subject_key=? "
                "ORDER BY COALESCE(story_order,-1e308),created_at,id",
                (context.project_id, context.world_id, subject_key),
            ).fetchall()
        output = []
        for row in rows:
            edge = dict(row)
            try:
                before = self.service.evaluate_proposition(self.store.get_proposition(edge["from_proposition_id"]), context)
                after = self.service.evaluate_proposition(self.store.get_proposition(edge["to_proposition_id"]), context)
            except KeyError:
                continue
            if not (before.get("knowledge_state") == "canon" or int(before.get("support_count") or 0) > 0):
                continue
            if not (after.get("knowledge_state") == "canon" or int(after.get("support_count") or 0) > 0):
                continue
            event = self.store.find_event_for_proposition(after["id"])
            edge["before"] = before
            edge["after"] = after
            edge["event"] = event
            edge["world_time"] = loads(edge.pop("world_time_json", None), None)
            output.append(edge)
        return output

    def resolve_conflict(self, conflict_id: str, *, action: str,
                         from_proposition_id: str | None = None,
                         to_proposition_id: str | None = None,
                         note: str = "") -> dict[str, Any]:
        if action not in {"correction", "story_change", "dismiss"}:
            raise ValueError("action must be correction, story_change, or dismiss")
        with self.store.connection() as con:
            row = con.execute("SELECT * FROM continuity_conflicts WHERE id=?", (conflict_id,)).fetchone()
        if row is None:
            raise KeyError(conflict_id)
        conflict = dict(row)
        pair = {conflict["left_proposition_id"], conflict["right_proposition_id"]}
        now = utc_now()
        if action == "dismiss":
            with self.store._lock, self.store.connection() as con:
                con.execute("UPDATE continuity_conflicts SET status='dismissed',resolved_at=? WHERE id=?", (now, conflict_id))
        else:
            if not from_proposition_id or not to_proposition_id or {from_proposition_id, to_proposition_id} != pair:
                raise ValueError("from_proposition_id and to_proposition_id must select the two conflicting claims")
            previous = self.store.get_proposition(from_proposition_id)
            current = self.store.get_proposition(to_proposition_id)
            session = {
                "project_id": conflict.get("project_id"), "world_id": conflict.get("world_id"),
                "branch_id": conflict.get("branch_id"), "id": conflict.get("session_id"),
            }
            self._insert_edge(
                previous=previous, current=current, kind=action, session=session,
                turn_id=conflict.get("source_turn_id") or "user_resolution",
                source_kind="user_continuity_resolution", story_order=None, world_time=None,
            )
            with self.store._lock, self.store.connection() as con:
                con.execute("UPDATE continuity_conflicts SET status='resolved',resolved_at=? WHERE id=?", (now, conflict_id))
        with self.store._lock, self.store.connection() as con:
            con.execute(
                "INSERT INTO continuity_conflict_resolutions(id,conflict_id,action,from_proposition_id,to_proposition_id,note,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (make_id("CONFRES"), conflict_id, action, from_proposition_id, to_proposition_id, note.strip(), now),
            )
            result = con.execute("SELECT * FROM continuity_conflicts WHERE id=?", (conflict_id,)).fetchone()
        return dict(result)

    def status(self) -> dict[str, Any]:
        with self.store.connection() as con:
            edges = con.execute("SELECT COUNT(*) AS n FROM continuity_edges").fetchone()["n"]
            conflicts = con.execute("SELECT COUNT(*) AS n FROM continuity_conflicts WHERE status='open'").fetchone()["n"]
            forms = con.execute("SELECT COUNT(*) AS n FROM continuity_forms").fetchone()["n"]
            events = con.execute("SELECT COUNT(*) AS n FROM continuity_events").fetchone()["n"]
            mentions = con.execute("SELECT COUNT(*) AS n FROM discovery_mentions").fetchone()["n"]
        return {
            "version": CONTINUITY_VERSION,
            "supersession_edges": int(edges),
            "open_conflicts": int(conflicts),
            "forms": int(forms),
            "events": int(events),
            "mentions": int(mentions),
        }


def install_continuity_runtime(service) -> ContinuityResolver:
    """Attach v1.2.2 continuity as a derived, idempotent post-capture layer."""
    existing = getattr(service, "continuity", None)
    if isinstance(existing, ContinuityResolver):
        return existing

    resolver = ContinuityResolver(service)
    original_capture_turn = service.capture_turn

    def capture_turn_with_continuity(turn_id: str, *, source_kind: str = "user_prompt"):
        report = original_capture_turn(turn_id, source_kind=source_kind)
        try:
            resolver.resolve_turn(turn_id, source_kind=source_kind)
        except Exception as exc:
            # Continuity is rebuildable derived state. Extraction/provenance must
            # never fail merely because continuity reconstruction had a problem.
            setattr(service, "_continuity_last_error", str(exc))
        return report

    service.capture_turn = capture_turn_with_continuity
    service.continuity = resolver
    service.continuity_current_view = resolver.current_view
    service.continuity_forms = resolver.list_forms
    service.continuity_events = resolver.list_events
    service.continuity_conflicts = resolver.list_conflicts
    service.continuity_history = resolver.change_history
    service._continuity_runtime_installed = True
    return resolver
