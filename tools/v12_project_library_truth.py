from __future__ import annotations

from pathlib import Path
from textwrap import dedent
import re

ROOT=Path(__file__).resolve().parents[1]
def read(path): return (ROOT/path).read_text(encoding="utf-8")
def write(path,text):
    target=ROOT/path; target.parent.mkdir(parents=True,exist_ok=True); target.write_text(text.rstrip()+"\n",encoding="utf-8")

# Expand lexical domains and projection schema.
path="src/memory/store.py"; text=read(path).replace("MEMORY_SCHEMA_VERSION = 3","MEMORY_SCHEMA_VERSION = 4")
text=text.replace('FTS_DOMAINS = {"manuscript", "chat", "summary", "import"}','FTS_DOMAINS = {"manuscript", "chat", "summary", "import", "event", "thread"}')
if "CREATE TABLE IF NOT EXISTS project_overlay_projection" not in text:
    anchor="                CREATE TABLE IF NOT EXISTS state_intervals("
    table=dedent(r'''
                CREATE TABLE IF NOT EXISTS project_overlay_projection(
                    project_id TEXT NOT NULL,
                    world_id TEXT,
                    branch_id TEXT,
                    owner_type TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    state_key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    source_overlay_id TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(project_id,world_id,branch_id,owner_type,owner_id,state_key)
                );
                CREATE INDEX IF NOT EXISTS idx_project_overlay_owner ON project_overlay_projection(project_id,world_id,branch_id,owner_id,state_key);
''')
    table=''.join('                '+line+'\n' if line else '\n' for line in table.splitlines())
    if anchor not in text: raise RuntimeError("state interval table anchor missing")
    text=text.replace(anchor,table+anchor,1)
# Track projection source metadata.
if "source_type TEXT" not in text[text.find("CREATE TABLE IF NOT EXISTS current_state_projection"):text.find("CREATE TABLE IF NOT EXISTS state_intervals")]:
    anchor="                    source_event_id TEXT,\n                    authority TEXT NOT NULL DEFAULT 'user_accepted',"
    replacement="                    source_event_id TEXT,\n                    source_type TEXT,\n                    source_id TEXT,\n                    authority TEXT NOT NULL DEFAULT 'user_accepted',"
    if anchor not in text: raise RuntimeError("current state source-event anchor missing")
    text=text.replace(anchor,replacement,1)
    migration_anchor='                ("epistemic_intervals","valid_to_world_time_json","TEXT"),'
    migration_replacement=migration_anchor+'\n                ("current_state_projection","source_type","TEXT"),\n                ("current_state_projection","source_id","TEXT"),'
    if migration_anchor not in text: raise RuntimeError("memory schema alter anchor missing")
    text=text.replace(migration_anchor,migration_replacement,1)
# set_current_state signature and SQL.
old='''    def set_current_state(self, *, world_id: str, branch_id: str | None, owner_type: str, owner_id: str, state_key: str, value: Any, source_event_id: str | None = None, authority: str = "user_accepted") -> None:\n        with self._lock, self.connection() as con:\n            con.execute(\n                "INSERT INTO current_state_projection(world_id,branch_id,owner_type,owner_id,state_key,value_json,source_event_id,authority,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(world_id,branch_id,owner_type,owner_id,state_key) DO UPDATE SET value_json=excluded.value_json,source_event_id=excluded.source_event_id,authority=excluded.authority,updated_at=excluded.updated_at",\n                (world_id, branch_id, owner_type, owner_id, state_key, dumps(value), source_event_id, authority, now()),\n            )'''
new='''    def set_current_state(self, *, world_id: str, branch_id: str | None, owner_type: str, owner_id: str, state_key: str, value: Any, source_event_id: str | None = None, source_type: str | None = None, source_id: str | None = None, authority: str = "user_accepted") -> None:\n        with self._lock, self.connection() as con:\n            con.execute(\n                "INSERT INTO current_state_projection(world_id,branch_id,owner_type,owner_id,state_key,value_json,source_event_id,source_type,source_id,authority,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(world_id,branch_id,owner_type,owner_id,state_key) DO UPDATE SET value_json=excluded.value_json,source_event_id=excluded.source_event_id,source_type=excluded.source_type,source_id=excluded.source_id,authority=excluded.authority,updated_at=excluded.updated_at",\n                (world_id, branch_id, owner_type, owner_id, state_key, dumps(value), source_event_id, source_type, source_id, authority, now()),\n            )'''
if old not in text: raise RuntimeError("set_current_state anchor missing")
text=text.replace(old,new,1)
# Project overlay/effective state/relationship helpers before events.
if "def effective_state(" not in text:
    anchor="        def state_at_world_time("
    methods=dedent(r'''
        def set_project_overlay(self, *, project_id: str, world_id: str | None, branch_id: str | None, owner_type: str, owner_id: str, state_key: str, value: Any, source_overlay_id: str | None = None) -> None:
            with self._lock,self.connection() as con:
                con.execute("INSERT INTO project_overlay_projection(project_id,world_id,branch_id,owner_type,owner_id,state_key,value_json,source_overlay_id,updated_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(project_id,world_id,branch_id,owner_type,owner_id,state_key) DO UPDATE SET value_json=excluded.value_json,source_overlay_id=excluded.source_overlay_id,updated_at=excluded.updated_at",(project_id,world_id,branch_id,owner_type,owner_id,state_key,dumps(value),source_overlay_id,now()))

        def project_overlays(self, *, project_id: str, world_id: str | None, branch_id: str | None, owner_id: str) -> list[dict[str,Any]]:
            with self.connection() as con: rows=con.execute("SELECT * FROM project_overlay_projection WHERE project_id=? AND (world_id IS NULL OR world_id=?) AND (branch_id IS NULL OR branch_id IS ?) AND owner_id=? ORDER BY CASE WHEN branch_id IS NULL THEN 0 ELSE 1 END",(project_id,world_id,branch_id,owner_id)).fetchall()
            result=[]
            for row in rows:
                item=dict(row); item["value"]=loads(item.pop("value_json"),None); result.append(item)
            return result

        def effective_state(self, *, project_id: str | None, world_id: str, branch_id: str | None, owner_id: str, story_order: float | None = None) -> list[dict[str,Any]]:
            result: dict[str,dict[str,Any]]={}
            visibility=self.branch_visibility(branch_id) if branch_id else []
            ordered=[]
            if branch_id is None: ordered=[{"visible_branch_id":None,"max_story_order":story_order,"depth":0}]
            else:
                # Global/base null state is the oldest layer; then ancestors; active branch last.
                ordered=[{"visible_branch_id":None,"max_story_order":story_order,"depth":999}]+list(reversed(visibility or [{"visible_branch_id":branch_id,"max_story_order":story_order,"depth":0}]))
            for rule in ordered:
                visible=rule.get("visible_branch_id"); cutoff=rule.get("max_story_order")
                if story_order is not None: cutoff=min(story_order,cutoff) if cutoff is not None else story_order
                rows=self.state_at(world_id=world_id,branch_id=visible,owner_id=owner_id,story_order=cutoff) if cutoff is not None else self.current_state(world_id=world_id,branch_id=visible,owner_id=owner_id)
                for item in rows: result[item["state_key"]]={**item,"effective_source":"branch_state","visible_branch_id":visible}
            if project_id:
                for item in self.project_overlays(project_id=project_id,world_id=world_id,branch_id=branch_id,owner_id=owner_id): result[item["state_key"]]={**item,"effective_source":"project_overlay"}
            return [result[key] for key in sorted(result)]

        def relationships_for_resources(self, resource_ids: list[str], *, world_id: str | None, branch_id: str | None, limit: int = 40) -> list[dict[str,Any]]:
            if not resource_ids: return []
            placeholders=','.join('?' for _ in resource_ids)
            with self.connection() as con:
                try:
                    rows=con.execute(f"SELECT r.*,sv.family_id AS subject_family_id,ov.family_id AS object_family_id FROM relationships r JOIN entity_variants sv ON sv.id=r.subject_variant_id JOIN entity_variants ov ON ov.id=r.object_variant_id WHERE (? IS NULL OR r.world_id=?) AND (r.branch_id IS NULL OR r.branch_id IS ?) AND (sv.family_id IN ({placeholders}) OR ov.family_id IN ({placeholders}) OR r.subject_variant_id IN ({placeholders}) OR r.object_variant_id IN ({placeholders})) LIMIT ?",[world_id,world_id,branch_id,*resource_ids,*resource_ids,*resource_ids,*resource_ids,limit]).fetchall()
                except sqlite3.OperationalError: rows=[]
            result=[]
            for row in rows:
                item=dict(row); item["attributes"]=loads(item.pop("attributes_json"),{}); result.append(item)
            return result

''')
    methods=''.join('    '+line+'\n' if line else '\n' for line in methods.splitlines())
    if anchor not in text: raise RuntimeError("state_at_world_time anchor missing")
    text=text.replace(anchor,methods+anchor,1)
# Include overlay counts.
text=text.replace('"memory_jobs")','"memory_jobs","project_overlay_projection")')
write(path,text)

# Structured Library backfill.
path="src/memory/index.py"; text=read(path)
if "def _refresh_library(" not in text:
    anchor="    def refresh(self, *, project_id: str | None = None, world_id: str | None = None, branch_id: str | None = None) -> dict[str, int]:"
    methods=dedent(r'''
    @staticmethod
    def _flatten(prefix: str, value: Any):
        if isinstance(value,dict):
            for key,item in value.items():
                next_key=f"{prefix}.{key}" if prefix else str(key)
                yield from MemoryIndexer._flatten(next_key,item)
        else: yield prefix,value

    def _refresh_library(self, *, project_id: str | None, world_id: str | None, branch_id: str | None) -> dict[str,int]:
        counts={"variants":0,"facts":0,"overlays":0,"events":0,"threads":0}
        with sqlite3.connect(self.database_path) as con:
            con.row_factory=sqlite3.Row
            variant_sql="SELECT v.*,f.project_id,f.name AS family_name FROM entity_variants v JOIN entity_families f ON f.id=v.family_id WHERE 1=1"; params=[]
            if world_id: variant_sql+=" AND v.world_id=?"; params.append(world_id)
            if branch_id: variant_sql+=" AND (v.branch_id IS NULL OR v.branch_id=?)"; params.append(branch_id)
            variants=con.execute(variant_sql,params).fetchall()
            for row in variants:
                for column,prefix in (("attributes_json","attributes"),("current_state_json","current_state")):
                    data=json.loads(row[column] or "{}")
                    for key,value in self._flatten(prefix,data):
                        self.store.set_current_state(world_id=row["world_id"],branch_id=row["branch_id"],owner_type="entity_variant",owner_id=row["id"],state_key=key,value=value,source_type="entity_variant",source_id=row["id"],authority="user_accepted_world_canon")
                        counts["variants"]+=1
                for column,state_type in (("knowledge_json","knowledge_snapshot"),("beliefs_json","belief_snapshot")):
                    data=json.loads(row[column] or "{}")
                    for topic,value in self._flatten("",data):
                        if topic: self.store.add_epistemic_interval(character_variant_id=row["id"],topic_type="topic",topic_id=topic,state_type=state_type,value=value,confidence=1,world_id=row["world_id"],branch_id=row["branch_id"],source_event_id=None)
            try:
                fact_sql="SELECT * FROM canon_facts WHERE status IN ('canon','accepted')"; fact_params=[]
                if project_id: fact_sql+=" AND project_id=?"; fact_params.append(project_id)
                if world_id: fact_sql+=" AND (world_id IS NULL OR world_id=?)"; fact_params.append(world_id)
                if branch_id: fact_sql+=" AND (branch_id IS NULL OR branch_id=?)"; fact_params.append(branch_id)
                facts=con.execute(fact_sql,fact_params).fetchall()
            except sqlite3.OperationalError: facts=[]
            for row in facts:
                if row["world_id"]:
                    self.store.set_current_state(world_id=row["world_id"],branch_id=row["branch_id"],owner_type=row["owner_type"],owner_id=row["owner_id"],state_key=row["path"],value=json.loads(row["value_json"]),source_type="canon_fact",source_id=row["id"],authority=row["authority"] or "user_accepted_world_canon")
                    counts["facts"]+=1
            # Project overlays are discovered dynamically because v1.1 preserved compatibility names.
            table_names={row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            overlay_table=next((name for name in ("project_overlays","project_entity_overlays") if name in table_names),None)
            if overlay_table:
                columns={row["name"] for row in con.execute(f"PRAGMA table_info({overlay_table})").fetchall()}
                rows=con.execute(f"SELECT * FROM {overlay_table}").fetchall()
                for row in rows:
                    data=dict(row); pid=data.get("project_id"); oid=data.get("owner_id") or data.get("resource_id"); path=data.get("path") or data.get("state_key")
                    if not pid or not oid or not path or (project_id and pid!=project_id): continue
                    raw=data.get("value_json") if "value_json" in columns else data.get("value")
                    try: value=json.loads(raw) if isinstance(raw,str) else raw
                    except json.JSONDecodeError: value=raw
                    self.store.set_project_overlay(project_id=pid,world_id=data.get("world_id"),branch_id=data.get("branch_id"),owner_type=data.get("owner_type") or data.get("resource_type") or "entity_variant",owner_id=oid,state_key=path,value=value,source_overlay_id=data.get("id")); counts["overlays"]+=1
            # Accepted events become temporal/causal projections and searchable evidence.
            try: events=self.store.events_for_resources([],world_id=world_id,branch_id=branch_id,limit=100000)
            except Exception: events=[]
            for event in events:
                summary=event.get("summary") or event.get("event_type") or event["id"]
                revision=str(event.get("updated_at") or event.get("recorded_at") or event.get("created_at") or event["id"])
                counts["events"]+=self._index_text(source_type="timeline_event",source_id=event["id"],revision=revision,text=summary,domain="event",metadata={"event_type":event.get("event_type"),"accepted":True},authority="accepted_event",trust_level="trusted_local",semantic_class="evidence",project_id=event.get("project_id"),world_id=event.get("world_id"),branch_id=event.get("branch_id"),story_order=event.get("resolved_story_order"))
                patch=event.get("state_patch") or {}; owner=event.get("owner_id")
                if owner and isinstance(patch,dict):
                    for key,value in self._flatten("",patch):
                        self.store.set_current_state(world_id=event.get("world_id") or world_id,branch_id=event.get("branch_id"),owner_type=event.get("owner_type") or "entity_variant",owner_id=owner,state_key=key,value=value,source_event_id=event["id"],source_type="timeline_event",source_id=event["id"],authority="accepted_event")
                        self.store.add_state_interval(world_id=event.get("world_id") or world_id,branch_id=event.get("branch_id"),owner_type=event.get("owner_type") or "entity_variant",owner_id=owner,state_key=key,value=value,valid_from_order=event.get("resolved_story_order"),valid_from_world_time=event.get("world_time"),source_event_id=event["id"],authority="accepted_event")
                for participant in event.get("participants") or []:
                    entity_id=participant.get("id") if isinstance(participant,dict) else participant
                    if entity_id: self.store.add_event_participant(event["id"],entity_id,participant.get("role","participant") if isinstance(participant,dict) else "participant")
                for edge in event.get("causal_links") or []:
                    target=edge.get("target_event_id") or edge.get("event_id") if isinstance(edge,dict) else None
                    if target: self.store.add_causal_edge(event["id"],edge.get("relation","caused_by"),target,confidence=float(edge.get("confidence",1)),branch_id=event.get("branch_id"),source_id=event["id"])
        # Threads live in MemoryStore and are indexed outside the workspace connection.
        for thread in self.store.list_threads(project_id=project_id,world_id=world_id,branch_id=branch_id):
            source_text=f"{thread['thread_type']}: {thread['title']}\n{thread['description']}\nstatus: {thread['status']}"
            counts["threads"]+=self._index_text(source_type="story_thread",source_id=thread["id"],revision=thread["updated_at"],text=source_text,domain="thread",metadata={"status":thread["status"],"thread_type":thread["thread_type"]},authority="user_accepted_world_canon",trust_level="trusted_local",semantic_class="accepted_concept",project_id=thread.get("project_id"),world_id=thread.get("world_id"),branch_id=thread.get("branch_id"),story_order=thread.get("opened_order"))
        return counts

''')
    if anchor not in text: raise RuntimeError("MemoryIndexer refresh anchor missing")
    text=text.replace(anchor,methods+anchor,1)
    text=text.replace('indexed = {"documents": 0, "turns": 0}','indexed = {"documents": 0, "turns": 0, "variants": 0, "facts": 0, "overlays": 0, "events": 0, "threads": 0}',1)
    return_anchor="        return indexed"
    replacement='''        library=self._refresh_library(project_id=project_id,world_id=world_id,branch_id=branch_id)\n        for key,value in library.items(): indexed[key]=indexed.get(key,0)+value\n        return indexed'''
    if return_anchor not in text: raise RuntimeError("MemoryIndexer return anchor missing")
    text=text.replace(return_anchor,replacement,1)
write(path,text)

# Query domain specialization and effective state/relations.
path="src/memory/query.py"; text=read(path)
if 'QueryRoute.EVENT_LOOKUP: ["event", "manuscript"]' not in text:
    domain_anchor='''        domains = {\n            QueryRoute.TEXT_RECALL: ["manuscript", "chat", "summary", "import"],\n            QueryRoute.GLOBAL_SUMMARY: ["summary", "manuscript"],\n            QueryRoute.STORY_CONTINUE: ["manuscript", "chat", "summary"],\n        }.get(route, ["manuscript", "chat"])'''
    domain_replacement='''        domains = {\n            QueryRoute.TEXT_RECALL: ["manuscript", "chat", "summary", "import", "event", "thread"],\n            QueryRoute.EVENT_LOOKUP: ["event", "manuscript"],\n            QueryRoute.WHY_CAUSAL: ["event", "manuscript"],\n            QueryRoute.THREAD_LOOKUP: ["thread", "manuscript"],\n            QueryRoute.GLOBAL_SUMMARY: ["summary", "manuscript"],\n            QueryRoute.STORY_CONTINUE: ["manuscript", "chat", "summary", "event", "thread"],\n        }.get(route, ["manuscript", "chat"])'''
    if domain_anchor not in text: raise RuntimeError("QueryCompiler domain anchor missing")
    text=text.replace(domain_anchor,domain_replacement,1)
write(path,text)

path="src/memory/retrieve.py"; text=read(path)
old='''                for index,item in enumerate(self.store.current_state(world_id=scope.world_id, branch_id=scope.branch_id, owner_id=rid),1):'''
new='''                for index,item in enumerate(self.store.effective_state(project_id=scope.project_id,world_id=scope.world_id,branch_id=scope.branch_id,owner_id=rid,story_order=scope.story_order),1):'''
if old not in text: raise RuntimeError("Retriever current state anchor missing")
text=text.replace(old,new,1)
# Add relationship candidates for Story/Current/Continuity routes.
if "source_type=\"relationship\"" not in text:
    anchor='''        if plan.route.value == "THREAD_LOOKUP":'''
    block=dedent(r'''
        if plan.route.value in {"CURRENT_STATE","STORY_CONTINUE","CONTINUITY_CHECK"} and resources:
            relationships=self.store.relationships_for_resources([item.get("id") for item in resources if item.get("id")],world_id=scope.world_id,branch_id=scope.branch_id,limit=plan.per_lane_budget)
            for index,relation in enumerate(relationships,1):
                text_value=f"{relation.get('subject_family_id') or relation.get('subject_variant_id')} --{relation.get('relation_type')}→ {relation.get('object_family_id') or relation.get('object_variant_id')} ({relation.get('status','current')})"
                result.append(MemoryCandidate(id=f"relationship:{relation['id']}",lane="relationships",source_type="relationship",source_id=relation["id"],text=text_value,display_excerpt=text_value,world_id=relation.get("world_id"),branch_id=relation.get("branch_id"),authority="user_accepted_world_canon" if relation.get("canon_status")=="canon" else "project_manuscript",source_rank=index,metadata={"structured":True,"relationship":relation}))
''')
    block=''.join('        '+line+'\n' if line else '\n' for line in block.splitlines())
    if anchor not in text: raise RuntimeError("Retriever thread anchor missing")
    text=text.replace(anchor,block+anchor,1)
write(path,text)

# Search endpoint over all memory result classes.
path="src/memory/web.py"; text=read(path)
if "class MemorySearchPayload" not in text:
    anchor="\ndef register_memory_routes(app: FastAPI, service) -> None:"
    cls=dedent(r'''

class MemorySearchPayload(BaseModel):
    query: str
    project_id: str | None = None
    world_id: str | None = None
    branch_id: str | None = None
    session_id: str | None = None
    story_order: float | None = None
    world_time: Any = None
    source_types: list[str] = Field(default_factory=list)
    limit: int = 30
''')
    text=text.replace(anchor,cls+anchor,1)
    routes=dedent(r'''

    @app.post("/api/memory/search")
    def search_memory(payload: MemorySearchPayload):
        result=service.query(payload.query,project_id=payload.project_id,world_id=payload.world_id,branch_id=payload.branch_id,session_id=payload.session_id,story_order=payload.story_order,world_time=payload.world_time,retrieval_mode="deep",refresh=True)
        selected=result.get("selected") or []
        if payload.source_types: selected=[item for item in selected if item.get("source_type") in payload.source_types]
        return {"results":selected[:min(max(payload.limit,1),200)],"trace_id":result.get("run_id"),"excluded":result.get("excluded") or []}
''')
    text=text.rstrip()+routes+"\n"
write(path,text)

# Tests.
write("tests/memory/test_library_truth_projection.py",dedent(r'''
from pathlib import Path
import json
import sqlite3
import tempfile
import unittest

from src.memory import MemoryIndexer, MemoryStore

class LibraryTruthProjectionTests(unittest.TestCase):
    def _workspace(self,path):
        con=sqlite3.connect(path)
        con.executescript('''
        CREATE TABLE entity_families(id TEXT PRIMARY KEY,project_id TEXT,name TEXT);
        CREATE TABLE entity_variants(id TEXT PRIMARY KEY,family_id TEXT,world_id TEXT,branch_id TEXT,attributes_json TEXT,current_state_json TEXT,knowledge_json TEXT,beliefs_json TEXT);
        CREATE TABLE canon_facts(id TEXT PRIMARY KEY,project_id TEXT,world_id TEXT,branch_id TEXT,owner_type TEXT,owner_id TEXT,path TEXT,value_json TEXT,status TEXT,authority TEXT);
        CREATE TABLE workspace_documents(id TEXT PRIMARY KEY,project_id TEXT,world_id TEXT,branch_id TEXT,title TEXT,content TEXT,document_type TEXT,status TEXT,sort_order INTEGER,updated_at TEXT);
        CREATE TABLE relationships(id TEXT PRIMARY KEY,world_id TEXT,branch_id TEXT,subject_variant_id TEXT,object_variant_id TEXT,relation_type TEXT,status TEXT,canon_status TEXT,attributes_json TEXT);
        CREATE TABLE timeline_events(id TEXT PRIMARY KEY,project_id TEXT,world_id TEXT,branch_id TEXT,owner_type TEXT,owner_id TEXT,summary TEXT,event_type TEXT,state_patch_json TEXT,status TEXT,order_key REAL,created_at TEXT);
        ''')
        con.execute("INSERT INTO entity_families VALUES('F','P','Vian')")
        con.execute("INSERT INTO entity_variants VALUES('V','F','W',NULL,?,?,?,?)",(json.dumps({'height':165}),json.dumps({'location':'A0325'}),json.dumps({}),json.dumps({})))
        con.execute("INSERT INTO canon_facts VALUES('CF','P','W',NULL,'entity_variant','V','identity.name',?,'canon','user_explicit')",(json.dumps('Vian'),))
        con.commit(); con.close()

    def test_library_backfill_and_effective_state(self):
        with tempfile.TemporaryDirectory() as td:
            db=Path(td)/'workspace.db'; self._workspace(db); store=MemoryStore(db); indexer=MemoryIndexer(store,database_path=db)
            result=indexer.refresh(project_id='P',world_id='W')
            self.assertGreater(result['variants'],0); self.assertEqual(store.effective_state(project_id='P',world_id='W',branch_id=None,owner_id='V')[0]['effective_source'],'branch_state')
            store.set_project_overlay(project_id='P',world_id='W',branch_id=None,owner_type='entity_variant',owner_id='V',state_key='current_state.location',value='Campus')
            values={item['state_key']:item for item in store.effective_state(project_id='P',world_id='W',branch_id=None,owner_id='V')}
            self.assertEqual(values['current_state.location']['value'],'Campus'); self.assertEqual(values['current_state.location']['effective_source'],'project_overlay')

if __name__ == '__main__': unittest.main()
'''))

# Backup-coordinated schema bump.
for path,old,new in (("src/workspace/store.py","WORKSPACE_SCHEMA_VERSION = 10","WORKSPACE_SCHEMA_VERSION = 11"),("src/workspace/foundation.py","SCHEMA_VERSION = 10","SCHEMA_VERSION = 11")):
    text=read(path).replace(old,new); write(path,text)

for disposable in ("tools/v12_project_library_truth.py",".github/workflows/v12-project-library-truth.yml"):
    target=ROOT/disposable
    if target.exists(): target.unlink()
