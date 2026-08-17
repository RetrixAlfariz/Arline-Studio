from __future__ import annotations

from pathlib import Path
from textwrap import dedent
import re

ROOT=Path(__file__).resolve().parents[1]
def read(path): return (ROOT/path).read_text(encoding="utf-8")
def write(path,text):
    target=ROOT/path; target.parent.mkdir(parents=True,exist_ok=True); target.write_text(text.rstrip()+"\n",encoding="utf-8")

write("src/eval/memory_benchmark.py",dedent(r'''
from __future__ import annotations

from dataclasses import dataclass,field,asdict
import json
from pathlib import Path
from statistics import mean
from typing import Any,Iterable

from .memory import score_retrieval


@dataclass(slots=True)
class MemoryBenchmarkCase:
    id: str
    query: str
    scope: dict[str,Any] = field(default_factory=dict)
    expected_ids: set[str] = field(default_factory=set)
    forbidden_ids: set[str] = field(default_factory=set)
    category: str = "retrieval"
    notes: str = ""

    @classmethod
    def from_dict(cls,data: dict[str,Any]) -> "MemoryBenchmarkCase":
        return cls(id=str(data.get("id") or data.get("question_id") or data.get("query_id")),query=str(data.get("query") or data.get("question") or data.get("prompt") or ""),scope=dict(data.get("scope") or {}),expected_ids=set(map(str,data.get("expected_ids") or data.get("evidence_ids") or data.get("gold_ids") or [])),forbidden_ids=set(map(str,data.get("forbidden_ids") or [])),category=str(data.get("category") or data.get("type") or "retrieval"),notes=str(data.get("notes") or ""))


@dataclass(slots=True)
class MemoryBenchmarkReport:
    cases: list[dict[str,Any]]
    summary: dict[str,Any]

    def to_dict(self): return {"summary":self.summary,"cases":self.cases}
    def to_markdown(self) -> str:
        lines=["# Arline memory benchmark","",f"Cases: {self.summary['case_count']}",f"Recall@k: {self.summary['recall_at_k']:.4f}",f"MRR: {self.summary['mrr']:.4f}",f"Forbidden-source rate: {self.summary['forbidden_source_rate']:.4f}",f"Branch isolation: {self.summary['branch_isolation_rate']:.4f}",f"Temporal validity: {self.summary['temporal_validity_rate']:.4f}",""]
        for case in self.cases: lines.extend([f"## {case['id']} · {case['category']}",f"- Query: {case['query']}",f"- Recall@k: {case['metrics']['recall_at_k']:.4f}",f"- Forbidden-source rate: {case['metrics']['forbidden_source_rate']:.4f}",f"- Selected: {', '.join(case['selected_ids']) or 'none'}",""])
        return "\n".join(lines)


class MemoryBenchmarkRunner:
    def __init__(self,memory_service): self.service=memory_service

    def run(self,cases: Iterable[MemoryBenchmarkCase], *, k: int = 10, refresh: bool = False) -> MemoryBenchmarkReport:
        results=[]
        for case in cases:
            response=self.service.query(case.query,refresh=refresh,retrieval_mode="debug",**case.scope)
            selected=response.get("selected") or []; selected_ids=[str(item.get("id")) for item in selected]
            temporal=[not ("future" in str(item).casefold()) for item in response.get("excluded") or []]
            # A selected candidate from a forbidden ID is branch/scope leakage by definition.
            branch_valid=[item not in case.forbidden_ids for item in selected_ids]
            metrics=score_retrieval(selected_ids,case.expected_ids,case.forbidden_ids,k=k,temporally_valid=temporal or [True],branch_valid=branch_valid or [True])
            results.append({"id":case.id,"query":case.query,"category":case.category,"selected_ids":selected_ids,"expected_ids":sorted(case.expected_ids),"forbidden_ids":sorted(case.forbidden_ids),"trace_id":response.get("run_id"),"abstained":bool(response.get("abstained")),"metrics":asdict(metrics)})
        def avg(name): return mean([item["metrics"][name] for item in results]) if results else 0.0
        summary={"case_count":len(results),"recall_at_k":avg("recall_at_k"),"mrr":avg("reciprocal_rank"),"forbidden_source_rate":avg("forbidden_source_rate"),"temporal_validity_rate":avg("temporal_validity_rate"),"branch_isolation_rate":avg("branch_isolation_rate"),"zero_leakage":all(item["metrics"]["forbidden_source_rate"]==0 for item in results)}
        return MemoryBenchmarkReport(results,summary)


def load_cases(path: Path|str) -> list[MemoryBenchmarkCase]:
    path=Path(path); text=path.read_text(encoding="utf-8"); raw=[]
    if path.suffix.casefold()==".jsonl": raw=[json.loads(line) for line in text.splitlines() if line.strip()]
    else:
        data=json.loads(text); raw=data if isinstance(data,list) else data.get("cases") or data.get("questions") or []
    return [MemoryBenchmarkCase.from_dict(item) for item in raw]


def load_longmemeval(path: Path|str) -> list[MemoryBenchmarkCase]:
    cases=load_cases(path)
    for case in cases: case.category=f"longmemeval:{case.category}"
    return cases


def load_locomo(path: Path|str) -> list[MemoryBenchmarkCase]:
    cases=load_cases(path)
    for case in cases: case.category=f"locomo:{case.category}"
    return cases
'''))

# Index generation state machine and query profiling.
path="src/memory/store.py"; text=read(path).replace("MEMORY_SCHEMA_VERSION = 4","MEMORY_SCHEMA_VERSION = 5")
if "def verify_generation(" not in text:
    anchor="    def activate_generation(self, generation_id: int) -> None:"
    methods=dedent(r'''
    def verify_generation(self,generation_id: int, *, expected_vectors: int | None = None) -> dict[str,Any]:
        with self._lock,self.connection() as con:
            row=con.execute("SELECT * FROM memory_index_generations WHERE generation_id=?",(generation_id,)).fetchone()
            if row is None: raise KeyError(generation_id)
            count=int(con.execute("SELECT COUNT(*) FROM memory_vectors WHERE generation_id=?",(generation_id,)).fetchone()[0])
            if expected_vectors is not None and count<expected_vectors:
                con.execute("UPDATE memory_index_generations SET status='failed' WHERE generation_id=?",(generation_id,))
                raise ValueError(f"Index generation contains {count} vectors; expected at least {expected_vectors}")
            con.execute("UPDATE memory_index_generations SET status='verified' WHERE generation_id=?",(generation_id,))
        return self.get_generation(generation_id)

    def fail_generation(self,generation_id: int) -> dict[str,Any]:
        with self._lock,self.connection() as con:
            cur=con.execute("UPDATE memory_index_generations SET status='failed' WHERE generation_id=?",(generation_id,))
            if not cur.rowcount: raise KeyError(generation_id)
        return self.get_generation(generation_id)

    def get_generation(self,generation_id: int) -> dict[str,Any]:
        with self.connection() as con: row=con.execute("SELECT * FROM memory_index_generations WHERE generation_id=?",(generation_id,)).fetchone()
        if row is None: raise KeyError(generation_id)
        return dict(row)

    def list_generations(self,limit: int=100) -> list[dict[str,Any]]:
        with self.connection() as con: rows=con.execute("SELECT * FROM memory_index_generations ORDER BY generation_id DESC LIMIT ?",(limit,)).fetchall()
        return [dict(row) for row in rows]

''')
    if anchor not in text: raise RuntimeError("activate generation anchor missing")
    text=text.replace(anchor,methods+anchor,1)
# Activation must only switch verified generation, preserving old active on failure.
old='''    def activate_generation(self, generation_id: int) -> None:\n        with self._lock, self.connection() as con:\n            con.execute("UPDATE memory_index_generations SET status='retired' WHERE status='active'")\n            cur = con.execute("UPDATE memory_index_generations SET status='active',activated_at=? WHERE generation_id=?", (now(), generation_id))\n            if not cur.rowcount: raise KeyError(generation_id)'''
new='''    def activate_generation(self, generation_id: int) -> None:\n        with self._lock, self.connection() as con:\n            row=con.execute("SELECT status FROM memory_index_generations WHERE generation_id=?",(generation_id,)).fetchone()\n            if row is None: raise KeyError(generation_id)\n            if row["status"] not in {"verified","active"}: raise ValueError("Only a verified index generation can become active")\n            con.execute("UPDATE memory_index_generations SET status='retired' WHERE status='active' AND generation_id<>?",(generation_id,))\n            con.execute("UPDATE memory_index_generations SET status='active',activated_at=? WHERE generation_id=?",(now(),generation_id))'''
if old not in text: raise RuntimeError("activate generation exact block missing")
text=text.replace(old,new,1)
write(path,text)

# Indexer alias cache and verified generation activation.
path="src/memory/index.py"; text=read(path)
if "self._alias_cache" not in text:
    text=text.replace("        self.chunker = StructuralChunker()","        self.chunker = StructuralChunker()\n        self._alias_cache: list[dict[str,Any]] | None = None")
    old='''    def _aliases(self) -> list[dict[str, Any]]:\n        with sqlite3.connect(self.database_path) as con:'''
    new='''    def _aliases(self) -> list[dict[str, Any]]:\n        if self._alias_cache is not None: return self._alias_cache\n        with sqlite3.connect(self.database_path) as con:'''
    if old not in text: raise RuntimeError("indexer aliases anchor missing")
    text=text.replace(old,new,1)
    text=text.replace("        result.sort(key=lambda item: len(item[\"label\"]), reverse=True)\n        return result","        result.sort(key=lambda item: len(item[\"label\"]), reverse=True)\n        self._alias_cache=result\n        return result",1)
    refresh_anchor='''        indexed = {"documents": 0, "turns": 0, "variants": 0, "facts": 0, "overlays": 0, "events": 0, "threads": 0}'''
    if refresh_anchor not in text: raise RuntimeError("refresh count anchor missing")
    text=text.replace(refresh_anchor,"        self._alias_cache=None\n"+refresh_anchor,1)
# Verify first embedding generation before atomic activation.
text=text.replace("            if not active_generation:\n                self.store.activate_generation(generation_id)","            if not active_generation:\n                self.store.verify_generation(generation_id,expected_vectors=len(stored))\n                self.store.activate_generation(generation_id)")
write(path,text)

# Eval endpoint and generation endpoints.
path="src/memory/web.py"; text=read(path)
if "class MemoryBenchmarkPayload" not in text:
    anchor="\ndef register_memory_routes(app: FastAPI, service) -> None:"
    cls=dedent(r'''

class MemoryBenchmarkPayload(BaseModel):
    cases: list[dict[str,Any]]
    k: int = 10
    refresh: bool = False
''')
    text=text.replace(anchor,cls+anchor,1)
    routes=dedent(r'''

    @app.get("/api/memory/index-generations")
    def list_index_generations(limit: int=100): return {"generations":service.store.list_generations(limit=min(max(limit,1),500))}

    @app.post("/api/memory/eval/run")
    def run_memory_benchmark(payload: MemoryBenchmarkPayload):
        from src.eval.memory_benchmark import MemoryBenchmarkCase,MemoryBenchmarkRunner
        cases=[MemoryBenchmarkCase.from_dict(item) for item in payload.cases]
        return MemoryBenchmarkRunner(service).run(cases,k=payload.k,refresh=payload.refresh).to_dict()
''')
    text=text.rstrip()+routes+"\n"
write(path,text)

# Developer panel benchmark input/report.
path="src/interface/web/static/index.html"; text=read(path)
if 'id="memoryBenchmarkBtn"' not in text:
    anchor='<div id="memoryQuarantineList" class="suggestion-cards"><div class="empty-note">No quarantined evidence loaded.</div></div>'
    addition=anchor+'\n        <div class="section-title-row"><span class="section-label">Evaluation</span></div><textarea id="memoryBenchmarkCases" rows="6" placeholder=\'[{"id":"case-1","query":"Where is Vian?","expected_ids":[],"forbidden_ids":[]}]\'></textarea><button id="memoryBenchmarkBtn" class="secondary-btn wide">Run benchmark cases</button><pre id="memoryBenchmarkOutput" class="json-block">No benchmark run yet.</pre>'
    if anchor not in text: raise RuntimeError("quarantine list anchor missing")
    text=text.replace(anchor,addition,1)
write(path,text)

path="src/interface/web/static/js/memory.js"; text=read(path)
if "runBenchmark" not in text:
    insertion=dedent(r'''

  async function runBenchmark(){
    const input=document.getElementById("memoryBenchmarkCases"),output=document.getElementById("memoryBenchmarkOutput"); if(!input||!output)return;
    try{const cases=JSON.parse(input.value||"[]");output.textContent="Running deterministic retrieval benchmark…";output.textContent=JSON.stringify(await api("/api/memory/eval/run",{method:"POST",body:{cases,k:10,refresh:false}}),null,2);}catch(error){output.textContent=error.message;}
  }
''')
    marker="  function bindSettings() {"
    text=text.replace(marker,insertion+"\n"+marker,1)
    text=text.replace('    document.getElementById("memoryRefreshQuarantineBtn")?.addEventListener("click", refreshQuarantine);','    document.getElementById("memoryRefreshQuarantineBtn")?.addEventListener("click", refreshQuarantine);\n    document.getElementById("memoryBenchmarkBtn")?.addEventListener("click", runBenchmark);')
write(path,text)

# Benchmark tests and performance smoke.
write("tests/memory/test_benchmark_and_generation.py",dedent(r'''
from pathlib import Path
import tempfile
import unittest

from src.eval.memory_benchmark import MemoryBenchmarkCase,MemoryBenchmarkRunner
from src.memory import MemoryStore

class FakeService:
    def query(self,query,**scope):
        return {"run_id":"R","selected":[{"id":"good"}],"excluded":[{"candidate":{"id":"forbidden"},"reason":"sibling branch"}],"abstained":False}

class BenchmarkGenerationTests(unittest.TestCase):
    def test_zero_leakage_report(self):
        report=MemoryBenchmarkRunner(FakeService()).run([MemoryBenchmarkCase("c","q",expected_ids={"good"},forbidden_ids={"forbidden"})])
        self.assertTrue(report.summary["zero_leakage"]);self.assertEqual(report.summary["recall_at_k"],1)

    def test_generation_requires_verification_and_preserves_active(self):
        with tempfile.TemporaryDirectory() as td:
            store=MemoryStore(Path(td)/"memory.db")
            first=store.create_generation("lmstudio","e5",2)
            with self.assertRaises(ValueError): store.activate_generation(first)
            store.upsert_chunk({"id":"C","source_type":"document","source_id":"D","source_revision":"1","text":"x","checksum":"x"},domain="manuscript")
            store.upsert_vector("C",[1,0],generation_id=first,model_id="e5");store.verify_generation(first,expected_vectors=1);store.activate_generation(first)
            second=store.create_generation("lmstudio","new",2);store.fail_generation(second)
            self.assertEqual(store.active_generation()["generation_id"],first)

    def test_large_fts_smoke(self):
        with tempfile.TemporaryDirectory() as td:
            store=MemoryStore(Path(td)/"memory.db")
            for index in range(1200): store.upsert_chunk({"id":f"C{index}","source_type":"document","source_id":f"D{index}","source_revision":"1","text":f"Scene evidence number {index} contains Dawnblade" if index==777 else f"ordinary scene {index}","checksum":str(index)},domain="manuscript")
            results=store.search_fts("Dawnblade",domains=["manuscript"],limit=10)
            self.assertTrue(results);self.assertEqual(results[0]["id"],"C777")

if __name__ == "__main__": unittest.main()
'''))

write("tests/fixtures/memory_branch_scope.json",dedent(r'''
{
  "cases": [
    {"id":"main-vs-whatif","query":"What is Vian's current location?","category":"branch_isolation","scope":{"world_id":"W","branch_id":"MAIN"},"expected_ids":[],"forbidden_ids":["whatif-only"]},
    {"id":"scratch-exclusion","query":"What did we decide?","category":"scratch_isolation","scope":{"project_id":"P","allow_scratch":false},"expected_ids":[],"forbidden_ids":["scratch-memory"]},
    {"id":"pov-future","query":"What does Fano know?","category":"pov_temporal","scope":{"world_id":"W","context_lens":"pov","story_order":10},"expected_ids":[],"forbidden_ids":["future-secret"]}
  ]
}
'''))

# Docs status closes the architecture implementation boundary.
path="docs/V12_IMPLEMENTATION_STATUS.md"; text=read(path)
if "## Evaluation and index safety" not in text:
    text += dedent('''

    ## Evaluation and index safety

    The branch includes Arline-specific benchmark case loading/reporting,
    LongMemEval/LoCoMo adapter hooks, zero-leakage metrics, large-FTS smoke
    coverage, and atomic embedding-index generation activation. A failed or
    incomplete generation cannot retire the currently active index.
    ''')
write(path,text)

# Backup-coordinated schema bump.
for path,old,new in (("src/workspace/store.py","WORKSPACE_SCHEMA_VERSION = 11","WORKSPACE_SCHEMA_VERSION = 12"),("src/workspace/foundation.py","SCHEMA_VERSION = 11","SCHEMA_VERSION = 12")):
    text=read(path).replace(old,new); write(path,text)

for disposable in ("tools/v12_complete_eval_performance.py",".github/workflows/v12-complete-eval-performance.yml"):
    target=ROOT/disposable
    if target.exists(): target.unlink()
