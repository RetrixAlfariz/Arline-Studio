from __future__ import annotations

from collections import Counter

from src.memory.query import MemoryQueryEngine
from src.memory.security import evidence_wrapper
from src.memory.service import MemoryService


_INSTALLED = False
_ORIGINAL_STRUCTURED = MemoryQueryEngine._structured_state
_ORIGINAL_RRF = MemoryQueryEngine._rrf
_ORIGINAL_PACK = MemoryQueryEngine._pack
_ORIGINAL_STATUS = MemoryService.status


def _structured_with_discovery(self: MemoryQueryEngine, plan, lane):
    output = list(_ORIGINAL_STRUCTURED(self, plan, lane))
    discovery = getattr(self, "discovery", None)
    if discovery is not None:
        try:
            output.extend(discovery.memory_candidates(plan))
        except Exception:
            # Discovery is an optional evidence layer. A broken derived view must
            # never make accepted state retrieval unavailable.
            pass
    return output


def _rrf_with_discovery(self: MemoryQueryEngine, lane_results):
    result = list(_ORIGINAL_RRF(self, lane_results))
    for candidate in result:
        if candidate.authority == "discovery_reviewed":
            candidate.score += 0.055
        elif candidate.authority == "discovery_detected":
            candidate.score += 0.012
    return sorted(result, key=lambda item: item.score, reverse=True)


def _pack_with_discovery(plan, selected, excluded):
    discovered = [item for item in selected if item.metadata.get("discovery")]
    ordinary = [item for item in selected if not item.metadata.get("discovery")]
    base = _ORIGINAL_PACK(plan, ordinary, excluded if not discovered else [])
    if not discovered:
        return base

    lines = base.rstrip().splitlines() if base.strip() else [
        "@ARLINE-MEMORY 1.0",
        f"route: {plan.route.value}",
        f"lens: {plan.scope.context_lens.value}",
    ]
    lines += [
        "",
        "[DISCOVERED NON-CANON]",
        "- The following items are narrative discoveries, not user-authorized canon. Preserve their confidence/status labels.",
    ]
    for item in discovered:
        state = str(item.metadata.get("knowledge_state") or "detected").upper()
        support = int(item.metadata.get("qualified_support_count") or item.metadata.get("support_count") or 0)
        label = f"discovery_proposition:{item.source_id}"
        lines.append(f"- [{state}; qualified_support={support}] {evidence_wrapper(item.text, label)}")
    if excluded:
        counts = Counter(item["decision"]["rule"] for item in excluded)
        lines += ["", "[EXCLUDED CANDIDATES]", "- " + ", ".join(f"{rule}={count}" for rule, count in sorted(counts.items()))]
    return "\n".join(lines).rstrip() + "\n"


def _status_with_discovery(self: MemoryService):
    status = dict(_ORIGINAL_STATUS(self))
    discovery = getattr(self, "discovery", None)
    if discovery is None:
        status["discovery"] = {"propositions": 0, "instances": 0, "active_instances": 0, "canon": 0}
        return status
    try:
        status["discovery"] = discovery.store.status()
    except Exception as exc:
        status["discovery"] = {
            "propositions": 0,
            "instances": 0,
            "active_instances": 0,
            "canon": 0,
            "error": str(exc),
        }
    return status


def install_discovery_memory_bridge() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    MemoryQueryEngine._structured_state = _structured_with_discovery
    MemoryQueryEngine._rrf = _rrf_with_discovery
    MemoryQueryEngine._pack = staticmethod(_pack_with_discovery)
    MemoryService.status = _status_with_discovery
    _INSTALLED = True
