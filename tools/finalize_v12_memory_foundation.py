from __future__ import annotations

from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text, encoding="utf-8")


# If the first one-shot applicator has not committed yet, apply it now.
app = read("src/interface/web/app.py")
if "/api/memory/status" not in app:
    applicator = ROOT / "tools/apply_v12_memory_foundation.py"
    if not applicator.exists():
        raise RuntimeError("v1.2 applicator is missing while integration is incomplete")
    subprocess.run(["python", str(applicator)], cwd=ROOT, check=True)

# Fix the initial chunk insert placeholder count.
store_path = "src/memory/store.py"
store = read(store_path)
store = store.replace(
    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'active','ready',?,?,?,?,?,?)",
    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'active','ready',?,?,?,?,?)",
)
if "def deactivate_source(" not in store:
    anchor = "    def get_chunk(self, chunk_id: str) -> dict[str, Any]:\n"
    addition = '''    def deactivate_source(self, source_type: str, source_id: str, status: str = "deleted") -> int:
        with self._lock, self.connection() as con:
            rows = con.execute(
                "SELECT id FROM memory_chunks WHERE source_type=? AND source_id=? AND semantic_status!='deleted'",
                (source_type, source_id),
            ).fetchall()
            con.execute(
                "UPDATE memory_chunks SET semantic_status=?,index_state='stale',updated_at=? WHERE source_type=? AND source_id=?",
                (status, utc_now(), source_type, source_id),
            )
            if self.fts_available:
                for row in rows:
                    for domain in FTS_DOMAINS:
                        con.execute(f"DELETE FROM memory_fts_{domain} WHERE chunk_id=?", (row["id"],))
        return len(rows)

'''
    if anchor not in store:
        raise RuntimeError("MemoryStore source lifecycle anchor missing")
    store = store.replace(anchor, addition + anchor, 1)
write(store_path, store)

# Add debounced incremental source hooks to MemoryService.
service_path = "src/memory/service.py"
service = read(service_path)
if "from threading import RLock, Timer" not in service:
    service = service.replace("from typing import Any\n", "from typing import Any\nfrom threading import RLock, Timer\n")
if "self._index_timers" not in service:
    service = service.replace(
        "        self.query_engine = MemoryQueryEngine(\n",
        "        self._timer_lock = RLock()\n        self._index_timers: dict[str, Timer] = {}\n        self.query_engine = MemoryQueryEngine(\n",
        1,
    )
if "def schedule_document(" not in service:
    anchor = "    def status(self) -> dict[str, Any]:\n"
    methods = '''    def _active_generation_id(self) -> int | None:
        generation = self.store.active_generation()
        return int(generation["generation_id"]) if generation else None

    def schedule_document(self, document: dict[str, Any], delay_seconds: float = 1.25) -> None:
        if not self.config.enabled:
            return
        key = f"document:{document['id']}"
        def work() -> None:
            try:
                self.indexer.index_document(document, generation_id=self._active_generation_id())
            finally:
                with self._timer_lock:
                    self._index_timers.pop(key, None)
        with self._timer_lock:
            previous = self._index_timers.pop(key, None)
            if previous is not None:
                previous.cancel()
            timer = Timer(max(0.05, delay_seconds), work)
            timer.daemon = True
            self._index_timers[key] = timer
            timer.start()

    def index_turn(self, turn: dict[str, Any]) -> None:
        if not self.config.enabled:
            return
        enriched = dict(turn)
        try:
            session = self.history.get_session_meta(turn["session_id"])
            for key in ("project_id", "world_id", "branch_id", "scratch_mode", "parent_session_id", "forked_from_turn_id"):
                enriched.setdefault(key, session.get(key))
        except Exception:
            pass
        self.indexer.index_turn(enriched, generation_id=self._active_generation_id())

    def deactivate_source(self, source_type: str, source_id: str) -> int:
        return self.store.deactivate_source(source_type, source_id)

'''
    if anchor not in service:
        raise RuntimeError("MemoryService method anchor missing")
    service = service.replace(anchor, methods + anchor, 1)
write(service_path, service)

# Wire source lifecycle through wrappers rather than duplicating route logic.
app_path = "src/interface/web/app.py"
app = read(app_path)
if "_memory_wrapped_create_document" not in app:
    anchor = "    media_root = workspace_path.parent / \"media\"\n"
    wrappers = '''    # Incremental memory indexing hooks. Document autosaves are debounced;
    # completed chat turns are indexed immediately. Source records remain truth.
    _memory_original_create_document = workspace.create_document
    def _memory_wrapped_create_document(*args, **kwargs):
        document = _memory_original_create_document(*args, **kwargs)
        memory_service.schedule_document(document)
        return document
    workspace.create_document = _memory_wrapped_create_document

    _memory_original_update_document = workspace.update_document
    def _memory_wrapped_update_document(*args, **kwargs):
        document = _memory_original_update_document(*args, **kwargs)
        memory_service.schedule_document(document)
        return document
    workspace.update_document = _memory_wrapped_update_document

    _memory_original_delete_document = workspace.delete_document
    def _memory_wrapped_delete_document(document_id, *args, **kwargs):
        result = _memory_original_delete_document(document_id, *args, **kwargs)
        memory_service.deactivate_source("document", document_id)
        return result
    workspace.delete_document = _memory_wrapped_delete_document

    _memory_original_add_turn = history.add_turn
    def _memory_wrapped_add_turn(*args, **kwargs):
        turn = _memory_original_add_turn(*args, **kwargs)
        try:
            memory_service.index_turn(turn)
        except Exception:
            pass
        return turn
    history.add_turn = _memory_wrapped_add_turn

'''
    if anchor not in app:
        raise RuntimeError("App incremental hook anchor missing")
    app = app.replace(anchor, wrappers + anchor, 1)
write(app_path, app)

# Ensure the permanent CI covers the v1.2 package and branch.
ci_path = ".github/workflows/ci.yml"
ci = read(ci_path)
if '      - "develop/**"' not in ci:
    ci = ci.replace('      - "release/**"\n', '      - "release/**"\n      - "develop/**"\n')
if "src/interface/web/static/js/memory.js" not in ci:
    ci = ci.replace(
        "          node --check src/interface/web/static/js/stream.js\n",
        "          node --check src/interface/web/static/js/stream.js\n          node --check src/interface/web/static/js/memory.js\n",
    )
write(ci_path, ci)

print("Finalized v1.2 memory foundation and incremental hooks")
