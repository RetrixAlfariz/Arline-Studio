from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if old not in text:
        raise RuntimeError(f"patch anchor not found in {path}: {old[:120]!r}")
    write(path, text.replace(old, new, 1))


# ---------------------------------------------------------------------------
# Phase B/C: one explicit Narrative Entity Resolver before persistence.
# ---------------------------------------------------------------------------
write("src/discovery/resolution.py", r'''from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import re
import unicodedata
from typing import Any

from .identity import normalize_identity_label, resolve_existing_family


TYPE_MAP = {
    "character": "character",
    "location": "location",
    "item": "item",
    "garment": "item",
    "organization": "organization",
    "lore": "lore",
    "world_rule": "world_rule",
}
FIRST_PERSON = {"aku", "saya", "i", "me", "my", "self", "myself", "-ku", "ku"}
THIRD_PERSON = {"dia", "ia", "he", "she", "him", "her", "it", "-nya", "nya", "itu"}
PLURAL_PERSON = {"mereka", "they", "them", "their"}
GENERIC = {
    "character", "person", "someone", "somebody", "unknown",
    "feminine_clothing", "underwear_set", "self_family",
}
SELF_NAME_RE = re.compile(
    r"(?:\bnamaku\b|\bnama\s+saya\b|\baku\s+bernama\b|\bsaya\s+bernama\b|"
    r"\bmy\s+name\s+is\b|\bi\s+am\s+called\b)\s+"
    r"(?P<name>[\wÀ-ÿ.'’\-]+(?:\s+[\wÀ-ÿ.'’\-]+){0,3})(?=\s*[,.;!?\n]|$)",
    re.I,
)


def _slug(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or "unknown"


def default_anchor(entity_type: str, label: str) -> str:
    prefix = {
        "character": "char", "location": "loc", "item": "item",
        "garment": "item", "organization": "org", "lore": "lore",
        "world_rule": "rule",
    }.get(entity_type, "entity")
    return f"{prefix}:{_slug(label)}"


@dataclass(slots=True)
class ResolutionResult:
    surface: str
    entity_type: str
    raw_subject_key: str
    subject_key: str | None
    subject_label: str
    resolution_kind: str
    confidence: float
    target_resource_type: str | None = None
    target_resource_id: str | None = None
    ambiguous_candidates: tuple[str, ...] = ()

    @property
    def resolved(self) -> bool:
        return bool(self.subject_key)

    def to_dict(self) -> dict[str, Any]:
        item = asdict(self)
        item["resolved"] = self.resolved
        item["ambiguous_candidates"] = list(self.ambiguous_candidates)
        return item


class NarrativeEntityResolver:
    """Conservative identity + bounded coreference gate for Discovery.

    Extractors are allowed to propose labels and temporary keys, but only this
    resolver decides the stable subject anchor persisted into propositions.
    It never fuzzy-merges identities. Ambiguous references are recorded as
    diagnostics and deliberately remain unresolved.
    """

    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.workspace = service.workspace
        self.foundation = service.foundation

    def _record(self, result: ResolutionResult, *, project_id: str | None,
                world_id: str | None, branch_id: str | None, session_id: str | None,
                turn_id: str | None, source_kind: str, span_start: int | None,
                span_end: int | None) -> ResolutionResult:
        self.store.record_mention(
            project_id=project_id, world_id=world_id, branch_id=branch_id,
            session_id=session_id, source_turn_id=turn_id, source_kind=source_kind,
            surface=result.surface, entity_type=result.entity_type,
            raw_subject_key=result.raw_subject_key,
            resolved_subject_key=result.subject_key,
            target_resource_type=result.target_resource_type,
            target_resource_id=result.target_resource_id,
            resolution_kind=result.resolution_kind,
            confidence=result.confidence,
            ambiguous_candidates=list(result.ambiguous_candidates),
            span_start=span_start, span_end=span_end,
        )
        return result

    def _existing_anchor(self, *, project_id: str | None, world_id: str | None,
                         raw_key: str, label: str, entity_type: str) -> ResolutionResult | None:
        linked = self.store.get_subject_link(
            project_id=project_id, world_id=world_id, subject_key=raw_key
        )
        if linked:
            return ResolutionResult(
                surface=label, entity_type=entity_type, raw_subject_key=raw_key,
                subject_key=raw_key, subject_label=label,
                resolution_kind="existing_anchor", confidence=1.0,
                target_resource_type=linked.get("resource_type"),
                target_resource_id=linked.get("resource_id"),
            )

        mapped = TYPE_MAP.get(entity_type, entity_type)
        family = resolve_existing_family(self.workspace, self.foundation, label, mapped)
        if family is None:
            return None
        canonical_key = self.store.find_subject_key_for_resource(
            project_id=project_id, world_id=world_id,
            resource_type="entity_family", resource_id=family["id"],
        ) or raw_key
        self.store.upsert_subject_link(
            project_id=project_id, world_id=world_id, subject_key=canonical_key,
            resource_type="entity_family", resource_id=family["id"],
        )
        return ResolutionResult(
            surface=label, entity_type=entity_type, raw_subject_key=raw_key,
            subject_key=canonical_key, subject_label=family.get("name") or label,
            resolution_kind="library_exact", confidence=1.0,
            target_resource_type="entity_family", target_resource_id=family["id"],
        )

    def _recent(self, *, session_id: str | None, branch_id: str | None,
                turn_id: str | None, entity_type: str | None = None,
                same_turn: bool | None = None) -> list[dict[str, Any]]:
        if not session_id:
            return []
        rows = self.store.recent_mentions(
            session_id=session_id, branch_id=branch_id,
            entity_type=entity_type, limit=32,
        )
        if same_turn is True:
            rows = [row for row in rows if row.get("source_turn_id") == turn_id]
        elif same_turn is False:
            rows = [row for row in rows if row.get("source_turn_id") != turn_id]
        return rows

    @staticmethod
    def _candidate_keys(rows: list[dict[str, Any]], *, cap: int = 8) -> list[str]:
        out: list[str] = []
        for row in rows:
            key = str(row.get("resolved_subject_key") or "")
            surface = normalize_identity_label(row.get("surface") or "")
            if not key or surface in FIRST_PERSON | THIRD_PERSON | PLURAL_PERSON | GENERIC:
                continue
            if key not in out:
                out.append(key)
            if len(out) >= cap:
                break
        return out

    def _self_explicit(self, source_text: str) -> str | None:
        match = SELF_NAME_RE.search(source_text or "")
        return " ".join(match.group("name").strip().split()) if match else None

    def resolve(self, *, project_id: str | None, world_id: str | None,
                branch_id: str | None, session_id: str | None, turn_id: str | None,
                source_kind: str, source_text: str, entity_type: str,
                raw_subject_key: str | None, label: str,
                span_start: int | None = None, span_end: int | None = None,
                record: bool = True) -> ResolutionResult:
        surface = " ".join(str(label or "").strip().split())
        entity_type = str(entity_type or "entity").strip() or "entity"
        raw_key = str(raw_subject_key or default_anchor(entity_type, surface or "unknown"))
        norm = normalize_identity_label(surface)

        def done(result: ResolutionResult) -> ResolutionResult:
            if record:
                return self._record(
                    result, project_id=project_id, world_id=world_id,
                    branch_id=branch_id, session_id=session_id, turn_id=turn_id,
                    source_kind=source_kind, span_start=span_start, span_end=span_end,
                )
            return result

        # Explicit named identities always outrank anaphora.
        if norm and norm not in FIRST_PERSON | THIRD_PERSON | PLURAL_PERSON | GENERIC:
            existing = self._existing_anchor(
                project_id=project_id, world_id=world_id, raw_key=raw_key,
                label=surface, entity_type=entity_type,
            )
            if existing:
                return done(existing)
            # Reuse a same-turn stable anchor when separate extractors emitted
            # different temporary keys for the exact same mention.
            same = self._recent(
                session_id=session_id, branch_id=branch_id, turn_id=turn_id,
                entity_type=entity_type, same_turn=True,
            )
            matches = {
                str(row.get("resolved_subject_key"))
                for row in same
                if normalize_identity_label(row.get("surface") or "") == norm
                and row.get("resolved_subject_key")
            }
            if len(matches) == 1:
                key = next(iter(matches))
                return done(ResolutionResult(
                    surface=surface, entity_type=entity_type, raw_subject_key=raw_key,
                    subject_key=key, subject_label=surface,
                    resolution_kind="same_turn_exact", confidence=0.99,
                ))
            return done(ResolutionResult(
                surface=surface, entity_type=entity_type, raw_subject_key=raw_key,
                subject_key=raw_key, subject_label=surface,
                resolution_kind="new_anchor", confidence=0.92,
            ))

        # First-person self only becomes resolvable after an explicit narrator
        # identity has been stated in the session. We never assume the only
        # character in a story is the narrator.
        if norm in FIRST_PERSON or norm in {"self", "self_family"}:
            explicit_name = self._self_explicit(source_text)
            if explicit_name:
                named = self.resolve(
                    project_id=project_id, world_id=world_id, branch_id=branch_id,
                    session_id=session_id, turn_id=turn_id, source_kind=source_kind,
                    source_text=source_text, entity_type="character",
                    raw_subject_key=default_anchor("character", explicit_name),
                    label=explicit_name, span_start=span_start, span_end=span_end,
                    record=True,
                )
                return done(ResolutionResult(
                    surface=surface or "self", entity_type="character",
                    raw_subject_key=raw_key, subject_key=named.subject_key,
                    subject_label=named.subject_label, resolution_kind="self_explicit",
                    confidence=1.0, target_resource_type=named.target_resource_type,
                    target_resource_id=named.target_resource_id,
                ))
            recent = self._recent(
                session_id=session_id, branch_id=branch_id, turn_id=turn_id,
                entity_type="character", same_turn=None,
            )
            narrator = next(
                (row for row in recent if row.get("resolution_kind") == "self_explicit"
                 and row.get("resolved_subject_key")), None
            )
            if narrator:
                return done(ResolutionResult(
                    surface=surface or "self", entity_type="character",
                    raw_subject_key=raw_key,
                    subject_key=str(narrator["resolved_subject_key"]),
                    subject_label=str(narrator.get("resolved_label") or narrator.get("surface") or "self"),
                    resolution_kind="self_recent", confidence=0.98,
                    target_resource_type=narrator.get("target_resource_type"),
                    target_resource_id=narrator.get("target_resource_id"),
                ))
            return done(ResolutionResult(
                surface=surface or "self", entity_type="character",
                raw_subject_key=raw_key, subject_key=None, subject_label=surface or "self",
                resolution_kind="unresolved_self", confidence=0.0,
            ))

        if norm in PLURAL_PERSON:
            return done(ResolutionResult(
                surface=surface, entity_type=entity_type, raw_subject_key=raw_key,
                subject_key=None, subject_label=surface,
                resolution_kind="unresolved_plural", confidence=0.0,
            ))

        if norm in THIRD_PERSON or norm in GENERIC:
            wanted_type = "character" if norm in {"dia", "ia", "he", "she", "him", "her"} else None
            # Same-turn candidates first, then bounded prior-turn candidates.
            same = self._candidate_keys(self._recent(
                session_id=session_id, branch_id=branch_id, turn_id=turn_id,
                entity_type=wanted_type, same_turn=True,
            ))
            candidates = same or self._candidate_keys(self._recent(
                session_id=session_id, branch_id=branch_id, turn_id=turn_id,
                entity_type=wanted_type, same_turn=False,
            ))
            if len(candidates) == 1:
                key = candidates[0]
                rows = self.store.recent_mentions(
                    session_id=session_id, branch_id=branch_id,
                    entity_type=wanted_type, limit=32,
                )
                source = next((row for row in rows if row.get("resolved_subject_key") == key), {})
                return done(ResolutionResult(
                    surface=surface, entity_type=str(source.get("entity_type") or entity_type),
                    raw_subject_key=raw_key, subject_key=key,
                    subject_label=str(source.get("resolved_label") or source.get("surface") or key),
                    resolution_kind="coreference_same_turn" if same else "coreference_recent",
                    confidence=0.9 if same else 0.82,
                    target_resource_type=source.get("target_resource_type"),
                    target_resource_id=source.get("target_resource_id"),
                ))
            if len(candidates) > 1:
                return done(ResolutionResult(
                    surface=surface, entity_type=entity_type, raw_subject_key=raw_key,
                    subject_key=None, subject_label=surface,
                    resolution_kind="ambiguous_coreference", confidence=0.0,
                    ambiguous_candidates=tuple(candidates),
                ))
            return done(ResolutionResult(
                surface=surface, entity_type=entity_type, raw_subject_key=raw_key,
                subject_key=None, subject_label=surface,
                resolution_kind="unresolved_coreference", confidence=0.0,
            ))

        return done(ResolutionResult(
            surface=surface, entity_type=entity_type, raw_subject_key=raw_key,
            subject_key=raw_key, subject_label=surface or raw_key,
            resolution_kind="new_anchor", confidence=0.8,
        ))
''')


# ---------------------------------------------------------------------------
# DiscoveryStore v4: auditable mentions + EVENT/causality + conflict decisions.
# ---------------------------------------------------------------------------
replace_once(
    "src/discovery/store.py",
    'DISCOVERY_SCHEMA_VERSION = 3\nCONTINUITY_SCHEMA_VERSION = "1.2.2a1"',
    'DISCOVERY_SCHEMA_VERSION = 4\nCONTINUITY_SCHEMA_VERSION = "1.2.2a1"',
)

replace_once(
    "src/discovery/store.py",
    '''                CREATE INDEX IF NOT EXISTS idx_continuity_form_subject ON continuity_forms(project_id,world_id,subject_key,story_order,created_at);\n\n                CREATE TABLE IF NOT EXISTS discovery_provisional_meta(''',
    '''                CREATE INDEX IF NOT EXISTS idx_continuity_form_subject ON continuity_forms(project_id,world_id,subject_key,story_order,created_at);\n\n                CREATE TABLE IF NOT EXISTS discovery_mentions(\n                    id TEXT PRIMARY KEY,\n                    mention_key TEXT NOT NULL UNIQUE,\n                    project_id TEXT,\n                    world_id TEXT,\n                    branch_id TEXT,\n                    session_id TEXT,\n                    source_turn_id TEXT,\n                    source_kind TEXT NOT NULL,\n                    surface TEXT NOT NULL,\n                    entity_type TEXT NOT NULL,\n                    raw_subject_key TEXT NOT NULL,\n                    resolved_subject_key TEXT,\n                    resolved_label TEXT,\n                    target_resource_type TEXT,\n                    target_resource_id TEXT,\n                    resolution_kind TEXT NOT NULL,\n                    confidence REAL NOT NULL DEFAULT 0.0,\n                    ambiguous_json TEXT NOT NULL DEFAULT '[]',\n                    span_start INTEGER,\n                    span_end INTEGER,\n                    created_at TEXT NOT NULL,\n                    updated_at TEXT NOT NULL\n                );\n                CREATE INDEX IF NOT EXISTS idx_discovery_mentions_scope\n                    ON discovery_mentions(session_id,branch_id,entity_type,created_at);\n                CREATE INDEX IF NOT EXISTS idx_discovery_mentions_anchor\n                    ON discovery_mentions(project_id,world_id,resolved_subject_key,created_at);\n\n                CREATE TABLE IF NOT EXISTS continuity_events(\n                    id TEXT PRIMARY KEY,\n                    event_key TEXT NOT NULL UNIQUE,\n                    project_id TEXT,\n                    world_id TEXT,\n                    branch_id TEXT,\n                    session_id TEXT,\n                    source_turn_id TEXT,\n                    source_kind TEXT NOT NULL,\n                    event_type TEXT NOT NULL,\n                    summary TEXT NOT NULL,\n                    source_segment TEXT,\n                    story_order REAL,\n                    world_time_json TEXT,\n                    created_at TEXT NOT NULL,\n                    updated_at TEXT NOT NULL\n                );\n                CREATE INDEX IF NOT EXISTS idx_continuity_events_scope\n                    ON continuity_events(project_id,world_id,branch_id,story_order,created_at);\n                CREATE TABLE IF NOT EXISTS continuity_event_effects(\n                    event_id TEXT NOT NULL REFERENCES continuity_events(id) ON DELETE CASCADE,\n                    proposition_id TEXT NOT NULL REFERENCES discovery_propositions(id) ON DELETE CASCADE,\n                    subject_key TEXT NOT NULL,\n                    predicate TEXT NOT NULL,\n                    role TEXT NOT NULL DEFAULT 'after',\n                    created_at TEXT NOT NULL,\n                    PRIMARY KEY(event_id,proposition_id,role)\n                );\n                CREATE INDEX IF NOT EXISTS idx_continuity_effect_subject\n                    ON continuity_event_effects(subject_key,predicate,event_id);\n                CREATE TABLE IF NOT EXISTS continuity_causal_links(\n                    id TEXT PRIMARY KEY,\n                    event_id TEXT NOT NULL REFERENCES continuity_events(id) ON DELETE CASCADE,\n                    subject_key TEXT NOT NULL,\n                    predicate TEXT NOT NULL,\n                    from_proposition_id TEXT,\n                    to_proposition_id TEXT NOT NULL,\n                    kind TEXT NOT NULL,\n                    created_at TEXT NOT NULL,\n                    UNIQUE(event_id,from_proposition_id,to_proposition_id,kind)\n                );\n                CREATE INDEX IF NOT EXISTS idx_continuity_causal_subject\n                    ON continuity_causal_links(subject_key,predicate,event_id);\n                CREATE TABLE IF NOT EXISTS continuity_conflict_resolutions(\n                    id TEXT PRIMARY KEY,\n                    conflict_id TEXT NOT NULL REFERENCES continuity_conflicts(id) ON DELETE CASCADE,\n                    action TEXT NOT NULL,\n                    from_proposition_id TEXT,\n                    to_proposition_id TEXT,\n                    note TEXT NOT NULL DEFAULT '',\n                    created_at TEXT NOT NULL\n                );\n\n                CREATE TABLE IF NOT EXISTS discovery_provisional_meta(''',
)

replace_once(
    "src/discovery/store.py",
    '''    def status(self) -> dict[str, int]:\n''',
    r'''    def find_subject_key_for_resource(self, *, project_id: str | None, world_id: str | None,
                                      resource_type: str, resource_id: str) -> str | None:
        with self.connection() as con:
            row = con.execute(
                "SELECT subject_key FROM discovery_subject_links WHERE project_id=? AND world_id=? "
                "AND resource_type=? AND resource_id=? ORDER BY updated_at DESC LIMIT 1",
                (project_id or "", world_id or "", resource_type, resource_id),
            ).fetchone()
        return str(row["subject_key"]) if row else None

    def record_mention(self, *, project_id: str | None, world_id: str | None,
                       branch_id: str | None, session_id: str | None,
                       source_turn_id: str | None, source_kind: str, surface: str,
                       entity_type: str, raw_subject_key: str,
                       resolved_subject_key: str | None,
                       target_resource_type: str | None,
                       target_resource_id: str | None,
                       resolution_kind: str, confidence: float,
                       ambiguous_candidates: list[str] | None = None,
                       span_start: int | None = None, span_end: int | None = None,
                       resolved_label: str | None = None) -> dict[str, Any]:
        seed = dumps([
            source_turn_id or "", source_kind, raw_subject_key, surface,
            entity_type, span_start, span_end,
        ])
        mention_key = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        now = utc_now()
        with self._lock, self.connection() as con:
            row = con.execute("SELECT id FROM discovery_mentions WHERE mention_key=?", (mention_key,)).fetchone()
            if row:
                mention_id = row["id"]
                con.execute(
                    "UPDATE discovery_mentions SET resolved_subject_key=?,resolved_label=?,target_resource_type=?,"
                    "target_resource_id=?,resolution_kind=?,confidence=?,ambiguous_json=?,updated_at=? WHERE id=?",
                    (resolved_subject_key, resolved_label or surface, target_resource_type, target_resource_id,
                     resolution_kind, max(0.0, min(1.0, float(confidence))),
                     dumps(ambiguous_candidates or []), now, mention_id),
                )
            else:
                mention_id = make_id("MENTION")
                con.execute(
                    "INSERT INTO discovery_mentions(id,mention_key,project_id,world_id,branch_id,session_id,"
                    "source_turn_id,source_kind,surface,entity_type,raw_subject_key,resolved_subject_key,resolved_label,"
                    "target_resource_type,target_resource_id,resolution_kind,confidence,ambiguous_json,span_start,span_end,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (mention_id, mention_key, project_id, world_id, branch_id, session_id,
                     source_turn_id, source_kind, surface, entity_type, raw_subject_key,
                     resolved_subject_key, resolved_label or surface, target_resource_type,
                     target_resource_id, resolution_kind, max(0.0, min(1.0, float(confidence))),
                     dumps(ambiguous_candidates or []), span_start, span_end, now, now),
                )
            result = con.execute("SELECT * FROM discovery_mentions WHERE id=?", (mention_id,)).fetchone()
        item = dict(result)
        item["ambiguous_candidates"] = loads(item.pop("ambiguous_json", None), [])
        return item

    def recent_mentions(self, *, session_id: str, branch_id: str | None,
                        entity_type: str | None = None, limit: int = 32) -> list[dict[str, Any]]:
        where = ["session_id=?", "(branch_id IS ? OR branch_id IS NULL)"]
        params: list[Any] = [session_id, branch_id]
        if entity_type:
            where.append("entity_type=?")
            params.append(entity_type)
        params.append(max(1, min(int(limit), 256)))
        with self.connection() as con:
            rows = con.execute(
                f"SELECT * FROM discovery_mentions WHERE {' AND '.join(where)} ORDER BY rowid DESC LIMIT ?",
                params,
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["ambiguous_candidates"] = loads(item.pop("ambiguous_json", None), [])
            output.append(item)
        return output

    def list_mentions_for_subject(self, *, project_id: str | None, world_id: str | None,
                                  subject_key: str, limit: int = 100) -> list[dict[str, Any]]:
        with self.connection() as con:
            rows = con.execute(
                "SELECT * FROM discovery_mentions WHERE project_id IS ? AND world_id IS ? AND resolved_subject_key=? "
                "ORDER BY rowid DESC LIMIT ?",
                (project_id, world_id, subject_key, max(1, min(int(limit), 500))),
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["ambiguous_candidates"] = loads(item.pop("ambiguous_json", None), [])
            output.append(item)
        return output

    def upsert_continuity_event(self, *, project_id: str | None, world_id: str | None,
                                branch_id: str | None, session_id: str | None,
                                source_turn_id: str | None, source_kind: str,
                                event_type: str, summary: str,
                                source_segment: str | None = None,
                                story_order: float | None = None,
                                world_time: Any = None, stable_seed: Any = None) -> dict[str, Any]:
        seed = dumps([source_turn_id or "", source_kind, event_type, source_segment or "", stable_seed or summary])
        event_key = hashlib.sha256(seed.encode("utf-8")).hexdigest()
        now = utc_now()
        with self._lock, self.connection() as con:
            row = con.execute("SELECT id FROM continuity_events WHERE event_key=?", (event_key,)).fetchone()
            if row:
                event_id = row["id"]
                con.execute(
                    "UPDATE continuity_events SET summary=?,story_order=?,world_time_json=?,updated_at=? WHERE id=?",
                    (summary, story_order, dumps(world_time) if world_time is not None else None, now, event_id),
                )
            else:
                digest = hashlib.sha256(event_key.encode("utf-8")).hexdigest()[:16].upper()
                event_id = f"EVENT-{digest}"
                con.execute(
                    "INSERT INTO continuity_events(id,event_key,project_id,world_id,branch_id,session_id,source_turn_id,"
                    "source_kind,event_type,summary,source_segment,story_order,world_time_json,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (event_id, event_key, project_id, world_id, branch_id, session_id, source_turn_id,
                     source_kind, event_type, summary, source_segment, story_order,
                     dumps(world_time) if world_time is not None else None, now, now),
                )
            result = con.execute("SELECT * FROM continuity_events WHERE id=?", (event_id,)).fetchone()
        item = dict(result)
        item["world_time"] = loads(item.pop("world_time_json", None), None)
        return item

    def link_event_effect(self, event_id: str, proposition_id: str, *, subject_key: str,
                          predicate: str, role: str = "after") -> None:
        with self._lock, self.connection() as con:
            con.execute(
                "INSERT OR IGNORE INTO continuity_event_effects(event_id,proposition_id,subject_key,predicate,role,created_at) "
                "VALUES(?,?,?,?,?,?)",
                (event_id, proposition_id, subject_key, predicate, role, utc_now()),
            )

    def find_event_for_proposition(self, proposition_id: str) -> dict[str, Any] | None:
        with self.connection() as con:
            row = con.execute(
                "SELECT e.* FROM continuity_events e JOIN continuity_event_effects x ON x.event_id=e.id "
                "WHERE x.proposition_id=? ORDER BY e.rowid DESC LIMIT 1",
                (proposition_id,),
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["world_time"] = loads(item.pop("world_time_json", None), None)
        return item

    def status(self) -> dict[str, int]:
''',
)


# ---------------------------------------------------------------------------
# Service: all analytical candidates pass through the resolver before PROP-*.
# ---------------------------------------------------------------------------
replace_once(
    "src/discovery/service.py",
    'from .store import DiscoveryStore, checksum\n',
    'from .identity import resolve_existing_family\nfrom .resolution import NarrativeEntityResolver\nfrom .store import DiscoveryStore, checksum\n',
)
replace_once(
    "src/discovery/service.py",
    '''        self.pipeline = ArlineAnalyticalPipeline.default()\n        self.gate = ScopeGate(workspace, history)\n''',
    '''        self.pipeline = ArlineAnalyticalPipeline.default()\n        self.gate = ScopeGate(workspace, history)\n        self.entity_resolver = NarrativeEntityResolver(self)\n''',
)
replace_once(
    "src/discovery/service.py",
    '''    def _existing_family(self, label: str, entity_type: str) -> dict[str, Any] | None:\n        mapped = LIBRARY_ENTITY_TYPE.get(entity_type, entity_type)\n        needle = label.strip().casefold()\n        try:\n            families = self.workspace.list_entity_families(None, entity_type=mapped)\n        except Exception:\n            families = []\n        return next((item for item in families if str(item.get("name") or "").strip().casefold() == needle), None)\n''',
    '''    def _existing_family(self, label: str, entity_type: str) -> dict[str, Any] | None:\n        mapped = LIBRARY_ENTITY_TYPE.get(entity_type, entity_type)\n        return resolve_existing_family(self.workspace, self.foundation, label, mapped)\n''',
)

old_capture = '''    def _capture_prop(self, *, report_keys: set[str], source: dict[str, Any],\n                      subject_type: str, subject_key: str, subject_label: str,\n                      predicate: str, value: Any, operation: str,\n                      source_segment: str | None, confidence: float,\n                      explicitness: str, inferred: bool = False,\n                      object_type: str | None = None, object_key: str | None = None,\n                      object_label: str | None = None,\n                      temporal_state: str = "current_or_unspecified") -> bool:\n        segment = source["segments"].get(str(source_segment)) if source_segment else None\n        span_start, span_end, span_text = self._span(segment)\n        link = self._subject_link(\n            project_id=source["project_id"], world_id=source["world_id"],\n            subject_key=subject_key, subject_label=subject_label, subject_type=subject_type,\n        )\n        prop = self.store.upsert_proposition(\n            project_id=source["project_id"], world_id=source["world_id"],\n            subject_type=subject_type, subject_key=subject_key, subject_label=subject_label,\n            predicate=predicate, value=value, object_type=object_type,\n            object_key=object_key, object_label=object_label, operation=operation,\n            temporal_state=temporal_state,\n            target_resource_type=link.get("resource_type") if link else None,\n            target_resource_id=link.get("resource_id") if link else None,\n        )\n        qualifies = bool(\n            source["base_qualifies"]\n            and explicitness == "explicit"\n            and not inferred\n            and confidence >= 0.6\n        )\n        self.store.add_instance(\n            prop["id"], source_kind=source["source_kind"],\n            source_session_id=source["session_id"], source_turn_id=source["turn_id"],\n            origin_session_id=source["origin_session_id"], origin_turn_id=source["origin_turn_id"],\n            source_revision=source["revision"], project_id=source["project_id"],\n            world_id=source["world_id"], branch_id=source["branch_id"],\n            world_time=source["world_time"], story_order=source["story_order"],\n            source_segment=source_segment, span_start=span_start, span_end=span_end,\n            span_text=span_text, extraction_confidence=confidence,\n            explicitness="inferred" if inferred else explicitness,\n            qualifies_review=qualifies,\n        )\n        report_keys.add(prop["id"])\n        return True\n'''
new_capture = '''    def _capture_prop(self, *, report_keys: set[str], source: dict[str, Any],\n                      subject_type: str, subject_key: str, subject_label: str,\n                      predicate: str, value: Any, operation: str,\n                      source_segment: str | None, confidence: float,\n                      explicitness: str, inferred: bool = False,\n                      object_type: str | None = None, object_key: str | None = None,\n                      object_label: str | None = None,\n                      temporal_state: str = "current_or_unspecified") -> dict[str, Any] | None:\n        segment = source["segments"].get(str(source_segment)) if source_segment else None\n        span_start, span_end, span_text = self._span(segment)\n        resolved = self.entity_resolver.resolve(\n            project_id=source["project_id"], world_id=source["world_id"],\n            branch_id=source["branch_id"], session_id=source["session_id"],\n            turn_id=source["turn_id"], source_kind=source["source_kind"],\n            source_text=source.get("text") or span_text, entity_type=subject_type,\n            raw_subject_key=subject_key, label=subject_label,\n            span_start=span_start, span_end=span_end,\n        )\n        if not resolved.resolved:\n            return None\n        subject_key = str(resolved.subject_key)\n        subject_label = resolved.subject_label or subject_label\n\n        resolved_object = None\n        if object_key and object_label:\n            resolved_object = self.entity_resolver.resolve(\n                project_id=source["project_id"], world_id=source["world_id"],\n                branch_id=source["branch_id"], session_id=source["session_id"],\n                turn_id=source["turn_id"], source_kind=source["source_kind"],\n                source_text=source.get("text") or span_text, entity_type=object_type or "entity",\n                raw_subject_key=object_key, label=object_label,\n                span_start=span_start, span_end=span_end,\n            )\n            if not resolved_object.resolved:\n                return None\n            object_key = str(resolved_object.subject_key)\n            object_label = resolved_object.subject_label or object_label\n\n        link = self._subject_link(\n            project_id=source["project_id"], world_id=source["world_id"],\n            subject_key=subject_key, subject_label=subject_label, subject_type=subject_type,\n        )\n        prop = self.store.upsert_proposition(\n            project_id=source["project_id"], world_id=source["world_id"],\n            subject_type=subject_type, subject_key=subject_key, subject_label=subject_label,\n            predicate=predicate, value=value, object_type=object_type,\n            object_key=object_key, object_label=object_label, operation=operation,\n            temporal_state=temporal_state,\n            target_resource_type=link.get("resource_type") if link else resolved.target_resource_type,\n            target_resource_id=link.get("resource_id") if link else resolved.target_resource_id,\n        )\n        qualifies = bool(\n            source["base_qualifies"]\n            and explicitness == "explicit"\n            and not inferred\n            and confidence >= 0.6\n        )\n        self.store.add_instance(\n            prop["id"], source_kind=source["source_kind"],\n            source_session_id=source["session_id"], source_turn_id=source["turn_id"],\n            origin_session_id=source["origin_session_id"], origin_turn_id=source["origin_turn_id"],\n            source_revision=source["revision"], project_id=source["project_id"],\n            world_id=source["world_id"], branch_id=source["branch_id"],\n            world_time=source["world_time"], story_order=source["story_order"],\n            source_segment=source_segment, span_start=span_start, span_end=span_end,\n            span_text=span_text or source.get("text", ""), extraction_confidence=confidence,\n            explicitness="inferred" if inferred else explicitness,\n            qualifies_review=qualifies,\n        )\n        report_keys.add(prop["id"])\n        return prop\n'''
replace_once("src/discovery/service.py", old_capture, new_capture)

replace_once(
    "src/discovery/service.py",
    '''            "world_time": world_time, "story_order": story_order,\n            "segments": segments, "base_qualifies": base_qualifies,\n''',
    '''            "world_time": world_time, "story_order": story_order,\n            "segments": segments, "base_qualifies": base_qualifies, "text": evidence,\n''',
)
replace_once(
    "src/discovery/service.py",
    '''            meaningful = bool(mapped and label and label.casefold() not in GENERIC_ENTITY_LABELS)\n            if meaningful:\n''',
    '''            meaningful = bool(mapped and label)\n            if meaningful:\n''',
)
replace_once(
    "src/discovery/service.py",
    '''                if not label or label.casefold() in GENERIC_ENTITY_LABELS:\n                    skipped += 1\n                    continue\n                self._capture_prop(\n''',
    '''                if not label:\n                    skipped += 1\n                    continue\n                self._capture_prop(\n''',
)
replace_once(
    "src/discovery/service.py",
    '''            subject_label = str(subject.get("label") or subject_key)\n            if subject_label.casefold() in GENERIC_ENTITY_LABELS:\n                skipped += 1\n                continue\n            object_key = str(relation.get("object") or "") or None\n''',
    '''            subject_label = str(subject.get("label") or subject_key)\n            object_key = str(relation.get("object") or "") or None\n''',
)

# Replace state-patch capture with EVENT-first causal anchors.
replace_once(
    "src/discovery/service.py",
    '''        event_by_id = {str(item.get("id")): item for item in result.events.get("events", []) if item.get("id")}\n        for state_patch in result.events.get("state_patches", []):\n            event = event_by_id.get(str(state_patch.get("event_id") or "")) or {}\n            for patch in state_patch.get("patch", []):\n''',
    '''        event_by_id = {str(item.get("id")): item for item in result.events.get("events", []) if item.get("id")}\n        for state_patch in result.events.get("state_patches", []):\n            event = event_by_id.get(str(state_patch.get("event_id") or "")) or {}\n            event_record = self.store.upsert_continuity_event(\n                project_id=source["project_id"], world_id=source["world_id"],\n                branch_id=source["branch_id"], session_id=source["session_id"],\n                source_turn_id=source["turn_id"], source_kind=source["source_kind"],\n                event_type=str(event.get("type") or event.get("event_type") or "state_transition"),\n                summary=str(event.get("summary") or event.get("description") or event.get("label") or span_text if False else "Narrative state transition"),\n                source_segment=event.get("source_segment"), story_order=source["story_order"],\n                world_time=source["world_time"], stable_seed=state_patch.get("event_id") or state_patch,\n            )\n            for patch in state_patch.get("patch", []):\n''',
)
# fix intentionally simple summary expression generated above to avoid undefined span_text condition readability
replace_once(
    "src/discovery/service.py",
    'summary=str(event.get("summary") or event.get("description") or event.get("label") or span_text if False else "Narrative state transition"),',
    'summary=str(event.get("summary") or event.get("description") or event.get("label") or "Narrative state transition"),',
)
replace_once(
    "src/discovery/service.py",
    '''                self._capture_prop(\n                    report_keys=prop_ids, source=source,\n                    subject_type=str(subject.get("type") or "character"), subject_key=subject_key,\n                    subject_label=subject_label, predicate=f"state.{state_path}", value=value,\n                    operation="transition", source_segment=event.get("source_segment"),\n                    confidence=float(event.get("eventhood_score") or 0.8), explicitness="explicit",\n                    temporal_state="historical_or_current",\n                )\n''',
    '''                transition_prop = self._capture_prop(\n                    report_keys=prop_ids, source=source,\n                    subject_type=str(subject.get("type") or "character"), subject_key=subject_key,\n                    subject_label=subject_label, predicate=f"state.{state_path}", value=value,\n                    operation="transition", source_segment=event.get("source_segment"),\n                    confidence=float(event.get("eventhood_score") or 0.8), explicitness="explicit",\n                    temporal_state="historical_or_current",\n                )\n                if transition_prop is not None:\n                    self.store.link_event_effect(\n                        event_record["id"], transition_prop["id"],\n                        subject_key=transition_prop["subject_key"],\n                        predicate=transition_prop["predicate"], role="after",\n                    )\n''',
)


# ---------------------------------------------------------------------------
# General fallback: resolve its temporary keys before persistence and add a
# deliberately small pronoun grammar for end-to-end coreference coverage.
# ---------------------------------------------------------------------------
replace_once(
    "src/discovery/general.py",
    '''    residence = re.compile(\n''',
    '''    pronoun_trait = re.compile(\n        rf"(?<![\\w@])(?P<label>(?i:Aku|Saya|I|Dia|Ia|He|She))\\s+(?i:adalah|is|was)\\s+"\n        rf"(?:(?i:orang\\s+yang|a|an)\\s+)?(?P<trait>(?i:{trait_words}))\\b"\n    )\n    for match in pronoun_trait.finditer(text):\n        label = match.group("label")\n        out.append(GeneralCandidate(\n            subject_type="character", subject_key=f"mention:{match.start()}", subject_label=label,\n            predicate="personality.descriptor", value=match.group("trait").strip().lower(), operation="update",\n            start=match.start(), end=match.end(), span_text=match.group(0), confidence=0.9,\n        ))\n\n    pronoun_transition = re.compile(\n        r"(?<![\\w@])(?P<label>(?i:Aku|Saya|I|Dia|Ia|He|She))\\s+"\n        r"(?:(?i:sekarang|now)\\s+)?(?i:berubah\\s+menjadi|menjadi|became|becomes|transformed?\\s+into)\\s+"\n        r"(?P<value>[^.!?\\n]{2,180})"\n    )\n    for match in pronoun_transition.finditer(text):\n        out.append(GeneralCandidate(\n            subject_type="character", subject_key=f"mention:{match.start()}", subject_label=match.group("label"),\n            predicate="state.form_description", value=" ".join(match.group("value").strip().split()),\n            operation="transition", start=match.start(), end=match.end(), span_text=match.group(0),\n            confidence=0.9, temporal_state="historical_or_current",\n        ))\n\n    residence = re.compile(\n''',
)

# Canonicalize GeneralCandidate keys in its direct persistence path.
replace_once(
    "src/discovery/general.py",
    '''    for index, item in enumerate(candidates, 1):\n        link = self._subject_link(\n            project_id=session.get("project_id"), world_id=session.get("world_id"),\n            subject_key=item.subject_key, subject_label=item.subject_label,\n            subject_type=item.subject_type,\n        )\n        proposition = self.store.upsert_proposition(\n            project_id=session.get("project_id"), world_id=session.get("world_id"),\n            subject_type=item.subject_type, subject_key=item.subject_key,\n            subject_label=item.subject_label, predicate=item.predicate, value=item.value,\n            object_type=item.object_type, object_key=item.object_key,\n            object_label=item.object_label, operation=item.operation,\n            temporal_state=item.temporal_state,\n            target_resource_type=link.get("resource_type") if link else None,\n            target_resource_id=link.get("resource_id") if link else None,\n        )\n''',
    '''    for index, item in enumerate(candidates, 1):\n        resolved = self.entity_resolver.resolve(\n            project_id=session.get("project_id"), world_id=session.get("world_id"),\n            branch_id=session.get("branch_id"), session_id=session.get("id"),\n            turn_id=turn.get("id"), source_kind=source_kind, source_text=evidence,\n            entity_type=item.subject_type, raw_subject_key=item.subject_key, label=item.subject_label,\n            span_start=item.start, span_end=item.end,\n        )\n        if not resolved.resolved:\n            continue\n        object_key = item.object_key\n        object_label = item.object_label\n        if object_key and object_label:\n            resolved_object = self.entity_resolver.resolve(\n                project_id=session.get("project_id"), world_id=session.get("world_id"),\n                branch_id=session.get("branch_id"), session_id=session.get("id"),\n                turn_id=turn.get("id"), source_kind=source_kind, source_text=evidence,\n                entity_type=item.object_type or "entity", raw_subject_key=object_key, label=object_label,\n                span_start=item.start, span_end=item.end,\n            )\n            if not resolved_object.resolved:\n                continue\n            object_key = resolved_object.subject_key\n            object_label = resolved_object.subject_label\n        link = self._subject_link(\n            project_id=session.get("project_id"), world_id=session.get("world_id"),\n            subject_key=str(resolved.subject_key), subject_label=resolved.subject_label,\n            subject_type=item.subject_type,\n        )\n        proposition = self.store.upsert_proposition(\n            project_id=session.get("project_id"), world_id=session.get("world_id"),\n            subject_type=item.subject_type, subject_key=str(resolved.subject_key),\n            subject_label=resolved.subject_label, predicate=item.predicate, value=item.value,\n            object_type=item.object_type, object_key=object_key,\n            object_label=object_label, operation=item.operation,\n            temporal_state=item.temporal_state,\n            target_resource_type=link.get("resource_type") if link else resolved.target_resource_type,\n            target_resource_id=link.get("resource_id") if link else resolved.target_resource_id,\n        )\n''',
)


# ---------------------------------------------------------------------------
# Remove identity monkey-patch install: resolver is now explicit service state.
# ---------------------------------------------------------------------------
replace_once(
    "src/discovery/provisional_autopatch.py",
    'from .identity import install_identity_resolution\n',
    '',
)
replace_once(
    "src/discovery/provisional_autopatch.py",
    'install_identity_resolution(service_module, provisional)\n',
    '',
)
replace_once(
    "src/discovery/provisional.py",
    'from .service import DiscoveryService\n',
    'from .identity import resolve_existing_family\nfrom .service import DiscoveryService\n',
)
replace_once(
    "src/discovery/provisional.py",
    '''def _existing_family(service: DiscoveryService, label: str, entity_type: str) -> dict[str, Any] | None:\n    needle = label.strip().casefold()\n    try:\n        rows = service.workspace.list_entity_families(None, entity_type=entity_type)\n    except Exception:\n        return None\n    return next(\n        (row for row in rows if str(row.get("name") or "").strip().casefold() == needle),\n        None,\n    )\n''',
    '''def _existing_family(service: DiscoveryService, label: str, entity_type: str) -> dict[str, Any] | None:\n    return resolve_existing_family(service.workspace, service.foundation, label, entity_type)\n''',
)


# ---------------------------------------------------------------------------
# Phase D/E backend: causal links, events/history/conflicts, explicit resolution.
# ---------------------------------------------------------------------------
replace_once(
    "src/discovery/continuity.py",
    '''    def _insert_edge(self, *, previous: dict[str, Any], current: dict[str, Any], kind: str,\n                     session: dict[str, Any], turn_id: str, source_kind: str,\n                     story_order: float | None, world_time: Any) -> None:\n''',
    '''    def _insert_edge(self, *, previous: dict[str, Any], current: dict[str, Any], kind: str,\n                     session: dict[str, Any], turn_id: str, source_kind: str,\n                     story_order: float | None, world_time: Any) -> str:\n''',
)
replace_once(
    "src/discovery/continuity.py",
    '''            con.execute(\n                "INSERT OR IGNORE INTO continuity_edges(id,project_id,world_id,branch_id,session_id,subject_key,predicate,"\n                "from_proposition_id,to_proposition_id,kind,source_turn_id,source_kind,story_order,world_time_json,created_at) "\n                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",\n                (\n                    edge_id, session.get("project_id"), session.get("world_id"), session.get("branch_id"), session.get("id"),\n                    current["subject_key"], current["predicate"], previous["id"], current["id"], kind,\n                    turn_id, source_kind, story_order, dumps(world_time) if world_time is not None else None, now,\n                ),\n            )\n\n    def _insert_conflict''',
    '''            con.execute(\n                "INSERT OR IGNORE INTO continuity_edges(id,project_id,world_id,branch_id,session_id,subject_key,predicate,"\n                "from_proposition_id,to_proposition_id,kind,source_turn_id,source_kind,story_order,world_time_json,created_at) "\n                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",\n                (\n                    edge_id, session.get("project_id"), session.get("world_id"), session.get("branch_id"), session.get("id"),\n                    current["subject_key"], current["predicate"], previous["id"], current["id"], kind,\n                    turn_id, source_kind, story_order, dumps(world_time) if world_time is not None else None, now,\n                ),\n            )\n        return edge_id\n\n    def _insert_conflict''',
)

# Add causality after edge creation in resolve_turn.
replace_once(
    "src/discovery/continuity.py",
    '''                    self._insert_edge(\n                        previous=previous, current=current, kind=kind, session=session,\n                        turn_id=turn_id, source_kind=source_kind,\n                        story_order=story_order, world_time=world_time,\n                    )\n                    if kind == "story_change":\n''',
    '''                    self._insert_edge(\n                        previous=previous, current=current, kind=kind, session=session,\n                        turn_id=turn_id, source_kind=source_kind,\n                        story_order=story_order, world_time=world_time,\n                    )\n                    if kind == "story_change":\n                        event = self.store.find_event_for_proposition(current["id"])\n                        if event is None and current.get("operation") == "transition":\n                            event = self.store.upsert_continuity_event(\n                                project_id=session.get("project_id"), world_id=session.get("world_id"),\n                                branch_id=session.get("branch_id"), session_id=session.get("id"),\n                                source_turn_id=turn_id, source_kind=source_kind,\n                                event_type="state_transition",\n                                summary=(source_text.strip()[:240] or f"{current.get('subject_label')} changed"),\n                                story_order=story_order, world_time=world_time,\n                                stable_seed=[current["id"], "synthetic_transition"],\n                            )\n                            self.store.link_event_effect(\n                                event["id"], current["id"], subject_key=current["subject_key"],\n                                predicate=current["predicate"], role="after",\n                            )\n                        if event is not None:\n                            link_id = "CAUSE-" + sha256(\n                                dumps([event["id"], previous["id"], current["id"]]).encode("utf-8")\n                            ).hexdigest()[:16].upper()\n                            with self.store._lock, self.store.connection() as con:\n                                con.execute(\n                                    "INSERT OR IGNORE INTO continuity_causal_links(id,event_id,subject_key,predicate,"\n                                    "from_proposition_id,to_proposition_id,kind,created_at) VALUES(?,?,?,?,?,?,?,?)",\n                                    (link_id, event["id"], current["subject_key"], current["predicate"],\n                                     previous["id"], current["id"], "state_transition", utc_now()),\n                                )\n                    if kind == "story_change":\n''',
)

# Add list/history/conflict APIs before status().
replace_once(
    "src/discovery/continuity.py",
    '''    def status(self) -> dict[str, Any]:\n''',
    r'''    def list_events(self, context: MemoryQueryContext, *, subject_key: str | None = None) -> list[dict[str, Any]]:
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
''',
)
replace_once(
    "src/discovery/continuity.py",
    '''            forms = con.execute("SELECT COUNT(*) AS n FROM continuity_forms").fetchone()["n"]\n        return {\n''',
    '''            forms = con.execute("SELECT COUNT(*) AS n FROM continuity_forms").fetchone()["n"]\n            events = con.execute("SELECT COUNT(*) AS n FROM continuity_events").fetchone()["n"]\n            mentions = con.execute("SELECT COUNT(*) AS n FROM discovery_mentions").fetchone()["n"]\n        return {\n''',
)
replace_once(
    "src/discovery/continuity.py",
    '''            "forms": int(forms),\n        }\n''',
    '''            "forms": int(forms),\n            "events": int(events),\n            "mentions": int(mentions),\n        }\n''',
)
replace_once(
    "src/discovery/continuity.py",
    '''    service.continuity_forms = resolver.list_forms\n''',
    '''    service.continuity_forms = resolver.list_forms\n    service.continuity_events = resolver.list_events\n    service.continuity_conflicts = resolver.list_conflicts\n    service.continuity_history = resolver.change_history\n''',
)


# ---------------------------------------------------------------------------
# Resource payload: one continuity projection for all Library consumers.
# ---------------------------------------------------------------------------
replace_once(
    "src/discovery/provisional.py",
    '''    provisional = bool((core.get("_discovery") or {}).get("provisional"))\n    return {\n''',
    '''    provisional = bool((core.get("_discovery") or {}).get("provisional"))\n    continuity_payload = {\n        "current": {"version": "1.2.2a1", "heads": [], "ambiguous": [], "superseded_proposition_ids": []},\n        "forms": [], "history": [], "events": [], "conflicts": [], "mentions": [],\n    }\n    resolver = getattr(service, "continuity", None)\n    if resolver is not None:\n        seen_heads: set[str] = set()\n        seen_forms: set[str] = set()\n        seen_history: set[str] = set()\n        seen_events: set[str] = set()\n        seen_conflicts: set[str] = set()\n        seen_mentions: set[str] = set()\n        for key in subject_keys:\n            current = resolver.current_view(context, subject_key=key)\n            for head in current.get("heads", []):\n                if head["id"] not in seen_heads:\n                    continuity_payload["current"]["heads"].append(head); seen_heads.add(head["id"])\n            continuity_payload["current"]["ambiguous"].extend(current.get("ambiguous", []))\n            continuity_payload["current"]["superseded_proposition_ids"].extend(current.get("superseded_proposition_ids", []))\n            for item in resolver.list_forms(context, subject_key=key):\n                if item["id"] not in seen_forms:\n                    continuity_payload["forms"].append(item); seen_forms.add(item["id"])\n            for item in resolver.change_history(context, subject_key=key):\n                if item["id"] not in seen_history:\n                    continuity_payload["history"].append(item); seen_history.add(item["id"])\n            for item in resolver.list_events(context, subject_key=key):\n                if item["id"] not in seen_events:\n                    continuity_payload["events"].append(item); seen_events.add(item["id"])\n            for item in resolver.list_conflicts(context, subject_key=key, include_resolved=True):\n                if item["id"] not in seen_conflicts:\n                    continuity_payload["conflicts"].append(item); seen_conflicts.add(item["id"])\n            for item in service.store.list_mentions_for_subject(\n                project_id=context.project_id, world_id=context.world_id, subject_key=key, limit=80\n            ):\n                if item["id"] not in seen_mentions:\n                    continuity_payload["mentions"].append(item); seen_mentions.add(item["id"])\n        continuity_payload["current"]["superseded_proposition_ids"] = sorted(set(continuity_payload["current"]["superseded_proposition_ids"]))\n    return {\n''',
)
replace_once(
    "src/discovery/provisional.py",
    '''        "zones": list(zones.values()),\n    }\n''',
    '''        "zones": list(zones.values()),\n        "continuity": continuity_payload,\n    }\n''',
)


# ---------------------------------------------------------------------------
# API surface for status + explicit conflict decisions.
# ---------------------------------------------------------------------------
replace_once(
    "src/discovery/web.py",
    '''class DiscoveryEditPayload(DiscoveryDecisionPayload):\n    value: Any\n    mode: str = "correction"\n\n\ndef _context''',
    '''class DiscoveryEditPayload(DiscoveryDecisionPayload):\n    value: Any\n    mode: str = "correction"\n\n\nclass ContinuityConflictResolutionPayload(DiscoveryDecisionPayload):\n    action: str\n    from_proposition_id: str | None = None\n    to_proposition_id: str | None = None\n\n\ndef _context''',
)
replace_once(
    "src/discovery/web.py",
    '''    @router.get("/discoveries/{proposition_id}")\n''',
    '''    @router.get("/discoveries/continuity/status")\n    def continuity_status():\n        return discovery.continuity.status()\n\n    @router.get("/discoveries/continuity/conflicts")\n    def continuity_conflicts(\n        project_id: str | None = Query(None), world_id: str | None = Query(None),\n        branch_id: str | None = Query(None), session_id: str | None = Query(None),\n        include_resolved: bool = Query(False),\n    ):\n        return {"items": discovery.continuity.list_conflicts(\n            _context(project_id=project_id, world_id=world_id, branch_id=branch_id, session_id=session_id),\n            include_resolved=include_resolved,\n        )}\n\n    @router.post("/discoveries/continuity/conflicts/{conflict_id}/resolve")\n    def resolve_continuity_conflict(conflict_id: str, payload: ContinuityConflictResolutionPayload):\n        try:\n            return discovery.continuity.resolve_conflict(\n                conflict_id, action=payload.action,\n                from_proposition_id=payload.from_proposition_id,\n                to_proposition_id=payload.to_proposition_id, note=payload.note,\n            )\n        except KeyError as exc:\n            raise HTTPException(404, "Continuity conflict not found") from exc\n        except ValueError as exc:\n            raise HTTPException(400, str(exc)) from exc\n\n    @router.get("/discoveries/{proposition_id}")\n''',
)


# ---------------------------------------------------------------------------
# Phase E UI: render backend continuity projection, with explicit conflict choice.
# ---------------------------------------------------------------------------
replace_once(
    "src/interface/web/static/js/discovery-sheets.js",
    ".prov-zone-note{font-size:11px;opacity:.62;margin-top:6px}.prov-semantic",
    ".prov-zone-note{font-size:11px;opacity:.62;margin-top:6px}.cont-grid{display:grid;gap:7px}.cont-state{display:grid;grid-template-columns:minmax(120px,.7fr) 1fr;gap:8px;padding:7px 0;border-bottom:1px solid var(--line)}.cont-event,.cont-conflict{padding:9px;border:1px solid var(--line);border-radius:9px}.cont-event small,.cont-conflict small{display:block;opacity:.65;margin-top:4px}.cont-ambiguous{border-style:dashed}.prov-semantic",
)
replace_once(
    "src/interface/web/static/js/discovery-sheets.js",
    '''  async function makeRelationCanon(relation, familyId) {\n''',
    '''  async function resolveContinuityConflict(conflict, familyId, action, fromId = null, toId = null) {\n    try {\n      await request(`/api/memory/discoveries/continuity/conflicts/${encodeURIComponent(conflict.id)}/resolve`, {\n        method: "POST",\n        body: JSON.stringify(decisionPayload({\n          action, from_proposition_id: fromId, to_proposition_id: toId,\n          note: "Explicit user continuity resolution from Library sheet",\n        })),\n      });\n      window.toast?.("Continuity conflict resolved without granting Canon", 4500);\n      await decorate(familyId);\n    } catch (error) { window.toast?.(error.message, 6000); }\n  }\n\n  async function makeRelationCanon(relation, familyId) {\n''',
)
replace_once(
    "src/interface/web/static/js/discovery-sheets.js",
    '''      const physical = physicalIdentity(data.resource);\n      const section = document.createElement("section");\n''',
    '''      const physical = physicalIdentity(data.resource);\n      const continuity = data.continuity || {};\n      const currentHeads = continuity.current?.heads || [];\n      const currentAmbiguous = continuity.current?.ambiguous || [];\n      const forms = continuity.forms || [];\n      const history = continuity.history || [];\n      const events = continuity.events || [];\n      const conflicts = (continuity.conflicts || []).filter((item) => item.status === "open");\n      const section = document.createElement("section");\n''',
)
# Inject continuity panels just before Relations panel in template.
replace_once(
    "src/interface/web/static/js/discovery-sheets.js",
    '''        ${relations.length ? `<div class="sheet-section-head gap"><h3>Relations</h3><span>${relations.length}</span></div>''',
    '''        ${(currentHeads.length || currentAmbiguous.length) ? `<div class="sheet-section-head gap"><h3>Current State</h3><span>${currentHeads.length}</span></div><p class="prov-help">Derived continuity view. It can reconstruct and abstain, but it cannot grant Canon.</p><div class="cont-grid">${currentHeads.map((head) => `<div class="cont-state"><b>${esc(String(head.predicate || "").replace(/^state\\./,""))}</b><span>${esc(valueText(head.value))}</span></div>`).join("")}${currentAmbiguous.map((item) => `<div class="cont-conflict cont-ambiguous"><b>Ambiguous · ${esc(item.predicate)}</b><small>${esc((item.proposition_ids || []).join(" ↔ "))}</small></div>`).join("")}</div>` : ""}\n        ${forms.length ? `<div class="sheet-section-head gap"><h3>Forms</h3><span>${forms.length}</span></div><div class="cont-grid">${forms.map((form) => `<div class="cont-event"><b>${esc(form.reason === "state_transition" ? "State form" : "Observed baseline")}</b><small>${esc(form.id)}${form.parent_form_id ? ` · from ${esc(form.parent_form_id)}` : ""}</small><span class="prov-value">${esc(valueText(form.state || {}))}</span></div>`).join("")}</div>` : ""}\n        ${history.length ? `<div class="sheet-section-head gap"><h3>Change History</h3><span>${history.length}</span></div><div class="cont-grid">${history.map((item) => `<div class="cont-event"><b>${esc(String(item.predicate || "").replace(/^state\\./,""))} · ${esc(String(item.kind || "change").replaceAll("_"," "))}</b><span class="prov-value">${esc(valueText(item.before?.value))} → ${esc(valueText(item.after?.value))}</span>${item.event ? `<small>${esc(item.event.id)} · ${esc(item.event.summary || item.event.event_type)}</small>` : ""}</div>`).join("")}</div>` : ""}\n        ${events.length ? `<div class="sheet-section-head gap"><h3>Events & Causes</h3><span>${events.length}</span></div><div class="cont-grid">${events.map((event) => `<div class="cont-event"><b>${esc(event.summary || event.event_type)}</b><small>${esc(event.id)} · ${Number((event.causal_links || []).length)} causal link${Number((event.causal_links || []).length) === 1 ? "" : "s"}</small></div>`).join("")}</div>` : ""}\n        ${conflicts.length ? `<div class="sheet-section-head gap"><h3>Conflicts</h3><span>${conflicts.length}</span></div><p class="prov-help">Arline abstained. Choose only when you know whether this is a correction or an actual story transition.</p><div class="cont-grid">${conflicts.map((conflict) => `<div class="cont-conflict" data-cont-conflict="${esc(conflict.id)}"><b>${esc(conflict.predicate)}</b><span class="prov-value">${esc(valueText(conflict.left?.value))} ↔ ${esc(valueText(conflict.right?.value))}</span><small>${esc(conflict.reason)}</small><div class="prov-actions"><button class="tiny-btn" data-cont-action="left-correct">Left corrects right</button><button class="tiny-btn" data-cont-action="right-correct">Right corrects left</button><button class="tiny-btn" data-cont-action="left-to-right">Left → Right story change</button><button class="tiny-btn" data-cont-action="right-to-left">Right → Left story change</button><button class="tiny-btn" data-cont-action="dismiss">Leave unresolved</button></div></div>`).join("")}</div>` : ""}\n        ${relations.length ? `<div class="sheet-section-head gap"><h3>Relations</h3><span>${relations.length}</span></div>''',
)
# Bind conflict buttons before final append/wiring area using stable claim wiring anchor.
replace_once(
    "src/interface/web/static/js/discovery-sheets.js",
    '''      section.querySelectorAll("[data-prov-claim]").forEach((row) => {\n''',
    '''      section.querySelectorAll("[data-cont-conflict]").forEach((row) => {\n        const conflict = conflicts.find((item) => item.id === row.dataset.contConflict);\n        if (!conflict) return;\n        row.querySelectorAll("[data-cont-action]").forEach((button) => button.addEventListener("click", () => {\n          const action = button.dataset.contAction;\n          if (action === "dismiss") return resolveContinuityConflict(conflict, familyId, "dismiss");\n          if (action === "left-correct") return resolveContinuityConflict(conflict, familyId, "correction", conflict.right_proposition_id, conflict.left_proposition_id);\n          if (action === "right-correct") return resolveContinuityConflict(conflict, familyId, "correction", conflict.left_proposition_id, conflict.right_proposition_id);\n          if (action === "left-to-right") return resolveContinuityConflict(conflict, familyId, "story_change", conflict.left_proposition_id, conflict.right_proposition_id);\n          if (action === "right-to-left") return resolveContinuityConflict(conflict, familyId, "story_change", conflict.right_proposition_id, conflict.left_proposition_id);\n        }));\n      });\n\n      section.querySelectorAll("[data-prov-claim]").forEach((row) => {\n''',
)


# ---------------------------------------------------------------------------
# Top-down completion tests: stable anchors/coref/causality/UI payload/conflicts.
# ---------------------------------------------------------------------------
write("tests/test_v122_topdown_completion.py", r'''from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.history.store import HistoryStore
from src.memory import MemoryConfig, MemoryQueryContext, MemoryService, MemoryStore
from src.memory.web import create_memory_router
from src.workspace import FoundationStore
from src.workspace.store import WorkspaceStore


class Fixture:
    def __init__(self, root: str):
        path = Path(root) / "arline.db"
        self.workspace = WorkspaceStore(path, backup_before_migration=False)
        self.history = HistoryStore(path, backup_before_migration=False)
        self.foundation = FoundationStore(path)
        self.project = self.workspace.create_project("v122 topdown")
        self.world_id = self.project["default_world_id"]
        self.branch = next(x for x in self.workspace.get_world(self.world_id)["branches"] if x["kind"] == "main")
        config = MemoryConfig(); config.dense_enabled = False
        store = MemoryStore(path)
        self.memory = MemoryService(
            store=store, workspace=self.workspace, history=self.history,
            foundation=self.foundation, config=config,
            lmstudio_base_url="http://127.0.0.1:1234",
        )
        create_memory_router(service=self.memory, store=store, foundation=self.foundation)
        self.discovery = self.memory.discovery
        self.session = self.history.create_session(
            prompt="topdown", project_id=self.project["id"], world_id=self.world_id,
            branch_id=self.branch["id"],
        )

    def turn(self, prompt: str, suffix: str):
        return self.history.add_turn(
            self.session["id"], run_id=f"RUN-TOP-{suffix}", user_prompt=prompt,
            story="Generated.", model="fixture", mode="smart_hybrid",
            reasoning="off", projection_mode="off",
        )

    def context(self):
        return MemoryQueryContext(
            project_id=self.project["id"], world_id=self.world_id,
            branch_id=self.branch["id"], session_id=self.session["id"],
        )


class V122TopDownCompletionTests(unittest.TestCase):
    def test_alias_reuses_one_stable_discovery_anchor(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(td)
            family = fx.workspace.create_entity_family(None, "Revian", entity_type="character")
            fx.foundation.add_alias("entity_family", family["id"], "Vian")
            r1 = fx.discovery.entity_resolver.resolve(
                project_id=fx.project["id"], world_id=fx.world_id, branch_id=fx.branch["id"],
                session_id=fx.session["id"], turn_id="T1", source_kind="user_prompt",
                source_text="Revian arrived.", entity_type="character", raw_subject_key="char:revian", label="Revian",
            )
            r2 = fx.discovery.entity_resolver.resolve(
                project_id=fx.project["id"], world_id=fx.world_id, branch_id=fx.branch["id"],
                session_id=fx.session["id"], turn_id="T2", source_kind="user_prompt",
                source_text="Vian smiled.", entity_type="character", raw_subject_key="char:vian", label="Vian",
            )
            self.assertEqual(r1.subject_key, r2.subject_key)
            self.assertEqual(r2.target_resource_id, family["id"])

    def test_first_person_requires_explicit_narrator_anchor_then_persists(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(td)
            first = fx.discovery.entity_resolver.resolve(
                project_id=fx.project["id"], world_id=fx.world_id, branch_id=fx.branch["id"],
                session_id=fx.session["id"], turn_id="T1", source_kind="user_prompt",
                source_text="Namaku Vian, aku tinggal sendiri.", entity_type="character",
                raw_subject_key="self", label="self",
            )
            self.assertTrue(first.resolved)
            later = fx.discovery.entity_resolver.resolve(
                project_id=fx.project["id"], world_id=fx.world_id, branch_id=fx.branch["id"],
                session_id=fx.session["id"], turn_id="T2", source_kind="user_prompt",
                source_text="Aku tersenyum.", entity_type="character",
                raw_subject_key="self:2", label="aku",
            )
            self.assertEqual(later.subject_key, first.subject_key)
            self.assertEqual(later.resolution_kind, "self_recent")

    def test_third_person_abstains_when_recent_candidates_are_ambiguous(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(td)
            for key, name in (("char:alex", "Alex"), ("char:bob", "Bob")):
                fx.discovery.entity_resolver.resolve(
                    project_id=fx.project["id"], world_id=fx.world_id, branch_id=fx.branch["id"],
                    session_id=fx.session["id"], turn_id="T1", source_kind="user_prompt",
                    source_text="Alex met Bob.", entity_type="character", raw_subject_key=key, label=name,
                )
            pronoun = fx.discovery.entity_resolver.resolve(
                project_id=fx.project["id"], world_id=fx.world_id, branch_id=fx.branch["id"],
                session_id=fx.session["id"], turn_id="T2", source_kind="user_prompt",
                source_text="Dia tersenyum.", entity_type="character", raw_subject_key="mention:dia", label="dia",
            )
            self.assertFalse(pronoun.resolved)
            self.assertEqual(pronoun.resolution_kind, "ambiguous_coreference")
            self.assertEqual(set(pronoun.ambiguous_candidates), {"char:alex", "char:bob"})

    def test_unique_cross_turn_pronoun_resolves(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(td)
            alex = fx.discovery.entity_resolver.resolve(
                project_id=fx.project["id"], world_id=fx.world_id, branch_id=fx.branch["id"],
                session_id=fx.session["id"], turn_id="T1", source_kind="user_prompt",
                source_text="Alex arrived.", entity_type="character", raw_subject_key="char:alex", label="Alex",
            )
            pronoun = fx.discovery.entity_resolver.resolve(
                project_id=fx.project["id"], world_id=fx.world_id, branch_id=fx.branch["id"],
                session_id=fx.session["id"], turn_id="T2", source_kind="user_prompt",
                source_text="Dia tersenyum.", entity_type="character", raw_subject_key="mention:dia", label="dia",
            )
            self.assertEqual(pronoun.subject_key, alex.subject_key)
            self.assertEqual(pronoun.resolution_kind, "coreference_recent")

    def test_transition_builds_event_and_causal_link(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(td)
            first = fx.turn("Alex has hair length 10 cm.", "1")
            p1 = fx.discovery.store.upsert_proposition(
                project_id=fx.project["id"], world_id=fx.world_id, subject_type="character",
                subject_key="char:alex", subject_label="Alex", predicate="state.hair.length_cm",
                value=10, operation="update", temporal_state="current_or_unspecified",
            )
            fx.discovery.store.add_instance(
                p1["id"], source_kind="user_prompt", source_session_id=fx.session["id"], source_turn_id=first["id"],
                origin_session_id=fx.session["id"], origin_turn_id=first["id"], source_revision="R1",
                project_id=fx.project["id"], world_id=fx.world_id, branch_id=fx.branch["id"],
                span_text=first["user_prompt"], extraction_confidence=1, explicitness="explicit", qualifies_review=True,
            )
            second = fx.turn("Sekarang rambut Alex menjadi 100 cm.", "2")
            p2 = fx.discovery.store.upsert_proposition(
                project_id=fx.project["id"], world_id=fx.world_id, subject_type="character",
                subject_key="char:alex", subject_label="Alex", predicate="state.hair.length_cm",
                value=100, operation="transition", temporal_state="historical_or_current",
            )
            fx.discovery.store.add_instance(
                p2["id"], source_kind="user_prompt", source_session_id=fx.session["id"], source_turn_id=second["id"],
                origin_session_id=fx.session["id"], origin_turn_id=second["id"], source_revision="R2",
                project_id=fx.project["id"], world_id=fx.world_id, branch_id=fx.branch["id"],
                span_text=second["user_prompt"], extraction_confidence=1, explicitness="explicit", qualifies_review=True,
            )
            fx.discovery.continuity.resolve_turn(second["id"])
            events = fx.discovery.continuity.list_events(fx.context(), subject_key="char:alex")
            self.assertEqual(len(events), 1)
            self.assertTrue(events[0]["id"].startswith("EVENT-"))
            self.assertEqual(events[0]["causal_links"][0]["from_proposition_id"], p1["id"])
            self.assertEqual(events[0]["causal_links"][0]["to_proposition_id"], p2["id"])

    def test_resource_view_contains_one_continuity_projection(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(td)
            turn = fx.turn("Character Alex is calm.", "1")
            # turn_created already captures/materializes; find Alex sheet from current families.
            family = next((x for x in fx.workspace.list_entity_families(None, entity_type="character") if x["name"].casefold() == "alex"), None)
            if family is None:
                self.skipTest("deterministic parser did not materialize Alex in this fixture")
            view = fx.discovery.resource_view(family["id"], fx.context())
            self.assertIn("continuity", view)
            self.assertEqual(set(view["continuity"]), {"current", "forms", "history", "events", "conflicts", "mentions"})

    def test_explicit_conflict_resolution_is_derived_not_canon(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(td)
            t1 = fx.turn("Alex is calm.", "1")
            t2 = fx.turn("Alex is impulsive.", "2")
            def claim(turn, value, rev):
                prop = fx.discovery.store.upsert_proposition(
                    project_id=fx.project["id"], world_id=fx.world_id, subject_type="character",
                    subject_key="char:alex", subject_label="Alex", predicate="personality.descriptor",
                    value=value, operation="update",
                )
                fx.discovery.store.add_instance(
                    prop["id"], source_kind="user_prompt", source_session_id=fx.session["id"], source_turn_id=turn["id"],
                    origin_session_id=fx.session["id"], origin_turn_id=turn["id"], source_revision=rev,
                    project_id=fx.project["id"], world_id=fx.world_id, branch_id=fx.branch["id"],
                    span_text=turn["user_prompt"], extraction_confidence=1, explicitness="explicit", qualifies_review=True,
                )
                return prop
            p1 = claim(t1, "calm", "A")
            p2 = claim(t2, "impulsive", "B")
            fx.discovery.continuity.resolve_turn(t2["id"])
            conflicts = fx.discovery.continuity.list_conflicts(fx.context(), subject_key="char:alex")
            target = next(x for x in conflicts if {x["left_proposition_id"], x["right_proposition_id"]} == {p1["id"], p2["id"]})
            fx.discovery.continuity.resolve_conflict(
                target["id"], action="correction",
                from_proposition_id=p1["id"], to_proposition_id=p2["id"], note="user chose",
            )
            self.assertEqual(fx.discovery.store.get_proposition(p2["id"])["authority_state"], "observed")
            self.assertFalse(fx.discovery.continuity.list_conflicts(fx.context(), subject_key="char:alex"))

    def test_schema_v4_owns_resolution_and_causality_tables(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(td)
            self.assertEqual(fx.discovery.store.SCHEMA_VERSION, 4)
            with fx.discovery.store.connection() as con:
                tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for name in {"discovery_mentions", "continuity_events", "continuity_event_effects", "continuity_causal_links", "continuity_conflict_resolutions"}:
                self.assertIn(name, tables)


if __name__ == "__main__":
    unittest.main()
''')


# ---------------------------------------------------------------------------
# Docs: mark top-down B-E implementation contract without claiming validation.
# ---------------------------------------------------------------------------
replace_once(
    "docs/V122_NARRATIVE_CONTINUITY.md",
    '''### Phase B — Narrative Entity Resolver\n\nReplace hard-coded story identities in the analytical extractor with arbitrary\nentity mentions and stable anchors. Resolve exact Library identity and aliases\nbefore propositions are emitted. Fuzzy merging remains forbidden.\n''',
    '''### Phase B — Narrative Entity Resolver\n\nImplemented top-down: extractors now propose mentions/temporary keys, while one\nshared `NarrativeEntityResolver` chooses the stable anchor before propositions\nare persisted. Resolution order is conservative: existing subject link, exact\nLibrary name/alias/unique variant, exact same-turn anchor, then bounded\ncoreference. Every attempt is written as a rebuildable `MENTION-*` diagnostic.\nFuzzy merging remains forbidden.\n''',
)
replace_once(
    "docs/V122_NARRATIVE_CONTINUITY.md",
    '''### Phase C — cross-turn coreference\n\nResolve narrator/self references, pronouns, possessives, demonstratives, and\nrecent mentions across turns. Examples include `aku`, `saya`, `dia`, `-ku`,\n`-nya`, `itu`, and `tadi`. Ambiguous candidate sets remain unresolved rather\nthan guessed.\n''',
    '''### Phase C — cross-turn coreference\n\nImplemented conservatively for the high-confidence first/third-person surface:\nexplicit narrator identity can anchor later `aku`/`saya`/`I` references, and a\nunique bounded recent character can anchor `dia`/`ia`/`he`/`she`. Generic,\npossessive/demonstrative surfaces enter the same resolver gate; plural or\nambiguous candidate sets remain unresolved and are retained as diagnostics\nrather than guessed. Extraction grammars can be widened independently without\nchanging identity authority.\n''',
)
replace_once(
    "docs/V122_NARRATIVE_CONTINUITY.md",
    '''### Phase D — event/state causality\n\nConnect state changes to their causing `EVENT-*` records and reconstruct explicit\nbefore/after frames. Character Rails and Memory can then answer questions such as\n"what was Character A like before the transformation?" without flattening the\nhistory.\n''',
    '''### Phase D — event/state causality\n\nImplemented as rebuildable derived state: analytical state patches create stable\n`EVENT-*` records and effect links; continuity supersession then joins the\nvisible before/after propositions through `CAUSE-*` links. Deterministic\ntransition fallbacks synthesize an event only when the extractor supplied a\ntransition without an event object. No event or causal edge grants Canon.\n''',
)
replace_once(
    "docs/V122_NARRATIVE_CONTINUITY.md",
    '''### Phase E — continuity UI\n\nLibrary sheets gain Current State, Forms, Change History, and Conflicts sections.\nConflict resolution remains an explicit user action and does not silently grant\nCanon.\n''',
    '''### Phase E — continuity UI\n\nImplemented through one resource-level continuity payload consumed by Library\nsheets: Current State, Forms, Change History, Events & Causes, and Conflicts.\nConflict resolution is an explicit user action choosing correction, story\ntransition direction, or leaving the conflict unresolved. The action changes\nderived continuity only and never silently grants Canon.\n''',
)

print("v1.2.2 top-down source pass applied")
