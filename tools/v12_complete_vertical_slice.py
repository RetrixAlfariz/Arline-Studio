from __future__ import annotations

from pathlib import Path
from textwrap import dedent
import re

ROOT=Path(__file__).resolve().parents[1]
def read(path): return (ROOT/path).read_text(encoding="utf-8")
def write(path,text):
    target=ROOT/path; target.parent.mkdir(parents=True,exist_ok=True); target.write_text(text.rstrip()+"\n",encoding="utf-8")

write("src/memory/profiles.py",dedent(r'''
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True, slots=True)
class TaskContract:
    id: str
    task_type: str
    context_recipe: str
    context_lens: str
    output_mode: str
    temperature: float
    reasoning: str
    allow_creative_inference: bool
    allow_cross_scope_evidence: bool = False
    may_create_proposal: bool = False
    may_commit_canon: bool = False
    evidence_required: bool = False
    multi_pass: bool = False
    output_schema: str | None = None

    def to_dict(self) -> dict[str, Any]: return asdict(self)


BUILTIN_TASK_CONTRACTS = {
    item.id: item for item in (
        TaskContract("story_writer","story","RECIPE-STORY","scene","prose",0.85,"off",True,may_create_proposal=True),
        TaskContract("dialogue_writer","dialogue","RECIPE-DIALOGUE","pov","prose",0.90,"off",True,may_create_proposal=True),
        TaskContract("structure_extractor","extract","RECIPE-EXTRACT","scene","structured",0.05,"off",False,may_create_proposal=True,evidence_required=True,output_schema="memory_proposals_v1"),
        TaskContract("memory_summarizer","summarize","RECIPE-SUMMARY","scene","structured",0.15,"off",False,evidence_required=True,output_schema="memory_summary_v1"),
        TaskContract("evidence_analyst","analysis","RECIPE-ANALYSIS","author","analysis",0.15,"optional",False,allow_cross_scope_evidence=True,evidence_required=True,multi_pass=True),
        TaskContract("continuity_explainer","explain_issue","RECIPE-CONTINUITY","scene","analysis",0.10,"off",False,evidence_required=True),
        TaskContract("branch_comparison","branch_compare","RECIPE-ANALYSIS","author","analysis",0.10,"off",False,allow_cross_scope_evidence=True,evidence_required=True),
        TaskContract("ambiguous_query_router","route","RECIPE-ANALYSIS","scene","structured",0.0,"off",False,output_schema="query_route_v1"),
    )
}


def task_contract(profile_id: str) -> TaskContract:
    return BUILTIN_TASK_CONTRACTS[profile_id]
'''))

write("src/memory/continuity.py",dedent(r'''
from __future__ import annotations

import json
import sqlite3
from typing import Any


class ContinuityChecker:
    """Deterministic issue detector; the LLM may explain, never decide issues."""

    def __init__(self, database_path, memory_store):
        self.database_path=str(database_path); self.store=memory_store

    @staticmethod
    def _loads(value):
        try: return json.loads(value) if value else None
        except (TypeError,json.JSONDecodeError): return value

    def check(self, *, project_id=None, world_id=None, branch_id=None, story_order=None, pov_variant_id=None) -> dict[str,Any]:
        issues=[]
        with sqlite3.connect(self.database_path) as con:
            con.row_factory=sqlite3.Row
            # Contradictory accepted facts with the same semantic path.
            try:
                rows=con.execute("SELECT owner_type,owner_id,path,COUNT(DISTINCT value_json) AS variants,GROUP_CONCAT(id) AS ids FROM canon_facts WHERE status IN ('canon','accepted') AND (? IS NULL OR world_id=?) AND (branch_id IS NULL OR branch_id IS ?) GROUP BY owner_type,owner_id,path HAVING variants>1",(world_id,world_id,branch_id)).fetchall()
                for row in rows: issues.append({"kind":"contradictory_facts","severity":"error","resource_type":row["owner_type"],"resource_id":row["owner_id"],"path":row["path"],"message":f"Multiple accepted values exist for {row['path']}.","sources":(row["ids"] or "").split(",")})
            except sqlite3.OperationalError: pass
            # Duplicate active spatial parents imply impossible simultaneous placement.
            rows=con.execute("SELECT subject_node_id,COUNT(*) AS parents,GROUP_CONCAT(object_node_id) AS parent_ids FROM spatial_edges WHERE relation IN ('part_of','inside','stored_in','on','under','mounted_on') AND valid_to_order IS NULL AND (? IS NULL OR world_id=?) AND (branch_id IS NULL OR branch_id IS ?) GROUP BY subject_node_id HAVING parents>1",(world_id,world_id,branch_id)).fetchall()
            for row in rows: issues.append({"kind":"multiple_spatial_parents","severity":"warning","resource_type":"spatial_node","resource_id":row["subject_node_id"],"message":"An object has multiple simultaneous active placements.","parents":(row["parent_ids"] or "").split(",")})
            # Dangling spatial references should never survive normal FK handling.
            rows=con.execute("SELECT e.id FROM spatial_edges e LEFT JOIN spatial_nodes s ON s.id=e.subject_node_id LEFT JOIN spatial_nodes o ON o.id=e.object_node_id WHERE s.id IS NULL OR o.id IS NULL").fetchall()
            for row in rows: issues.append({"kind":"dangling_spatial_edge","severity":"error","resource_type":"spatial_edge","resource_id":row["id"],"message":"Spatial edge points to a missing node."})
            # POV knowledge used before acquisition can be checked against an explicit query time.
            if pov_variant_id and story_order is not None:
                rows=con.execute("SELECT id,topic_type,topic_id,state_type,valid_from_order FROM epistemic_intervals WHERE character_variant_id=? AND world_id=? AND branch_id IS ? AND valid_from_order>?",(pov_variant_id,world_id,branch_id,story_order)).fetchall()
                for row in rows: issues.append({"kind":"future_knowledge_available","severity":"warning","resource_type":row["topic_type"],"resource_id":row["topic_id"],"message":f"{pov_variant_id} only acquires this {row['state_type']} after the active scene.","valid_from_order":row["valid_from_order"]})
        return {"issues":issues,"warning_count":sum(item["severity"]=="warning" for item in issues),"error_count":sum(item["severity"]=="error" for item in issues),"scope":{"project_id":project_id,"world_id":world_id,"branch_id":branch_id,"story_order":story_order,"pov_variant_id":pov_variant_id}}
'''))

# Add advanced methods inside MemoryStore before its status method.
path="src/memory/store.py"; text=read(path)
if "def events_for_resources(" not in text:
    anchor="    def status(self) -> dict[str, Any]:"
    methods=dedent(r'''
        def events_for_resources(self, resource_ids: list[str], *, world_id: str | None, branch_id: str | None, limit: int = 40) -> list[dict[str, Any]]:
            with self.connection() as con:
                columns={row["name"] for row in con.execute("PRAGMA table_info(timeline_events)").fetchall()}
                if not columns: return []
                order_col="story_order" if "story_order" in columns else ("order_key" if "order_key" in columns else "NULL")
                clauses=[]; params=[]
                if world_id and "world_id" in columns: clauses.append("e.world_id=?"); params.append(world_id)
                if "branch_id" in columns: clauses.append("(e.branch_id IS NULL OR e.branch_id IS ?)"); params.append(branch_id)
                statuses=[]
                if "status" in columns: clauses.append("e.status IN ('accepted','canon','what_if')")
                if resource_ids:
                    placeholders=','.join('?' for _ in resource_ids)
                    owner_clause=f"e.owner_id IN ({placeholders})" if "owner_id" in columns else "0"
                    participant_clause=f"EXISTS(SELECT 1 FROM event_participants p WHERE p.event_id=e.id AND p.entity_variant_id IN ({placeholders}))"
                    clauses.append(f"({owner_clause} OR {participant_clause})"); params.extend(resource_ids); params.extend(resource_ids)
                where=" AND ".join(clauses) if clauses else "1=1"
                rows=con.execute(f"SELECT e.*,{order_col} AS resolved_story_order FROM timeline_events e WHERE {where} ORDER BY resolved_story_order DESC LIMIT ?",params+[limit]).fetchall()
            result=[]
            for row in rows:
                item=dict(row)
                for key in ("state_patch_json","world_time_json","participants_json","causal_links_json"):
                    if key in item: item[key[:-5] if key.endswith('_json') else key]=loads(item.pop(key),{} if key=='state_patch_json' else [])
                result.append(item)
            return result

        def causal_chain(self, event_ids: list[str], *, branch_id: str | None = None, limit: int = 40) -> list[dict[str, Any]]:
            if not event_ids: return []
            placeholders=','.join('?' for _ in event_ids)
            params=event_ids+event_ids
            sql=f"SELECT * FROM causal_edges WHERE status='accepted' AND (source_event_id IN ({placeholders}) OR target_event_id IN ({placeholders}))"
            if branch_id is not None: sql += " AND (branch_id IS NULL OR branch_id=?)"; params.append(branch_id)
            sql += " LIMIT ?"; params.append(limit)
            with self.connection() as con: rows=con.execute(sql,params).fetchall()
            return [dict(row) for row in rows]

        def add_event_participant(self, event_id: str, entity_variant_id: str, role: str = "participant") -> None:
            with self._lock,self.connection() as con: con.execute("INSERT OR REPLACE INTO event_participants(event_id,entity_variant_id,role) VALUES(?,?,?)",(event_id,entity_variant_id,role))

        def add_causal_edge(self, source_event_id: str, relation: str, target_event_id: str, *, confidence: float = 1.0, branch_id: str | None = None, source_id: str | None = None) -> None:
            with self._lock,self.connection() as con: con.execute("INSERT OR REPLACE INTO causal_edges(source_event_id,relation,target_event_id,confidence,status,branch_id,source_id) VALUES(?,?,?,?,?,?,?)",(source_event_id,relation,target_event_id,float(confidence),"accepted",branch_id,source_id))

        def create_summary(self, *, summary_type: str, subject_type: str, subject_id: str, text: str, evidence_chunk_ids: list[str], evidence_hash: str, project_id: str | None = None, world_id: str | None = None, branch_id: str | None = None, start_order: float | None = None, end_order: float | None = None, structured: dict[str, Any] | None = None) -> dict[str, Any]:
            summary_id=make_id("SUMMARY"); timestamp=now()
            with self._lock,self.connection() as con:
                con.execute("INSERT INTO memory_summaries(id,summary_type,subject_type,subject_id,project_id,world_id,branch_id,start_order,end_order,text,structured_json,evidence_hash,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(summary_id,summary_type,subject_type,subject_id,project_id,world_id,branch_id,start_order,end_order,text,dumps(structured or {}),evidence_hash,"active",timestamp,timestamp))
                con.executemany("INSERT OR IGNORE INTO memory_summary_sources(summary_id,memory_chunk_id) VALUES(?,?)",[(summary_id,item) for item in evidence_chunk_ids])
            checksum=__import__('hashlib').sha256(text.encode('utf-8')).hexdigest()
            self.upsert_chunk({"id":f"MEM-SUMMARY-{summary_id}","source_type":"derived_summary","source_id":summary_id,"source_revision":evidence_hash,"project_id":project_id,"world_id":world_id,"branch_id":branch_id,"story_order":end_order,"semantic_class":"summary","authority":"derived_summary","trust_level":"generated","text":text,"retrieval_text":text,"display_excerpt":text[:500],"checksum":checksum,"metadata":{"summary_type":summary_type,"subject_type":subject_type,"subject_id":subject_id,"evidence_chunk_ids":evidence_chunk_ids}},domain="summary")
            return self.get_summary(summary_id)

        def get_summary(self, summary_id: str) -> dict[str, Any]:
            with self.connection() as con:
                row=con.execute("SELECT * FROM memory_summaries WHERE id=?",(summary_id,)).fetchone(); sources=con.execute("SELECT memory_chunk_id FROM memory_summary_sources WHERE summary_id=?",(summary_id,)).fetchall()
            if row is None: raise KeyError(summary_id)
            item=dict(row); item["structured"]=loads(item.pop("structured_json"),{}); item["evidence_chunk_ids"]=[source[0] for source in sources]; return item

        def list_summaries(self, *, project_id: str | None, world_id: str | None, branch_id: str | None, subject_ids: list[str] | None = None, limit: int = 30) -> list[dict[str, Any]]:
            sql="SELECT id FROM memory_summaries WHERE status='active' AND (project_id IS NULL OR project_id=?) AND (world_id IS NULL OR world_id=?) AND (branch_id IS NULL OR branch_id IS ?)"; params=[project_id,world_id,branch_id]
            if subject_ids:
                placeholders=','.join('?' for _ in subject_ids); sql+=f" AND subject_id IN ({placeholders})"; params.extend(subject_ids)
            sql+=" ORDER BY updated_at DESC LIMIT ?"; params.append(limit)
            with self.connection() as con: ids=[row[0] for row in con.execute(sql,params).fetchall()]
            return [self.get_summary(item) for item in ids]

        def invalidate_summaries_for_chunk(self, chunk_id: str) -> int:
            with self._lock,self.connection() as con:
                cur=con.execute("UPDATE memory_summaries SET status='stale',updated_at=? WHERE id IN (SELECT summary_id FROM memory_summary_sources WHERE memory_chunk_id=?) AND status='active'",(now(),chunk_id))
                con.execute("UPDATE memory_chunks SET semantic_status='stale',updated_at=? WHERE source_type='derived_summary' AND source_id IN (SELECT summary_id FROM memory_summary_sources WHERE memory_chunk_id=?)",(now(),chunk_id))
                return cur.rowcount

        def update_chunk_admission(self, chunk_id: str, *, semantic_status: str | None = None, trust_level: str | None = None, authority: str | None = None) -> dict[str, Any]:
            fields=[]; params=[]
            for key,value in (("semantic_status",semantic_status),("trust_level",trust_level),("authority",authority)):
                if value is not None: fields.append(f"{key}=?"); params.append(value)
            if fields:
                fields.append("updated_at=?"); params.extend([now(),chunk_id])
                with self._lock,self.connection() as con: con.execute(f"UPDATE memory_chunks SET {','.join(fields)} WHERE id=?",params)
            return self.get_chunk(chunk_id)

        def list_quarantine(self, limit: int = 100) -> list[dict[str, Any]]:
            with self.connection() as con: rows=con.execute("SELECT * FROM memory_chunks WHERE trust_level='quarantined' OR semantic_status='quarantined' ORDER BY updated_at DESC LIMIT ?",(limit,)).fetchall()
            return [self._row(row) for row in rows]

        def rebuild_current_state_from_events(self, *, world_id: str, branch_id: str | None = None) -> dict[str, int]:
            events=self.events_for_resources([],world_id=world_id,branch_id=branch_id,limit=100000); applied=0; skipped=0
            for event in reversed(events):
                patch=event.get("state_patch") or {}; owner_id=event.get("owner_id"); owner_type=event.get("owner_type") or "entity_variant"
                if not owner_id or not isinstance(patch,dict): skipped+=1; continue
                for key,value in patch.items():
                    self.set_current_state(world_id=world_id,branch_id=branch_id,owner_type=owner_type,owner_id=owner_id,state_key=key,value=value,source_event_id=event.get("id"),authority="accepted_event")
                    applied+=1
            return {"events":len(events),"state_values":applied,"skipped":skipped}

''')
    if anchor not in text: raise RuntimeError("MemoryStore status anchor missing")
    # dedent placed methods at column zero; indent into class.
    methods=''.join('    '+line+'\n' if line else '\n' for line in methods.splitlines())
    text=text.replace(anchor,methods+anchor,1)
write(path,text)

# Advanced structured retrieval lanes.
path="src/memory/retrieve.py"; text=read(path)
if 'source_type="timeline_event"' not in text:
    anchor="        if plan.route.value == \"THREAD_LOOKUP\":"
    block=dedent(r'''
        if plan.route.value in {"EVENT_LOOKUP","WHY_CAUSAL","CONTINUITY_CHECK"}:
            resource_ids=[item.get("id") for item in resources if item.get("id")]
            events=self.store.events_for_resources(resource_ids,world_id=scope.world_id,branch_id=scope.branch_id,limit=plan.per_lane_budget)
            for index,event in enumerate(events,1):
                summary=event.get("summary") or event.get("event_type") or event.get("id")
                result.append(MemoryCandidate(id=f"event:{event['id']}",lane="events",source_type="timeline_event",source_id=event["id"],text=f"{event.get('event_type','event')}: {summary}",display_excerpt=summary,project_id=event.get("project_id"),world_id=event.get("world_id"),branch_id=event.get("branch_id"),story_order=event.get("resolved_story_order"),authority="accepted_event",source_rank=index,metadata={"structured":True,"event":event}))
            if plan.route.value == "WHY_CAUSAL":
                edges=self.store.causal_chain([event["id"] for event in events],branch_id=scope.branch_id,limit=plan.per_lane_budget)
                for index,edge in enumerate(edges,1):
                    result.append(MemoryCandidate(id=f"causal:{edge['source_event_id']}:{edge['relation']}:{edge['target_event_id']}",lane="causal",source_type="causal_edge",source_id=edge.get("source_id") or edge["source_event_id"],text=f"{edge['source_event_id']} --{edge['relation']}→ {edge['target_event_id']}",display_excerpt=f"{edge['relation']}: {edge['source_event_id']} → {edge['target_event_id']}",world_id=scope.world_id,branch_id=edge.get("branch_id"),authority="accepted_event",source_rank=index,metadata={"structured":True,"causal_edge":edge}))
        if plan.route.value == "GLOBAL_SUMMARY":
            summaries=self.store.list_summaries(project_id=scope.project_id,world_id=scope.world_id,branch_id=scope.branch_id,subject_ids=[item.get("id") for item in resources if item.get("id")],limit=plan.per_lane_budget)
            for index,summary in enumerate(summaries,1):
                result.append(MemoryCandidate(id=f"summary:{summary['id']}",lane="summaries",source_type="derived_summary",source_id=summary["id"],text=summary["text"],display_excerpt=summary["text"][:500],project_id=summary.get("project_id"),world_id=summary.get("world_id"),branch_id=summary.get("branch_id"),story_order=summary.get("end_order"),authority="derived_summary",trust_level="generated",source_rank=index,metadata={"structured":True,"summary":summary}))
''')
    block=''.join('        '+line+'\n' if line else '\n' for line in block.splitlines())
    if anchor not in text: raise RuntimeError("Retriever thread anchor missing")
    text=text.replace(anchor,block+anchor,1)
write(path,text)

# Service extensions.
path="src/memory/service.py"; text=read(path)
if "ContinuityChecker" not in text:
    text=text.replace("from .config import MemorySettings","from .config import MemorySettings\nfrom .continuity import ContinuityChecker")
    text=text.replace("from .spatial import SpatialService","from .spatial import SpatialService\nfrom .profiles import BUILTIN_TASK_CONTRACTS")
    text=text.replace("        self.spatial=SpatialService(self.store)","        self.spatial=SpatialService(self.store)\n        self.continuity_checker=ContinuityChecker(database_path,self.store)")
    text=text.replace("    def status(self): return {","    def continuity(self, **scope): return self.continuity_checker.check(**scope)\n    def task_contracts(self): return {key:value.to_dict() for key,value in BUILTIN_TASK_CONTRACTS.items()}\n    def status(self): return {")
    text=text.replace('"store":self.store.status()}','"task_contracts":self.task_contracts(),"store":self.store.status()}')
write(path,text)

# Web API additions.
path="src/memory/web.py"; text=read(path)
if "class SummaryPayload" not in text:
    class_anchor="\ndef register_memory_routes(app: FastAPI, service) -> None:"
    classes=dedent(r'''

class SummaryPayload(BaseModel):
    summary_type: str
    subject_type: str
    subject_id: str
    text: str
    evidence_chunk_ids: list[str] = Field(default_factory=list)
    evidence_hash: str
    project_id: str | None = None
    world_id: str | None = None
    branch_id: str | None = None
    start_order: float | None = None
    end_order: float | None = None
    structured: dict[str,Any] = Field(default_factory=dict)


class CausalEdgePayload(BaseModel):
    source_event_id: str
    relation: str
    target_event_id: str
    confidence: float = 1.0
    branch_id: str | None = None
    source_id: str | None = None


class AdmissionPayload(BaseModel):
    semantic_status: str | None = None
    trust_level: str | None = None
    authority: str | None = None
''')
    if class_anchor not in text: raise RuntimeError("memory web register anchor missing")
    text=text.replace(class_anchor,classes+class_anchor,1)
    routes=dedent(r'''

    @app.get("/api/memory/profiles")
    def memory_profiles(): return {"profiles":service.task_contracts()}

    @app.get("/api/memory/events")
    def memory_events(world_id: str|None=None,branch_id: str|None=None,resource_id: list[str]=Query(default=[]),limit: int=40): return {"events":service.store.events_for_resources(resource_id,world_id=world_id,branch_id=branch_id,limit=min(max(limit,1),500))}

    @app.post("/api/memory/causal")
    def create_causal_edge(payload: CausalEdgePayload): service.store.add_causal_edge(**payload.model_dump()); return {"ok":True}

    @app.post("/api/memory/summaries")
    def create_summary(payload: SummaryPayload): return service.store.create_summary(**payload.model_dump())

    @app.get("/api/memory/summaries")
    def list_summaries(project_id: str|None=None,world_id: str|None=None,branch_id: str|None=None,subject_id: list[str]=Query(default=[]),limit: int=30): return {"summaries":service.store.list_summaries(project_id=project_id,world_id=world_id,branch_id=branch_id,subject_ids=subject_id or None,limit=min(max(limit,1),200))}

    @app.post("/api/memory/state/rebuild")
    def rebuild_state(world_id: str,branch_id: str|None=None): return service.store.rebuild_current_state_from_events(world_id=world_id,branch_id=branch_id)

    @app.get("/api/memory/continuity")
    def memory_continuity(project_id: str|None=None,world_id: str|None=None,branch_id: str|None=None,story_order: float|None=None,pov_variant_id: str|None=None): return service.continuity(project_id=project_id,world_id=world_id,branch_id=branch_id,story_order=story_order,pov_variant_id=pov_variant_id)

    @app.get("/api/memory/quarantine")
    def memory_quarantine(limit: int=100): return {"chunks":service.store.list_quarantine(limit=min(max(limit,1),500))}

    @app.patch("/api/memory/chunks/{chunk_id}/admission")
    def update_admission(chunk_id: str,payload: AdmissionPayload):
        try: return service.store.update_chunk_admission(chunk_id,**payload.model_dump())
        except KeyError as exc: raise HTTPException(status_code=404,detail="Memory chunk not found") from exc
''')
    # register_memory_routes occupies the rest of the file; append indented routes.
    text=text.rstrip()+routes+"\n"
write(path,text)

# Package exports.
path="src/memory/__init__.py"; text=read(path)
if "ContinuityChecker" not in text:
    text="from .continuity import ContinuityChecker\nfrom .profiles import BUILTIN_TASK_CONTRACTS, TaskContract, task_contract\n"+text
    text=text.replace('"ContextLens",','"BUILTIN_TASK_CONTRACTS","ContinuityChecker","ContextLens",')
    text=text.replace('"TemporalStateService","register_memory_routes",','"TaskContract","TemporalStateService","register_memory_routes","task_contract",')
write(path,text)

# Tests.
write("tests/memory/test_v12_vertical_slice.py",dedent(r'''
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest

from src.memory import MemoryStore
from src.memory.continuity import ContinuityChecker
from src.memory.profiles import BUILTIN_TASK_CONTRACTS

class V12VerticalSliceTests(unittest.TestCase):
    def test_profiles_never_commit_canon(self):
        self.assertTrue(BUILTIN_TASK_CONTRACTS)
        self.assertTrue(all(not profile.may_commit_canon for profile in BUILTIN_TASK_CONTRACTS.values()))

    def test_summary_invalidation_quarantine_and_causality(self):
        with tempfile.TemporaryDirectory() as td:
            store=MemoryStore(Path(td)/"memory.db")
            chunk=store.upsert_chunk({"source_type":"document","source_id":"D","source_revision":"1","text":"Fano left voluntarily.","checksum":"x"},domain="manuscript")
            summary=store.create_summary(summary_type="scene",subject_type="entity_family",subject_id="FANO",text="Fano left.",evidence_chunk_ids=[chunk["id"]],evidence_hash="h")
            self.assertEqual(summary["status"],"active")
            self.assertEqual(store.invalidate_summaries_for_chunk(chunk["id"]),1)
            store.update_chunk_admission(chunk["id"],trust_level="quarantined")
            self.assertEqual(store.list_quarantine()[0]["id"],chunk["id"])
            store.add_causal_edge("E1","motivated","E2")
            self.assertEqual(store.causal_chain(["E1"])[0]["relation"],"motivated")

    def test_continuity_detects_multiple_active_placements(self):
        with tempfile.TemporaryDirectory() as td:
            db=Path(td)/"memory.db"; store=MemoryStore(db)
            a=store.ensure_spatial_node(resource_type=None,resource_id=None,label="Item",spatial_kind="item",world_id="W",branch_id=None)
            b=store.ensure_spatial_node(resource_type=None,resource_id=None,label="Room A",spatial_kind="room",world_id="W",branch_id=None)
            c=store.ensure_spatial_node(resource_type=None,resource_id=None,label="Room B",spatial_kind="room",world_id="W",branch_id=None)
            store.add_spatial_edge(subject_node_id=a["id"],relation="inside",object_node_id=b["id"],world_id="W",branch_id=None)
            store.add_spatial_edge(subject_node_id=a["id"],relation="inside",object_node_id=c["id"],world_id="W",branch_id=None)
            report=ContinuityChecker(db,store).check(world_id="W",branch_id=None)
            self.assertTrue(any(item["kind"]=="multiple_spatial_parents" for item in report["issues"]))

if __name__ == "__main__": unittest.main()
'''))

# Remove this one-shot implementation job.
for disposable in ("tools/v12_complete_vertical_slice.py",".github/workflows/v12-complete-vertical-slice.yml"):
    target=ROOT/disposable
    if target.exists(): target.unlink()
