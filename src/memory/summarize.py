from __future__ import annotations

import hashlib
from typing import Any

from .models import Authority, SemanticClass, TrustLevel


class SummaryService:
    """Derived summaries remain caches linked to immutable evidence."""

    def __init__(self, store):
        self.store = store

    @staticmethod
    def evidence_hash(chunk_ids: list[str], texts: list[str]) -> str:
        payload = "\n".join([*sorted(chunk_ids), *texts])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def create(self, *, summary_type: str, subject_type: str, subject_id: str,
               text: str, source_chunk_ids: list[str], project_id: str | None = None,
               world_id: str | None = None, branch_id: str | None = None,
               structured_payload: dict[str, Any] | None = None,
               story_order_from: float | None = None,
               story_order_to: float | None = None) -> dict[str, Any]:
        source_chunks = [self.store.get_chunk(chunk_id) for chunk_id in source_chunk_ids]
        summary = self.store.create_summary(
            summary_type=summary_type, subject_type=subject_type, subject_id=subject_id,
            project_id=project_id, world_id=world_id, branch_id=branch_id,
            text=text, structured_payload=structured_payload or {},
            story_order_from=story_order_from, story_order_to=story_order_to,
            evidence_hash=self.evidence_hash(source_chunk_ids, [item["checksum"] for item in source_chunks]),
            source_chunk_ids=source_chunk_ids,
        )
        chunk = self.store.upsert_chunk(
            source_type="derived_summary", source_id=summary["id"],
            source_revision=summary["evidence_hash"], text=text,
            retrieval_text=f"{summary_type} summary for {subject_type}:{subject_id}\n{text}",
            project_id=project_id, world_id=world_id, branch_id=branch_id,
            story_order=story_order_to, semantic_class=SemanticClass.SUMMARY.value,
            authority=Authority.DERIVED_SUMMARY.value, trust_level=TrustLevel.GENERATED.value,
            importance=0.65,
        )
        self.store.replace_links(chunk["id"], [{
            "resource_type": subject_type, "resource_id": subject_id,
            "relation": "summarizes", "confidence": 1.0, "resolution_method": "summary_subject",
        }])
        return {**summary, "memory_chunk_id": chunk["id"]}

    def mark_stale_for_source(self, chunk_id: str) -> int:
        return self.store.invalidate_summaries_for_chunk(chunk_id)
