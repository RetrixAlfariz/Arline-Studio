from __future__ import annotations

from pathlib import Path
from textwrap import dedent
import re

ROOT=Path(__file__).resolve().parents[1]
def read(path): return (ROOT/path).read_text(encoding="utf-8")
def write(path,text):
    target=ROOT/path; target.parent.mkdir(parents=True,exist_ok=True); target.write_text(text.rstrip()+"\n",encoding="utf-8")

write("src/memory/time.py",dedent(r'''
from __future__ import annotations

from datetime import datetime
from typing import Any


def world_time_key(value: Any) -> tuple | None:
    """Return a comparable key for common fictional/world-time encodings.

    Arline stores the original JSON. This helper only supplies deterministic
    ordering where the user provided a comparable representation. Unknown or
    intentionally vague time remains incomparable instead of being guessed.
    """
    if value is None: return None
    if isinstance(value,(int,float)): return (0,float(value))
    if isinstance(value,str):
        text=value.strip()
        if not text: return None
        try: return (1,datetime.fromisoformat(text.replace("Z","+00:00")).timestamp())
        except ValueError:
            try: return (0,float(text))
            except ValueError: return None
    if not isinstance(value,dict): return None
    if isinstance(value.get("order"),(int,float)): return (0,float(value["order"]))
    if value.get("timestamp") is not None: return world_time_key(value["timestamp"])
    if isinstance(value.get("year"),(int,float)):
        return (
            2,
            str(value.get("calendar") or "default"),
            float(value["year"]),
            int(value.get("month") or 0),
            int(value.get("day") or 0),
            int(value.get("hour") or 0),
            int(value.get("minute") or 0),
            float(value.get("second") or 0),
        )
    return None


def compare_world_time(left: Any, right: Any) -> int | None:
    lkey=world_time_key(left); rkey=world_time_key(right)
    if lkey is None or rkey is None or lkey[0] != rkey[0]: return None
    if lkey < rkey: return -1
    if lkey > rkey: return 1
    return 0


def world_time_visible(candidate: Any, upper_bound: Any) -> bool | None:
    comparison=compare_world_time(candidate,upper_bound)
    return None if comparison is None else comparison <= 0
'''))

# Model carries original world time on every candidate.
path="src/memory/models.py"; text=read(path)
if "    world_time: dict[str, Any] | str | float | None = None" not in text:
    anchor="    story_order: float | None = None\n    semantic_class: str = \"evidence\""
    replacement="    story_order: float | None = None\n    world_time: dict[str, Any] | str | float | None = None\n    semantic_class: str = \"evidence\""
    if anchor not in text: raise RuntimeError("MemoryCandidate story_order anchor missing")
    text=text.replace(anchor,replacement,1)
write(path,text)

# Temporal-aware scope gate.
path="src/memory/scope.py"; text=read(path)
if "from .time import world_time_visible" not in text:
    text=text.replace("from .models import ContextLens, GateDecision, MemoryCandidate, MemoryQueryContext","from .models import ContextLens, GateDecision, MemoryCandidate, MemoryQueryContext\nfrom .time import world_time_visible")
    branch_anchor='            cutoff = rule.get("max_story_order")\n            if cutoff is not None and candidate.story_order is not None and candidate.story_order > cutoff:\n                return GateDecision(False, "ancestor evidence occurs after the fork cutoff")'
    branch_replacement=branch_anchor+'\n            world_cutoff=rule.get("max_world_time")\n            if world_cutoff is not None and candidate.world_time is not None and world_time_visible(candidate.world_time,world_cutoff) is False:\n                return GateDecision(False, "ancestor evidence occurs after the world-time fork cutoff")'
    if branch_anchor not in text: raise RuntimeError("ScopeGate branch cutoff anchor missing")
    text=text.replace(branch_anchor,branch_replacement,1)
    future_anchor='        if (\n            scope.context_lens in {ContextLens.SCENE, ContextLens.POV}\n            and not scope.allow_future_author_knowledge\n            and scope.story_order is not None\n            and candidate.story_order is not None\n            and candidate.story_order > scope.story_order\n        ):\n            return GateDecision(False, "future evidence blocked by context lens")'
    future_replacement=future_anchor+'\n        if (scope.context_lens in {ContextLens.SCENE,ContextLens.POV} and not scope.allow_future_author_knowledge and scope.world_time is not None and candidate.world_time is not None and world_time_visible(candidate.world_time,scope.world_time) is False):\n            return GateDecision(False,"future world-time evidence blocked by context lens")'
    if future_anchor not in text: raise RuntimeError("ScopeGate future anchor missing")
    text=text.replace(future_anchor,future_replacement,1)
write(path,text)

# Store migrations and temporal methods.
path="src/memory/store.py"; text=read(path).replace("MEMORY_SCHEMA_VERSION = 2","MEMORY_SCHEMA_VERSION = 3")
if "max_world_time_json" not in text:
    schema_anchor="                    max_story_order REAL,\n                    fork_event_id TEXT,"
    schema_replacement="                    max_story_order REAL,\n                    max_world_time_json TEXT,\n                    fork_event_id TEXT,"
    if schema_anchor not in text: raise RuntimeError("branch_visibility schema anchor missing")
    text=text.replace(schema_anchor,schema_replacement,1)
    state_anchor="                    valid_from_order REAL,\n                    valid_to_order REAL,\n                    valid_from_event_id TEXT,"
    state_replacement="                    valid_from_order REAL,\n                    valid_to_order REAL,\n                    valid_from_world_time_json TEXT,\n                    valid_to_world_time_json TEXT,\n                    valid_from_event_id TEXT,"
    if state_anchor not in text: raise RuntimeError("state interval schema anchor missing")
    text=text.replace(state_anchor,state_replacement,1)
    spatial_anchor="                    valid_from_order REAL,\n                    valid_to_order REAL,\n                    authority TEXT NOT NULL DEFAULT 'user_accepted',"
    spatial_replacement="                    valid_from_order REAL,\n                    valid_to_order REAL,\n                    valid_from_world_time_json TEXT,\n                    valid_to_world_time_json TEXT,\n                    authority TEXT NOT NULL DEFAULT 'user_accepted',"
    text=text.replace(spatial_anchor,spatial_replacement,1)
    epi_anchor="                    valid_from_order REAL,\n                    valid_to_order REAL,\n                    source_event_id TEXT,"
    epi_replacement="                    valid_from_order REAL,\n                    valid_to_order REAL,\n                    valid_from_world_time_json TEXT,\n                    valid_to_world_time_json TEXT,\n                    source_event_id TEXT,"
    text=text.replace(epi_anchor,epi_replacement,1)
    # Existing v1.2 alpha databases need ALTERs because CREATE IF NOT EXISTS does not add columns.
    fts_anchor="            try:\n                for domain in self.FTS_DOMAINS:"
    migrations=dedent(r'''
            for table,column,definition in (
                ("branch_visibility","max_world_time_json","TEXT"),
                ("state_intervals","valid_from_world_time_json","TEXT"),
                ("state_intervals","valid_to_world_time_json","TEXT"),
                ("spatial_edges","valid_from_world_time_json","TEXT"),
                ("spatial_edges","valid_to_world_time_json","TEXT"),
                ("epistemic_intervals","valid_from_world_time_json","TEXT"),
                ("epistemic_intervals","valid_to_world_time_json","TEXT"),
            ):
                columns={row["name"] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
                if column not in columns: con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
''')
    migrations=''.join('            '+line+'\n' if line else '\n' for line in migrations.splitlines())
    if fts_anchor not in text: raise RuntimeError("MemoryStore FTS init anchor missing")
    text=text.replace(fts_anchor,migrations+fts_anchor,1)
# Candidate rows already parse world_time_json. Branch visibility parse and writes world time.
text=text.replace('"INSERT INTO branch_visibility(query_branch_id,visible_branch_id,depth,max_story_order,fork_event_id) VALUES(?,?,?,?,?)"','"INSERT INTO branch_visibility(query_branch_id,visible_branch_id,depth,max_story_order,max_world_time_json,fork_event_id) VALUES(?,?,?,?,?,?)"')
text=text.replace('(query_branch_id, row["visible_branch_id"], int(row.get("depth", 0)), row.get("max_story_order"), row.get("fork_event_id")) for row in rows','(query_branch_id, row["visible_branch_id"], int(row.get("depth", 0)), row.get("max_story_order"), dumps(row.get("max_world_time")) if row.get("max_world_time") is not None else None, row.get("fork_event_id")) for row in rows')
# Replace compact branch_visibility method with parsed variant.
old='''    def branch_visibility(self, query_branch_id: str) -> list[dict[str, Any]]:\n        with self.connection() as con:\n            rows = con.execute("SELECT * FROM branch_visibility WHERE query_branch_id=? ORDER BY depth", (query_branch_id,)).fetchall()\n        return [dict(row) for row in rows]'''
new='''    def branch_visibility(self, query_branch_id: str) -> list[dict[str, Any]]:\n        with self.connection() as con:\n            rows = con.execute("SELECT * FROM branch_visibility WHERE query_branch_id=? ORDER BY depth", (query_branch_id,)).fetchall()\n        result=[]\n        for row in rows:\n            item=dict(row); item["max_world_time"]=loads(item.pop("max_world_time_json"),None); result.append(item)\n        return result'''
if old in text: text=text.replace(old,new,1)
# State interval insert supports both time axes.
old='''                "INSERT INTO state_intervals(id,world_id,branch_id,owner_type,owner_id,state_key,value_json,valid_from_order,valid_to_order,valid_from_event_id,valid_to_event_id,source_event_id,authority) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",\n                (interval_id, data["world_id"], data.get("branch_id"), data["owner_type"], data["owner_id"], data["state_key"], dumps(data.get("value")), data.get("valid_from_order"), data.get("valid_to_order"), data.get("valid_from_event_id"), data.get("valid_to_event_id"), data.get("source_event_id"), data.get("authority", "user_accepted")),'''
new='''                "INSERT INTO state_intervals(id,world_id,branch_id,owner_type,owner_id,state_key,value_json,valid_from_order,valid_to_order,valid_from_world_time_json,valid_to_world_time_json,valid_from_event_id,valid_to_event_id,source_event_id,authority) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",\n                (interval_id, data["world_id"], data.get("branch_id"), data["owner_type"], data["owner_id"], data["state_key"], dumps(data.get("value")), data.get("valid_from_order"), data.get("valid_to_order"), dumps(data.get("valid_from_world_time")) if data.get("valid_from_world_time") is not None else None, dumps(data.get("valid_to_world_time")) if data.get("valid_to_world_time") is not None else None, data.get("valid_from_event_id"), data.get("valid_to_event_id"), data.get("source_event_id"), data.get("authority", "user_accepted")),'''
if old not in text: raise RuntimeError("state interval insert anchor missing")
text=text.replace(old,new,1)
# Insert world-time query and branch comparison before event helpers.
if "def state_at_world_time(" not in text:
    anchor="        def events_for_resources("
    methods=dedent(r'''
        def state_at_world_time(self, *, world_id: str, branch_id: str | None, owner_id: str, world_time: Any, state_key: str | None = None) -> list[dict[str, Any]]:
            from .time import compare_world_time
            sql="SELECT * FROM state_intervals WHERE world_id=? AND branch_id IS ? AND owner_id=?"; params=[world_id,branch_id,owner_id]
            if state_key: sql+=" AND state_key=?"; params.append(state_key)
            with self.connection() as con: rows=con.execute(sql,params).fetchall()
            result=[]
            for row in rows:
                item=dict(row); lower=loads(item.pop("valid_from_world_time_json"),None); upper=loads(item.pop("valid_to_world_time_json"),None)
                if lower is not None and compare_world_time(lower,world_time)==1: continue
                if upper is not None and compare_world_time(world_time,upper) not in {-1,None}: continue
                item["value"]=loads(item.pop("value_json"),None); item["valid_from_world_time"]=lower; item["valid_to_world_time"]=upper; result.append(item)
            return result

        def compare_branch_state(self, *, world_id: str, left_branch_id: str | None, right_branch_id: str | None) -> dict[str, Any]:
            def state(branch_id):
                with self.connection() as con: rows=con.execute("SELECT * FROM current_state_projection WHERE world_id=? AND branch_id IS ?",(world_id,branch_id)).fetchall()
                return {(row["owner_type"],row["owner_id"],row["state_key"]):loads(row["value_json"],None) for row in rows}
            left=state(left_branch_id); right=state(right_branch_id); keys=sorted(set(left)|set(right)); changes=[]
            for key in keys:
                if left.get(key)!=right.get(key): changes.append({"owner_type":key[0],"owner_id":key[1],"state_key":key[2],"left":left.get(key),"right":right.get(key)})
            left_threads=self.list_threads(project_id=None,world_id=world_id,branch_id=left_branch_id); right_threads=self.list_threads(project_id=None,world_id=world_id,branch_id=right_branch_id)
            return {"world_id":world_id,"left_branch_id":left_branch_id,"right_branch_id":right_branch_id,"state_changes":changes,"left_threads":left_threads,"right_threads":right_threads}

''')
    methods=''.join('    '+line+'\n' if line else '\n' for line in methods.splitlines())
    if anchor not in text: raise RuntimeError("event methods anchor missing")
    text=text.replace(anchor,methods+anchor,1)
write(path,text)

# Candidate conversion and structured event world time.
path="src/memory/retrieve.py"; text=read(path)
text=text.replace('branch_id=row.get("branch_id"), session_id=row.get("session_id"), story_order=row.get("story_order"),','branch_id=row.get("branch_id"), session_id=row.get("session_id"), story_order=row.get("story_order"), world_time=row.get("world_time"),')
text=text.replace('story_order=event.get("resolved_story_order"),authority="accepted_event"','story_order=event.get("resolved_story_order"),world_time=event.get("world_time"),authority="accepted_event"')
write(path,text)

# Temporal service world-time API.
path="src/memory/temporal.py"; text=read(path)
if "def at_world_time" not in text:
    text=text.replace('    def at(self, *, world_id, branch_id, owner_id, story_order, state_key=None):\n        return self.store.state_at(world_id=world_id, branch_id=branch_id, owner_id=owner_id, story_order=story_order, state_key=state_key)','    def at(self, *, world_id, branch_id, owner_id, story_order, state_key=None):\n        return self.store.state_at(world_id=world_id, branch_id=branch_id, owner_id=owner_id, story_order=story_order, state_key=state_key)\n\n    def at_world_time(self, *, world_id, branch_id, owner_id, world_time, state_key=None):\n        return self.store.state_at_world_time(world_id=world_id,branch_id=branch_id,owner_id=owner_id,world_time=world_time,state_key=state_key)')
write(path,text)

# Branch visibility carries fork world time.
path="src/memory/service.py"; text=read(path)
text=text.replace("        rows=[]; current=branch_id; depth=0; inherited_cutoff=None","        rows=[]; current=branch_id; depth=0; inherited_cutoff=None; inherited_world_cutoff=None")
text=text.replace('row=con.execute("SELECT id,parent_branch_id,fork_event_id,fork_story_order FROM world_branches WHERE id=?",(current,)).fetchone()','row=con.execute("SELECT id,parent_branch_id,fork_event_id,fork_story_order,fork_world_time_json FROM world_branches WHERE id=?",(current,)).fetchone()')
text=text.replace('row=con.execute("SELECT id,parent_branch_id,NULL AS fork_event_id,NULL AS fork_story_order FROM world_branches WHERE id=?",(current,)).fetchone()','row=con.execute("SELECT id,parent_branch_id,NULL AS fork_event_id,NULL AS fork_story_order,NULL AS fork_world_time_json FROM world_branches WHERE id=?",(current,)).fetchone()')
text=text.replace('rows.append({"visible_branch_id":row["id"],"depth":depth,"max_story_order":inherited_cutoff,"fork_event_id":row["fork_event_id"]})','rows.append({"visible_branch_id":row["id"],"depth":depth,"max_story_order":inherited_cutoff,"max_world_time":__import__("json").loads(row["fork_world_time_json"]) if row["fork_world_time_json"] else inherited_world_cutoff,"fork_event_id":row["fork_event_id"]})')
text=text.replace('inherited_cutoff=row["fork_story_order"] if row["fork_story_order"] is not None else inherited_cutoff','inherited_cutoff=row["fork_story_order"] if row["fork_story_order"] is not None else inherited_cutoff\n                inherited_world_cutoff=__import__("json").loads(row["fork_world_time_json"]) if row["fork_world_time_json"] else inherited_world_cutoff')
# Query accepts world_time.
text=text.replace('def query(self, query: str, *, project_id=None, world_id=None, branch_id=None, session_id=None, current_turn_id=None, story_order=None, pov_variant_id=None,','def query(self, query: str, *, project_id=None, world_id=None, branch_id=None, session_id=None, current_turn_id=None, world_time=None, story_order=None, pov_variant_id=None,')
text=text.replace('scope=MemoryQueryContext(project_id=project_id,world_id=world_id,branch_id=branch_id,session_id=session_id,current_turn_id=current_turn_id,story_order=story_order,','scope=MemoryQueryContext(project_id=project_id,world_id=world_id,branch_id=branch_id,session_id=session_id,current_turn_id=current_turn_id,world_time=world_time,story_order=story_order,')
write(path,text)

write("src/memory/analysis.py",dedent(r'''
from __future__ import annotations

import hashlib
import json
from typing import Any

from .inference import LMStudioTaskProvider, TaskProviderUnavailable
from .profiles import task_contract

SUMMARY_SCHEMA={"type":"object","properties":{"summary":{"type":"string"},"explicit_facts":{"type":"array","items":{"type":"string"}},"inferences":{"type":"array","items":{"type":"string"}},"uncertainties":{"type":"array","items":{"type":"string"}},"source_ids":{"type":"array","items":{"type":"string"}}},"required":["summary","explicit_facts","inferences","uncertainties","source_ids"],"additionalProperties":False}
ANALYSIS_SCHEMA={"type":"object","properties":{"answer":{"type":"string"},"facts":{"type":"array","items":{"type":"object"}},"inferences":{"type":"array","items":{"type":"object"}},"uncertainties":{"type":"array","items":{"type":"string"}},"source_ids":{"type":"array","items":{"type":"string"}},"abstain":{"type":"boolean"}},"required":["answer","facts","inferences","uncertainties","source_ids","abstain"],"additionalProperties":False}
EXPLANATION_SCHEMA={"type":"object","properties":{"explanation":{"type":"string"},"intentional_interpretations":{"type":"array","items":{"type":"string"}},"review_actions":{"type":"array","items":{"type":"string"}}},"required":["explanation","intentional_interpretations","review_actions"],"additionalProperties":False}

class MemoryAnalysisService:
    def __init__(self,store,task_provider: LMStudioTaskProvider|None): self.store=store; self.task_provider=task_provider
    def _provider(self):
        if not self.task_provider: raise TaskProviderUnavailable("No LM Studio generative model configured")
        return self.task_provider

    def propose_summary(self, *, chunk_ids: list[str], summary_type: str, subject_type: str, subject_id: str, scope: dict[str,Any]) -> dict[str,Any]:
        chunks=[self.store.get_chunk(item) for item in chunk_ids]; evidence_hash=hashlib.sha256("|".join(item["checksum"] for item in chunks).encode()).hexdigest()
        prompt=json.dumps({"instruction":"Summarize only supplied evidence. Separate explicit facts from inference. Preserve uncertainty.","evidence":[{"id":item["id"],"text":item["text"]} for item in chunks]},ensure_ascii=False)
        output=self._provider().run(task_contract("memory_summarizer"),system_contract="Create an evidence-linked derived summary. Never invent events or treat the summary as canon.",user_content=prompt,response_schema=SUMMARY_SCHEMA,max_tokens=3072)
        structured=output["structured"]
        proposal=self.store.create_proposal(proposal_type="summary",payload={"summary_type":summary_type,"subject_type":subject_type,"subject_id":subject_id,"text":structured["summary"],"structured":{"explicit_facts":structured["explicit_facts"],"inferences":structured["inferences"],"uncertainties":structured["uncertainties"]},"evidence_chunk_ids":chunk_ids,"evidence_hash":evidence_hash,"start_order":min((item.get("story_order") for item in chunks if item.get("story_order") is not None),default=None),"end_order":max((item.get("story_order") for item in chunks if item.get("story_order") is not None),default=None)},scope=scope,source_type="memory_chunks",source_id=subject_id,source_text="\n\n".join(item["text"] for item in chunks),evidence=[{"chunk_id":item["id"]} for item in chunks],confidence=1.0,validation={"schema":"memory_summary_v1"})
        return {"proposal":proposal,"model":output["model"],"usage":output["usage"]}

    def analyze(self, *, query: str, retrieval: dict[str,Any]) -> dict[str,Any]:
        evidence=[{"id":item["id"],"source":f"{item['source_type']}:{item['source_id']}","text":item["text"],"authority":item["authority"]} for item in retrieval.get("selected") or []]
        prompt=json.dumps({"query":query,"evidence":evidence,"excluded":retrieval.get("excluded") or []},ensure_ascii=False)
        return self._provider().run(task_contract("evidence_analyst"),system_contract="Answer only from supplied admitted evidence. Separate facts from inference, preserve uncertainty, cite source IDs, and abstain on unsupported premises.",user_content=prompt,response_schema=ANALYSIS_SCHEMA,max_tokens=4096)

    def explain_continuity(self, *, issue: dict[str,Any], supporting_context: dict[str,Any]) -> dict[str,Any]:
        prompt=json.dumps({"issue":issue,"supporting_context":supporting_context},ensure_ascii=False)
        return self._provider().run(task_contract("continuity_explainer"),system_contract="Explain this deterministic issue. You do not decide whether it exists and you may not change canon. Include plausible intentional interpretations and review actions.",user_content=prompt,response_schema=EXPLANATION_SCHEMA,max_tokens=2048)
'''))

# Service analysis and branch compare.
path="src/memory/service.py"; text=read(path)
if "MemoryAnalysisService" not in text:
    text=text.replace("from .config import MemorySettings","from .analysis import MemoryAnalysisService\nfrom .config import MemorySettings")
    text=text.replace("        self.retcon=RetconImpactService(database_path,self.store)","        self.retcon=RetconImpactService(database_path,self.store)\n        self.analysis=MemoryAnalysisService(self.store,self.task_provider)")
    text=text.replace("    def continuity(self, **scope): return self.continuity_checker.check(**scope)","    def continuity(self, **scope): return self.continuity_checker.check(**scope)\n    def compare_branches(self, **scope): return self.store.compare_branch_state(**scope)")
write(path,text)

# Web payloads/routes.
path="src/memory/web.py"; text=read(path)
if "class WorldTimeStatePayload" not in text:
    anchor="\ndef register_memory_routes(app: FastAPI, service) -> None:"
    classes=dedent(r'''

class WorldTimeStatePayload(BaseModel):
    world_id: str
    owner_id: str
    world_time: Any
    branch_id: str | None = None
    state_key: str | None = None

class SummaryProposalPayload(BaseModel):
    chunk_ids: list[str]
    summary_type: str
    subject_type: str
    subject_id: str
    project_id: str | None = None
    world_id: str | None = None
    branch_id: str | None = None

class EvidenceAnalysisPayload(BaseModel):
    query: str
    retrieval_run_id: str | None = None
    retrieval: dict[str,Any] | None = None

class ContinuityExplanationPayload(BaseModel):
    issue: dict[str,Any]
    supporting_context: dict[str,Any] = Field(default_factory=dict)

class BranchComparePayload(BaseModel):
    world_id: str
    left_branch_id: str | None = None
    right_branch_id: str | None = None
''')
    if anchor not in text: raise RuntimeError("web register anchor missing")
    text=text.replace(anchor,classes+anchor,1)
# MemoryQueryPayload world_time.
if "    world_time: Any = None" not in text:
    text=text.replace("    story_order: float | None = None\n    pov_variant_id", "    world_time: Any = None\n    story_order: float | None = None\n    pov_variant_id",1)
    routes=dedent(r'''

    @app.post("/api/memory/state/world-time")
    def get_world_time_state(payload: WorldTimeStatePayload): return {"state":service.temporal.at_world_time(**payload.model_dump())}

    @app.post("/api/memory/summaries/propose")
    def propose_summary(payload: SummaryProposalPayload):
        scope={"project_id":payload.project_id,"world_id":payload.world_id,"branch_id":payload.branch_id}
        try: return service.analysis.propose_summary(chunk_ids=payload.chunk_ids,summary_type=payload.summary_type,subject_type=payload.subject_type,subject_id=payload.subject_id,scope=scope)
        except Exception as exc: raise HTTPException(status_code=400,detail=str(exc)) from exc

    @app.post("/api/memory/analyze")
    def analyze_memory(payload: EvidenceAnalysisPayload):
        try:
            retrieval=payload.retrieval or (service.store.get_retrieval(payload.retrieval_run_id) if payload.retrieval_run_id else service.query(payload.query))
            return service.analysis.analyze(query=payload.query,retrieval=retrieval)
        except Exception as exc: raise HTTPException(status_code=400,detail=str(exc)) from exc

    @app.post("/api/memory/continuity/explain")
    def explain_continuity(payload: ContinuityExplanationPayload):
        try: return service.analysis.explain_continuity(issue=payload.issue,supporting_context=payload.supporting_context)
        except Exception as exc: raise HTTPException(status_code=400,detail=str(exc)) from exc

    @app.post("/api/memory/branches/compare")
    def compare_memory_branches(payload: BranchComparePayload): return service.compare_branches(**payload.model_dump())
''')
    text=text.rstrip()+routes+"\n"
write(path,text)

# Exports.
path="src/memory/__init__.py"; text=read(path)
if "MemoryAnalysisService" not in text:
    text="from .analysis import MemoryAnalysisService\nfrom .time import compare_world_time, world_time_key, world_time_visible\n"+text
    text=text.replace('"MemoryCandidate",','"MemoryAnalysisService","MemoryCandidate",')
    text=text.replace('"register_memory_routes",','"compare_world_time","register_memory_routes","world_time_key","world_time_visible",')
write(path,text)

# Entity Memory section grows beyond spatial links.
path="src/interface/web/static/js/memory.js"; text=read(path)
if "mountEntityMemorySections" not in text:
    insertion=dedent(r'''

  async function mountEntityMemorySections({ resourceType, resourceId, label, worldId = null, branchId = null }) {
    const body=document.getElementById("sheetBody"); if(!body||!resourceId) return;
    body.querySelector("[data-memory-entity]")?.remove();
    const section=document.createElement("section"); section.className="sheet-section"; section.dataset.memoryEntity="1";
    section.innerHTML=`<div class="sheet-section-head"><h3>Memory</h3><button class="tiny-btn" data-memory-refresh>Refresh</button></div><div class="memory-entity-grid"><div><b>Evidence</b><div data-memory-evidence class="empty-note">Loading…</div></div><div><b>Events</b><div data-memory-events class="empty-note">Loading…</div></div><div><b>Open threads</b><div data-memory-threads class="empty-note">Loading…</div></div></div>`;
    body.appendChild(section);
    const refresh=async()=>{
      const query=encodeURIComponent(label||resourceId);
      const [memory,events,threads]=await Promise.all([
        api("/api/memory/query",{method:"POST",body:{query,world_id:worldId,branch_id:branchId,explicit_references:[{type:resourceType,id:resourceId,label}],refresh:false}}).catch(()=>({selected:[]})),
        api(`/api/memory/events?world_id=${encodeURIComponent(worldId||"")}&branch_id=${encodeURIComponent(branchId||"")}&resource_id=${encodeURIComponent(resourceId)}`).catch(()=>({events:[]})),
        api(`/api/memory/threads?world_id=${encodeURIComponent(worldId||"")}&branch_id=${encodeURIComponent(branchId||"")}&status=open`).catch(()=>({threads:[]})),
      ]);
      section.querySelector("[data-memory-evidence]").innerHTML=(memory.selected||[]).slice(0,6).map(item=>`<small>${esc(item.display_excerpt||item.text)}</small>`).join("")||"<small>No admitted evidence yet.</small>";
      section.querySelector("[data-memory-events]").innerHTML=(events.events||[]).slice(0,6).map(item=>`<small>${esc(item.summary||item.event_type||item.id)}</small>`).join("")||"<small>No accepted events.</small>";
      const linked=(threads.threads||[]).filter(item=>(item.links||[]).some(link=>link.resource_type===resourceType&&link.resource_id===resourceId));
      section.querySelector("[data-memory-threads]").innerHTML=linked.slice(0,6).map(item=>`<small>${esc(item.title)} · ${esc(item.status)}</small>`).join("")||"<small>No linked open threads.</small>";
    };
    section.querySelector("[data-memory-refresh]")?.addEventListener("click",refresh); await refresh();
  }
''')
    marker="  window.ArlineMemoryUI = { refreshStatus, mountSpatialSection };"
    if marker not in text: raise RuntimeError("memory UI export anchor missing")
    text=text.replace(marker,insertion+'\n  window.ArlineMemoryUI = { refreshStatus, mountSpatialSection, mountEntityMemorySections };',1)
write(path,text)

path="src/interface/web/static/arline.js"; text=read(path)
if "mountEntityMemorySections" not in text:
    spatial_call='''  window.ArlineMemoryUI?.mountSpatialSection({\n    resourceType: variant ? "entity_variant" : "entity_family",\n    resourceId: variant?.id || family.id,'''
    pos=text.find(spatial_call)
    if pos<0: raise RuntimeError("Entity spatial mount anchor missing")
    call_end=text.find("  });",pos)
    call_end=text.find("\n",call_end+4)
    extra='''  window.ArlineMemoryUI?.mountEntityMemorySections({\n    resourceType: variant ? "entity_variant" : "entity_family",\n    resourceId: variant?.id || family.id,\n    label: variant?.display_name || family.name,\n    worldId: state.activeWorld?.id || null,\n    branchId: state.activeBranch?.kind === "main" ? null : state.activeBranch?.id || null,\n  });\n'''
    text=text[:call_end+1]+extra+text[call_end+1:]
write(path,text)

path="src/interface/web/static/arline.css"; text=read(path)
if ".memory-entity-grid" not in text:
    text+='''\n.memory-entity-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.memory-entity-grid>div{display:grid;align-content:start;gap:7px;padding:10px;border:1px solid var(--border);border-radius:12px;background:var(--panel-soft)}.memory-entity-grid small{display:block;line-height:1.45;color:var(--muted)}@media(max-width:900px){.memory-entity-grid{grid-template-columns:1fr}}\n'''
write(path,text)

# Tests.
write("tests/memory/test_temporal_analysis.py",dedent(r'''
from pathlib import Path
import tempfile
import unittest

from src.memory import MemoryCandidate, MemoryQueryContext, MemoryStore, ScopeGate, compare_world_time

class TemporalAnalysisTests(unittest.TestCase):
    def test_world_time_compare_and_scope(self):
        self.assertEqual(compare_world_time({"year":2026,"month":7},{"year":2026,"month":8}),-1)
        with tempfile.TemporaryDirectory() as td:
            store=MemoryStore(Path(td)/"memory.db"); gate=ScopeGate(store)
            scope=MemoryQueryContext(world_id="W",world_time={"year":2026,"month":7})
            future=MemoryCandidate(id="x",lane="events",source_type="event",source_id="E",text="future",display_excerpt="future",world_id="W",world_time={"year":2026,"month":8})
            self.assertFalse(gate.decide(future,scope).allowed)

    def test_world_time_state_and_branch_compare(self):
        with tempfile.TemporaryDirectory() as td:
            store=MemoryStore(Path(td)/"memory.db")
            store.add_state_interval(world_id="W",branch_id=None,owner_type="entity",owner_id="V",state_key="location",value="A",valid_from_world_time={"year":2026,"month":1},valid_to_world_time={"year":2026,"month":8})
            self.assertEqual(store.state_at_world_time(world_id="W",branch_id=None,owner_id="V",world_time={"year":2026,"month":7})[0]["value"],"A")
            store.set_current_state(world_id="W",branch_id="A",owner_type="entity",owner_id="V",state_key="mood",value="calm")
            store.set_current_state(world_id="W",branch_id="B",owner_type="entity",owner_id="V",state_key="mood",value="angry")
            diff=store.compare_branch_state(world_id="W",left_branch_id="A",right_branch_id="B")
            self.assertEqual(diff["state_changes"][0]["state_key"],"mood")

if __name__ == "__main__": unittest.main()
'''))

# Bump backup-coordinated schema.
for path,old,new in (("src/workspace/store.py","WORKSPACE_SCHEMA_VERSION = 9","WORKSPACE_SCHEMA_VERSION = 10"),("src/workspace/foundation.py","SCHEMA_VERSION = 9","SCHEMA_VERSION = 10")):
    text=read(path).replace(old,new); write(path,text)

for disposable in ("tools/v12_complete_temporal_analysis.py",".github/workflows/v12-complete-temporal-analysis.yml"):
    target=ROOT/disposable
    if target.exists(): target.unlink()
