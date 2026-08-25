from __future__ import annotations

from collections import OrderedDict, defaultdict
from hashlib import sha256
from threading import RLock, local
from time import monotonic
from types import SimpleNamespace
from typing import Any, Iterable

from src.memory.models import MemoryQueryContext
from src.narrative.rails import CharacterRailParser

from .semantics import describe_claim
from .service import CaptureReport
from .store import checksum, dumps, loads, utc_now


PERFORMANCE_SCHEMA_VERSION = "1"
CAPTURE_PIPELINE_REVISION = "v121-discovery-light-2"
MATERIALIZATION_REVISION = "v121-provisional-physical-items-2"
STARTUP_BUDGET_SECONDS = 0.18
STARTUP_BATCH_SIZE = 48


class DiscoveryExtractionPipeline:
    """Run only the deterministic extraction half of Arline's full pipeline.

    Narrative Discovery needs entities, relations, claims, events, transitions,
    and source segments. It does not need the expensive analytical reasoner,
    surface planner, semantic-core builder, or writer runtime that the generation
    path already runs independently.
    """

    VERSION = CAPTURE_PIPELINE_REVISION

    def __init__(self, base_pipeline):
        self.base = base_pipeline

    def run(self, text: str):
        base = self.base
        structure = base.structural_parser.parse(text)
        semantic = base.semantic_segmenter.segment(structure)
        normalized = base.normalizer.normalize(semantic)
        annotations = base.annotation_resolver.resolve(normalized)
        entity_resolution = base.reference_resolver.resolve(normalized, annotations)
        scoped = base.scope_resolver.resolve(normalized)
        aspect = base.aspect_resolver.resolve(scoped)
        discourse = base.discourse_resolver.resolve(aspect)
        claims = base.claim_extractor.extract(discourse, entity_resolution, annotations, discourse)
        state = base.state_extractor.extract(discourse, entity_resolution, claims)
        scenario = base.scenario_builder.build(claims, state)
        event_data = base.event_builder.build(discourse, state, scenario)
        transitions = base.transition_resolver.resolve(state, event_data)

        extracted_state = {
            "system_version": getattr(base, "VERSION", "unknown"),
            "component_version": state.get("version"),
            "entities": state.get("entities", []),
            "relations": state.get("relations", []),
            "experience": state.get("experience", []),
            "norms": state.get("norms", []),
            "knowledge": state.get("knowledge", []),
            "beliefs": state.get("beliefs", []),
            "relationship_timeline": state.get("relationship_timeline", []),
            "claim_conflicts": state.get("claim_conflicts", []),
            "claims": state.get("claims", []),
            "scenario": scenario,
            "directives": state.get("directives", []),
            "requests": state.get("requests", []),
            "unknowns": state.get("unknowns", []),
            "reference_resolutions": entity_resolution.get("resolutions", []),
            "entity_aliases": entity_resolution.get("aliases", []),
            "entity_lifecycle": entity_resolution.get("lifecycle", []),
            "discourse_relations": discourse.get("relations", []),
            "diagnostics": (
                structure.get("diagnostics", [])
                + semantic.get("diagnostics", [])
                + normalized.get("diagnostics", [])
                + annotations.get("diagnostics", [])
                + entity_resolution.get("diagnostics", [])
                + scoped.get("diagnostics", [])
                + aspect.get("diagnostics", [])
                + discourse.get("diagnostics", [])
                + claims.get("diagnostics", [])
                + state.get("diagnostics", [])
                + scenario.get("diagnostics", [])
            ),
        }
        events = {
            "system_version": getattr(base, "VERSION", "unknown"),
            "event_builder_version": event_data.get("version"),
            "transition_resolver_version": transitions.get("version"),
            "events": event_data.get("events", []),
            "scenario_events": event_data.get("scenario_events", []),
            "event_candidates": event_data.get("event_candidates", []),
            "state_patches": transitions.get("patches", []),
            "state_snapshots": transitions.get("snapshots", []),
            "conflicts": transitions.get("conflicts", []),
            "diagnostics": event_data.get("diagnostics", []) + transitions.get("diagnostics", []),
        }
        debug = {
            "structure": structure,
            "semantic_segments": semantic,
            "normalized_segments": normalized,
            "annotations": annotations,
            "entity_resolution": entity_resolution,
            "scoped_segments": scoped,
            "aspect_segments": aspect,
            "discourse": discourse,
            "claims": claims,
            "scenario": scenario,
        }
        return SimpleNamespace(extracted_state=extracted_state, events=events, debug=debug)


def _metrics(service) -> dict[str, int]:
    metrics = getattr(service, "_discovery_performance_metrics", None)
    if metrics is None:
        metrics = {
            "capture_hits": 0,
            "capture_misses": 0,
            "materialization_hits": 0,
            "materialization_misses": 0,
            "list_hits": 0,
            "list_misses": 0,
            "physical_index_hits": 0,
            "physical_index_misses": 0,
            "startup_materialized": 0,
            "branch_repairs": 0,
        }
        service._discovery_performance_metrics = metrics
    return metrics


def _increment(service, key: str, amount: int = 1) -> None:
    metrics = _metrics(service)
    metrics[key] = int(metrics.get(key, 0)) + int(amount)


def _ensure_performance_schema(service) -> None:
    if getattr(service, "_discovery_performance_schema_ready", False):
        return
    with service.store._lock, service.store.connection() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS discovery_capture_cache(
                source_turn_id TEXT NOT NULL,
                source_kind TEXT NOT NULL,
                source_revision TEXT NOT NULL,
                pipeline_revision TEXT NOT NULL,
                propositions INTEGER NOT NULL,
                instances INTEGER NOT NULL,
                skipped INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(source_turn_id,source_kind)
            );

            CREATE TABLE IF NOT EXISTS discovery_materialization_cache(
                source_turn_id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                report_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS discovery_branch_projection_cache(
                proposition_id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_discovery_instance_scope_fast
                ON discovery_instances(project_id,world_id,branch_id,source_session_id,active,proposition_id);
            CREATE INDEX IF NOT EXISTS idx_discovery_instance_revision_fast
                ON discovery_instances(source_turn_id,source_kind,source_revision,active,proposition_id);
            CREATE INDEX IF NOT EXISTS idx_discovery_prop_object_fast
                ON discovery_propositions(object_key,operation,authority_state);
            CREATE INDEX IF NOT EXISTS idx_discovery_prop_physical_item
                ON discovery_propositions(project_id,world_id,subject_type,subject_key,authority_state,updated_at);
            CREATE INDEX IF NOT EXISTS idx_discovery_subject_link_resource
                ON discovery_subject_links(resource_type,resource_id,project_id,world_id);
            """
        )
        con.execute(
            "INSERT INTO discovery_meta(key,value) VALUES('performance_schema_version',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (PERFORMANCE_SCHEMA_VERSION,),
        )
    service._discovery_performance_schema_ready = True


def _scope_revision(service, context: MemoryQueryContext) -> str:
    with service.store.connection() as con:
        row = con.execute(
            "SELECT "
            "(SELECT COUNT(*) FROM discovery_propositions WHERE project_id IS ? AND world_id IS ?) AS pc,"
            "(SELECT COALESCE(MAX(updated_at),'') FROM discovery_propositions WHERE project_id IS ? AND world_id IS ?) AS pu,"
            "(SELECT COUNT(*) FROM discovery_instances WHERE project_id IS ? AND world_id IS ?) AS ic,"
            "(SELECT COALESCE(MAX(updated_at),'') FROM discovery_instances WHERE project_id IS ? AND world_id IS ?) AS iu",
            (
                context.project_id, context.world_id,
                context.project_id, context.world_id,
                context.project_id, context.world_id,
                context.project_id, context.world_id,
            ),
        ).fetchone()
    return f"{row['pc']}|{row['pu']}|{row['ic']}|{row['iu']}"


def _context_key(context: MemoryQueryContext) -> tuple[Any, ...]:
    lens = getattr(context.context_lens, "value", context.context_lens)
    return (
        context.project_id,
        context.world_id,
        context.branch_id,
        context.session_id,
        context.story_order,
        dumps(context.world_time) if context.world_time is not None else None,
        lens,
        bool(context.allow_future_author_knowledge),
    )


def _copy_report(report: dict[str, Any], *, cached: bool) -> dict[str, Any]:
    return {**report, "cached": cached}


def _source_cache_row(service, turn_id: str, source_kind: str):
    with service.store.connection() as con:
        return con.execute(
            "SELECT * FROM discovery_capture_cache WHERE source_turn_id=? AND source_kind=?",
            (turn_id, source_kind),
        ).fetchone()


def _source_counts(service, turn_id: str, source_kind: str, revision: str) -> tuple[int, int, int]:
    with service.store.connection() as con:
        row = con.execute(
            "SELECT "
            "COUNT(DISTINCT CASE WHEN source_revision=? THEN proposition_id END) AS propositions,"
            "SUM(CASE WHEN source_revision=? THEN 1 ELSE 0 END) AS instances,"
            "SUM(CASE WHEN source_revision!=? THEN 1 ELSE 0 END) AS other_instances "
            "FROM discovery_instances WHERE source_turn_id=? AND source_kind=? AND active=1",
            (revision, revision, revision, turn_id, source_kind),
        ).fetchone()
    return int(row["propositions"] or 0), int(row["instances"] or 0), int(row["other_instances"] or 0)


def _write_source_cache(service, report: CaptureReport, revision: str) -> None:
    propositions, instances, _other = _source_counts(
        service, report.turn_id, report.source_kind, revision
    )
    with service.store._lock, service.store.connection() as con:
        con.execute(
            "INSERT INTO discovery_capture_cache(source_turn_id,source_kind,source_revision,pipeline_revision,"
            "propositions,instances,skipped,updated_at) VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(source_turn_id,source_kind) DO UPDATE SET "
            "source_revision=excluded.source_revision,pipeline_revision=excluded.pipeline_revision,"
            "propositions=excluded.propositions,instances=excluded.instances,skipped=excluded.skipped,"
            "updated_at=excluded.updated_at",
            (
                report.turn_id,
                report.source_kind,
                revision,
                CAPTURE_PIPELINE_REVISION,
                propositions,
                instances,
                int(report.skipped),
                utc_now(),
            ),
        )


def _invalidate_runtime_caches(service, turn_id: str) -> None:
    with service.store._lock, service.store.connection() as con:
        prop_rows = con.execute(
            "SELECT DISTINCT proposition_id FROM discovery_instances WHERE source_turn_id=?",
            (turn_id,),
        ).fetchall()
        prop_ids = [str(row["proposition_id"]) for row in prop_rows]
        con.execute("DELETE FROM discovery_materialization_cache WHERE source_turn_id=?", (turn_id,))
        if prop_ids:
            marks = ",".join("?" for _ in prop_ids)
            con.execute(
                f"DELETE FROM discovery_branch_projection_cache WHERE proposition_id IN ({marks})",
                prop_ids,
            )
    getattr(service, "_discovery_list_cache", {}).clear()
    getattr(service, "_physical_item_scope_cache", {}).clear()


def _install_capture_fast_path(service) -> None:
    if getattr(service, "_discovery_capture_fast_path_installed", False):
        return
    original = service.capture_text

    def capture_text(text: str, *, source_kind: str, turn: dict[str, Any],
                     session: dict[str, Any], qualifies_review: bool | None = None):
        compiled = CharacterRailParser.parse(text)
        evidence = str(compiled.evidence_prompt if compiled.active else text or "").strip()
        revision = checksum(evidence)
        cached = _source_cache_row(service, turn["id"], source_kind)
        if cached is not None:
            propositions, instances, other = _source_counts(
                service, turn["id"], source_kind, revision
            )
            if (
                cached["source_revision"] == revision
                and cached["pipeline_revision"] == CAPTURE_PIPELINE_REVISION
                and int(cached["propositions"]) == propositions
                and int(cached["instances"]) == instances
                and other == 0
            ):
                _increment(service, "capture_hits")
                return CaptureReport(
                    turn["id"], source_kind, propositions, instances, int(cached["skipped"])
                )

        _increment(service, "capture_misses")
        report = original(
            text,
            source_kind=source_kind,
            turn=turn,
            session=session,
            qualifies_review=qualifies_review,
        )
        _write_source_cache(service, report, revision)
        _invalidate_runtime_caches(service, turn["id"])
        return report

    service.capture_text = capture_text
    service._discovery_capture_fast_path_installed = True


def _turn_rows(service, turn_id: str) -> list[dict[str, Any]]:
    with service.store.connection() as con:
        rows = con.execute(
            "SELECT id,proposition_id,source_kind,source_revision,active,updated_at "
            "FROM discovery_instances WHERE source_turn_id=? ORDER BY proposition_id,id",
            (turn_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _turn_fingerprint(rows: list[dict[str, Any]]) -> str:
    payload = [
        [row["id"], row["proposition_id"], row["source_kind"], row["source_revision"], row["active"], row["updated_at"]]
        for row in rows
    ]
    return sha256(dumps(payload).encode("utf-8")).hexdigest()


def _install_materialization_cache(provisional_module) -> None:
    if getattr(provisional_module, "_PERFORMANCE_MATERIALIZATION_INSTALLED", False):
        return

    def materialize_turn(service, turn_id: str) -> dict[str, Any]:
        _ensure_performance_schema(service)
        provisional_module._ensure_schema(service)
        rows = _turn_rows(service, turn_id)
        fingerprint = _turn_fingerprint(rows)
        with service.store.connection() as con:
            cached = con.execute(
                "SELECT fingerprint,report_json FROM discovery_materialization_cache WHERE source_turn_id=?",
                (turn_id,),
            ).fetchone()
        if cached is not None and cached["fingerprint"] == fingerprint:
            _increment(service, "materialization_hits")
            return _copy_report(loads(cached["report_json"], {}), cached=True)

        _increment(service, "materialization_misses")
        total = provisional_module.ProvisionalMaterializationReport()
        prop_ids = sorted({str(row["proposition_id"]) for row in rows if row["active"]})
        for prop_id in prop_ids:
            item = provisional_module._materialize_proposition(service, prop_id)
            for field in ("sheets", "zones", "claims", "relations", "changes"):
                setattr(total, field, getattr(total, field) + getattr(item, field))
        report = total.to_dict()
        with service.store._lock, service.store.connection() as con:
            con.execute(
                "INSERT INTO discovery_materialization_cache(source_turn_id,fingerprint,report_json,updated_at) "
                "VALUES(?,?,?,?) ON CONFLICT(source_turn_id) DO UPDATE SET "
                "fingerprint=excluded.fingerprint,report_json=excluded.report_json,updated_at=excluded.updated_at",
                (turn_id, fingerprint, dumps(report), utc_now()),
            )
        return _copy_report(report, cached=False)

    def dirty_ids(service, limit: int) -> list[str]:
        supported = sorted(set(provisional_module.SUPPORTED_SHEET_TYPES) - {"spatial_zone"})
        marks = ",".join("?" for _ in supported) or "''"
        with service.store.connection() as con:
            rows = con.execute(
                f"SELECT DISTINCT p.id FROM discovery_propositions p "
                "JOIN discovery_instances i ON i.proposition_id=p.id AND i.active=1 "
                "LEFT JOIN discovery_subject_links sl ON sl.project_id=COALESCE(p.project_id,'') "
                "AND sl.world_id=COALESCE(p.world_id,'') AND sl.subject_key=p.subject_key "
                "LEFT JOIN discovery_spatial_zones z ON z.world_id=p.world_id AND z.subject_key=p.subject_key "
                "WHERE p.authority_state!='dismissed' AND ("
                "(p.subject_type='spatial_zone' AND z.id IS NULL) OR "
                "(p.subject_type!='spatial_zone' AND sl.resource_id IS NULL) OR "
                f"(p.operation='relation' AND p.object_key IS NOT NULL AND p.object_type IN ({marks}) AND NOT EXISTS("
                "SELECT 1 FROM discovery_subject_links ol WHERE ol.project_id=COALESCE(p.project_id,'') "
                "AND ol.world_id=COALESCE(p.world_id,'') AND ol.subject_key=p.object_key))) "
                "ORDER BY p.rowid LIMIT ?",
                [*supported, max(1, int(limit))],
            ).fetchall()
        return [str(row["id"]) for row in rows]

    def materialize_existing(service, *, limit: int = 5000) -> dict[str, Any]:
        _ensure_performance_schema(service)
        provisional_module._ensure_schema(service)
        deadline = monotonic() + STARTUP_BUDGET_SECONDS
        total = provisional_module.ProvisionalMaterializationReport()
        processed = 0
        while processed < max(1, int(limit)) and monotonic() < deadline:
            batch = dirty_ids(service, min(STARTUP_BATCH_SIZE, int(limit) - processed))
            if not batch:
                break
            for prop_id in batch:
                item = provisional_module._materialize_proposition(service, prop_id)
                for field in ("sheets", "zones", "claims", "relations", "changes"):
                    setattr(total, field, getattr(total, field) + getattr(item, field))
                processed += 1
                if monotonic() >= deadline:
                    break
        pending = bool(dirty_ids(service, 1))
        report = total.to_dict()
        report.update({
            "processed": processed,
            "pending": pending,
            "revision": MATERIALIZATION_REVISION,
            "budget_ms": int(STARTUP_BUDGET_SECONDS * 1000),
        })
        _increment(service, "startup_materialized", processed)
        return report

    provisional_module.materialize_turn = materialize_turn
    provisional_module.materialize_existing = materialize_existing
    provisional_module._PERFORMANCE_MATERIALIZATION_INSTALLED = True


def _branch_fingerprint(rows: Iterable[dict[str, Any]]) -> str:
    payload = sorted(
        (
            str(row.get("id") or ""),
            str(row.get("branch_id") or ""),
            str(row.get("updated_at") or ""),
            bool(row.get("active")),
        )
        for row in rows
    )
    return sha256(dumps(payload).encode("utf-8")).hexdigest()


def _install_branch_repair_cache(runtime_module) -> None:
    if getattr(runtime_module, "_PERFORMANCE_BRANCH_REPAIR_INSTALLED", False):
        return
    original_repair = runtime_module.repair_proposition_branch_projection

    def cached_fingerprint(service, proposition_id: str) -> str | None:
        with service.store.connection() as con:
            row = con.execute(
                "SELECT fingerprint FROM discovery_branch_projection_cache WHERE proposition_id=?",
                (proposition_id,),
            ).fetchone()
        return str(row["fingerprint"]) if row else None

    def save_fingerprint(service, proposition_id: str, fingerprint: str) -> None:
        with service.store._lock, service.store.connection() as con:
            con.execute(
                "INSERT INTO discovery_branch_projection_cache(proposition_id,fingerprint,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(proposition_id) DO UPDATE SET fingerprint=excluded.fingerprint,updated_at=excluded.updated_at",
                (proposition_id, fingerprint, utc_now()),
            )

    def repair_group(service, grouped: dict[str, list[dict[str, Any]]], *, deadline: float | None = None) -> int:
        repaired = 0
        for prop_id in sorted(grouped):
            fingerprint = _branch_fingerprint(grouped[prop_id])
            if cached_fingerprint(service, prop_id) == fingerprint:
                continue
            original_repair(service, prop_id)
            save_fingerprint(service, prop_id, fingerprint)
            repaired += 1
            if deadline is not None and monotonic() >= deadline:
                break
        _increment(service, "branch_repairs", repaired)
        return repaired

    def repair_turn(service, turn_id: str) -> None:
        _ensure_performance_schema(service)
        with service.store.connection() as con:
            rows = con.execute(
                "SELECT id,proposition_id,branch_id,active,updated_at FROM discovery_instances "
                "WHERE source_turn_id=? AND active=1 ORDER BY proposition_id,id",
                (turn_id,),
            ).fetchall()
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[str(row["proposition_id"])].append(dict(row))
        repair_group(service, grouped)

    def repair_existing(service, limit: int = 10000) -> None:
        _ensure_performance_schema(service)
        deadline = monotonic() + STARTUP_BUDGET_SECONDS
        with service.store.connection() as con:
            rows = con.execute(
                "SELECT id,proposition_id,branch_id,active,updated_at FROM discovery_instances "
                "WHERE active=1 ORDER BY proposition_id,id LIMIT ?",
                (max(1, min(int(limit) * 16, 50000)),),
            ).fetchall()
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[str(row["proposition_id"])].append(dict(row))
        repair_group(service, grouped, deadline=deadline)

    runtime_module.repair_turn_branch_projection = repair_turn
    runtime_module.repair_existing_branch_projections = repair_existing
    runtime_module._PERFORMANCE_BRANCH_REPAIR_INSTALLED = True


def _install_gate_cache(service) -> None:
    if getattr(service, "_discovery_gate_cache_installed", False):
        return
    gate = service.gate
    original_branches = gate.branch_cutoffs
    original_sessions = gate.session_cutoffs
    branch_cache: dict[str | None, dict[str | None, str | None]] = {}
    session_cache: dict[str | None, dict[str | None, str | None]] = {}

    def branch_cutoffs(branch_id):
        if branch_id not in branch_cache:
            branch_cache[branch_id] = original_branches(branch_id)
        return branch_cache[branch_id]

    def session_cutoffs(session_id):
        if session_id not in session_cache:
            session_cache[session_id] = original_sessions(session_id)
        return session_cache[session_id]

    gate.branch_cutoffs = branch_cutoffs
    gate.session_cutoffs = session_cutoffs
    service._discovery_gate_cache_installed = True


def _load_instances_for_props(service, proposition_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for offset in range(0, len(proposition_ids), 400):
        chunk = proposition_ids[offset:offset + 400]
        if not chunk:
            continue
        marks = ",".join("?" for _ in chunk)
        with service.store.connection() as con:
            rows = con.execute(
                f"SELECT * FROM discovery_instances WHERE proposition_id IN ({marks}) "
                "ORDER BY proposition_id,created_at,id",
                chunk,
            ).fetchall()
        for row in rows:
            item = service.store._instance_row(row)
            grouped[str(item["proposition_id"])].append(item)
    return grouped


def _evaluate_many(service, propositions: list[dict[str, Any]], context: MemoryQueryContext,
                   *, include_instances: bool = False) -> list[dict[str, Any]]:
    if not propositions:
        return []
    instance_map = _load_instances_for_props(service, [str(item["id"]) for item in propositions])
    output: list[dict[str, Any]] = []
    for proposition in propositions:
        all_instances = instance_map.get(str(proposition["id"]), [])
        visible_active = [
            item for item in all_instances
            if item.get("active") and service._instance_allowed(item, context)
        ]
        inactive = [item for item in all_instances if not item.get("active")]

        if proposition.get("authority_state") == "canon":
            knowledge_state = "canon"
            qualified_count = 0
        elif proposition.get("authority_state") == "dismissed":
            knowledge_state = "dismissed"
            qualified_count = 0
        elif context.session_id is None:
            by_session: dict[str, set[tuple[str, str]]] = {}
            for item in visible_active:
                if not item.get("qualifies_review"):
                    continue
                session_key = str(item.get("source_session_id") or "")
                by_session.setdefault(session_key, set()).add((
                    str(item.get("source_kind") or ""),
                    str(item.get("origin_turn_id") or item.get("source_turn_id") or item.get("id")),
                ))
            qualified_count = max((len(values) for values in by_session.values()), default=0)
            knowledge_state = "reviewed" if qualified_count >= 2 else "detected"
        else:
            qualified = {
                (
                    str(item.get("source_kind") or ""),
                    str(item.get("origin_turn_id") or item.get("source_turn_id") or item.get("id")),
                )
                for item in visible_active if item.get("qualifies_review")
            }
            qualified_count = len(qualified)
            knowledge_state = "reviewed" if qualified_count >= 2 else "detected"

        has_user_edit = any(
            item.get("source_kind") == "user_library_edit" for item in visible_active
        )
        if has_user_edit and knowledge_state == "detected":
            knowledge_state = "reviewed"

        provenance_state = (
            "partial" if visible_active and inactive
            else "active" if visible_active
            else "orphaned"
        )
        qualified_visible = {
            (
                str(item.get("source_kind") or ""),
                str(item.get("origin_turn_id") or item.get("source_turn_id") or item.get("id")),
            )
            for item in visible_active if item.get("qualifies_review")
        }
        item = {
            **proposition,
            "knowledge_state": knowledge_state,
            "provenance_state": provenance_state,
            "support_count": len(visible_active),
            "qualified_support_count": len(qualified_visible),
            "total_support_count": len(all_instances),
            "out_of_scope_support_count": max(
                0,
                sum(1 for instance in all_instances if instance.get("active")) - len(visible_active),
            ),
            "inactive_support_count": len(inactive),
        }
        if has_user_edit:
            item["review_reason"] = "explicit_user_library_edit"
        item["semantics"] = describe_claim(item)
        if include_instances:
            item["instances"] = all_instances
            item["visible_instance_ids"] = [instance["id"] for instance in visible_active]
        output.append(item)
    return output


def _install_batch_evaluation(service) -> None:
    if getattr(service, "_discovery_batch_evaluation_installed", False):
        return
    _install_gate_cache(service)
    cache_lock = RLock()
    list_cache: OrderedDict[tuple[Any, ...], list[dict[str, Any]]] = OrderedDict()
    service._discovery_list_cache = list_cache

    def evaluate_many(propositions, context, *, include_instances: bool = False):
        return _evaluate_many(
            service,
            list(propositions),
            context,
            include_instances=include_instances,
        )

    def list_fast(context: MemoryQueryContext, *, include_dismissed: bool = False,
                  include_orphaned: bool = False, limit: int = 500):
        revision = _scope_revision(service, context)
        key = (
            *_context_key(context),
            bool(include_dismissed),
            bool(include_orphaned),
            int(limit),
            revision,
        )
        with cache_lock:
            cached = list_cache.get(key)
            if cached is not None:
                list_cache.move_to_end(key)
                _increment(service, "list_hits")
                return [dict(item) for item in cached]

        _increment(service, "list_misses")
        rows = service.store.list_propositions(
            project_id=context.project_id,
            world_id=context.world_id,
            include_dismissed=include_dismissed,
            limit=limit,
        )
        evaluated = evaluate_many(rows, context, include_instances=False)
        if not include_orphaned:
            evaluated = [
                item for item in evaluated
                if item["provenance_state"] != "orphaned" or item["knowledge_state"] == "canon"
            ]
        rank = {"canon": 3, "reviewed": 2, "detected": 1, "dismissed": 0}
        evaluated = sorted(
            evaluated,
            key=lambda item: (
                rank.get(item["knowledge_state"], 0),
                item["qualified_support_count"],
                item["support_count"],
                item["updated_at"],
            ),
            reverse=True,
        )
        with cache_lock:
            list_cache[key] = evaluated
            list_cache.move_to_end(key)
            while len(list_cache) > 16:
                list_cache.popitem(last=False)
        return [dict(item) for item in evaluated]

    service.evaluate_many = evaluate_many
    service.list = list_fast
    service._discovery_batch_evaluation_installed = True


def _install_resource_prefetch(service) -> None:
    if getattr(service, "_discovery_resource_prefetch_installed", False):
        return
    original_evaluate = service.evaluate_proposition
    original_resource_view = service.resource_view
    state = local()

    def evaluate_with_prefetch(proposition, context, *, include_instances: bool = False):
        cache = getattr(state, "evaluations", None)
        if cache is not None:
            item = cache.get(str(proposition["id"]))
            if item is not None:
                value = dict(item)
                if not include_instances:
                    value.pop("instances", None)
                    value.pop("visible_instance_ids", None)
                return value
        return original_evaluate(proposition, context, include_instances=include_instances)

    def resource_view(resource_id: str, context: MemoryQueryContext):
        with service.store.connection() as con:
            links = con.execute(
                "SELECT subject_key FROM discovery_subject_links WHERE resource_type='entity_family' AND resource_id=?",
                (resource_id,),
            ).fetchall()
            keys = sorted({str(row["subject_key"]) for row in links})
            rows = []
            if keys:
                marks = ",".join("?" for _ in keys)
                rows = con.execute(
                    f"SELECT * FROM discovery_propositions WHERE (subject_key IN ({marks}) OR object_key IN ({marks})) "
                    "AND authority_state!='dismissed' ORDER BY rowid",
                    [*keys, *keys],
                ).fetchall()
        propositions = [service.store._prop_row(row) for row in rows]
        state.evaluations = {
            item["id"]: item
            for item in service.evaluate_many(propositions, context, include_instances=True)
        }
        try:
            return original_resource_view(resource_id, context)
        finally:
            state.evaluations = None

    service.evaluate_proposition = evaluate_with_prefetch
    service.resource_view = resource_view
    service._discovery_resource_prefetch_installed = True


def _install_physical_item_index(service, physical_items_module) -> None:
    # The wrapper is module-global, but cache ownership is service-local. A
    # captured cache from the first DiscoveryService leaked entries and, more
    # importantly, could not be invalidated by later services. Python/runtime
    # timing then made physical-item resolution nondeterministic across fixtures.
    if not hasattr(service, "_physical_item_scope_cache"):
        service._physical_item_scope_cache = OrderedDict()
    if getattr(physical_items_module, "_PERFORMANCE_ITEM_INDEX_INSTALLED", False):
        return

    def clone(item):
        return physical_items_module.PhysicalItem(
            subject_key=item.subject_key,
            item_id=item.item_id,
            garment_type=item.garment_type,
            label=item.label,
            attributes=dict(item.attributes),
            existing=item.existing,
            family_id=item.family_id,
        )

    def existing_items(service_obj, context: MemoryQueryContext):
        scope_cache = getattr(service_obj, "_physical_item_scope_cache", None)
        if scope_cache is None:
            scope_cache = OrderedDict()
            service_obj._physical_item_scope_cache = scope_cache
        revision = _scope_revision(service_obj, context)
        key = (*_context_key(context), revision)
        cached = scope_cache.get(key)
        if cached is not None:
            scope_cache.move_to_end(key)
            _increment(service_obj, "physical_index_hits")
            return [clone(item) for item in cached]

        _increment(service_obj, "physical_index_misses")
        with service_obj.store.connection() as con:
            rows = con.execute(
                "SELECT * FROM discovery_propositions WHERE project_id IS ? AND world_id IS ? "
                "AND subject_type='garment' AND subject_key LIKE 'item:ITEM-%' "
                "AND authority_state!='dismissed' ORDER BY updated_at DESC,rowid DESC",
                (context.project_id, context.world_id),
            ).fetchall()
        propositions = [service_obj.store._prop_row(row) for row in rows]
        evaluated = service_obj.evaluate_many(propositions, context, include_instances=False)
        visible = [
            item for item in evaluated
            if item["knowledge_state"] == "canon" or int(item.get("support_count") or 0) > 0
        ]
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in visible:
            grouped[str(item["subject_key"])].append(item)

        subject_keys = sorted(grouped)
        links: dict[str, str] = {}
        if subject_keys:
            marks = ",".join("?" for _ in subject_keys)
            with service_obj.store.connection() as con:
                link_rows = con.execute(
                    f"SELECT subject_key,resource_id FROM discovery_subject_links WHERE project_id=? AND world_id=? "
                    f"AND subject_key IN ({marks})",
                    [context.project_id or "", context.world_id or "", *subject_keys],
                ).fetchall()
            links = {str(row["subject_key"]): str(row["resource_id"]) for row in link_rows}

        result = []
        for subject_key, items in grouped.items():
            identity = next((item for item in items if item["predicate"] == "entity.exists"), None)
            if identity is None:
                continue
            identity_value = identity.get("value") if isinstance(identity.get("value"), dict) else {}
            item_id = str(
                identity_value.get("physical_item_id")
                or physical_items_module._physical_item_id_from_key(subject_key)
                or ""
            )
            if not item_id:
                continue
            garment_type = str(identity_value.get("garment_type") or "garment").casefold()
            attributes: dict[str, Any] = {}
            for item in sorted(items, key=lambda value: str(value.get("updated_at") or ""), reverse=True):
                predicate = str(item.get("predicate") or "")
                if not predicate.startswith("garment.") or predicate == "garment.type":
                    continue
                name = predicate.removeprefix("garment.")
                attributes.setdefault(name, item.get("value"))
            result.append(physical_items_module.PhysicalItem(
                subject_key=subject_key,
                item_id=item_id,
                garment_type=garment_type,
                label=str(identity.get("subject_label") or garment_type.title()),
                attributes=attributes,
                existing=True,
                family_id=links.get(subject_key),
            ))

        scope_cache[key] = result
        scope_cache.move_to_end(key)
        while len(scope_cache) > 12:
            scope_cache.popitem(last=False)
        return [clone(item) for item in result]

    physical_items_module._existing_items = existing_items
    physical_items_module._PERFORMANCE_ITEM_INDEX_INSTALLED = True


def _install_status(service) -> None:
    if getattr(service, "_discovery_performance_status_installed", False):
        return
    original_status = service.store.status

    def performance_status() -> dict[str, Any]:
        metrics = dict(_metrics(service))
        return {
            "pipeline": "lightweight_extraction",
            "pipeline_revision": CAPTURE_PIPELINE_REVISION,
            "materialization_revision": MATERIALIZATION_REVISION,
            "startup_budget_ms": int(STARTUP_BUDGET_SECONDS * 1000),
            "metrics": metrics,
            "list_cache_entries": len(getattr(service, "_discovery_list_cache", {})),
            "physical_item_cache_entries": len(getattr(service, "_physical_item_scope_cache", {})),
        }

    def status():
        return {**original_status(), "performance": performance_status()}

    service.performance_status = performance_status
    service.store.status = status
    service._discovery_performance_status_installed = True


def prepare_discovery_performance(service, provisional_module, runtime_module, physical_items_module) -> None:
    """Install pre-materialization performance primitives.

    This runs after semantic/physical capture adapters are installed but before
    provisional installation performs its first startup projection.
    """
    _ensure_performance_schema(service)
    if not isinstance(service.pipeline, DiscoveryExtractionPipeline):
        service.pipeline = DiscoveryExtractionPipeline(service.pipeline)
    _install_materialization_cache(provisional_module)
    _install_branch_repair_cache(runtime_module)
    _install_physical_item_index(service, physical_items_module)
    _install_capture_fast_path(service)


def finalize_discovery_performance(service) -> None:
    """Install query/UI-facing caches after all correctness wrappers exist."""
    if getattr(service, "_discovery_performance_finalized", False):
        return
    _install_batch_evaluation(service)
    _install_resource_prefetch(service)
    _install_status(service)
    service._discovery_performance_finalized = True
