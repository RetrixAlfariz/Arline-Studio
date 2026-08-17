from __future__ import annotations

from pathlib import Path
from textwrap import dedent
import re

ROOT=Path(__file__).resolve().parents[1]
def read(path): return (ROOT/path).read_text(encoding="utf-8")
def write(path,text):
    target=ROOT/path; target.parent.mkdir(parents=True,exist_ok=True); target.write_text(text.rstrip()+"\n",encoding="utf-8")

write("src/memory/inference.py",dedent(r'''
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any
import httpx

from .profiles import TaskContract


class TaskProviderUnavailable(RuntimeError): pass
class StructuredTaskError(RuntimeError): pass


def _json_payload(text: str) -> Any:
    text=(text or "").strip()
    fence=re.search(r"```(?:json)?\s*(.*?)```",text,re.S|re.I)
    if fence: text=fence.group(1).strip()
    start=min([pos for pos in (text.find("{"),text.find("[")) if pos>=0],default=0)
    try: return json.loads(text[start:])
    except json.JSONDecodeError as exc: raise StructuredTaskError(f"Model did not return valid JSON: {exc}") from exc


@dataclass(slots=True)
class LMStudioTaskProvider:
    base_url: str
    model: str
    api_key: str = ""
    timeout_seconds: float = 180.0
    client: httpx.Client | None = None

    def _url(self) -> str:
        base=self.base_url.strip().rstrip("/")
        for suffix in ("/v1","/api/v1"):
            if base.endswith(suffix): base=base[:-len(suffix)]
        return base.rstrip("/")+"/v1/chat/completions"

    def run(self, contract: TaskContract, *, system_contract: str, user_content: str, response_schema: dict[str,Any] | None = None, max_tokens: int = 4096) -> dict[str,Any]:
        payload={
            "model":self.model,
            "messages":[{"role":"system","content":system_contract},{"role":"user","content":user_content}],
            "temperature":contract.temperature,
            "max_tokens":max_tokens,
            "stream":False,
        }
        if response_schema:
            payload["response_format"]={"type":"json_schema","json_schema":{"name":contract.output_schema or "arline_output","strict":True,"schema":response_schema}}
        headers={"Content-Type":"application/json"}
        if self.api_key: headers["Authorization"]=f"Bearer {self.api_key}"
        owns=self.client is None; client=self.client or httpx.Client(timeout=self.timeout_seconds)
        try:
            response=client.post(self._url(),json=payload,headers=headers); response.raise_for_status(); raw=response.json()
            choices=raw.get("choices") or []
            if not choices: raise TaskProviderUnavailable("LM Studio returned no completion choice")
            message=choices[0].get("message") or {}; content=message.get("content") or ""
            result={"content":content,"reasoning":message.get("reasoning_content") or message.get("reasoning") or "","usage":raw.get("usage") or {},"model":raw.get("model") or self.model,"finish_reason":choices[0].get("finish_reason")}
            if response_schema: result["structured"]=_json_payload(content)
            return result
        except (httpx.HTTPError,ValueError,TypeError) as exc: raise TaskProviderUnavailable(str(exc)) from exc
        finally:
            if owns: client.close()
'''))

write("src/memory/proposals.py",dedent(r'''
from __future__ import annotations

import json
from typing import Any

from .inference import LMStudioTaskProvider, StructuredTaskError, TaskProviderUnavailable
from .profiles import task_contract


PROPOSAL_SCHEMA={
    "type":"object",
    "properties":{
        "events":{"type":"array","items":{"type":"object"}},
        "state_changes":{"type":"array","items":{"type":"object"}},
        "knowledge_changes":{"type":"array","items":{"type":"object"}},
        "belief_changes":{"type":"array","items":{"type":"object"}},
        "relationship_changes":{"type":"array","items":{"type":"object"}},
        "story_threads":{"type":"array","items":{"type":"object"}},
        "uncertainties":{"type":"array","items":{"type":"object"}},
        "unresolved_references":{"type":"array","items":{"type":"object"}},
    },
    "required":["events","state_changes","knowledge_changes","belief_changes","relationship_changes","story_threads","uncertainties","unresolved_references"],
    "additionalProperties":False,
}

SYSTEM_CONTRACT="""You are Arline's Structure Extractor. Convert only explicitly supported source text into reviewable proposals. Never invent missing details, resolve uncertainty as fact, treat hypothetical/instruction/question language as an event, or commit canon. Preserve source spans, immutable IDs, alternate interpretations, and uncertainty. Return empty arrays when the source does not support a proposal."""


class MemoryProposalService:
    TYPE_MAP={
        "events":"event","state_changes":"state_change","knowledge_changes":"knowledge_change","belief_changes":"belief_change","relationship_changes":"relationship_change","story_threads":"story_thread"
    }

    def __init__(self, store, task_provider: LMStudioTaskProvider | None = None):
        self.store=store; self.task_provider=task_provider

    @staticmethod
    def validate_payload(data: dict[str,Any]) -> list[str]:
        errors=[]
        for key in PROPOSAL_SCHEMA["required"]:
            if key not in data: errors.append(f"missing {key}")
            elif not isinstance(data[key],list): errors.append(f"{key} must be an array")
        return errors

    def extract(self, source_text: str, *, scope: dict[str,Any], resolved_resources: list[dict[str,Any]], source_type: str, source_id: str, source_span: dict[str,Any] | None = None) -> dict[str,Any]:
        if not self.task_provider: raise TaskProviderUnavailable("No generative task provider configured")
        contract=task_contract("structure_extractor")
        user=json.dumps({"scope":scope,"resolved_resources":resolved_resources,"source":{"type":source_type,"id":source_id,"span":source_span or {},"text":source_text}},ensure_ascii=False)
        output=self.task_provider.run(contract,system_contract=SYSTEM_CONTRACT,user_content=user,response_schema=PROPOSAL_SCHEMA,max_tokens=4096)
        structured=output["structured"]; errors=self.validate_payload(structured)
        if errors: raise StructuredTaskError("; ".join(errors))
        proposals=[]
        for array_name,proposal_type in self.TYPE_MAP.items():
            for item in structured[array_name]:
                evidence=item.get("evidence") or item.get("evidence_spans") or [source_span or {"source_type":source_type,"source_id":source_id}]
                proposals.append(self.store.create_proposal(proposal_type=proposal_type,payload=item,scope=scope,source_type=source_type,source_id=source_id,source_text=source_text,evidence=evidence,confidence=float(item.get("confidence",0.5)),validation={"schema":"memory_proposals_v1","errors":[]}))
        return {"proposals":proposals,"uncertainties":structured["uncertainties"],"unresolved_references":structured["unresolved_references"],"model":output["model"],"usage":output["usage"]}

    def review(self, proposal_id: str, *, accept: bool, edits: dict[str,Any] | None = None, note: str = "") -> dict[str,Any]:
        status="reviewed" if accept else "rejected"
        return self.store.review_proposal(proposal_id,status=status,payload=edits,note=note)

    def commit(self, proposal_id: str) -> dict[str,Any]:
        proposal=self.store.get_proposal(proposal_id)
        if proposal["status"]!="reviewed": raise ValueError("Proposal must be explicitly reviewed before commit")
        payload=proposal["payload"]; scope=proposal["scope"]; ptype=proposal["proposal_type"]
        result: dict[str,Any]
        if ptype=="state_change":
            required=("owner_id","path","value")
            if any(key not in payload for key in required): raise ValueError("State proposal requires owner_id, path, and value")
            self.store.set_current_state(world_id=scope["world_id"],branch_id=scope.get("branch_id"),owner_type=payload.get("owner_type","entity_variant"),owner_id=payload["owner_id"],state_key=payload["path"],value=payload["value"],source_event_id=payload.get("source_event_id"),authority="user_accepted_world_canon")
            if scope.get("story_order") is not None:
                self.store.add_state_interval(world_id=scope["world_id"],branch_id=scope.get("branch_id"),owner_type=payload.get("owner_type","entity_variant"),owner_id=payload["owner_id"],state_key=payload["path"],value=payload["value"],valid_from_order=scope["story_order"],source_event_id=payload.get("source_event_id"),authority="user_accepted_world_canon")
            result={"state_key":payload["path"],"owner_id":payload["owner_id"]}
        elif ptype in {"knowledge_change","belief_change"}:
            character=payload.get("character_variant_id") or payload.get("owner_id")
            if not character or not payload.get("topic_id"): raise ValueError("Epistemic proposal requires character_variant_id and topic_id")
            item_id=self.store.add_epistemic_interval(character_variant_id=character,topic_type=payload.get("topic_type","fact"),topic_id=payload["topic_id"],state_type=payload.get("state_type", "knowledge_acquired" if ptype=="knowledge_change" else "belief_formed"),value=payload.get("value",True),confidence=float(payload.get("confidence",proposal["confidence"])),world_id=scope["world_id"],branch_id=scope.get("branch_id"),valid_from_order=scope.get("story_order"),source_event_id=payload.get("source_event_id"))
            result={"epistemic_id":item_id}
        elif ptype=="story_thread":
            thread=self.store.create_thread(thread_type=payload.get("thread_type","mystery"),title=payload.get("title") or payload.get("summary") or "Untitled thread",description=payload.get("description",""),project_id=scope.get("project_id"),world_id=scope.get("world_id"),branch_id=scope.get("branch_id"),opened_order=scope.get("story_order"),source_id=proposal["source_id"],metadata={"proposal_id":proposal_id})
            for link in payload.get("links") or []: self.store.link_thread(thread["id"],link["resource_type"],link["resource_id"],link.get("relation","subject"))
            result={"thread_id":thread["id"]}
        elif ptype=="event":
            result=self.store.insert_timeline_event_from_proposal(payload,scope=scope,proposal_id=proposal_id)
        elif ptype=="summary":
            result=self.store.create_summary(summary_type=payload["summary_type"],subject_type=payload["subject_type"],subject_id=payload["subject_id"],text=payload["text"],evidence_chunk_ids=payload.get("evidence_chunk_ids") or [],evidence_hash=payload["evidence_hash"],project_id=scope.get("project_id"),world_id=scope.get("world_id"),branch_id=scope.get("branch_id"),start_order=payload.get("start_order"),end_order=payload.get("end_order"),structured=payload.get("structured") or {})
        else:
            raise ValueError(f"Proposal type {ptype!r} has no automatic commit adapter; review it manually")
        return self.store.commit_proposal(proposal_id,result=result)
'''))

write("src/memory/jobs.py",dedent(r'''
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import RLock
from typing import Any


class MemoryJobManager:
    def __init__(self, store, indexer):
        self.store=store; self.indexer=indexer; self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix="arline-memory"); self._lock=RLock(); self._cancelled=set()

    def schedule_backfill(self, *, project_id=None, world_id=None, branch_id=None) -> dict[str,Any]:
        job=self.store.create_job("memory_backfill",payload={"project_id":project_id,"world_id":world_id,"branch_id":branch_id})
        self.executor.submit(self._run_backfill,job["id"],project_id,world_id,branch_id)
        return job

    def _run_backfill(self, job_id, project_id, world_id, branch_id):
        if job_id in self._cancelled: self.store.update_job(job_id,status="cancelled",message="Cancelled before start"); return
        self.store.update_job(job_id,status="running",progress=0.05,message="Indexing source revisions")
        try:
            result=self.indexer.refresh(project_id=project_id,world_id=world_id,branch_id=branch_id)
            if job_id in self._cancelled: self.store.update_job(job_id,status="cancelled",progress=1,message="Cancelled after current batch",result=result)
            else: self.store.update_job(job_id,status="done",progress=1,message="Memory index refreshed",result=result)
        except Exception as exc: self.store.update_job(job_id,status="failed",message=str(exc),result={"error":str(exc)})

    def cancel(self, job_id: str) -> dict[str,Any]:
        with self._lock: self._cancelled.add(job_id)
        current=self.store.get_job(job_id)
        if current["status"] in {"queued","running"}: self.store.update_job(job_id,status="cancelling",message="Cancellation requested")
        return self.store.get_job(job_id)
'''))

write("src/memory/retcon.py",dedent(r'''
from __future__ import annotations

import sqlite3


class RetconImpactService:
    def __init__(self,database_path,memory_store): self.database_path=str(database_path); self.store=memory_store

    def preview(self, *, owner_id: str, world_id: str, branch_id: str|None, story_order: float|None, state_key: str|None=None) -> dict:
        with sqlite3.connect(self.database_path) as con:
            con.row_factory=sqlite3.Row
            params=[world_id,branch_id,owner_id]; interval_sql="SELECT id FROM state_intervals WHERE world_id=? AND branch_id IS ? AND owner_id=?"
            if state_key: interval_sql+=" AND state_key=?"; params.append(state_key)
            if story_order is not None: interval_sql+=" AND (valid_from_order IS NULL OR valid_from_order>=?)"; params.append(story_order)
            intervals=[row[0] for row in con.execute(interval_sql,params).fetchall()]
            events=self.store.events_for_resources([owner_id],world_id=world_id,branch_id=branch_id,limit=100000)
            if story_order is not None: events=[event for event in events if event.get("resolved_story_order") is None or event["resolved_story_order"]>=story_order]
            summaries=self.store.list_summaries(project_id=None,world_id=world_id,branch_id=branch_id,subject_ids=[owner_id],limit=100000)
            try:
                snapshot_cols={row["name"] for row in con.execute("PRAGMA table_info(world_snapshots)").fetchall()}
                snapshots=[]
                if snapshot_cols:
                    sql="SELECT id FROM world_snapshots WHERE world_id=? AND branch_id IS ?"; args=[world_id,branch_id]
                    if story_order is not None and "story_order" in snapshot_cols: sql+=" AND (story_order IS NULL OR story_order>=?)"; args.append(story_order)
                    snapshots=[row[0] for row in con.execute(sql,args).fetchall()]
            except sqlite3.OperationalError: snapshots=[]
        return {"owner_id":owner_id,"state_key":state_key,"scope":{"world_id":world_id,"branch_id":branch_id,"story_order":story_order},"affected":{"state_intervals":intervals,"events":[event["id"] for event in events],"summaries":[summary["id"] for summary in summaries],"snapshots":snapshots},"counts":{"state_intervals":len(intervals),"events":len(events),"summaries":len(summaries),"snapshots":len(snapshots)},"actions":["cancel","scope_to_branch","review_and_commit"]}
'''))

# Extend MemoryStore schema and methods.
path="src/memory/store.py"; text=read(path).replace("MEMORY_SCHEMA_VERSION = 1","MEMORY_SCHEMA_VERSION = 2")
if "CREATE TABLE IF NOT EXISTS memory_proposals" not in text:
    anchor="                CREATE TABLE IF NOT EXISTS memory_lexical("
    tables=dedent(r'''
                CREATE TABLE IF NOT EXISTS memory_proposals(
                    id TEXT PRIMARY KEY,
                    proposal_type TEXT NOT NULL,
                    project_id TEXT,
                    world_id TEXT,
                    branch_id TEXT,
                    session_id TEXT,
                    turn_id TEXT,
                    source_type TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    source_text TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL DEFAULT '[]',
                    confidence REAL NOT NULL DEFAULT 0.5,
                    status TEXT NOT NULL DEFAULT 'proposed',
                    validation_json TEXT NOT NULL DEFAULT '{}',
                    review_note TEXT NOT NULL DEFAULT '',
                    commit_result_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT,
                    committed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_memory_proposals_scope ON memory_proposals(project_id,world_id,branch_id,status,created_at);
                CREATE TABLE IF NOT EXISTS memory_jobs(
                    id TEXT PRIMARY KEY,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    progress REAL NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
''')
    tables=''.join('                '+line+'\n' if line else '\n' for line in tables.splitlines())
    if anchor not in text: raise RuntimeError("memory lexical schema anchor missing")
    text=text.replace(anchor,tables+anchor,1)
if "def create_proposal(" not in text:
    anchor="    def status(self) -> dict[str, Any]:"
    methods=dedent(r'''
        def create_proposal(self, *, proposal_type: str, payload: dict[str,Any], scope: dict[str,Any], source_type: str, source_id: str, source_text: str, evidence: list[dict[str,Any]], confidence: float, validation: dict[str,Any]) -> dict[str,Any]:
            proposal_id=make_id("PROPOSAL"); timestamp=now()
            with self._lock,self.connection() as con:
                con.execute("INSERT INTO memory_proposals(id,proposal_type,project_id,world_id,branch_id,session_id,turn_id,source_type,source_id,source_text,payload_json,evidence_json,confidence,status,validation_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'proposed',?,?)",(proposal_id,proposal_type,scope.get("project_id"),scope.get("world_id"),scope.get("branch_id"),scope.get("session_id"),scope.get("turn_id"),source_type,source_id,source_text,dumps(payload),dumps(evidence),float(confidence),dumps(validation),timestamp))
            return self.get_proposal(proposal_id)

        def _proposal_row(self,row):
            item=dict(row)
            for source,target,fallback in (("payload_json","payload",{}),("evidence_json","evidence",[]),("validation_json","validation",{}),("commit_result_json","commit_result",{})):
                item[target]=loads(item.pop(source),fallback)
            item["scope"]={key:item.get(key) for key in ("project_id","world_id","branch_id","session_id","turn_id")}
            return item

        def get_proposal(self,proposal_id: str) -> dict[str,Any]:
            with self.connection() as con: row=con.execute("SELECT * FROM memory_proposals WHERE id=?",(proposal_id,)).fetchone()
            if row is None: raise KeyError(proposal_id)
            return self._proposal_row(row)

        def list_proposals(self, *, project_id=None, world_id=None, branch_id=None, status=None, limit=100) -> list[dict[str,Any]]:
            sql="SELECT * FROM memory_proposals WHERE (? IS NULL OR project_id=?) AND (? IS NULL OR world_id=?) AND (branch_id IS NULL OR branch_id IS ?)"; params=[project_id,project_id,world_id,world_id,branch_id]
            if status: sql+=" AND status=?"; params.append(status)
            sql+=" ORDER BY created_at DESC LIMIT ?"; params.append(limit)
            with self.connection() as con: rows=con.execute(sql,params).fetchall()
            return [self._proposal_row(row) for row in rows]

        def review_proposal(self,proposal_id: str, *, status: str, payload: dict[str,Any]|None=None, note: str="") -> dict[str,Any]:
            if status not in {"reviewed","rejected"}: raise ValueError("Review status must be reviewed or rejected")
            current=self.get_proposal(proposal_id); merged={**current["payload"],**(payload or {})}
            with self._lock,self.connection() as con: con.execute("UPDATE memory_proposals SET payload_json=?,status=?,review_note=?,reviewed_at=? WHERE id=?",(dumps(merged),status,note,now(),proposal_id))
            return self.get_proposal(proposal_id)

        def commit_proposal(self,proposal_id: str, *, result: dict[str,Any]) -> dict[str,Any]:
            current=self.get_proposal(proposal_id)
            if current["status"]!="reviewed": raise ValueError("Only reviewed proposals can be committed")
            with self._lock,self.connection() as con: con.execute("UPDATE memory_proposals SET status='committed',commit_result_json=?,committed_at=? WHERE id=?",(dumps(result),now(),proposal_id))
            return self.get_proposal(proposal_id)

        def insert_timeline_event_from_proposal(self,payload: dict[str,Any], *, scope: dict[str,Any], proposal_id: str) -> dict[str,Any]:
            event_id=make_id("EVENT"); timestamp=now()
            with self._lock,self.connection() as con:
                columns={row["name"] for row in con.execute("PRAGMA table_info(timeline_events)").fetchall()}
                if not columns: raise ValueError("timeline_events table is unavailable")
                values={"id":event_id,"project_id":scope.get("project_id"),"world_id":scope.get("world_id"),"branch_id":scope.get("branch_id"),"owner_type":payload.get("owner_type","world"),"owner_id":payload.get("owner_id") or scope.get("world_id"),"time_label":payload.get("time_label","") or str(payload.get("world_time") or ""),"order_key":scope.get("story_order") or payload.get("story_order") or 0,"summary":payload.get("summary") or payload.get("description") or payload.get("event_type","event"),"event_type":payload.get("event_type","event"),"state_patch_json":dumps(payload.get("state_patch") or {}),"status":"accepted","created_at":timestamp,"recorded_at":timestamp,"accepted_at":timestamp,"story_order":scope.get("story_order") or payload.get("story_order"),"world_time_json":dumps(payload.get("world_time")) if payload.get("world_time") is not None else None,"participants_json":dumps(payload.get("participants") or []),"causal_links_json":dumps(payload.get("causal_links") or []),"authority":"user_accepted","confidence":float(payload.get("confidence",1.0)),"importance":float(payload.get("importance",0.5))}
                selected={key:value for key,value in values.items() if key in columns}
                con.execute(f"INSERT INTO timeline_events({','.join(selected)}) VALUES({','.join('?' for _ in selected)})",list(selected.values()))
            for participant in payload.get("participants") or []:
                entity_id=participant.get("id") if isinstance(participant,dict) else participant
                if entity_id: self.add_event_participant(event_id,entity_id,participant.get("role","participant") if isinstance(participant,dict) else "participant")
            for edge in payload.get("causal_links") or []:
                target=edge.get("target_event_id") or edge.get("event_id")
                if target: self.add_causal_edge(event_id,edge.get("relation","caused_by"),target,confidence=float(edge.get("confidence",1)),branch_id=scope.get("branch_id"),source_id=proposal_id)
            return {"event_id":event_id}

        def create_job(self,job_type: str, *, payload: dict[str,Any]) -> dict[str,Any]:
            job_id=make_id("JOB"); timestamp=now()
            with self._lock,self.connection() as con: con.execute("INSERT INTO memory_jobs(id,job_type,status,progress,message,payload_json,result_json,created_at,updated_at) VALUES(?,?,'queued',0,'',?,'{}',?,?)",(job_id,job_type,dumps(payload),timestamp,timestamp))
            return self.get_job(job_id)

        def _job_row(self,row):
            item=dict(row); item["payload"]=loads(item.pop("payload_json"),{}); item["result"]=loads(item.pop("result_json"),{}); return item

        def get_job(self,job_id: str) -> dict[str,Any]:
            with self.connection() as con: row=con.execute("SELECT * FROM memory_jobs WHERE id=?",(job_id,)).fetchone()
            if row is None: raise KeyError(job_id)
            return self._job_row(row)

        def list_jobs(self,limit=100):
            with self.connection() as con: rows=con.execute("SELECT * FROM memory_jobs ORDER BY created_at DESC LIMIT ?",(limit,)).fetchall()
            return [self._job_row(row) for row in rows]

        def update_job(self,job_id: str, *, status=None, progress=None, message=None, result=None) -> dict[str,Any]:
            fields=[]; params=[]
            for key,value in (("status",status),("progress",progress),("message",message)):
                if value is not None: fields.append(f"{key}=?"); params.append(value)
            if result is not None: fields.append("result_json=?"); params.append(dumps(result))
            fields.append("updated_at=?"); params.extend([now(),job_id])
            with self._lock,self.connection() as con: con.execute(f"UPDATE memory_jobs SET {','.join(fields)} WHERE id=?",params)
            return self.get_job(job_id)

''')
    methods=''.join('    '+line+'\n' if line else '\n' for line in methods.splitlines())
    if anchor not in text: raise RuntimeError("MemoryStore status anchor missing for proposals")
    text=text.replace(anchor,methods+anchor,1)
# Include proposal/job counts.
text=text.replace('"epistemic_intervals")','"epistemic_intervals","memory_proposals","memory_jobs")')
write(path,text)

# Service orchestration.
path="src/memory/service.py"; text=read(path)
if "MemoryProposalService" not in text:
    text=text.replace("from .embedding import LMStudioEmbeddingProvider, NullEmbeddingProvider","from .embedding import LMStudioEmbeddingProvider, NullEmbeddingProvider\nfrom .inference import LMStudioTaskProvider\nfrom .jobs import MemoryJobManager\nfrom .proposals import MemoryProposalService\nfrom .retcon import RetconImpactService")
    text=text.replace('def __init__(self, *, database_path, config_path, lmstudio_base_url, lmstudio_api_key=""):', 'def __init__(self, *, database_path, config_path, lmstudio_base_url, lmstudio_api_key="", lmstudio_model=""):')
    anchor="        self.database_path=str(database_path)"
    addition=anchor+'\n        self.task_provider=LMStudioTaskProvider(lmstudio_base_url,lmstudio_model,api_key=lmstudio_api_key) if lmstudio_model else None\n        self.proposals=MemoryProposalService(self.store,self.task_provider)\n        self.jobs=MemoryJobManager(self.store,self.indexer)\n        self.retcon=RetconImpactService(database_path,self.store)'
    if anchor not in text: raise RuntimeError("MemoryService database_path anchor missing")
    text=text.replace(anchor,addition,1)
write(path,text)

# App passes the selected generative model.
path="src/interface/web/app.py"; text=read(path)
if "lmstudio_model=initial_cfg.lmstudio.model" not in text:
    anchor="        lmstudio_api_key=initial_cfg.lmstudio.api_key,"
    if anchor not in text: raise RuntimeError("MemoryService API key anchor missing")
    text=text.replace(anchor,anchor+"\n        lmstudio_model=initial_cfg.lmstudio.model,",1)
write(path,text)

# Web review/job/retcon endpoints.
path="src/memory/web.py"; text=read(path)
if "class ExtractProposalPayload" not in text:
    anchor="\ndef register_memory_routes(app: FastAPI, service) -> None:"
    classes=dedent(r'''

class ExtractProposalPayload(BaseModel):
    source_text: str
    source_type: str
    source_id: str
    source_span: dict[str,Any] = Field(default_factory=dict)
    project_id: str | None = None
    world_id: str | None = None
    branch_id: str | None = None
    session_id: str | None = None
    turn_id: str | None = None
    story_order: float | None = None
    resolved_resources: list[dict[str,Any]] = Field(default_factory=list)

class ReviewProposalPayload(BaseModel):
    accept: bool
    edits: dict[str,Any] = Field(default_factory=dict)
    note: str = ""

class RetconImpactPayload(BaseModel):
    owner_id: str
    world_id: str
    branch_id: str | None = None
    story_order: float | None = None
    state_key: str | None = None
''')
    if anchor not in text: raise RuntimeError("Memory web register anchor missing")
    text=text.replace(anchor,classes+anchor,1)
    routes=dedent(r'''

    @app.post("/api/memory/proposals/extract")
    def extract_memory_proposals(payload: ExtractProposalPayload):
        scope={key:value for key,value in payload.model_dump().items() if key in {"project_id","world_id","branch_id","session_id","turn_id","story_order"}}
        try: return service.proposals.extract(payload.source_text,scope=scope,resolved_resources=payload.resolved_resources,source_type=payload.source_type,source_id=payload.source_id,source_span=payload.source_span)
        except Exception as exc: raise HTTPException(status_code=400,detail=str(exc)) from exc

    @app.get("/api/memory/proposals")
    def list_memory_proposals(project_id: str|None=None,world_id: str|None=None,branch_id: str|None=None,status: str|None=None,limit: int=100): return {"proposals":service.store.list_proposals(project_id=project_id,world_id=world_id,branch_id=branch_id,status=status,limit=min(max(limit,1),500))}

    @app.post("/api/memory/proposals/{proposal_id}/review")
    def review_memory_proposal(proposal_id: str,payload: ReviewProposalPayload):
        try: return service.proposals.review(proposal_id,accept=payload.accept,edits=payload.edits,note=payload.note)
        except (KeyError,ValueError) as exc: raise HTTPException(status_code=400,detail=str(exc)) from exc

    @app.post("/api/memory/proposals/{proposal_id}/commit")
    def commit_memory_proposal(proposal_id: str):
        try: return service.proposals.commit(proposal_id)
        except KeyError as exc: raise HTTPException(status_code=404,detail="Proposal not found") from exc
        except ValueError as exc: raise HTTPException(status_code=400,detail=str(exc)) from exc

    @app.post("/api/memory/jobs/backfill")
    def schedule_memory_backfill(payload: BackfillPayload): return service.jobs.schedule_backfill(project_id=payload.project_id,world_id=payload.world_id,branch_id=payload.branch_id)

    @app.get("/api/memory/jobs")
    def list_memory_jobs(limit: int=100): return {"jobs":service.store.list_jobs(limit=min(max(limit,1),500))}

    @app.get("/api/memory/jobs/{job_id}")
    def get_memory_job(job_id: str):
        try: return service.store.get_job(job_id)
        except KeyError as exc: raise HTTPException(status_code=404,detail="Job not found") from exc

    @app.post("/api/memory/jobs/{job_id}/cancel")
    def cancel_memory_job(job_id: str):
        try: return service.jobs.cancel(job_id)
        except KeyError as exc: raise HTTPException(status_code=404,detail="Job not found") from exc

    @app.post("/api/memory/retcon/impact")
    def preview_retcon_impact(payload: RetconImpactPayload): return service.retcon.preview(**payload.model_dump())
''')
    text=text.rstrip()+routes+"\n"
write(path,text)

# Exports.
path="src/memory/__init__.py"; text=read(path)
if "MemoryProposalService" not in text:
    text="from .inference import LMStudioTaskProvider, StructuredTaskError, TaskProviderUnavailable\nfrom .jobs import MemoryJobManager\nfrom .proposals import MemoryProposalService, PROPOSAL_SCHEMA\nfrom .retcon import RetconImpactService\n"+text
    text=text.replace('"MemoryCandidate",','"LMStudioTaskProvider","MemoryCandidate","MemoryJobManager","MemoryProposalService",')
    text=text.replace('"QueryCompiler",','"PROPOSAL_SCHEMA","QueryCompiler",')
    text=text.replace('"ScopeGate",','"RetconImpactService","ScopeGate","StructuredTaskError","TaskProviderUnavailable",')
write(path,text)

# Proposal UI in Developer Memory panel.
path="src/interface/web/static/index.html"; text=read(path)
if 'id="memoryProposalList"' not in text:
    anchor='<pre id="memoryTraceOutput" class="json-block">No retrieval trace yet.</pre>'
    addition=anchor+'\n        <div class="section-title-row"><span class="section-label">Reviewable proposals</span><button id="memoryRefreshProposalsBtn" class="tiny-btn">Refresh</button></div><div id="memoryProposalList" class="suggestion-cards"><div class="empty-note">No proposals loaded.</div></div>\n        <div class="section-title-row"><span class="section-label">Quarantine</span><button id="memoryRefreshQuarantineBtn" class="tiny-btn">Refresh</button></div><div id="memoryQuarantineList" class="suggestion-cards"><div class="empty-note">No quarantined evidence loaded.</div></div>'
    if anchor not in text: raise RuntimeError("Memory trace output anchor missing")
    text=text.replace(anchor,addition,1)
write(path,text)

path="src/interface/web/static/js/memory.js"; text=read(path)
if "refreshProposals" not in text:
    insertion=dedent(r'''

  async function refreshProposals() {
    const target=document.getElementById("memoryProposalList"); if(!target) return;
    try {
      const data=await api("/api/memory/proposals?status=proposed"); const proposals=data.proposals||[];
      target.innerHTML=proposals.length?proposals.map((item)=>`<article class="suggestion-card"><b>${esc(item.proposal_type)}</b><small>${esc(item.source_type)}:${esc(item.source_id)} · confidence ${Number(item.confidence||0).toFixed(2)}</small><pre>${esc(JSON.stringify(item.payload,null,2))}</pre><div><button class="tiny-btn" data-proposal-review="${esc(item.id)}">Review</button><button class="tiny-danger-btn" data-proposal-reject="${esc(item.id)}">Reject</button></div></article>`).join(""):`<div class="empty-note">No proposals waiting for review.</div>`;
      target.querySelectorAll("[data-proposal-review]").forEach((button)=>button.addEventListener("click",async()=>{await api(`/api/memory/proposals/${button.dataset.proposalReview}/review`,{method:"POST",body:{accept:true}});await refreshProposals();}));
      target.querySelectorAll("[data-proposal-reject]").forEach((button)=>button.addEventListener("click",async()=>{await api(`/api/memory/proposals/${button.dataset.proposalReject}/review`,{method:"POST",body:{accept:false}});await refreshProposals();}));
    } catch(error){target.textContent=error.message;}
  }

  async function refreshQuarantine() {
    const target=document.getElementById("memoryQuarantineList"); if(!target) return;
    try {
      const data=await api("/api/memory/quarantine"); const chunks=data.chunks||[];
      target.innerHTML=chunks.length?chunks.map((item)=>`<article class="suggestion-card"><b>${esc(item.source_type)}:${esc(item.source_id)}</b><small>${esc(item.display_excerpt||item.text||"")}</small><button class="tiny-btn" data-trust-chunk="${esc(item.id)}">Trust local</button></article>`).join(""):`<div class="empty-note">No quarantined evidence.</div>`;
      target.querySelectorAll("[data-trust-chunk]").forEach((button)=>button.addEventListener("click",async()=>{await api(`/api/memory/chunks/${button.dataset.trustChunk}/admission`,{method:"PATCH",body:{semantic_status:"active",trust_level:"user_provided"}});await refreshQuarantine();}));
    } catch(error){target.textContent=error.message;}
  }
''')
    marker="  function bindSettings() {"
    if marker not in text: raise RuntimeError("memory.js bindSettings anchor missing")
    text=text.replace(marker,insertion+"\n"+marker,1)
    text=text.replace('    document.getElementById("memoryTestBtn")?.addEventListener("click", testQuery);','    document.getElementById("memoryTestBtn")?.addEventListener("click", testQuery);\n    document.getElementById("memoryRefreshProposalsBtn")?.addEventListener("click", refreshProposals);\n    document.getElementById("memoryRefreshQuarantineBtn")?.addEventListener("click", refreshQuarantine);')
    text=text.replace("    tab?.addEventListener(\"click\", refreshStatus);","    tab?.addEventListener(\"click\", async()=>{ await refreshStatus(); await refreshProposals(); await refreshQuarantine(); });")
write(path,text)

# Tests.
write("tests/memory/test_review_pipeline.py",dedent(r'''
from pathlib import Path
import tempfile
import time
import unittest

from src.memory import MemoryProposalService, MemoryStore, RetconImpactService

class ReviewPipelineTests(unittest.TestCase):
    def test_state_proposal_requires_review_before_commit(self):
        with tempfile.TemporaryDirectory() as td:
            store=MemoryStore(Path(td)/"memory.db"); service=MemoryProposalService(store,None)
            proposal=store.create_proposal(proposal_type="state_change",payload={"owner_id":"V","path":"location","value":"ROOM"},scope={"world_id":"W","branch_id":None,"story_order":2},source_type="document",source_id="D",source_text="V moved.",evidence=[{"start":0,"end":8}],confidence=.9,validation={})
            with self.assertRaises(ValueError): service.commit(proposal["id"])
            service.review(proposal["id"],accept=True)
            committed=service.commit(proposal["id"])
            self.assertEqual(committed["status"],"committed")
            self.assertEqual(store.current_state(world_id="W",branch_id=None,owner_id="V",state_key="location")[0]["value"],"ROOM")

    def test_rejected_proposal_never_commits(self):
        with tempfile.TemporaryDirectory() as td:
            store=MemoryStore(Path(td)/"memory.db"); service=MemoryProposalService(store,None)
            proposal=store.create_proposal(proposal_type="state_change",payload={"owner_id":"V","path":"x","value":1},scope={"world_id":"W"},source_type="chat",source_id="T",source_text="maybe",evidence=[],confidence=.2,validation={})
            service.review(proposal["id"],accept=False)
            with self.assertRaises(ValueError): service.commit(proposal["id"])

    def test_job_and_retcon_foundation(self):
        with tempfile.TemporaryDirectory() as td:
            store=MemoryStore(Path(td)/"memory.db")
            job=store.create_job("test",payload={}); store.update_job(job["id"],status="done",progress=1,result={"ok":True})
            self.assertEqual(store.get_job(job["id"])["result"],{"ok":True})
            store.add_state_interval(world_id="W",branch_id=None,owner_type="entity_variant",owner_id="V",state_key="location",value="A",valid_from_order=4)
            impact=RetconImpactService(Path(td)/"memory.db",store).preview(owner_id="V",world_id="W",branch_id=None,story_order=3,state_key="location")
            self.assertEqual(impact["counts"]["state_intervals"],1)

if __name__ == "__main__": unittest.main()
'''))

# Schema bump ensures a pre-migration backup before proposal/job tables appear.
for path,old,new in (("src/workspace/store.py","WORKSPACE_SCHEMA_VERSION = 8","WORKSPACE_SCHEMA_VERSION = 9"),("src/workspace/foundation.py","SCHEMA_VERSION = 8","SCHEMA_VERSION = 9")):
    text=read(path).replace(old,new); write(path,text)

# Remove this one-shot job.
for disposable in ("tools/v12_complete_review_pipeline.py",".github/workflows/v12-complete-review-pipeline.yml"):
    target=ROOT/disposable
    if target.exists(): target.unlink()
