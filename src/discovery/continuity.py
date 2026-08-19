from __future__ import annotations

from dataclasses import dataclass, asdict
from hashlib import sha256
import re
from typing import Any

from src.memory.models import MemoryQueryContext

from .store import dumps, loads, make_id, utc_now


CONTINUITY_VERSION = "1.2.2b1"

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
        if current.get("operation") == "correction":
            return "correction"
        if CORRECTION_CUES.search(source_text):
            return "correction"
        if TRANSITION_CUES.search(source_text):
            return "story_change"
        return "conflict"

    def _insert_edge(self, *, previous: dict[str, Any], current: dict[str, Any], kind: str,
                     session: dict[str, Any], turn_id: str | None, source_kind: str,
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
                    previous_prop: dict[str, Any] | None, event_id: str | None,
                    context: MemoryQueryContext, session: dict[str, Any], turn_id: str,
                    source_kind: str, story_order: float | None, world_time: Any) -> bool:
        current = self.current_view(context, subject_key=subject_key)
        after_state = {
            item["predicate"].removeprefix("state."): item.get("value")
            for item in current["heads"]
            if str(item.get("predicate") or "").startswith("state.")
        }
        if not after_state:
            return False
        form_id = self._form_id(subject_key, turn_id, source_kind)
        with self.store.connection() as con:
            existing = con.execute("SELECT id FROM continuity_forms WHERE id=?", (form_id,)).fetchone()
            parent = con.execute(
                "SELECT * FROM continuity_forms WHERE project_id IS ? AND world_id IS ? AND subject_key=? AND id!=? "
                "ORDER BY COALESCE(story_order,-1e308) DESC,created_at DESC LIMIT 1",
                (session.get("project_id"), session.get("world_id"), subject_key, form_id),
            ).fetchone()
        if existing:
            return False
        before_state = loads(parent["after_state_json"] or parent["state_json"], {}) if parent else dict(after_state)
        if previous_prop and str(previous_prop.get("predicate") or "").startswith("state."):
            before_state[previous_prop["predicate"].removeprefix("state.")] = previous_prop.get("value")
        form_name = f"State after {turn_id}"
        with self.store._lock, self.store.connection() as con:
            con.execute(
                "INSERT INTO continuity_forms(id,project_id,world_id,branch_id,session_id,subject_key,subject_label,"
                "source_turn_id,source_kind,anchor_proposition_id,parent_form_id,reason,story_order,world_time_json,state_json,"
                "created_at,event_id,form_name,before_state_json,after_state_json) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    form_id, session.get("project_id"), session.get("world_id"), session.get("branch_id"), session.get("id"),
                    subject_key, subject_label, turn_id, source_kind, anchor_prop_id,
                    parent["id"] if parent else None, "state_transition" if previous_prop else "baseline_observed",
                    story_order, dumps(world_time) if world_time is not None else None, dumps(after_state), utc_now(),
                    event_id, form_name, dumps(before_state), dumps(after_state),
                ),
            )
        return True

    def resolve_turn(self, turn_id: str, *, source_kind: str = "user_prompt") -> dict[str, Any]:
        turn, session, context, world_time, story_order = self._turn_scope(turn_id)
        source_text = self._source_text(turn, source_kind)
        current_props = self._current_propositions(turn_id, source_kind)
        report = ContinuityResolutionReport(turn_id=turn_id, source_kind=source_kind)
        transitioned_characters: dict[str, tuple[str, str, dict[str, Any] | None, str | None]] = {}

        for current in current_props:
            if current.get("predicate") in NON_HEAD_PREDICATES or current.get("operation") == "relation":
                continue
            report.examined += 1
            previous = self._previous_candidate(current, context, turn_id)
            event_id = None
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
                    event_id = self.service.events.attach_before(
                        after_proposition_id=current["id"], before_proposition_id=previous["id"], change_kind=kind
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
                transitioned_characters[current["subject_key"]] = (
                    current.get("subject_label") or current["subject_key"], current["id"], previous,
                    event_id or self.service.events.event_for_after(current["id"]),
                )

        for subject_key, (label, anchor_prop_id, previous_prop, event_id) in transitioned_characters.items():
            if self._build_form(
                subject_key=subject_key, subject_label=label, anchor_prop_id=anchor_prop_id,
                previous_prop=previous_prop, event_id=event_id,
                context=context, session=session, turn_id=turn_id, source_kind=source_kind,
                story_order=story_order, world_time=world_time,
            ):
                report.forms += 1
        return report.to_dict()

    def record_explicit_change(
        self, previous: dict[str, Any], current: dict[str, Any], context: MemoryQueryContext,
        *, kind: str, note: str = "",
    ) -> str:
        if kind not in {"correction", "story_change", "refinement"}:
            raise ValueError("continuity change kind must be correction, story_change, or refinement")
        session = {
            "id": context.session_id, "project_id": context.project_id or current.get("project_id"),
            "world_id": context.world_id or current.get("world_id"), "branch_id": context.branch_id,
        }
        edge_id = self._insert_edge(
            previous=previous, current=current, kind=kind, session=session,
            turn_id=None, source_kind="user_library_edit", story_order=context.story_order, world_time=context.world_time,
        )
        self.service.events.attach_before(
            after_proposition_id=current["id"], before_proposition_id=previous["id"], change_kind=kind
        )
        return edge_id

    def _conflict_rows(self, context: MemoryQueryContext, *, subject_keys: list[str] | None = None, status: str = "open"):
        where = ["project_id IS ?", "world_id IS ?"]
        params: list[Any] = [context.project_id, context.world_id]
        if status:
            where.append("status=?")
            params.append(status)
        if subject_keys:
            marks = ",".join("?" for _ in subject_keys)
            where.append(f"subject_key IN ({marks})")
            params.extend(subject_keys)
        with self.store.connection() as con:
            return con.execute(
                f"SELECT * FROM continuity_conflicts WHERE {' AND '.join(where)} ORDER BY created_at,id", params
            ).fetchall()

    def list_conflicts(self, context: MemoryQueryContext, *, subject_keys: list[str] | None = None, status: str = "open") -> list[dict[str, Any]]:
        output = []
        for row in self._conflict_rows(context, subject_keys=subject_keys, status=status):
            item = dict(row)
            try:
                left = self.store.get_proposition(item["left_proposition_id"])
                right = self.store.get_proposition(item["right_proposition_id"])
            except KeyError:
                continue
            visible = []
            for prop in (left, right):
                evaluated = self.service.evaluate_proposition(prop, context)
                if evaluated.get("knowledge_state") == "canon" or int(evaluated.get("support_count") or 0) > 0:
                    visible.append(prop)
            if len(visible) != 2:
                continue
            item["left"] = left
            item["right"] = right
            output.append(item)
        return output

    def resolve_conflict(
        self, conflict_id: str, context: MemoryQueryContext, *, resolution: str, note: str = ""
    ) -> dict[str, Any]:
        allowed = {"correction", "story_change", "prefer_left", "prefer_right", "keep_ambiguous"}
        if resolution not in allowed:
            raise ValueError(f"resolution must be one of {sorted(allowed)}")
        with self.store.connection() as con:
            row = con.execute("SELECT * FROM continuity_conflicts WHERE id=?", (conflict_id,)).fetchone()
        if not row:
            raise KeyError(conflict_id)
        conflict = dict(row)
        visible = self.list_conflicts(context, subject_keys=[conflict["subject_key"]], status=conflict["status"])
        if not any(item["id"] == conflict_id for item in visible):
            raise ValueError("Conflict is not visible in the requested narrative scope")
        left = self.store.get_proposition(conflict["left_proposition_id"])
        right = self.store.get_proposition(conflict["right_proposition_id"])
        chosen = None
        if resolution != "keep_ambiguous":
            if resolution in {"prefer_left", "prefer_right"}:
                chosen = left if resolution == "prefer_left" else right
                previous = right if chosen is left else left
                kind = "refinement"
            else:
                # The proposition supported by the turn that opened the conflict is
                # the newer observation. Explicit user resolution determines how it
                # relates to the previous observation; it still does not grant Canon.
                def in_source(prop):
                    return any(
                        inst.get("source_turn_id") == conflict.get("source_turn_id")
                        for inst in self.store.list_instances(prop["id"], active=True)
                    )
                current = right if in_source(right) else left if in_source(left) else right
                previous = left if current is right else right
                chosen = current
                kind = resolution
            session = {
                "id": context.session_id or conflict.get("session_id"),
                "project_id": context.project_id or conflict.get("project_id"),
                "world_id": context.world_id or conflict.get("world_id"),
                "branch_id": context.branch_id or conflict.get("branch_id"),
            }
            self._insert_edge(
                previous=previous, current=chosen, kind=kind, session=session,
                turn_id=conflict.get("source_turn_id"), source_kind="continuity_resolution",
                story_order=context.story_order, world_time=context.world_time,
            )
        with self.store._lock, self.store.connection() as con:
            con.execute(
                "UPDATE continuity_conflicts SET status='resolved',resolution_kind=?,resolution_note=?,"
                "chosen_proposition_id=?,resolved_at=? WHERE id=?",
                (resolution, note, chosen.get("id") if chosen else None, utc_now(), conflict_id),
            )
        return next(
            (item for item in self.list_conflicts(context, subject_keys=[conflict["subject_key"]], status="resolved") if item["id"] == conflict_id),
            {**conflict, "status": "resolved", "resolution_kind": resolution},
        )

    def list_mentions(self, context: MemoryQueryContext, *, subject_keys: list[str] | None = None, limit: int = 100) -> list[dict[str, Any]]:
        where = ["active=1", "project_id IS ?", "world_id IS ?"]
        params: list[Any] = [context.project_id, context.world_id]
        if context.session_id is not None:
            where.append("source_session_id IS ?")
            params.append(context.session_id)
        if subject_keys:
            marks = ",".join("?" for _ in subject_keys)
            where.append(f"(resolved_subject_key IN ({marks}) OR resolution_state!='resolved')")
            params.extend(subject_keys)
        params.append(max(1, min(int(limit), 1000)))
        with self.store.connection() as con:
            rows = con.execute(
                f"SELECT * FROM discovery_mentions WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT ?", params
            ).fetchall()
        items = []
        for raw in rows:
            item = dict(raw)
            item["candidates"] = loads(item.pop("candidates_json", None), [])
            item["world_time"] = loads(item.pop("world_time_json", None), None)
            item["active"] = bool(item.get("active"))
            items.append(item)
        return items

    def resource_summary(self, context: MemoryQueryContext, *, subject_keys: list[str]) -> dict[str, Any]:
        keys = [str(key) for key in subject_keys if key]
        combined_heads = []
        combined_ambiguous = []
        superseded: set[str] = set()
        forms = []
        events = []
        for key in keys:
            view = self.current_view(context, subject_key=key)
            combined_heads.extend(view["heads"])
            combined_ambiguous.extend(view["ambiguous"])
            superseded.update(view["superseded_proposition_ids"])
            forms.extend(self.list_forms(context, subject_key=key))
            events.extend(self.service.events.list_for_subject(context, subject_key=key))
        current_state = [
            item for item in combined_heads if str(item.get("predicate") or "").startswith("state.")
        ]
        conflicts = self.list_conflicts(context, subject_keys=keys, status="open")
        mentions = self.list_mentions(context, subject_keys=keys, limit=40)
        return {
            "version": CONTINUITY_VERSION,
            "current": combined_heads,
            "current_state": current_state,
            "ambiguous": combined_ambiguous,
            "superseded_proposition_ids": sorted(superseded),
            "forms": forms,
            "events": events,
            "conflicts": conflicts,
            "mentions": mentions,
        }

    def rebuild(self, context: MemoryQueryContext, *, limit: int = 2000) -> dict[str, Any]:
        where = ["i.active=1", "i.source_turn_id IS NOT NULL", "i.project_id IS ?", "i.world_id IS ?"]
        params: list[Any] = [context.project_id, context.world_id]
        if context.session_id is not None:
            where.append("i.source_session_id IS ?")
            params.append(context.session_id)
        params.append(max(1, min(int(limit), 10000)))
        with self.store.connection() as con:
            rows = con.execute(
                f"SELECT DISTINCT i.source_turn_id,i.source_kind,MIN(COALESCE(i.story_order,-1e308)) AS ord "
                f"FROM discovery_instances i WHERE {' AND '.join(where)} "
                "GROUP BY i.source_turn_id,i.source_kind ORDER BY ord,i.source_turn_id LIMIT ?", params
            ).fetchall()
        reports = []
        errors = []
        for row in rows:
            try:
                reports.append(self.resolve_turn(str(row["source_turn_id"]), source_kind=str(row["source_kind"])))
            except (KeyError, ValueError) as exc:
                errors.append({"turn_id": row["source_turn_id"], "source_kind": row["source_kind"], "error": str(exc)})
        return {"processed": len(reports), "errors": errors, "reports": reports}

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
            item["before_state"] = loads(item.pop("before_state_json", None), {})
            item["after_state"] = loads(item.pop("after_state_json", None), item["state"])
            forms.append(item)
        return forms

    def status(self) -> dict[str, Any]:
        with self.store.connection() as con:
            edges = con.execute("SELECT COUNT(*) AS n FROM continuity_edges").fetchone()["n"]
            conflicts = con.execute("SELECT COUNT(*) AS n FROM continuity_conflicts WHERE status='open'").fetchone()["n"]
            forms = con.execute("SELECT COUNT(*) AS n FROM continuity_forms").fetchone()["n"]
        with self.store.connection() as con:
            mentions = con.execute("SELECT COUNT(*) AS n FROM discovery_mentions WHERE active=1").fetchone()["n"]
            unresolved = con.execute("SELECT COUNT(*) AS n FROM discovery_mentions WHERE active=1 AND resolution_state!='resolved'").fetchone()["n"]
        return {
            "version": CONTINUITY_VERSION,
            "supersession_edges": int(edges),
            "open_conflicts": int(conflicts),
            "forms": int(forms),
            "mentions": int(mentions),
            "unresolved_mentions": int(unresolved),
            **self.service.events.status(),
        }


def install_continuity_runtime(service) -> ContinuityResolver:
    """Compatibility entrypoint for the explicit v1.2.2 orchestration spine.

    DiscoveryService owns NarrativeSemanticOrchestrator directly. This function
    no longer wraps ``capture_turn`` or mutates call order at runtime.
    """
    resolver = getattr(service, "continuity", None)
    if not isinstance(resolver, ContinuityResolver):
        resolver = ContinuityResolver(service)
        service.continuity = resolver
    service.continuity_current_view = resolver.current_view
    service.continuity_forms = resolver.list_forms
    service._continuity_runtime_installed = True
    return resolver
