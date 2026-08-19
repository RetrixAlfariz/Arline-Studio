from __future__ import annotations

from hashlib import sha256
from typing import Any

from src.memory.models import MemoryQueryContext

from .store import dumps, loads, utc_now


class NarrativeEventProjector:
    """Persist rebuildable EVENT-* records and state-transition causality links."""

    def __init__(self, service):
        self.service = service
        self.store = service.store

    def capture_events(
        self,
        events_payload: dict[str, Any] | None,
        *,
        source: dict[str, Any],
        key_map: dict[str, str],
    ) -> dict[str, str]:
        payload = events_payload or {}
        now = utc_now()
        with self.store._lock, self.store.connection() as con:
            con.execute(
                "UPDATE narrative_events SET active=0,updated_at=? WHERE source_turn_id=? AND source_kind=? "
                "AND active=1 AND source_revision!=?",
                (now, source.get("turn_id"), source.get("source_kind"), source.get("revision")),
            )

        mapping: dict[str, str] = {}
        for index, event in enumerate(payload.get("events") or []):
            raw_id = str(event.get("id") or f"event-{index}")
            digest = sha256(dumps([
                source.get("turn_id"), source.get("source_kind"), source.get("revision"), raw_id,
            ]).encode("utf-8")).hexdigest()[:16].upper()
            event_id = f"EVENT-{digest}"
            mapping[raw_id] = event_id
            segment_id = event.get("source_segment")
            segment = source.get("segments", {}).get(str(segment_id)) if segment_id else None
            segment_text = str(
                (segment or {}).get("raw_text") or (segment or {}).get("text")
                or (segment or {}).get("normalized_text") or ""
            )
            kind = str(event.get("event_type") or event.get("type") or event.get("kind") or "narrative_event")
            summary = str(event.get("summary") or event.get("description") or event.get("label") or segment_text or kind)
            participants = []
            for raw in event.get("participants") or event.get("entities") or []:
                if isinstance(raw, dict):
                    raw = raw.get("id") or raw.get("entity_id")
                key = key_map.get(str(raw), str(raw or ""))
                if key:
                    participants.append(key)
            with self.store._lock, self.store.connection() as con:
                con.execute(
                    "INSERT INTO narrative_events(id,project_id,world_id,branch_id,session_id,source_turn_id,source_kind,"
                    "source_revision,raw_event_id,event_type,summary,source_segment,participants_json,story_order,"
                    "world_time_json,metadata_json,active,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET event_type=excluded.event_type,summary=excluded.summary,"
                    "participants_json=excluded.participants_json,metadata_json=excluded.metadata_json,active=1,updated_at=excluded.updated_at",
                    (
                        event_id, source.get("project_id"), source.get("world_id"), source.get("branch_id"),
                        source.get("session_id"), source.get("turn_id"), source.get("source_kind"), source.get("revision"),
                        raw_id, kind, summary, segment_id, dumps(participants), source.get("story_order"),
                        dumps(source.get("world_time")) if source.get("world_time") is not None else None,
                        dumps(event), now, now,
                    ),
                )
        return mapping

    def link_after(
        self,
        *,
        event_id: str | None,
        subject_key: str,
        predicate: str,
        after_proposition_id: str,
    ) -> None:
        if not event_id:
            return
        link_id = "EVLINK-" + sha256(
            dumps([event_id, subject_key, predicate, after_proposition_id]).encode("utf-8")
        ).hexdigest()[:16].upper()
        with self.store._lock, self.store.connection() as con:
            con.execute(
                "INSERT INTO narrative_event_state_links(id,event_id,subject_key,predicate,before_proposition_id,"
                "after_proposition_id,change_kind,created_at,updated_at) VALUES(?,?,?,?,NULL,?,NULL,?,?) "
                "ON CONFLICT(event_id,after_proposition_id) DO UPDATE SET subject_key=excluded.subject_key,"
                "predicate=excluded.predicate,updated_at=excluded.updated_at",
                (link_id, event_id, subject_key, predicate, after_proposition_id, utc_now(), utc_now()),
            )

    def attach_before(self, *, after_proposition_id: str, before_proposition_id: str, change_kind: str) -> str | None:
        with self.store._lock, self.store.connection() as con:
            row = con.execute(
                "SELECT id,event_id FROM narrative_event_state_links WHERE after_proposition_id=? "
                "ORDER BY created_at DESC LIMIT 1",
                (after_proposition_id,),
            ).fetchone()
            if not row:
                return None
            con.execute(
                "UPDATE narrative_event_state_links SET before_proposition_id=?,change_kind=?,updated_at=? WHERE id=?",
                (before_proposition_id, change_kind, utc_now(), row["id"]),
            )
            return str(row["event_id"])

    def event_for_after(self, after_proposition_id: str) -> str | None:
        with self.store.connection() as con:
            row = con.execute(
                "SELECT event_id FROM narrative_event_state_links WHERE after_proposition_id=? "
                "ORDER BY created_at DESC LIMIT 1",
                (after_proposition_id,),
            ).fetchone()
        return str(row["event_id"]) if row else None

    def list_for_subject(self, context: MemoryQueryContext, *, subject_key: str) -> list[dict[str, Any]]:
        with self.store.connection() as con:
            rows = con.execute(
                "SELECT e.*,l.id AS link_id,l.predicate,l.before_proposition_id,l.after_proposition_id,l.change_kind "
                "FROM narrative_event_state_links l JOIN narrative_events e ON e.id=l.event_id "
                "WHERE e.active=1 AND e.project_id IS ? AND e.world_id IS ? AND l.subject_key=? "
                "ORDER BY COALESCE(e.story_order,-1e308),e.created_at,e.id",
                (context.project_id, context.world_id, subject_key),
            ).fetchall()
        output: list[dict[str, Any]] = []
        for raw in rows:
            item = dict(raw)
            try:
                after = self.store.get_proposition(item["after_proposition_id"])
                evaluated = self.service.evaluate_proposition(after, context)
            except KeyError:
                continue
            if evaluated.get("knowledge_state") != "canon" and int(evaluated.get("support_count") or 0) <= 0:
                continue
            before = None
            if item.get("before_proposition_id"):
                try:
                    before = self.store.get_proposition(item["before_proposition_id"])
                except KeyError:
                    before = None
            item["world_time"] = loads(item.pop("world_time_json", None), None)
            item["participants"] = loads(item.pop("participants_json", None), [])
            item["metadata"] = loads(item.pop("metadata_json", None), {})
            item["before"] = before
            item["after"] = after
            output.append(item)
        return output

    def status(self) -> dict[str, int]:
        with self.store.connection() as con:
            events = con.execute("SELECT COUNT(*) AS n FROM narrative_events WHERE active=1").fetchone()["n"]
            links = con.execute("SELECT COUNT(*) AS n FROM narrative_event_state_links").fetchone()["n"]
        return {"events": int(events), "state_links": int(links)}
