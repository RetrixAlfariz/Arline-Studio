
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

from .config import MemoryConfig
from .embedding import EmbeddingProvider
from .models import Authority, SemanticClass, TrustLevel
from .security import inspect_retrieved_text
from .store import MemoryStore


@dataclass(slots=True)
class ChunkUnit:
    text: str
    start_id: str
    end_id: str
    ordinal: int


class StructuralChunker:
    VERSION = 1

    def __init__(self, max_chars: int = 1800, overlap_chars: int = 180):
        self.max_chars = max(400, int(max_chars))
        self.overlap_chars = max(0, min(int(overlap_chars), self.max_chars // 3))

    def chunk(self, text: str, *, source_id: str) -> list[ChunkUnit]:
        normalized = text.replace("\r\n", "\n").strip()
        if not normalized:
            return []
        blocks = [block.strip() for block in re.split(r"\n\s*\n", normalized) if block.strip()] or [normalized]
        output: list[ChunkUnit] = []
        current: list[str] = []
        current_chars = 0

        def flush() -> None:
            nonlocal current, current_chars
            if not current:
                return
            body = "\n\n".join(current).strip()
            ordinal = len(output)
            output.append(ChunkUnit(body, f"{source_id}:block:{ordinal}", f"{source_id}:block:{ordinal}", ordinal))
            overlap = body[-self.overlap_chars:].strip() if self.overlap_chars else ""
            current = [overlap] if overlap else []
            current_chars = len(overlap)

        for block in blocks:
            sentences = re.split(r"(?<=[.!?])\s+", block) if len(block) > self.max_chars else [block]
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence:
                    continue
                projected = current_chars + len(sentence) + (2 if current else 0)
                if current and projected > self.max_chars:
                    flush()
                current.append(sentence)
                current_chars += len(sentence) + (2 if len(current) > 1 else 0)
        flush()
        return output


class MemoryIndexer:
    def __init__(self, *, store: MemoryStore, workspace, history, foundation=None,
                 config: MemoryConfig | None = None, embedding: EmbeddingProvider | None = None):
        self.store = store
        self.workspace = workspace
        self.history = history
        self.foundation = foundation
        self.config = config or MemoryConfig()
        self.embedding = embedding
        self.chunker = StructuralChunker(self.config.chunk_chars, self.config.chunk_overlap_chars)

    @staticmethod
    def _revision(*parts: Any) -> str:
        return hashlib.sha256("|".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()[:24]

    def _identity_catalog(self) -> list[dict[str, Any]]:
        catalog: list[dict[str, Any]] = []
        try:
            families = self.workspace.list_entity_families(None)
        except Exception:
            families = []
        for family in families:
            catalog.append({"resource_type": "entity_family", "resource_id": family["id"], "label": family.get("name") or family["id"]})
        try:
            variants = self.workspace.list_variants()
        except Exception:
            variants = []
        for variant in variants:
            catalog.append({"resource_type": "entity_variant", "resource_id": variant["id"], "label": variant.get("display_name") or variant["id"]})
        if self.foundation is not None:
            for item in list(catalog):
                try:
                    aliases = self.foundation.list_aliases(item["resource_type"], item["resource_id"])
                except Exception:
                    aliases = []
                for alias in aliases:
                    catalog.append({**item, "label": alias.get("alias") or ""})
        return [item for item in catalog if item.get("label")]

    def _links(self, text: str, catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
        lower = text.casefold(); links=[]; seen=set()
        for item in sorted(catalog, key=lambda row: len(row["label"]), reverse=True):
            label = item["label"].strip()
            if len(label) < 2 or label.casefold() not in lower:
                continue
            key=(item["resource_type"], item["resource_id"])
            if key in seen:
                continue
            seen.add(key)
            links.append({"resource_type": key[0], "resource_id": key[1], "relation": "mentions", "confidence": 0.95, "resolution_method": "name_or_alias"})
        return links[:48]

    def _document_temporal(self, document: dict[str, Any]) -> tuple[float | None, Any]:
        scene_card = None
        try:
            scene_card = self.workspace.get_scene_card(document["id"])
        except Exception:
            scene_card = None
        story_order = (scene_card or {}).get("sort_order")
        if story_order is None:
            story_order = document.get("sort_order")
        world_time = (scene_card or {}).get("narrative_time") or None
        return (float(story_order) if story_order is not None else None, world_time)

    @staticmethod
    def _turn_scope(turn: dict[str, Any]) -> dict[str, Any]:
        scope = turn.get("workspace_scope")
        if isinstance(scope, dict):
            return scope
        raw = turn.get("workspace_scope_json")
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}

    def _turn_temporal(self, turn: dict[str, Any]) -> tuple[float | None, Any]:
        scope = self._turn_scope(turn)
        scene_card = scope.get("scene_card") or {}
        active_scene = scope.get("active_scene") or {}
        order = scene_card.get("sort_order")
        world_time = active_scene.get("narrative_time") or scene_card.get("narrative_time") or None
        return (float(order) if order is not None else None, world_time)

    def _same_source_database(self, owner: Any) -> bool:
        path = getattr(owner, "path", None)
        if path is None:
            return False
        try:
            return Path(path).resolve() == self.store.path.resolve()
        except Exception:
            return False

    def _vectors(self, rows: list[dict[str, Any]], generation_id: int | None) -> list[list[float]] | None:
        if not rows or generation_id is None or not self.config.dense_enabled:
            return None
        if self.embedding is None or not self.embedding.available():
            raise RuntimeError("Dense retrieval is enabled but the embedding provider is unavailable")
        texts = [row.get("retrieval_text") or row.get("text") or "" for row in rows]
        vectors = self.embedding.embed_passages(texts)
        if len(vectors) != len(rows):
            raise RuntimeError("Embedding provider returned incomplete vector coverage")
        return vectors

    def _ensure_generation_vectors(self, rows: list[dict[str, Any]], generation_id: int | None) -> None:
        if not rows or generation_id is None or not self.config.dense_enabled:
            return
        coverage = self.store.vector_coverage(generation_id, [row["id"] for row in rows])
        if not coverage["missing"]:
            return
        missing = set(coverage["missing"])
        subset = [row for row in rows if row["id"] in missing]
        vectors = self._vectors(subset, generation_id) or []
        for row, vector in zip(subset, vectors):
            self.store.upsert_vector(row["id"], generation_id, self.embedding.model_id, vector)

    def index_document(self, document: dict[str, Any], *, generation_id: int | None = None,
                       catalog: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        if not self.config.enabled:
            return []
        source_id = document["id"]
        story_order, world_time = self._document_temporal(document)
        revision = self._revision(document.get("updated_at"), document.get("title"), document.get("content"), story_order, world_time)
        title = str(document.get("title") or "Untitled")
        units = self.chunker.chunk(str(document.get("content") or ""), source_id=source_id)
        active_rows = self.store.list_chunks(source_type="document", source_id=source_id, status="active", limit=5000)
        if len(active_rows) == len(units) and active_rows and all(
            str(row.get("source_revision") or "").startswith(f"{revision}:") for row in active_rows
        ):
            self._ensure_generation_vectors(active_rows, generation_id)
            return active_rows

        catalog = catalog if catalog is not None else self._identity_catalog()
        prepared = []
        for unit in units:
            retrieval = f"Document: {title}\nType: {document.get('document_type','scene')}\n{unit.text}"
            prepared.append({
                "source_revision": f"{revision}:{unit.ordinal}", "text": unit.text, "retrieval_text": retrieval,
                "display_excerpt": unit.text[:700], "project_id": document.get("project_id"),
                "world_id": document.get("world_id"), "branch_id": document.get("branch_id"),
                "source_start_id": unit.start_id, "source_end_id": unit.end_id,
                "source_recorded_at": document.get("updated_at") or document.get("created_at"),
                "world_time": world_time, "story_order": story_order,
                "semantic_class": SemanticClass.EVIDENCE.value, "authority": Authority.PROJECT_MANUSCRIPT.value,
                "trust_level": TrustLevel.TRUSTED_LOCAL.value, "importance": 0.65,
                "chunker_version": self.chunker.VERSION, "links": self._links(unit.text, catalog),
            })
        vectors = self._vectors(prepared, generation_id)
        guard = {"table": "workspace_documents", "id": source_id, "updated_at": document.get("updated_at")} if self._same_source_database(self.workspace) else None
        if guard is None:
            current = self.workspace.get_document(source_id)
            if str(current.get("updated_at")) != str(document.get("updated_at")):
                raise RuntimeError("Document changed while Memory was indexing it")
        return self.store.replace_source_revision(
            source_type="document", source_id=source_id, prepared=prepared, source_guard=guard,
            generation_id=generation_id, embedding_model=self.embedding.model_id if vectors is not None else None,
            vectors=vectors,
        )

    def _iter_turns(self, project_id: str | None = None) -> list[dict[str, Any]]:
        path = getattr(self.history, "path", None)
        if path is None:
            return []
        con = sqlite3.connect(path, timeout=30); con.row_factory=sqlite3.Row
        try:
            where=""; params=[]
            if project_id:
                where="WHERE s.project_id=?"; params=[project_id]
            rows = con.execute(
                "SELECT t.*,s.project_id,s.world_id,s.branch_id,s.scratch_mode,s.parent_session_id,s.forked_from_turn_id "
                "FROM turns t JOIN sessions s ON s.id=t.session_id " + where + " ORDER BY t.created_at,t.rowid", params
            ).fetchall()
            return [dict(row) for row in rows]
        finally:
            con.close()

    def index_turn(self, turn: dict[str, Any], *, generation_id: int | None = None,
                   catalog: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        if not self.config.enabled:
            return []
        scratch = bool(turn.get("scratch_mode")); feedback = turn.get("feedback_status") or "unreviewed"
        semantic = SemanticClass.EXPLORATORY.value
        authority = Authority.SCRATCH.value if scratch else Authority.CHAT_EXPLORATION.value
        if feedback in {"accepted", "edited_accept"}:
            semantic = SemanticClass.DECISION.value
            authority = Authority.ACCEPTED_GENERATED_OUTPUT.value
        combined = f"USER:\n{turn.get('user_prompt') or ''}\n\nASSISTANT:\n{turn.get('edited_story') if feedback == 'edited_accept' and turn.get('edited_story') else turn.get('story') or ''}".strip()
        if not combined:
            return []
        report = inspect_retrieved_text(combined, trust_level=TrustLevel.GENERATED.value)
        revision = self._revision(turn.get("updated_at"), combined, feedback)
        units = self.chunker.chunk(combined, source_id=turn["id"])
        active_rows = self.store.list_chunks(source_type="chat_window", source_id=turn["id"], status="active", limit=5000)
        if len(active_rows) == len(units) and active_rows and all(
            str(row.get("source_revision") or "").startswith(f"{revision}:") for row in active_rows
        ):
            self._ensure_generation_vectors(active_rows, generation_id)
            return active_rows

        catalog = catalog if catalog is not None else self._identity_catalog()
        story_order, world_time = self._turn_temporal(turn)
        prepared = []
        for unit in units:
            prepared.append({
                "source_revision": f"{revision}:{unit.ordinal}", "text": unit.text, "retrieval_text": unit.text,
                "display_excerpt": unit.text[:700], "project_id": turn.get("project_id"), "world_id": turn.get("world_id"),
                "branch_id": turn.get("branch_id"), "session_id": turn.get("session_id"),
                "source_start_id": unit.start_id, "source_end_id": unit.end_id,
                "source_recorded_at": turn.get("updated_at") or turn.get("created_at"),
                "world_time": world_time, "story_order": story_order,
                "semantic_class": semantic, "authority": authority, "trust_level": report.trust_level,
                "importance": 0.75 if feedback in {"accepted", "edited_accept"} else 0.4,
                "chunker_version": self.chunker.VERSION, "links": self._links(unit.text, catalog),
            })
        vectors = self._vectors(prepared, generation_id)
        guard = {"table": "turns", "id": turn["id"], "updated_at": turn.get("updated_at")} if self._same_source_database(self.history) else None
        if guard is None:
            current = self.history.get_turn(turn["id"])
            if str(current.get("updated_at")) != str(turn.get("updated_at")):
                raise RuntimeError("Chat turn changed while Memory was indexing it")
        return self.store.replace_source_revision(
            source_type="chat_window", source_id=turn["id"], prepared=prepared, source_guard=guard,
            generation_id=generation_id, embedding_model=self.embedding.model_id if vectors is not None else None,
            vectors=vectors,
        )

    def backfill(self, project_id: str | None = None) -> dict[str, Any]:
        if not self.config.enabled:
            return {"disabled": True, "documents": 0, "turns": 0, "chunks": 0}
        # Dense generations are global derived snapshots. Activating a generation
        # that only covers one project would make every other project disappear
        # from vector search, so a dense rebuild always covers the whole store.
        effective_project_id = None if self.config.dense_enabled else project_id
        generation = self.store.create_generation(
            provider=("lmstudio" if self.config.dense_enabled and not self.config.fts_enabled else
                      "fts5+lmstudio" if self.config.dense_enabled else "fts5"),
            embedding_model=self.embedding.model_id if self.embedding and self.config.dense_enabled else None,
            dimension=self.embedding.dimension if self.embedding and self.config.dense_enabled else None,
            chunker_version=self.chunker.VERSION,
            detail={"requested_project_id": project_id, "effective_project_id": effective_project_id},
        )
        generation_id = generation["generation_id"]
        catalog = self._identity_catalog()
        expected_ids: list[str] = []
        document_count = turn_count = 0
        try:
            if self.config.dense_enabled and (self.embedding is None or not self.embedding.available()):
                raise RuntimeError("Dense backfill requested but embedding provider is unavailable")
            projects = [self.workspace.get_project(effective_project_id)] if effective_project_id else self.workspace.list_projects()
            for project in projects:
                if project.get("id") == "PROJ-WORLD-BIBLE":
                    continue
                for document in self.workspace.list_documents(project["id"]):
                    rows = self.index_document(document, generation_id=generation_id, catalog=catalog)
                    document_count += 1
                    expected_ids.extend(row["id"] for row in rows)
            for turn in self._iter_turns(effective_project_id):
                rows = self.index_turn(turn, generation_id=generation_id, catalog=catalog)
                turn_count += 1
                expected_ids.extend(row["id"] for row in rows)
            coverage = self.store.vector_coverage(generation_id, expected_ids) if self.config.dense_enabled else {"expected": 0, "covered": 0, "missing": []}
            if coverage["missing"]:
                raise RuntimeError(f"Dense generation is incomplete: {len(coverage['missing'])} chunks lack vectors")
            self.store.set_generation_status(generation_id, "verified")
            self.store.set_generation_status(generation_id, "active")
        except Exception:
            self.store.set_generation_status(generation_id, "failed")
            raise
        return {
            "generation_id": generation_id, "documents": document_count, "turns": turn_count,
            "chunks": len(expected_ids), "dense_requested": self.config.dense_enabled,
            "dense_model": self.embedding.model_id if self.embedding else None,
            "dense_scope": "global" if self.config.dense_enabled else (project_id or "global"),
            "vector_coverage": coverage,
        }
