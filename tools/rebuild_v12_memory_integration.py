from __future__ import annotations

from pathlib import Path
from textwrap import dedent
import re

ROOT = Path(__file__).resolve().parents[1]


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dedent(content).lstrip().rstrip() + "\n", encoding="utf-8")


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def replace_once(path: str, old: str, new: str, *, optional: bool = False) -> bool:
    text = read(path)
    if new in text:
        return True
    if old not in text:
        if optional:
            return False
        raise RuntimeError(f"Anchor missing in {path}: {old[:120]!r}")
    write(path, text.replace(old, new, 1))
    return True


def function_block(text: str, name: str) -> tuple[int, int] | None:
    match = re.search(rf"(?m)^(?:async\s+)?function\s+{re.escape(name)}\s*\(", text)
    if not match:
        return None
    brace = text.find("{", match.end())
    if brace < 0:
        return None
    depth = 0
    quote = None
    escaped = False
    for index in range(brace, len(text)):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {'"', "'", "`"}:
            quote = char
            continue
        if char == "{": depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return match.start(), index + 1
    return None


write("src/memory/index.py", r'''
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import sqlite3
from typing import Any

from .security import should_quarantine


@dataclass(slots=True)
class ChunkDraft:
    text: str
    start: int
    end: int


class StructuralChunker:
    VERSION = 1

    def __init__(self, *, target_chars: int = 1800, overlap_chars: int = 180):
        self.target_chars = max(400, target_chars)
        self.overlap_chars = max(0, overlap_chars)

    def chunk(self, text: str) -> list[ChunkDraft]:
        text = (text or "").replace("\r\n", "\n").strip()
        if not text:
            return []
        blocks = [block.strip() for block in re.split(r"\n{2,}", text) if block.strip()]
        if not blocks:
            blocks = [text]
        result: list[ChunkDraft] = []
        current = ""; current_start = 0; cursor = 0
        for block in blocks:
            found = text.find(block, cursor)
            if found < 0: found = cursor
            cursor = found + len(block)
            if current and len(current) + len(block) + 2 > self.target_chars:
                result.append(ChunkDraft(current, current_start, current_start + len(current)))
                overlap = current[-self.overlap_chars:] if self.overlap_chars else ""
                current = (overlap + "\n\n" + block).strip()
                current_start = max(0, found - len(overlap))
            else:
                if not current: current_start = found
                current = (current + "\n\n" + block).strip()
        if current:
            result.append(ChunkDraft(current, current_start, current_start + len(current)))
        return result


class MemoryIndexer:
    def __init__(self, store, *, database_path, embedding_provider=None, dense_enabled=False):
        self.store = store
        self.database_path = str(database_path)
        self.embedding_provider = embedding_provider
        self.dense_enabled = dense_enabled
        self.chunker = StructuralChunker()

    @staticmethod
    def checksum(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def speech_act(text: str) -> str:
        lowered = text.casefold()
        if re.search(r"\b(?:maybe|what if|perhaps|could|suppose)\b", lowered): return "hypothesis"
        if re.search(r"\b(?:actually|correction|keep this canon|make this canon|decide|confirmed)\b", lowered): return "decision"
        if "?" in text: return "question"
        if re.search(r"\b(?:do not|must|please|write|continue|focus)\b", lowered): return "instruction"
        return "assertion"

    def _aliases(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.database_path) as con:
            con.row_factory = sqlite3.Row
            families = con.execute("SELECT id,name FROM entity_families").fetchall()
            aliases = []
            try: aliases = con.execute("SELECT resource_id,alias FROM resource_aliases WHERE resource_type='entity_family'").fetchall()
            except sqlite3.OperationalError: pass
        result = [{"id": row["id"], "label": row["name"]} for row in families]
        result.extend({"id": row["resource_id"], "label": row["alias"]} for row in aliases)
        result.sort(key=lambda item: len(item["label"]), reverse=True)
        return result

    def _link_entities(self, chunk_id: str, text: str) -> None:
        folded = text.casefold()
        seen = set()
        for item in self._aliases():
            label = item["label"].strip()
            if not label or item["id"] in seen: continue
            if re.search(rf"(?<!\w){re.escape(label.casefold())}(?!\w)", folded):
                seen.add(item["id"])
                self.store.add_link(chunk_id, "entity_family", item["id"], relation="mentions", confidence=1.0, method="alias")

    def _index_text(self, *, source_type: str, source_id: str, revision: str, text: str, domain: str, metadata: dict[str, Any], authority: str, trust_level: str, semantic_class: str, project_id=None, world_id=None, branch_id=None, session_id=None, story_order=None) -> int:
        if self.store.source_revision_exists(source_type, source_id, revision): return 0
        self.store.mark_source_stale(source_type, source_id, except_revision=revision)
        drafts = self.chunker.chunk(text)
        stored = []
        for index, draft in enumerate(drafts):
            checksum = self.checksum(draft.text)
            status = "quarantined" if should_quarantine(draft.text, trust_level) else "active"
            chunk = self.store.upsert_chunk({
                "id": f"MEM-{source_type.upper()}-{source_id}-{index}",
                "source_type": source_type,
                "source_id": source_id,
                "source_revision": revision,
                "project_id": project_id,
                "world_id": world_id,
                "branch_id": branch_id,
                "session_id": session_id,
                "source_start_id": str(draft.start),
                "source_end_id": str(draft.end),
                "story_order": story_order,
                "semantic_class": semantic_class,
                "authority": authority,
                "trust_level": "quarantined" if status == "quarantined" else trust_level,
                "text": draft.text,
                "retrieval_text": draft.text,
                "display_excerpt": draft.text[:500],
                "token_count": max(1, len(draft.text) // 4),
                "semantic_status": status,
                "checksum": checksum,
                "chunker_version": self.chunker.VERSION,
                "metadata": {**metadata, "chunk_index": index},
            }, domain=domain)
            self._link_entities(chunk["id"], draft.text)
            stored.append(chunk)
        if self.dense_enabled and self.embedding_provider and stored:
            active_generation = self.store.active_generation()
            if not active_generation:
                generation_id = self.store.create_generation("lmstudio", getattr(self.embedding_provider, "model", None), None, self.chunker.VERSION)
            else:
                generation_id = int(active_generation["generation_id"])
            vectors = self.embedding_provider.embed_texts([item["retrieval_text"] for item in stored], kind="passage")
            for item, vector in zip(stored, vectors):
                self.store.upsert_vector(item["id"], vector, generation_id=generation_id, model_id=getattr(self.embedding_provider, "model", "embedding"))
            if not active_generation:
                self.store.activate_generation(generation_id)
        return len(stored)

    def refresh(self, *, project_id: str | None = None, world_id: str | None = None, branch_id: str | None = None) -> dict[str, int]:
        indexed = {"documents": 0, "turns": 0}
        with sqlite3.connect(self.database_path) as con:
            con.row_factory = sqlite3.Row
            document_sql = "SELECT * FROM workspace_documents WHERE 1=1"; params=[]
            if project_id: document_sql += " AND project_id=?"; params.append(project_id)
            if world_id: document_sql += " AND (world_id IS NULL OR world_id=?)"; params.append(world_id)
            if branch_id: document_sql += " AND (branch_id IS NULL OR branch_id=?)"; params.append(branch_id)
            documents = con.execute(document_sql, params).fetchall()
            for row in documents:
                text = f"# {row['title']}\n\n{row['content']}"
                revision = str(row["updated_at"] or self.checksum(text))
                indexed["documents"] += self._index_text(
                    source_type="document", source_id=row["id"], revision=revision, text=text, domain="manuscript",
                    metadata={"title": row["title"], "document_type": row["document_type"], "status": row["status"]},
                    authority="project_manuscript", trust_level="trusted_local", semantic_class="evidence",
                    project_id=row["project_id"], world_id=row["world_id"], branch_id=row["branch_id"], story_order=float(row["sort_order"] or 0),
                )
            try:
                turn_sql = "SELECT t.*,s.project_id,s.world_id,s.branch_id,s.scratch_mode FROM turns t JOIN sessions s ON s.id=t.session_id WHERE 1=1"; turn_params=[]
                if project_id: turn_sql += " AND (s.project_id IS NULL OR s.project_id=?)"; turn_params.append(project_id)
                if world_id: turn_sql += " AND (s.world_id IS NULL OR s.world_id=?)"; turn_params.append(world_id)
                if branch_id: turn_sql += " AND (s.branch_id IS NULL OR s.branch_id=?)"; turn_params.append(branch_id)
                turns = con.execute(turn_sql, turn_params).fetchall()
            except sqlite3.OperationalError:
                turns = []
            for order, row in enumerate(turns):
                user = row["user_prompt"] or ""; story = row["story"] or ""
                text = f"User:\n{user}\n\nArline:\n{story}"
                revision = str(row["updated_at"] or row["created_at"] or self.checksum(text))
                accepted = row["feedback_status"] in {"accepted", "edited_accept"}
                semantic_class = "accepted_concept" if accepted else "exploratory"
                authority = "accepted_generated_output" if accepted else ("chat_decision" if self.speech_act(user) == "decision" else "chat_exploration")
                indexed["turns"] += self._index_text(
                    source_type="chat_window", source_id=row["id"], revision=revision, text=text, domain="chat",
                    metadata={"run_id": row["run_id"], "feedback_status": row["feedback_status"], "speech_act": self.speech_act(user), "scratch": bool(row["scratch_mode"])},
                    authority=authority, trust_level="generated", semantic_class=semantic_class,
                    project_id=row["project_id"], world_id=row["world_id"], branch_id=row["branch_id"], session_id=row["session_id"], story_order=float(order),
                )
        return indexed
''')

write("src/memory/retrieve.py", r'''
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .embedding import EmbeddingUnavailable
from .models import MemoryCandidate, QueryPlan, RetrievalResult
from .scope import ScopeGate


AUTHORITY_BOOST = {
    "user_accepted_overlay": 0.20,
    "user_accepted_branch_canon": 0.18,
    "user_accepted_world_canon": 0.17,
    "accepted_event": 0.15,
    "user_explicit_note": 0.12,
    "accepted_generated_output": 0.10,
    "project_manuscript": 0.08,
    "chat_decision": 0.06,
    "chat_exploration": 0.00,
    "derived_summary": -0.01,
    "imported_reference": -0.03,
    "scratch": -0.10,
}


class MemoryRetriever:
    def __init__(self, store, *, embedding_provider=None, dense_enabled=False, max_items_per_source=3):
        self.store = store
        self.embedding_provider = embedding_provider
        self.dense_enabled = dense_enabled
        self.max_items_per_source = max_items_per_source
        self.gate = ScopeGate(store)

    @staticmethod
    def _candidate(row: dict[str, Any], lane: str, rank: int) -> MemoryCandidate:
        return MemoryCandidate(
            id=row["id"], lane=lane, source_type=row["source_type"], source_id=row["source_id"], text=row["text"],
            display_excerpt=row.get("display_excerpt") or row["text"][:500], project_id=row.get("project_id"), world_id=row.get("world_id"),
            branch_id=row.get("branch_id"), session_id=row.get("session_id"), story_order=row.get("story_order"),
            semantic_class=row.get("semantic_class", "evidence"), semantic_status=row.get("semantic_status", "active"), authority=row.get("authority", "project_manuscript"),
            trust_level=row.get("trust_level", "trusted_local"), importance=float(row.get("importance", 0.5)), token_count=int(row.get("token_count", 0)),
            source_rank=rank, links=row.get("links") or [], metadata=row.get("metadata") or {},
        )

    def _structured(self, plan: QueryPlan) -> list[MemoryCandidate]:
        result=[]; scope=plan.scope; resources=plan.resolved_resources
        for resource in resources[:8]:
            rid=resource.get("id")
            if not rid: continue
            if plan.route.value == "CURRENT_STATE" and scope.world_id:
                for index,item in enumerate(self.store.current_state(world_id=scope.world_id, branch_id=scope.branch_id, owner_id=rid),1):
                    result.append(MemoryCandidate(id=f"state:{rid}:{item['state_key']}",lane="current_state",source_type="structured_state",source_id=item.get("source_event_id") or rid,text=f"{resource.get('label',rid)}.{item['state_key']} = {item['value']!r}",display_excerpt=f"{item['state_key']}: {item['value']!r}",world_id=scope.world_id,branch_id=scope.branch_id,authority=item.get("authority","user_accepted_world_canon"),source_rank=index,metadata={"structured":True,"value":item["value"]}))
            elif plan.route.value == "TEMPORAL_STATE" and scope.world_id and scope.story_order is not None:
                for index,item in enumerate(self.store.state_at(world_id=scope.world_id, branch_id=scope.branch_id, owner_id=rid, story_order=scope.story_order),1):
                    result.append(MemoryCandidate(id=f"interval:{item['id']}",lane="state_intervals",source_type="state_interval",source_id=item.get("source_event_id") or item["id"],text=f"{resource.get('label',rid)}.{item['state_key']} = {item['value']!r}",display_excerpt=f"{item['state_key']}: {item['value']!r}",world_id=scope.world_id,branch_id=scope.branch_id,story_order=scope.story_order,authority=item.get("authority","user_accepted_world_canon"),source_rank=index,metadata={"structured":True,"value":item["value"]}))
            elif plan.route.value == "SPATIAL_LOOKUP":
                node=self.store.find_spatial_node(resource.get("type","entity_family"),rid,world_id=scope.world_id,branch_id=scope.branch_id)
                if node:
                    ancestors=self.store.spatial_ancestors(node["id"],world_id=scope.world_id,branch_id=scope.branch_id)
                    neighborhood=self.store.spatial_neighborhood(node["id"],world_id=scope.world_id,branch_id=scope.branch_id,recursive=False)
                    labels=" → ".join([node["label"]]+[item["label"] for item in ancestors])
                    result.append(MemoryCandidate(id=f"spatial:{node['id']}",lane="spatial",source_type="spatial_graph",source_id=node["id"],text=f"Spatial path: {labels}\nNearby: {', '.join(item['label'] for item in neighborhood['nodes'] if item['id'] != node['id'])}",display_excerpt=labels,world_id=scope.world_id,branch_id=scope.branch_id,authority="user_accepted_world_canon",source_rank=1,metadata={"structured":True,"node":node,"ancestors":ancestors,"neighborhood":neighborhood}))
        if plan.route.value == "THREAD_LOOKUP":
            for index,thread in enumerate(self.store.list_threads(project_id=scope.project_id,world_id=scope.world_id,branch_id=scope.branch_id,status="open"),1):
                result.append(MemoryCandidate(id=f"thread:{thread['id']}",lane="threads",source_type="story_thread",source_id=thread["id"],text=f"{thread['thread_type']}: {thread['title']}\n{thread['description']}",display_excerpt=thread["title"],project_id=thread.get("project_id"),world_id=thread.get("world_id"),branch_id=thread.get("branch_id"),authority="user_accepted_world_canon",source_rank=index,metadata={"structured":True,"thread":thread}))
        if plan.route.value == "EPISTEMIC_STATE" and scope.pov_variant_id and resources and scope.world_id:
            for index,resource in enumerate(resources,1):
                for item in self.store.epistemic_state(character_variant_id=scope.pov_variant_id,topic_type=resource.get("type","entity_family"),topic_id=resource["id"],world_id=scope.world_id,branch_id=scope.branch_id,story_order=scope.story_order):
                    result.append(MemoryCandidate(id=f"epistemic:{item['id']}",lane="epistemic",source_type="epistemic_state",source_id=item.get("source_event_id") or item["id"],text=f"{item['state_type']}: {item['value']!r} (confidence {item['confidence']:.2f})",display_excerpt=f"{item['state_type']}: {item['value']!r}",world_id=scope.world_id,branch_id=scope.branch_id,story_order=scope.story_order,authority="accepted_event",source_rank=index,metadata={"structured":True,"epistemic":item}))
        return result

    @staticmethod
    def _rrf(lanes: dict[str,list[MemoryCandidate]], k: int = 60) -> list[MemoryCandidate]:
        merged: dict[str,MemoryCandidate]={}
        for lane,items in lanes.items():
            for rank,item in enumerate(items,1):
                current=merged.get(item.id)
                if current is None: current=item; merged[item.id]=current
                current.fused_score += 1.0/(k+rank)
                current.fused_score += AUTHORITY_BOOST.get(current.authority,0.0)
                current.fused_score += min(0.08,max(0.0,current.importance)*0.04)
        return sorted(merged.values(),key=lambda item:item.fused_score,reverse=True)

    def execute(self, plan: QueryPlan) -> RetrievalResult:
        run_id=self.store.begin_retrieval(plan.query,plan.route.value,plan.scope.to_dict(),plan.to_dict())
        lanes: dict[str,list[MemoryCandidate]]=defaultdict(list)
        structured=self._structured(plan)
        for item in structured: lanes[item.lane].append(item)
        if "fts" in plan.required_lanes or "fts" in plan.optional_lanes:
            for row in self.store.search_fts(plan.query,domains=plan.domains,limit=plan.per_lane_budget):
                lanes[f"fts:{row.get('domain','memory')}"] .append(self._candidate(row,f"fts:{row.get('domain','memory')}",int(row.get("rank",1))))
        if plan.resolved_resources:
            for rank,row in enumerate(self.store.linked_chunks(plan.resolved_resources,limit=plan.per_lane_budget),1): lanes["links"].append(self._candidate(row,"links",rank))
        if self.dense_enabled and self.embedding_provider and ("dense" in plan.optional_lanes or "dense" in plan.required_lanes):
            try:
                vector=self.embedding_provider.embed_query(plan.query)
                generation=self.store.active_generation(); generation_id=int(generation["generation_id"]) if generation else None
                for rank,row in enumerate(self.store.vector_candidates(vector,generation_id=generation_id,limit=plan.per_lane_budget),1): lanes["dense"].append(self._candidate(row,"dense",rank))
            except EmbeddingUnavailable:
                pass
        excluded=[]; allowed: dict[str,list[MemoryCandidate]]=defaultdict(list)
        for lane,items in lanes.items():
            for item in items:
                decision=self.gate.decide(item,plan.scope)
                if decision.allowed: allowed[lane].append(item)
                else: excluded.append({"candidate":item.to_dict(),"reason":decision.reason})
        fused=self._rrf(allowed)
        selected=[]; per_source=defaultdict(int); tokens=0
        for item in fused:
            key=(item.source_type,item.source_id)
            if per_source[key]>=self.max_items_per_source: excluded.append({"candidate":item.to_dict(),"reason":"source diversity cap"}); continue
            if len(selected)>=plan.final_budget: excluded.append({"candidate":item.to_dict(),"reason":"candidate budget"}); continue
            if selected and tokens+item.token_count>plan.token_budget: excluded.append({"candidate":item.to_dict(),"reason":"token budget"}); continue
            selected.append(item); per_source[key]+=1; tokens+=item.token_count
        abstained=not selected and plan.require_abstention
        result=RetrievalResult(run_id=run_id,plan=plan,selected=selected,excluded=excluded,lane_counts={lane:len(items) for lane,items in lanes.items()},abstained=abstained,abstention_reason="No admissible evidence in the active scope" if abstained else "")
        self.store.finish_retrieval(run_id,[item.to_dict() for item in selected],excluded)
        return result
''')

write("src/memory/service.py", r'''
from __future__ import annotations

from pathlib import Path
import sqlite3
from typing import Any

from .config import MemorySettings
from .embedding import LMStudioEmbeddingProvider, NullEmbeddingProvider
from .index import MemoryIndexer
from .models import ContextLens, MemoryQueryContext, RetrievalMode
from .query import QueryCompiler
from .retrieve import MemoryRetriever
from .security import wrap_evidence
from .spatial import SpatialService
from .store import MemoryStore
from .temporal import TemporalStateService


class MemoryService:
    def __init__(self, *, database_path, config_path, lmstudio_base_url, lmstudio_api_key=""):
        self.settings=MemorySettings.load(config_path)
        self.store=MemoryStore(database_path)
        if self.settings.dense_enabled and self.settings.embedding.provider == "lmstudio":
            self.embedding=LMStudioEmbeddingProvider(base_url=lmstudio_base_url,model=self.settings.embedding.model,api_key=lmstudio_api_key,timeout_seconds=self.settings.embedding.timeout_seconds,query_prefix=self.settings.embedding.query_prefix,passage_prefix=self.settings.embedding.passage_prefix)
        else: self.embedding=NullEmbeddingProvider()
        self.indexer=MemoryIndexer(self.store,database_path=database_path,embedding_provider=self.embedding,dense_enabled=self.settings.dense_enabled)
        self.retriever=MemoryRetriever(self.store,embedding_provider=self.embedding,dense_enabled=self.settings.dense_enabled,max_items_per_source=self.settings.max_items_per_source)
        self.temporal=TemporalStateService(self.store)
        self.spatial=SpatialService(self.store)
        self.database_path=str(database_path)

    def _branch_visibility(self, branch_id: str | None) -> None:
        if not branch_id: return
        rows=[]; current=branch_id; depth=0; inherited_cutoff=None
        with sqlite3.connect(self.database_path) as con:
            con.row_factory=sqlite3.Row
            while current and depth<64:
                try: row=con.execute("SELECT id,parent_branch_id,fork_event_id,fork_story_order FROM world_branches WHERE id=?",(current,)).fetchone()
                except sqlite3.OperationalError: row=con.execute("SELECT id,parent_branch_id,NULL AS fork_event_id,NULL AS fork_story_order FROM world_branches WHERE id=?",(current,)).fetchone()
                if not row: break
                rows.append({"visible_branch_id":row["id"],"depth":depth,"max_story_order":inherited_cutoff,"fork_event_id":row["fork_event_id"]})
                inherited_cutoff=row["fork_story_order"] if row["fork_story_order"] is not None else inherited_cutoff
                current=row["parent_branch_id"]; depth+=1
        if rows: self.store.set_branch_visibility(branch_id,rows)

    def _session_scope(self, session_id: str | None) -> dict[str,float|None]:
        if not session_id: return {}
        result={session_id:None}; current=session_id
        with sqlite3.connect(self.database_path) as con:
            con.row_factory=sqlite3.Row
            for _ in range(64):
                try: row=con.execute("SELECT parent_session_id,forked_from_turn_id FROM sessions WHERE id=?",(current,)).fetchone()
                except sqlite3.OperationalError: break
                if not row or not row["parent_session_id"]: break
                cutoff=None
                if row["forked_from_turn_id"]:
                    turn=con.execute("SELECT rowid FROM turns WHERE id=?",(row["forked_from_turn_id"],)).fetchone(); cutoff=float(turn[0]) if turn else None
                current=row["parent_session_id"]; result[current]=cutoff
        return result

    def resolve_resources(self, references: list[dict[str,Any]], query: str) -> list[dict[str,Any]]:
        result=[]; seen=set()
        for ref in references:
            if ref.get("id") and (ref.get("type"),ref.get("id")) not in seen:
                seen.add((ref.get("type"),ref.get("id"))); result.append({"type":ref.get("type"),"id":ref.get("id"),"label":ref.get("label") or ref.get("id")})
        with sqlite3.connect(self.database_path) as con:
            con.row_factory=sqlite3.Row
            try:
                rows=con.execute("SELECT id,name FROM entity_families UNION ALL SELECT resource_id,alias FROM resource_aliases WHERE resource_type='entity_family'").fetchall()
            except sqlite3.OperationalError: rows=con.execute("SELECT id,name FROM entity_families").fetchall()
        folded=query.casefold()
        for row in sorted(rows,key=lambda row:len(row[1]),reverse=True):
            key=("entity_family",row[0])
            if key not in seen and row[1].casefold() in folded:
                seen.add(key); result.append({"type":"entity_family","id":row[0],"label":row[1]})
        return result

    def query(self, query: str, *, project_id=None, world_id=None, branch_id=None, session_id=None, current_turn_id=None, story_order=None, pov_variant_id=None, context_lens="scene", retrieval_mode="standard", explicit_references=None, allow_scratch=False, allow_future_author_knowledge=False, refresh=True):
        if not self.settings.enabled: return {"disabled":True,"selected":[],"excluded":[]}
        self._branch_visibility(branch_id)
        if refresh and self.settings.auto_refresh: self.indexer.refresh(project_id=project_id,world_id=world_id,branch_id=branch_id)
        try: lens=ContextLens(context_lens)
        except ValueError: lens=ContextLens.SCENE
        try: mode=RetrievalMode(retrieval_mode)
        except ValueError: mode=RetrievalMode.STANDARD
        resources=self.resolve_resources(explicit_references or [],query)
        scope=MemoryQueryContext(project_id=project_id,world_id=world_id,branch_id=branch_id,session_id=session_id,current_turn_id=current_turn_id,story_order=story_order,pov_variant_id=pov_variant_id,context_lens=lens,retrieval_mode=mode,explicit_references=explicit_references or [],visible_sessions=self._session_scope(session_id),allow_scratch=allow_scratch,allow_future_author_knowledge=allow_future_author_knowledge)
        plan=QueryCompiler.compile(query,scope,resolved_resources=resources,final_budget=self.settings.selected_items,max_candidates=self.settings.max_candidates)
        return self.retriever.execute(plan).to_dict()

    def context_fragment(self, query: str, **scope) -> dict[str,Any]:
        result=self.query(query,**scope)
        if result.get("disabled"): return {"text":"","trace":result}
        lines=["[MEMORY QUERY]",f"route: {result['plan']['route']}",f"lens: {result['plan']['scope']['context_lens']}"]
        if result.get("abstained"):
            lines.extend(["",f"ABSTAIN: {result.get('abstention_reason')}"])
        else:
            lines.extend(["","[ADMITTED EVIDENCE]"])
            for index,item in enumerate(result["selected"],1):
                lines.append(f"{index}. lane={item['lane']} authority={item['authority']} source={item['source_type']}:{item['source_id']}")
                lines.append(wrap_evidence(item["text"],source_type=item["source_type"],source_id=item["source_id"],trust_level=item["trust_level"]))
        if result.get("excluded"):
            lines.extend(["","[EXCLUDED CANDIDATES]"])
            for item in result["excluded"][:20]: lines.append(f"- {item['reason']}: {item['candidate'].get('source_type')}:{item['candidate'].get('source_id')}")
        return {"text":"\n".join(lines),"trace":result}

    def backfill(self, **scope): return self.indexer.refresh(**scope)
    def status(self): return {"enabled":self.settings.enabled,"dense_enabled":self.settings.dense_enabled,"embedding_provider":self.settings.embedding.provider,"embedding_model":self.settings.embedding.model,"reranker_enabled":self.settings.reranker.enabled,"store":self.store.status()}
''')

write("src/memory/web.py", r'''
from __future__ import annotations

from typing import Any
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field


class MemoryQueryPayload(BaseModel):
    query: str
    project_id: str | None = None
    world_id: str | None = None
    branch_id: str | None = None
    session_id: str | None = None
    current_turn_id: str | None = None
    story_order: float | None = None
    pov_variant_id: str | None = None
    context_lens: str = "scene"
    retrieval_mode: str = "standard"
    explicit_references: list[dict[str,Any]] = Field(default_factory=list)
    allow_scratch: bool = False
    allow_future_author_knowledge: bool = False
    refresh: bool = True


class BackfillPayload(BaseModel):
    project_id: str | None = None
    world_id: str | None = None
    branch_id: str | None = None


class StatePayload(BaseModel):
    world_id: str
    branch_id: str | None = None
    owner_type: str
    owner_id: str
    state_key: str
    value: Any
    source_event_id: str | None = None
    authority: str = "user_accepted"


class SpatialNodePayload(BaseModel):
    resource_type: str | None = None
    resource_id: str | None = None
    label: str
    spatial_kind: str = "place"
    world_id: str | None = None
    branch_id: str | None = None
    metadata: dict[str,Any] = Field(default_factory=dict)


class SpatialEdgePayload(BaseModel):
    subject_node_id: str
    relation: str
    object_node_id: str
    world_id: str | None = None
    branch_id: str | None = None
    valid_from_order: float | None = None
    valid_to_order: float | None = None
    authority: str = "user_accepted"
    source_id: str | None = None


class EpistemicPayload(BaseModel):
    character_variant_id: str
    topic_type: str
    topic_id: str
    state_type: str
    value: Any
    confidence: float = 1.0
    world_id: str
    branch_id: str | None = None
    valid_from_order: float | None = None
    valid_to_order: float | None = None
    source_event_id: str | None = None


class ThreadPayload(BaseModel):
    thread_type: str = "mystery"
    title: str
    description: str = ""
    status: str = "open"
    project_id: str | None = None
    world_id: str | None = None
    branch_id: str | None = None
    opened_order: float | None = None
    resolved_order: float | None = None
    source_id: str | None = None
    metadata: dict[str,Any] = Field(default_factory=dict)
    links: list[dict[str,str]] = Field(default_factory=list)


def register_memory_routes(app: FastAPI, service) -> None:
    @app.get("/api/memory/status")
    def memory_status(): return service.status()

    @app.post("/api/memory/backfill")
    def memory_backfill(payload: BackfillPayload): return service.backfill(project_id=payload.project_id,world_id=payload.world_id,branch_id=payload.branch_id)

    @app.post("/api/memory/query")
    def memory_query(payload: MemoryQueryPayload):
        try: return service.query(**payload.model_dump())
        except Exception as exc: raise HTTPException(status_code=400,detail=str(exc)) from exc

    @app.get("/api/memory/retrieval/{run_id}")
    def memory_retrieval(run_id: str):
        try: return service.store.get_retrieval(run_id)
        except KeyError as exc: raise HTTPException(status_code=404,detail="Retrieval run not found") from exc

    @app.post("/api/memory/state")
    def set_memory_state(payload: StatePayload): service.store.set_current_state(**payload.model_dump()); return {"ok":True}

    @app.get("/api/memory/state")
    def get_memory_state(world_id: str,owner_id: str,branch_id: str|None=None,state_key: str|None=None,story_order: float|None=None):
        if story_order is None: return {"state":service.temporal.current(world_id=world_id,branch_id=branch_id,owner_id=owner_id,state_key=state_key)}
        return {"state":service.temporal.at(world_id=world_id,branch_id=branch_id,owner_id=owner_id,story_order=story_order,state_key=state_key)}

    @app.post("/api/memory/spatial/nodes")
    def create_spatial_node(payload: SpatialNodePayload): return service.store.ensure_spatial_node(**payload.model_dump())

    @app.get("/api/memory/spatial/node")
    def get_spatial_resource(resource_type: str,resource_id: str,world_id: str|None=None,branch_id: str|None=None):
        node=service.store.find_spatial_node(resource_type,resource_id,world_id=world_id,branch_id=branch_id)
        if not node: raise HTTPException(status_code=404,detail="Spatial node not found")
        return {"node":node,"neighborhood":service.store.spatial_neighborhood(node["id"],world_id=world_id,branch_id=branch_id),"ancestors":service.store.spatial_ancestors(node["id"],world_id=world_id,branch_id=branch_id)}

    @app.post("/api/memory/spatial/edges")
    def create_spatial_edge(payload: SpatialEdgePayload):
        try: return service.store.add_spatial_edge(**payload.model_dump())
        except (ValueError,KeyError) as exc: raise HTTPException(status_code=400,detail=str(exc)) from exc

    @app.delete("/api/memory/spatial/edges/{edge_id}")
    def delete_spatial_edge(edge_id: str):
        try: service.store.delete_spatial_edge(edge_id); return {"deleted":edge_id}
        except KeyError as exc: raise HTTPException(status_code=404,detail="Spatial edge not found") from exc

    @app.post("/api/memory/epistemic")
    def create_epistemic(payload: EpistemicPayload): return {"id":service.store.add_epistemic_interval(**payload.model_dump())}

    @app.get("/api/memory/epistemic")
    def get_epistemic(character_variant_id: str,topic_type: str,topic_id: str,world_id: str,branch_id: str|None=None,story_order: float|None=None): return {"state":service.store.epistemic_state(character_variant_id=character_variant_id,topic_type=topic_type,topic_id=topic_id,world_id=world_id,branch_id=branch_id,story_order=story_order)}

    @app.post("/api/memory/threads")
    def create_thread(payload: ThreadPayload):
        data=payload.model_dump(); links=data.pop("links",[]); thread=service.store.create_thread(**data)
        for link in links: service.store.link_thread(thread["id"],link["resource_type"],link["resource_id"],link.get("relation","subject"))
        return service.store.get_thread(thread["id"])

    @app.get("/api/memory/threads")
    def list_threads(project_id: str|None=None,world_id: str|None=None,branch_id: str|None=None,status: str|None=None): return {"threads":service.store.list_threads(project_id=project_id,world_id=world_id,branch_id=branch_id,status=status)}

    @app.patch("/api/memory/threads/{thread_id}")
    def update_thread(thread_id: str,payload: dict[str,Any]):
        try: return service.store.update_thread(thread_id,**payload)
        except KeyError as exc: raise HTTPException(status_code=404,detail="Thread not found") from exc
''')

write("src/memory/__init__.py", r'''
from .config import EmbeddingSettings, MemorySettings, RerankerSettings
from .embedding import EmbeddingUnavailable, LMStudioEmbeddingProvider, NullEmbeddingProvider
from .index import MemoryIndexer, StructuralChunker
from .models import ContextLens, GateDecision, MemoryCandidate, MemoryQueryContext, QueryPlan, QueryRoute, RetrievalMode, RetrievalResult
from .query import QueryCompiler, QueryRouter
from .retrieve import MemoryRetriever
from .scope import ScopeGate
from .service import MemoryService
from .spatial import SpatialService
from .store import MEMORY_SCHEMA_VERSION, MemoryStore
from .temporal import TemporalStateService
from .web import register_memory_routes

__all__ = [
    "ContextLens","EmbeddingSettings","EmbeddingUnavailable","GateDecision","LMStudioEmbeddingProvider","MEMORY_SCHEMA_VERSION",
    "MemoryCandidate","MemoryIndexer","MemoryQueryContext","MemoryRetriever","MemoryService","MemorySettings","MemoryStore",
    "NullEmbeddingProvider","QueryCompiler","QueryPlan","QueryRoute","QueryRouter","RerankerSettings","RetrievalMode","RetrievalResult",
    "ScopeGate","SpatialService","StructuralChunker","TemporalStateService","register_memory_routes",
]
''')

write("src/eval/memory.py", r'''
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(slots=True)
class RetrievalMetrics:
    recall_at_k: float
    reciprocal_rank: float
    forbidden_source_rate: float
    temporal_validity_rate: float
    branch_isolation_rate: float


def score_retrieval(selected_ids: list[str], expected_ids: set[str], forbidden_ids: set[str], *, k: int = 10, temporally_valid: Iterable[bool] | None = None, branch_valid: Iterable[bool] | None = None) -> RetrievalMetrics:
    top=selected_ids[:k]
    recall=len(expected_ids.intersection(top))/max(1,len(expected_ids))
    reciprocal=0.0
    for rank,item in enumerate(selected_ids,1):
        if item in expected_ids: reciprocal=1.0/rank; break
    forbidden=len(forbidden_ids.intersection(top))/max(1,len(top))
    temporal=list(temporally_valid or [True]*len(top)); branch=list(branch_valid or [True]*len(top))
    return RetrievalMetrics(recall,reciprocal,forbidden, sum(temporal)/max(1,len(temporal)), sum(branch)/max(1,len(branch)))
''')

# Workspace schema extensions are added here so the pre-migration backup is
# performed by WorkspaceStore before any v1.2 table/column changes.
workspace_path="src/workspace/store.py"
workspace=read(workspace_path)
workspace=workspace.replace("WORKSPACE_SCHEMA_VERSION = 7","WORKSPACE_SCHEMA_VERSION = 8")
marker="""            con.execute(\n                \"INSERT INTO workspace_meta(key,value) VALUES('schema_version',?) \""" 
if "fork_story_order" not in workspace:
    migration='''            # v1.2 branch/time metadata. Hot query dimensions are normalized\n            # rather than repeatedly parsed from JSON during retrieval.\n            for table, column, definition in (\n                (\"world_branches\", \"fork_event_id\", \"TEXT\"),\n                (\"world_branches\", \"fork_world_time_json\", \"TEXT\"),\n                (\"world_branches\", \"fork_story_order\", \"REAL\"),\n                (\"world_branches\", \"inheritance_mode\", \"TEXT NOT NULL DEFAULT 'inherit_until_fork'\"),\n                (\"timeline_events\", \"event_schema_version\", \"INTEGER NOT NULL DEFAULT 1\"),\n                (\"timeline_events\", \"world_time_json\", \"TEXT\"),\n                (\"timeline_events\", \"story_order\", \"REAL\"),\n                (\"timeline_events\", \"location_variant_id\", \"TEXT\"),\n                (\"timeline_events\", \"participants_json\", \"TEXT NOT NULL DEFAULT '[]'\"),\n                (\"timeline_events\", \"causal_links_json\", \"TEXT NOT NULL DEFAULT '[]'\"),\n                (\"timeline_events\", \"confidence\", \"REAL NOT NULL DEFAULT 1.0\"),\n                (\"timeline_events\", \"importance\", \"REAL NOT NULL DEFAULT 0.5\"),\n                (\"timeline_events\", \"supersedes_event_id\", \"TEXT\"),\n                (\"timeline_events\", \"accepted_at\", \"TEXT\"),\n                (\"canon_facts\", \"valid_from_event_id\", \"TEXT\"),\n                (\"canon_facts\", \"valid_to_event_id\", \"TEXT\"),\n                (\"canon_facts\", \"supersedes_fact_id\", \"TEXT\"),\n                (\"canon_facts\", \"accepted_at\", \"TEXT\"),\n                (\"world_snapshots\", \"snapshot_kind\", \"TEXT NOT NULL DEFAULT 'manual'\"),\n                (\"world_snapshots\", \"base_event_id\", \"TEXT\"),\n                (\"world_snapshots\", \"world_time_json\", \"TEXT\"),\n                (\"world_snapshots\", \"story_order\", \"REAL\"),\n                (\"world_snapshots\", \"state_schema_version\", \"INTEGER NOT NULL DEFAULT 1\"),\n                (\"world_snapshots\", \"index_generation\", \"INTEGER\"),\n            ):\n                columns = {row[\"name\"] for row in con.execute(f\"PRAGMA table_info({table})\").fetchall()}\n                if column not in columns:\n                    con.execute(f\"ALTER TABLE {table} ADD COLUMN {column} {definition}\")\n\n'''
    if marker not in workspace: raise RuntimeError("workspace schema-version marker missing")
    workspace=workspace.replace(marker,migration+marker,1)
write(workspace_path,workspace)

# Foundation schema version follows the shared SQLite workspace generation.
foundation_path="src/workspace/foundation.py"; foundation=read(foundation_path).replace("SCHEMA_VERSION = 7","SCHEMA_VERSION = 8"); write(foundation_path,foundation)

# Context resolver integration is deliberately optional: v1.1 behavior remains
# the exact fallback if memory is disabled or fails.
context_path="src/workspace/context.py"; context=read(context_path)
if "memory_service" not in context:
    context=context.replace("    def __init__(self, store", "    def __init__(self, store",1)
    # Patch constructor by matching its first complete signature.
    context=re.sub(r"def __init__\(self, store: WorkspaceStore([^)]*)\):",r"def __init__(self, store: WorkspaceStore\1, memory_service=None):",context,count=1)
    init_anchor="        self.store = store"
    if init_anchor in context: context=context.replace(init_anchor,init_anchor+"\n        self.memory_service = memory_service",1)
    # Add optional query parameters to resolve. Existing callers continue to work.
    context=re.sub(r"(def resolve\(\s*self,)(.*?)\n    \) -> WorkspaceContext:",lambda m:m.group(1)+m.group(2)+"\n        query_text: str = \"\",\n        session_id: str | None = None,\n        current_turn_id: str | None = None,\n        context_lens: str = \"scene\",\n        story_order: float | None = None,\n        pov_variant_id: str | None = None,\n    ) -> WorkspaceContext:",context,count=1,flags=re.S)
    # Memory is appended as attributed evidence before context text is finalized.
    text_anchor='        text = "\\n".join(lines).strip()'
    memory_block='''        memory_trace = None\n        if self.memory_service is not None and query_text.strip():\n            try:\n                memory_result = self.memory_service.context_fragment(\n                    query_text, project_id=project_id, world_id=world_id, branch_id=branch_id,\n                    session_id=session_id, current_turn_id=current_turn_id, story_order=story_order,\n                    pov_variant_id=pov_variant_id, context_lens=context_lens, explicit_references=references or [],\n                    allow_scratch=False, refresh=True,\n                )\n                if memory_result.get(\"text\"):\n                    lines.extend([\"\", memory_result[\"text\"]])\n                memory_trace = memory_result.get(\"trace\")\n            except Exception as exc:  # retrieval must never break normal writing\n                memory_trace = {\"status\": \"fallback\", \"error\": str(exc)}\n\n'''
    if text_anchor in context: context=context.replace(text_anchor,memory_block+text_anchor,1)
    # Expose trace through the existing result object without requiring a DB migration.
    return_anchor="            text=text,"
    if return_anchor in context: context=context.replace(return_anchor,return_anchor+"\n            memory_trace=memory_trace,",1)
    # Dataclass field and to_dict serialization.
    field_anchor="    text: str"
    if field_anchor in context: context=context.replace(field_anchor,field_anchor+"\n    memory_trace: dict[str, Any] | None = None",1)
    dict_anchor='            "text": self.text,'
    if dict_anchor in context: context=context.replace(dict_anchor,dict_anchor+'\n            "memory_trace": self.memory_trace,',1)
write(context_path,context)

# FastAPI wiring.
app_path="src/interface/web/app.py"; app=read(app_path)
if "from src.memory import MemoryService, register_memory_routes" not in app:
    import_anchor="from src.history import HistoryStore"
    if import_anchor in app: app=app.replace(import_anchor,import_anchor+"\nfrom src.memory import MemoryService, register_memory_routes",1)
    else: app="from src.memory import MemoryService, register_memory_routes\n"+app
if "memory_service = MemoryService(" not in app:
    anchor="    foundation = FoundationStore(initial_cfg.workspace.database_path)"
    block=anchor+'''\n    memory_service = MemoryService(\n        database_path=initial_cfg.workspace.database_path,\n        config_path=config_path,\n        lmstudio_base_url=initial_cfg.lmstudio.base_url,\n        lmstudio_api_key=initial_cfg.lmstudio.api_key,\n    )'''
    if anchor not in app: raise RuntimeError("FoundationStore initialization anchor missing")
    app=app.replace(anchor,block,1)
# Pass memory into the existing resolver constructor.
app=re.sub(r"WorkspaceContextResolver\(workspace\)(?!,)","WorkspaceContextResolver(workspace, memory_service=memory_service)",app)
if "register_memory_routes(app, memory_service)" not in app:
    fastapi_anchor="    app = FastAPI("
    pos=app.find(fastapi_anchor)
    if pos<0: raise RuntimeError("FastAPI constructor anchor missing")
    # Insert registration after the constructor block by locating first line after title/version block.
    close=app.find("\n    )",pos)
    if close<0: raise RuntimeError("FastAPI constructor close missing")
    close=app.find("\n",close+1)
    app=app[:close+1]+"    register_memory_routes(app, memory_service)\n"+app[close+1:]
# Supply query text to resolver calls when the payload is available.
app=app.replace("recipe_id=payload.context_recipe_id,\n        )","recipe_id=payload.context_recipe_id,\n            query_text=payload.prompt, session_id=payload.session_id,\n        )")
app=app.replace("recipe_id=payload.context_recipe_id,\n            )","recipe_id=payload.context_recipe_id,\n                query_text=payload.prompt, session_id=payload.session_id,\n            )")
write(app_path,app)

# Memory developer UI is isolated from the large v1.1 frontend file.
write("src/interface/web/static/js/memory.js", r'''
(() => {
  const api = async (path, options = {}) => {
    const response = await fetch(path, { headers: { "Content-Type": "application/json", ...(options.headers || {}) }, ...options, body: options.body && typeof options.body !== "string" ? JSON.stringify(options.body) : options.body });
    if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || response.statusText);
    return response.json();
  };
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));

  async function refreshStatus() {
    const target = document.getElementById("memoryStatusCard"); if (!target) return;
    try {
      const status = await api("/api/memory/status");
      const counts = status.store?.counts || {};
      target.innerHTML = `<b>Memory Query Engine</b><div><span>Mode</span><strong>${status.dense_enabled ? "FTS + dense" : "Structured + FTS"}</strong></div><div><span>Embedding</span><strong>${esc(status.embedding_model)}</strong></div><div><span>Chunks</span><strong>${counts.memory_chunks || 0}</strong></div><div><span>Spatial links</span><strong>${counts.spatial_edges || 0}</strong></div>`;
    } catch (error) { target.textContent = `Memory unavailable: ${error.message}`; }
  }

  async function runBackfill() {
    const button = document.getElementById("memoryBackfillBtn"); if (!button) return;
    button.disabled = true; button.textContent = "Indexing…";
    try { const result = await api("/api/memory/backfill", { method: "POST", body: {} }); button.textContent = `Indexed ${result.documents || 0} docs · ${result.turns || 0} turns`; await refreshStatus(); }
    catch (error) { button.textContent = `Failed: ${error.message}`; }
    finally { setTimeout(() => { button.disabled = false; button.textContent = "Refresh memory index"; }, 2500); }
  }

  async function testQuery() {
    const input = document.getElementById("memoryTestQuery"); const output = document.getElementById("memoryTraceOutput");
    if (!input?.value.trim() || !output) return;
    output.textContent = "Compiling query…";
    try { output.textContent = JSON.stringify(await api("/api/memory/query", { method: "POST", body: { query: input.value, retrieval_mode: "debug", refresh: true } }), null, 2); }
    catch (error) { output.textContent = error.message; }
  }

  function bindSettings() {
    document.getElementById("memoryBackfillBtn")?.addEventListener("click", runBackfill);
    document.getElementById("memoryTestBtn")?.addEventListener("click", testQuery);
    const tab = document.querySelector('[data-inspector-tab="memory"]');
    tab?.addEventListener("click", refreshStatus);
  }

  async function mountSpatialSection({ resourceType, resourceId, label, spatialKind = "place", worldId = null, branchId = null }) {
    const body = document.getElementById("sheetBody"); if (!body || !resourceId) return;
    body.querySelector("[data-memory-spatial]")?.remove();
    const section = document.createElement("section"); section.className = "sheet-section"; section.dataset.memorySpatial = "1";
    section.innerHTML = `<div class="sheet-section-head"><h3>Linked space</h3><button class="tiny-btn" data-spatial-add>＋ Link</button></div><div data-spatial-content class="empty-note">Loading spatial links…</div>`;
    body.appendChild(section);
    const content = section.querySelector("[data-spatial-content]");
    let node;
    try {
      const data = await api(`/api/memory/spatial/node?resource_type=${encodeURIComponent(resourceType)}&resource_id=${encodeURIComponent(resourceId)}&world_id=${encodeURIComponent(worldId || "")}&branch_id=${encodeURIComponent(branchId || "")}`);
      node = data.node;
      const nearby = data.neighborhood?.nodes?.filter((item) => item.id !== node.id) || [];
      const path = [node.label, ...(data.ancestors || []).map((item) => item.label)].join(" → ");
      content.innerHTML = `<b>${esc(path)}</b><small>${nearby.length ? `Linked: ${nearby.map((item) => esc(item.label)).join(", ")}` : "No linked contents yet."}</small>`;
    } catch (_) {
      node = await api("/api/memory/spatial/nodes", { method: "POST", body: { resource_type: resourceType, resource_id: resourceId, label, spatial_kind: spatialKind, world_id: worldId, branch_id: branchId } });
      content.innerHTML = `<b>${esc(label)}</b><small>No linked contents yet.</small>`;
    }
    section.querySelector("[data-spatial-add]")?.addEventListener("click", async () => {
      const targetType = prompt("Target resource type", "entity_family"); if (!targetType) return;
      const targetId = prompt("Target resource ID"); if (!targetId) return;
      const targetLabel = prompt("Target label", targetId) || targetId;
      const relation = prompt("Relation: contains / part_of / inside / stored_in / on / under / adjacent_to / connected_to", "contains") || "contains";
      try {
        const target = await api("/api/memory/spatial/nodes", { method: "POST", body: { resource_type: targetType, resource_id: targetId, label: targetLabel, spatial_kind: "place", world_id: worldId, branch_id: branchId } });
        await api("/api/memory/spatial/edges", { method: "POST", body: { subject_node_id: node.id, relation, object_node_id: target.id, world_id: worldId, branch_id: branchId } });
        await mountSpatialSection({ resourceType, resourceId, label, spatialKind, worldId, branchId });
      } catch (error) { alert(error.message); }
    });
  }

  window.ArlineMemoryUI = { refreshStatus, mountSpatialSection };
  document.addEventListener("DOMContentLoaded", bindSettings);
})();
''')

# Add Memory settings tab and panel, and load the module.
index_path="src/interface/web/static/index.html"; index=read(index_path)
if 'data-inspector-tab="memory"' not in index:
    index=index.replace('<button data-inspector-tab="review">Review & Evals</button>','<button data-inspector-tab="memory">Memory & Retrieval</button>\n        <button data-inspector-tab="review">Review & Evals</button>',1)
    panel='''      <div class="inspector-panel" data-inspector-panel="memory">\n        <span class="eyebrow">Developer · v1.2</span><h3>Memory & Retrieval</h3>\n        <div id="memoryStatusCard" class="info-card">Open this section to inspect the Memory Query Engine.</div>\n        <button id="memoryBackfillBtn" class="secondary-btn wide">Refresh memory index</button>\n        <label>Test query<input id="memoryTestQuery" placeholder="Where is the black dress?" /></label>\n        <button id="memoryTestBtn" class="secondary-btn wide">Compile and retrieve</button>\n        <pre id="memoryTraceOutput" class="json-block">No retrieval trace yet.</pre>\n      </div>\n'''
    anchor='      <div class="inspector-panel" data-inspector-panel="review">'
    if anchor not in index: raise RuntimeError("Review panel anchor missing")
    index=index.replace(anchor,panel+anchor,1)
if 'static/js/memory.js' not in index:
    index=index.replace('<script src="/static/js/stream.js', '<script src="/static/js/memory.js?v=1.2.0-alpha1"></script>\n  <script src="/static/js/stream.js',1)
write(index_path,index)

# Inject spatial inspector enhancer into the existing entity sheet function.
arline_path="src/interface/web/static/arline.js"; arline=read(arline_path)
if "ArlineMemoryUI?.mountSpatialSection" not in arline:
    block=function_block(arline,"openEntitySheet")
    if block:
        start,end=block; function=arline[start:end]
        insert='''\n  window.ArlineMemoryUI?.mountSpatialSection({\n    resourceType: variant ? "entity_variant" : "entity_family",\n    resourceId: variant?.id || family.id,\n    label: variant?.display_name || family.name,\n    spatialKind: family.entity_type === "location" ? "location" : family.entity_type,\n    worldId: state.activeWorld?.id || null,\n    branchId: state.activeBranch?.kind === "main" ? null : state.activeBranch?.id || null,\n  });\n'''
        marker="  openSheet();"
        pos=function.rfind(marker)
        if pos>=0: function=function[:pos]+insert+function[pos:]; arline=arline[:start]+function+arline[end:]
write(arline_path,arline)

css_path="src/interface/web/static/arline.css"; css=read(css_path)
if "/* v1.2 memory */" not in css:
    css += '''\n/* v1.2 memory */\n[data-inspector-panel="memory"] .json-block{max-height:420px;overflow:auto;font-size:11px;line-height:1.55}\n[data-memory-spatial] [data-spatial-content]{display:grid;gap:4px}\n[data-memory-spatial] [data-spatial-content] small{display:block;color:var(--muted)}\n'''
write(css_path,css)

# Tests.
write("tests/memory/test_query_engine.py", r'''
from pathlib import Path
import tempfile
import unittest

from src.memory import ContextLens, MemoryQueryContext, MemoryStore, QueryCompiler, QueryRoute, ScopeGate


class QueryEngineTests(unittest.TestCase):
    def test_router_and_compiler_specialize_spatial_queries(self):
        scope=MemoryQueryContext(world_id="W",branch_id="B",context_lens=ContextLens.SCENE)
        plan=QueryCompiler.compile("Where is the black dress inside the apartment?",scope)
        self.assertEqual(plan.route,QueryRoute.SPATIAL_LOOKUP)
        self.assertIn("spatial",plan.required_lanes)

    def test_scope_gate_blocks_sibling_branch_and_future(self):
        with tempfile.TemporaryDirectory() as td:
            store=MemoryStore(Path(td)/"memory.db")
            store.set_branch_visibility("A2",[{"visible_branch_id":"A2","depth":0},{"visible_branch_id":"MAIN","depth":1,"max_story_order":40}])
            from src.memory.models import MemoryCandidate
            gate=ScopeGate(store); scope=MemoryQueryContext(world_id="W",branch_id="A2",story_order=20)
            sibling=MemoryCandidate(id="x",lane="fts",source_type="document",source_id="D",text="x",display_excerpt="x",world_id="W",branch_id="SIB")
            future=MemoryCandidate(id="y",lane="fts",source_type="document",source_id="D2",text="y",display_excerpt="y",world_id="W",branch_id="A2",story_order=30)
            self.assertFalse(gate.decide(sibling,scope).allowed)
            self.assertFalse(gate.decide(future,scope).allowed)


if __name__ == "__main__": unittest.main()
''')

write("tests/memory/test_memory_store.py", r'''
from pathlib import Path
import tempfile
import unittest

from src.memory import MemoryStore


class MemoryStoreTests(unittest.TestCase):
    def test_fts_state_spatial_and_threads(self):
        with tempfile.TemporaryDirectory() as td:
            store=MemoryStore(Path(td)/"memory.db")
            store.upsert_chunk({"source_type":"document","source_id":"DOC","source_revision":"1","text":"The black dress hangs inside the bedroom wardrobe.","checksum":"abc"},domain="manuscript")
            self.assertTrue(store.search_fts("black dress",domains=["manuscript"]))
            store.set_current_state(world_id="W",branch_id=None,owner_type="entity_variant",owner_id="DRESS",state_key="location",value="WARDROBE")
            self.assertEqual(store.current_state(world_id="W",branch_id=None,owner_id="DRESS")[0]["value"],"WARDROBE")
            apartment=store.ensure_spatial_node(resource_type="entity_family",resource_id="APT",label="A0325",spatial_kind="unit",world_id="W",branch_id=None)
            room=store.ensure_spatial_node(resource_type="entity_family",resource_id="ROOM",label="Bedroom",spatial_kind="room",world_id="W",branch_id=None)
            wardrobe=store.ensure_spatial_node(resource_type="entity_family",resource_id="WARD",label="Wardrobe",spatial_kind="container",world_id="W",branch_id=None)
            store.add_spatial_edge(subject_node_id=apartment["id"],relation="contains",object_node_id=room["id"],world_id="W",branch_id=None)
            store.add_spatial_edge(subject_node_id=room["id"],relation="contains",object_node_id=wardrobe["id"],world_id="W",branch_id=None)
            self.assertEqual([item["label"] for item in store.spatial_ancestors(wardrobe["id"],world_id="W",branch_id=None)],["Bedroom","A0325"])
            with self.assertRaises(ValueError): store.add_spatial_edge(subject_node_id=wardrobe["id"],relation="contains",object_node_id=apartment["id"],world_id="W",branch_id=None)
            thread=store.create_thread(title="Return Dawnblade",thread_type="promise",world_id="W")
            self.assertEqual(thread["status"],"open")


if __name__ == "__main__": unittest.main()
''')

write("tests/memory/test_embedding_provider.py", r'''
import unittest
import httpx

from src.memory import LMStudioEmbeddingProvider


class EmbeddingProviderTests(unittest.TestCase):
    def test_lmstudio_provider_uses_prefixes_and_order(self):
        seen={}
        def handler(request):
            seen.update(request.json())
            return httpx.Response(200,json={"data":[{"index":1,"embedding":[0.0,1.0]},{"index":0,"embedding":[1.0,0.0]}]})
        client=httpx.Client(transport=httpx.MockTransport(handler))
        provider=LMStudioEmbeddingProvider("http://localhost:1234","e5",client=client)
        vectors=provider.embed_texts(["a","b"],kind="passage")
        self.assertEqual(vectors,[[1.0,0.0],[0.0,1.0]])
        self.assertEqual(seen["input"],["passage: a","passage: b"])
        client.close()


if __name__ == "__main__": unittest.main()
''')

write("tests/test_v12_app_memory.py", r'''
from pathlib import Path
import unittest


class V12AppMemoryContractTests(unittest.TestCase):
    def test_app_and_context_are_wired(self):
        root=Path(__file__).resolve().parents[1]
        app=(root/"src/interface/web/app.py").read_text(encoding="utf-8")
        context=(root/"src/workspace/context.py").read_text(encoding="utf-8")
        self.assertIn("MemoryService",app)
        self.assertIn("register_memory_routes",app)
        self.assertIn("memory_service",context)
        self.assertIn("memory_trace",context)

    def test_memory_ui_is_modular(self):
        root=Path(__file__).resolve().parents[1]
        html=(root/"src/interface/web/static/index.html").read_text(encoding="utf-8")
        self.assertIn('data-inspector-tab="memory"',html)
        self.assertIn("/static/js/memory.js",html)


if __name__ == "__main__": unittest.main()
''')

# Remove all one-shot applicators after the workflow has used them.
for path in (
    "tools/rebuild_v12_memory_core.py","tools/rebuild_v12_memory_integration.py",
    ".github/workflows/rebuild-v12-memory.yml","tools/finalize_v12_implementation.py",
    ".github/workflows/finalize-v12-implementation.yml",
):
    target=ROOT/path
    if target.exists(): target.unlink()
