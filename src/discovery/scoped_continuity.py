from __future__ import annotations

from typing import Any

from src.memory.models import MemoryQueryContext

from .continuity import ContinuityResolver
from .store import dumps, utc_now


class LineageScopedContinuityResolver(ContinuityResolver):
    """Continuity resolver whose FORM ancestry obeys the same Scope Gate as reads.

    The base v1.2.2 continuity logic is retained; only FORM parent selection is
    specialized here so a sibling branch can never become an invisible parent
    of a newly derived state frame.
    """

    def _build_form(
        self,
        *,
        subject_key: str,
        subject_label: str,
        anchor_prop_id: str,
        previous_prop: dict[str, Any] | None,
        event_id: str | None,
        context: MemoryQueryContext,
        session: dict[str, Any],
        turn_id: str,
        source_kind: str,
        story_order: float | None,
        world_time: Any,
    ) -> bool:
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
            existing = con.execute(
                "SELECT id FROM continuity_forms WHERE id=?", (form_id,)
            ).fetchone()
        if existing:
            return False

        # The same scoped read model that exposes FORM history chooses ancestry.
        # This admits valid ancestors/fork history while excluding sibling state.
        visible_parents = self.list_forms(context, subject_key=subject_key)
        parent = visible_parents[-1] if visible_parents else None
        before_state = (
            dict(parent.get("after_state") or parent.get("state") or after_state)
            if parent
            else dict(after_state)
        )
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
                    form_id,
                    session.get("project_id"),
                    session.get("world_id"),
                    session.get("branch_id"),
                    session.get("id"),
                    subject_key,
                    subject_label,
                    turn_id,
                    source_kind,
                    anchor_prop_id,
                    parent["id"] if parent else None,
                    "state_transition" if previous_prop else "baseline_observed",
                    story_order,
                    dumps(world_time) if world_time is not None else None,
                    dumps(after_state),
                    utc_now(),
                    event_id,
                    form_name,
                    dumps(before_state),
                    dumps(after_state),
                ),
            )
        return True
