from __future__ import annotations

from dataclasses import dataclass, field
from math import log2
from typing import Any


@dataclass(slots=True)
class MemoryEvalCase:
    id: str
    query: str
    expected_source_ids: set[str] = field(default_factory=set)
    forbidden_source_ids: set[str] = field(default_factory=set)
    route: str | None = None


@dataclass(slots=True)
class MemoryEvalResult:
    case_id: str
    recall_at_k: float
    reciprocal_rank: float
    ndcg_at_k: float
    forbidden_leakage: int
    route_correct: bool
    selected_ids: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "recall_at_k": self.recall_at_k,
            "reciprocal_rank": self.reciprocal_rank,
            "ndcg_at_k": self.ndcg_at_k,
            "forbidden_leakage": self.forbidden_leakage,
            "route_correct": self.route_correct,
            "selected_ids": self.selected_ids,
        }


def score_memory_case(case: MemoryEvalCase, retrieval: dict[str, Any], k: int = 10) -> MemoryEvalResult:
    selected = retrieval.get("selected") or []
    ids = [str(item.get("source_id") or item.get("id") or "") for item in selected[:k]]
    hits = [1 if item in case.expected_source_ids else 0 for item in ids]
    recall = sum(hits) / max(1, len(case.expected_source_ids))
    rr = 0.0
    for rank, hit in enumerate(hits, 1):
        if hit:
            rr = 1.0 / rank
            break
    dcg = sum(hit / log2(rank + 1) for rank, hit in enumerate(hits, 1))
    ideal_hits = [1] * min(len(case.expected_source_ids), k)
    idcg = sum(hit / log2(rank + 1) for rank, hit in enumerate(ideal_hits, 1)) or 1.0
    route = ((retrieval.get("plan") or {}).get("route"))
    return MemoryEvalResult(
        case_id=case.id,
        recall_at_k=min(1.0, recall),
        reciprocal_rank=rr,
        ndcg_at_k=dcg / idcg,
        forbidden_leakage=sum(1 for item in ids if item in case.forbidden_source_ids),
        route_correct=(case.route is None or route == case.route),
        selected_ids=ids,
    )


def aggregate_memory_results(results: list[MemoryEvalResult]) -> dict[str, Any]:
    if not results:
        return {"cases": 0, "recall_at_k": 0.0, "mrr": 0.0, "ndcg_at_k": 0.0, "forbidden_leakage": 0, "route_accuracy": 0.0}
    count = len(results)
    return {
        "cases": count,
        "recall_at_k": sum(item.recall_at_k for item in results) / count,
        "mrr": sum(item.reciprocal_rank for item in results) / count,
        "ndcg_at_k": sum(item.ndcg_at_k for item in results) / count,
        "forbidden_leakage": sum(item.forbidden_leakage for item in results),
        "route_accuracy": sum(1 for item in results if item.route_correct) / count,
    }
