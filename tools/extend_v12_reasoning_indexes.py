from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# MemoryStore summary + causal methods and stale propagation
# ---------------------------------------------------------------------------
store_path = ROOT / "src/memory/store.py"
store = store_path.read_text(encoding="utf-8")
old_update = '''            con.execute(
                "UPDATE memory_chunks SET semantic_status='stale',index_state='stale',updated_at=? "
                "WHERE source_type=? AND source_id=? AND semantic_status='active'",
                (utc_now(), source_type, source_id),
            )
'''
new_update = '''            old_rows = con.execute(
                "SELECT id FROM memory_chunks WHERE source_type=? AND source_id=? AND semantic_status='active'",
                (source_type, source_id),
            ).fetchall()
            if old_rows:
                old_ids = [row["id"] for row in old_rows]
                placeholders = ",".join("?" for _ in old_ids)
                con.execute(
                    f"UPDATE memory_summaries SET status='stale',updated_at=? WHERE id IN ("
                    f"SELECT summary_id FROM memory_summary_sources WHERE memory_chunk_id IN ({placeholders}))",
                    [utc_now(), *old_ids],
                )
            con.execute(
                "UPDATE memory_chunks SET semantic_status='stale',index_state='stale',updated_at=? "
                "WHERE source_type=? AND source_id=? AND semantic_status='active'",
                (utc_now(), source_type, source_id),
            )
'''
if old_update in store:
    store = store.replace(old_update, new_update, 1)

if "def create_summary(" not in store:
    anchor = "    def create_generation(self, *, provider: str, embedding_model: str | None, dimension: int | None,\n"
    methods = '''    def create_summary(self, *, summary_type: str, subject_type: str, subject_id: str,
                       text: str, evidence_hash: str, source_chunk_ids: list[str],
                       project_id: str | None = None, world_id: str | None = None,
                       branch_id: str | None = None, structured_payload: dict[str, Any] | None = None,
                       story_order_from: float | None = None, story_order_to: float | None = None) -> dict[str, Any]:
        summary_id = make_id("SUMMARY"); now = utc_now()
        with self._lock, self.connection() as con:
            con.execute(
                "INSERT INTO memory_summaries(id,summary_type,subject_type,subject_id,project_id,world_id,branch_id,story_order_from,story_order_to,text,structured_payload_json,evidence_hash,status,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?, 'active',?,?)",
                (summary_id, summary_type, subject_type, subject_id, project_id, world_id, branch_id,
                 story_order_from, story_order_to, text.strip(), dumps(structured_payload or {}), evidence_hash, now, now),
            )
            for chunk_id in source_chunk_ids:
                con.execute("INSERT OR IGNORE INTO memory_summary_sources(summary_id,memory_chunk_id) VALUES(?,?)", (summary_id, chunk_id))
        return self.get_summary(summary_id)

    def get_summary(self, summary_id: str) -> dict[str, Any]:
        with self.connection() as con:
            row = con.execute("SELECT * FROM memory_summaries WHERE id=?", (summary_id,)).fetchone()
            if not row: raise KeyError(summary_id)
            sources = con.execute("SELECT memory_chunk_id FROM memory_summary_sources WHERE summary_id=?", (summary_id,)).fetchall()
        item = dict(row)
        item["structured_payload"] = loads(item.pop("structured_payload_json"), {})
        item["source_chunk_ids"] = [source["memory_chunk_id"] for source in sources]
        return item

    def list_summaries(self, *, world_id: str | None = None, branch_id: str | None = None,
                       subject_type: str | None = None, subject_id: str | None = None,
                       status: str = "active", limit: int = 100) -> list[dict[str, Any]]:
        where=["status=?"]; params: list[Any]=[status]
        if world_id: where.append("world_id=?"); params.append(world_id)
        if branch_id is not None: where.append("(branch_id IS NULL OR branch_id IS ?)"); params.append(branch_id)
        if subject_type: where.append("subject_type=?"); params.append(subject_type)
        if subject_id: where.append("subject_id=?"); params.append(subject_id)
        params.append(max(1,min(1000,limit)))
        with self.connection() as con:
            rows=con.execute(f"SELECT id FROM memory_summaries WHERE {' AND '.join(where)} ORDER BY updated_at DESC LIMIT ?",params).fetchall()
        return [self.get_summary(row["id"]) for row in rows]

    def invalidate_summaries_for_chunk(self, chunk_id: str) -> int:
        with self._lock, self.connection() as con:
            cur=con.execute(
                "UPDATE memory_summaries SET status='stale',updated_at=? WHERE id IN (SELECT summary_id FROM memory_summary_sources WHERE memory_chunk_id=?) AND status='active'",
                (utc_now(),chunk_id),
            )
        return int(cur.rowcount)

    def add_event_participant(self, event_id: str, entity_variant_id: str, role: str = "participant") -> None:
        with self._lock,self.connection() as con:
            con.execute("INSERT OR REPLACE INTO event_participants(event_id,entity_variant_id,role) VALUES(?,?,?)",(event_id,entity_variant_id,role))

    def events_for_participant(self, entity_variant_id: str) -> list[dict[str, Any]]:
        with self.connection() as con:
            rows=con.execute("SELECT * FROM event_participants WHERE entity_variant_id=? ORDER BY event_id",(entity_variant_id,)).fetchall()
        return [dict(row) for row in rows]

    def add_causal_edge(self, source_event_id: str, target_event_id: str, relation: str,
                        confidence: float = 1.0, authority: str = "accepted_event",
                        status: str = "accepted") -> dict[str, Any]:
        with self._lock,self.connection() as con:
            con.execute(
                "INSERT OR REPLACE INTO event_causal_edges(source_event_id,target_event_id,relation,confidence,authority,status) VALUES(?,?,?,?,?,?)",
                (source_event_id,target_event_id,relation,float(confidence),authority,status),
            )
        return {"source_event_id":source_event_id,"target_event_id":target_event_id,"relation":relation,"confidence":confidence,"authority":authority,"status":status}

    def causal_edges(self, event_id: str | None = None, *, direction: str = "both") -> list[dict[str, Any]]:
        where=["status='accepted'"]; params: list[Any]=[]
        if event_id:
            if direction=="incoming": where.append("target_event_id=?"); params.append(event_id)
            elif direction=="outgoing": where.append("source_event_id=?"); params.append(event_id)
            else: where.append("(source_event_id=? OR target_event_id=?)"); params += [event_id,event_id]
        with self.connection() as con:
            rows=con.execute(f"SELECT * FROM event_causal_edges WHERE {' AND '.join(where)} ORDER BY confidence DESC",params).fetchall()
        return [dict(row) for row in rows]

'''
    if anchor not in store:
        raise RuntimeError("MemoryStore summary/causal anchor missing")
    store = store.replace(anchor, methods + anchor, 1)
store_path.write_text(store, encoding="utf-8")

# ---------------------------------------------------------------------------
# QueryEngine causal and summary lanes
# ---------------------------------------------------------------------------
query_path = ROOT / "src/memory/query.py"
query = query_path.read_text(encoding="utf-8")
if "def _causal(" not in query:
    anchor = "    def _fts(self, query: str, lane: RetrievalLane, budget: int) -> list[MemoryCandidate]:\n"
    methods = '''    def _causal(self, plan: QueryPlan) -> list[MemoryCandidate]:
        output: list[MemoryCandidate] = []
        event_ids: set[str] = set()
        for variant in self._variant_targets(plan):
            for link in self.store.events_for_participant(variant["id"]):
                event_ids.add(link["event_id"])
        if not event_ids:
            event_ids.update(item.id for item in self._events(plan))
        try:
            event_map = {item["id"]: item for item in self.workspace.list_timeline_events(plan.scope.world_id, branch_id=plan.scope.branch_id)} if plan.scope.world_id else {}
        except Exception:
            event_map = {}
        seen: set[tuple[str,str,str]] = set()
        for event_id in list(event_ids)[:30]:
            for edge in self.store.causal_edges(event_id):
                key=(edge["source_event_id"],edge["target_event_id"],edge["relation"])
                if key in seen: continue
                seen.add(key)
                source=event_map.get(edge["source_event_id"],{}); target=event_map.get(edge["target_event_id"],{})
                output.append(MemoryCandidate(
                    id=f"CAUSE:{edge['source_event_id']}:{edge['target_event_id']}:{edge['relation']}",
                    lane=RetrievalLane.GRAPH,
                    text=f"{source.get('summary',edge['source_event_id'])} --{edge['relation']}--> {target.get('summary',edge['target_event_id'])}",
                    source_type="causal_edge",source_id=edge["source_event_id"],world_id=plan.scope.world_id,branch_id=plan.scope.branch_id,
                    authority=edge.get("authority") or Authority.ACCEPTED_EVENT.value,trust_level=TrustLevel.TRUSTED_LOCAL.value,
                    importance=0.9,metadata={"causal_edge":edge,"structured":True},
                ))
        return output

    def _summaries(self, plan: QueryPlan) -> list[MemoryCandidate]:
        output=[]
        targets=self._resource_targets(plan)
        rows=[]
        if targets:
            for resource_type,resource_id in targets:
                rows.extend(self.store.list_summaries(world_id=plan.scope.world_id,branch_id=plan.scope.branch_id,subject_type=resource_type,subject_id=resource_id,limit=20))
        else:
            rows=self.store.list_summaries(world_id=plan.scope.world_id,branch_id=plan.scope.branch_id,limit=20)
        seen=set()
        for row in rows:
            if row["id"] in seen: continue
            seen.add(row["id"])
            output.append(MemoryCandidate(
                id=row["id"],lane=RetrievalLane.SUMMARIES,text=row["text"],source_type="derived_summary",source_id=row["id"],
                project_id=row.get("project_id"),world_id=row.get("world_id"),branch_id=row.get("branch_id"),story_order=row.get("story_order_to"),
                authority=Authority.DERIVED_SUMMARY.value,trust_level=TrustLevel.GENERATED.value,importance=0.65,
                metadata={"summary":row},
            ))
        return output

'''
    if anchor not in query:
        raise RuntimeError("QueryEngine causal anchor missing")
    query=query.replace(anchor,methods+anchor,1)
query=query.replace(
    "        if lane == RetrievalLane.SUMMARIES: return self._fts(plan.normalized_query, RetrievalLane.FTS_SUMMARY, budget)\n        if lane == RetrievalLane.GRAPH: return self._events(plan) + self._spatial(plan)\n",
    "        if lane == RetrievalLane.SUMMARIES: return self._summaries(plan) + self._fts(plan.normalized_query, RetrievalLane.FTS_SUMMARY, budget)\n        if lane == RetrievalLane.GRAPH: return self._causal(plan) + self._spatial(plan)\n",
)
query_path.write_text(query,encoding="utf-8")

# ---------------------------------------------------------------------------
# Exports and application services/routes
# ---------------------------------------------------------------------------
init_path=ROOT/"src/memory/__init__.py"
init=init_path.read_text(encoding="utf-8")
if "ContinuityService" not in init:
    init=init.replace("from .config import", "from .continuity import ContinuityService\nfrom .summarize import SummaryService\nfrom .config import",1)
    init=init.replace('    "Authority",', '    "Authority", "ContinuityService", "SummaryService",',1)
init_path.write_text(init,encoding="utf-8")

app_path=ROOT/"src/interface/web/app.py"
app=app_path.read_text(encoding="utf-8")
app=app.replace(
    "    MemoryService, MemoryStore, SpatialMemory, TemporalMemory,\n",
    "    ContinuityService, MemoryService, MemoryStore, SpatialMemory, SummaryService, TemporalMemory,\n",
)
app=app.replace(
    "    temporal_memory = TemporalMemory(memory_store)\n",
    "    temporal_memory = TemporalMemory(memory_store)\n    summary_service = SummaryService(memory_store)\n    memory_continuity = ContinuityService(memory_store, workspace)\n",
)
if "class MemorySummaryPayload" not in app:
    anchor="class MemoryBackfillPayload(BaseModel):\n"
    payload='''class MemorySummaryPayload(BaseModel):
    summary_type: str
    subject_type: str
    subject_id: str
    text: str
    source_chunk_ids: list[str]
    project_id: str | None = None
    world_id: str | None = None
    branch_id: str | None = None
    structured_payload: dict[str, Any] = Field(default_factory=dict)
    story_order_from: float | None = None
    story_order_to: float | None = None


class EventParticipantPayload(BaseModel):
    event_id: str
    entity_variant_id: str
    role: str = "participant"


class CausalEdgePayload(BaseModel):
    source_event_id: str
    target_event_id: str
    relation: str
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    authority: str = "accepted_event"
    status: str = "accepted"


'''
    if anchor not in app: raise RuntimeError("Memory summary payload anchor missing")
    app=app.replace(anchor,payload+anchor,1)
if '/api/memory/summaries' not in app:
    anchor='    @app.get("/api/memory/status")\n'
    routes='''    @app.post("/api/memory/summaries")
    def create_memory_summary(payload: MemorySummaryPayload):
        try:
            return summary_service.create(**(payload.model_dump() if hasattr(payload,"model_dump") else payload.dict()))
        except KeyError as exc:
            raise HTTPException(400, f"Unknown evidence chunk: {exc}") from exc

    @app.get("/api/memory/summaries")
    def list_memory_summaries(world_id: str | None = Query(None), branch_id: str | None = Query(None),
                              subject_type: str | None = Query(None), subject_id: str | None = Query(None),
                              status: str = Query("active"), limit: int = Query(100)):
        return {"items":memory_store.list_summaries(world_id=world_id,branch_id=branch_id,subject_type=subject_type,subject_id=subject_id,status=status,limit=limit)}

    @app.post("/api/memory/events/participants")
    def add_memory_event_participant(payload: EventParticipantPayload):
        memory_store.add_event_participant(payload.event_id,payload.entity_variant_id,payload.role)
        return {"ok":True}

    @app.post("/api/memory/events/causal")
    def add_memory_causal_edge(payload: CausalEdgePayload):
        return memory_store.add_causal_edge(**(payload.model_dump() if hasattr(payload,"model_dump") else payload.dict()))

    @app.get("/api/memory/events/causal")
    def list_memory_causal_edges(event_id: str | None = Query(None), direction: str = Query("both")):
        return {"items":memory_store.causal_edges(event_id,direction=direction)}

    @app.get("/api/memory/continuity")
    def memory_continuity_report(world_id: str, branch_id: str | None = Query(None), story_order: float | None = Query(None)):
        return memory_continuity.check(world_id=world_id,branch_id=branch_id,story_order=story_order)

'''
    if anchor not in app: raise RuntimeError("Memory route insertion anchor missing")
    app=app.replace(anchor,routes+anchor,1)
app_path.write_text(app,encoding="utf-8")

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
test_path=ROOT/"tests/memory/test_summaries_causal_continuity.py"
if not test_path.exists():
    test_path.write_text('''from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.memory import ContinuityService, MemoryStore, SummaryService


class StubWorkspace:
    def list_conflicts(self, **kwargs): return []


class SummaryCausalContinuityTests(unittest.TestCase):
    def test_summary_invalidation_and_causal_edges(self):
        with tempfile.TemporaryDirectory() as td:
            store=MemoryStore(Path(td)/"memory.db")
            chunk=store.upsert_chunk(source_type="document",source_id="D",source_revision="1",text="Fano left because the Order threatened Vian.",world_id="W",branch_id="B")
            summary=SummaryService(store).create(summary_type="scene",subject_type="entity_family",subject_id="FANO",text="Fano left to protect Vian.",source_chunk_ids=[chunk["id"]],world_id="W",branch_id="B")
            self.assertEqual(summary["status"],"active")
            store.upsert_chunk(source_type="document",source_id="D",source_revision="2",text="The source was corrected.",world_id="W",branch_id="B")
            self.assertEqual(store.get_summary(summary["id"])["status"],"stale")
            edge=store.add_causal_edge("E1","E2","motivated")
            self.assertEqual(store.causal_edges("E1")[0]["relation"],edge["relation"])

    def test_continuity_flags_multiple_temporary_placements(self):
        with tempfile.TemporaryDirectory() as td:
            store=MemoryStore(Path(td)/"memory.db")
            for target in ("DESK","BAG"):
                store.create_spatial_edge(world_id="W",branch_id="B",subject_type="entity_family",subject_id="LAPTOP",relation="inside",object_type="entity_family",object_id=target,structural=False)
            report=ContinuityService(store,StubWorkspace()).check(world_id="W",branch_id="B")
            self.assertTrue(any(item["kind"]=="multiple_current_placements" for item in report["issues"]))


if __name__=="__main__": unittest.main()
''',encoding="utf-8")

print("Extended causal, summary, stale propagation and deterministic continuity indexes")
