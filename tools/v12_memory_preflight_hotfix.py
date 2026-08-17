from __future__ import annotations

from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]


def read(path): return (ROOT/path).read_text(encoding="utf-8")
def write(path,text):
    target=ROOT/path; target.parent.mkdir(parents=True,exist_ok=True); target.write_text(text.rstrip()+"\n",encoding="utf-8")

# Dataclass defaults must use factories.
path="src/memory/config.py"; text=read(path)
text=text.replace("from dataclasses import dataclass","from dataclasses import dataclass, field")
text=text.replace("    embedding: EmbeddingSettings = EmbeddingSettings()","    embedding: EmbeddingSettings = field(default_factory=EmbeddingSettings)")
text=text.replace("    reranker: RerankerSettings = RerankerSettings()","    reranker: RerankerSettings = field(default_factory=RerankerSettings)")
write(path,text)

# HTTPX Request does not expose .json() in MockTransport handlers.
path="tests/memory/test_embedding_provider.py"; text=read(path)
text=text.replace("import unittest\nimport httpx","import unittest\nimport json\nimport httpx")
text=text.replace("seen.update(request.json())","seen.update(json.loads(request.content.decode('utf-8')))")
write(path,text)

# Some older History databases do not have a turns.updated_at column.
path="src/memory/index.py"; text=read(path)
text=text.replace('revision = str(row["updated_at"] or row["created_at"] or self.checksum(text))','revision = str((row["updated_at"] if "updated_at" in row.keys() else None) or row["created_at"] or self.checksum(text))')
write(path,text)

# Repair WorkspaceContext field ordering and constructor integration without
# relying on the exact v1.1 field sequence.
path="src/workspace/context.py"; text=read(path)
text=text.replace("    memory_trace: dict[str, Any] | None = None\n","")
class_match=re.search(r"(?m)^class WorkspaceContext:\s*$",text)
if class_match:
    method_match=re.search(r"(?m)^    def \w+\(",text[class_match.end():])
    if method_match:
        insert_at=class_match.end()+method_match.start()
        text=text[:insert_at]+"    memory_trace: dict[str, Any] | None = None\n\n"+text[insert_at:]
# Ensure constructor accepts and stores memory_service.
constructor=re.search(r"def __init__\(self, store: WorkspaceStore(?P<tail>[^)]*)\):",text)
if constructor and "memory_service" not in constructor.group(0):
    replacement=constructor.group(0)[:-2]+", memory_service=None):"
    text=text[:constructor.start()]+replacement+text[constructor.end():]
if "self.memory_service = memory_service" not in text:
    text=text.replace("        self.store = store","        self.store = store\n        self.memory_service = memory_service",1)
# Remove duplicated serialization/constructor assignments if the previous pass
# inserted them more than once.
text=re.sub(r'(\n\s*"memory_trace": self\.memory_trace,){2,}',r'\1',text)
text=re.sub(r'(\n\s*memory_trace=memory_trace,){2,}',r'\1',text)
write(path,text)

# Ensure app wiring exists exactly once and resolver construction is valid.
path="src/interface/web/app.py"; text=read(path)
if "from src.memory import MemoryService, register_memory_routes" not in text:
    text=text.replace("from src.history import HistoryStore","from src.history import HistoryStore\nfrom src.memory import MemoryService, register_memory_routes",1)
text=re.sub(r"WorkspaceContextResolver\(workspace(?:,\s*memory_service=memory_service)?\)","WorkspaceContextResolver(workspace, memory_service=memory_service)",text)
# Deduplicate route registration if necessary.
lines=text.splitlines(); out=[]; seen_registration=False
for line in lines:
    if "register_memory_routes(app, memory_service)" in line:
        if seen_registration: continue
        seen_registration=True
    out.append(line)
text="\n".join(out)+"\n"
write(path,text)

# Context tests should also instantiate the resolver through the full app smoke
# test, catching malformed constructor edits.
path="tests/test_v12_app_memory.py"; text=read(path)
if "import src.workspace.context" not in text:
    text=text.replace("import unittest","import unittest\nimport src.workspace.context")
    text=text.replace("    def test_app_and_context_are_wired(self):","    def test_context_module_imports(self):\n        self.assertTrue(hasattr(src.workspace.context, 'WorkspaceContextResolver'))\n\n    def test_app_and_context_are_wired(self):")
write(path,text)

# Remove one-shot files from the final commit.
for disposable in (
    "tools/rebuild_v12_memory_core.py","tools/rebuild_v12_memory_integration.py","tools/v12_memory_preflight_hotfix.py",
    ".github/workflows/rebuild-v12-memory.yml",".github/workflows/rebuild-v12-memory-v2.yml",
    "tools/finalize_v12_implementation.py",".github/workflows/finalize-v12-implementation.yml",
):
    target=ROOT/disposable
    if target.exists(): target.unlink()
