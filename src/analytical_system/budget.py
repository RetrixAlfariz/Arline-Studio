from __future__ import annotations
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ReasoningBudget:
    max_depth: int = 4
    max_nodes: int = 500
    min_confidence: float = .35
    min_relevance: float = .25


class ReasoningBudgetGuard:
    """
    Guard the symbolic inference graph against confidence inflation and
    runaway multi-hop expansion.

    The reasoner may remain domain-specific; this guard is a global policy
    pass applied after rule execution.
    """

    VERSION = "0.2"
    SOURCE_KINDS = {"fact", "event", "scenario_event", "relation"}

    def __init__(self, budget: ReasoningBudget | None = None):
        self.budget = budget or ReasoningBudget()

    def apply(self, reasoning: dict[str, Any]) -> dict[str, Any]:
        graph = reasoning.get("inference_graph", {}) or {}
        nodes = list(graph.get("nodes", []) or [])
        edges = list(graph.get("edges", []) or [])
        diagnostics = list(reasoning.get("diagnostics", []) or [])
        by_id = {n.get("id"): n for n in nodes}

        # Compute graph depth recursively. Cycles are treated as over-budget
        # instead of allowing an infinite traversal.
        depth_cache: dict[str, int] = {}
        visiting: set[str] = set()

        def depth(node_id: str | None) -> int:
            if not node_id:
                return 0
            if node_id in depth_cache:
                return depth_cache[node_id]
            if node_id in visiting:
                diagnostics.append({"type": "reasoning_cycle_detected", "node": node_id})
                return self.budget.max_depth + 1
            visiting.add(node_id)
            node = by_id.get(node_id, {})
            parents = [p for p in node.get("parents", []) or [] if p in by_id]
            value = 0 if not parents else 1 + max(depth(p) for p in parents)
            visiting.discard(node_id)
            depth_cache[node_id] = value
            return value

        for node in nodes:
            node_depth = depth(node.get("id"))
            node.setdefault("metadata", {})["depth"] = node_depth

            # Confidence propagation guard: a child should not become more
            # certain than its strongest parent unless it is a source node.
            parents = [by_id.get(p) for p in node.get("parents", []) if by_id.get(p)]
            if parents and node.get("kind") not in self.SOURCE_KINDS:
                cap = max(float(p.get("confidence", 0)) for p in parents)
                if float(node.get("confidence", 0)) > cap:
                    diagnostics.append({
                        "type": "confidence_clamped",
                        "node": node.get("id"),
                        "from": node.get("confidence"),
                        "to": round(cap, 4),
                    })
                    node["confidence"] = round(cap, 4)

        keep: list[dict[str, Any]] = []
        depth_pruned = 0
        relevance_pruned = 0
        confidence_pruned = 0

        for node in nodes:
            is_source = node.get("kind") in self.SOURCE_KINDS
            node_depth = int((node.get("metadata") or {}).get("depth", 0))
            relevance = (node.get("metadata") or {}).get("relevance")

            if not is_source and node_depth > self.budget.max_depth:
                depth_pruned += 1
                continue
            if (
                not is_source
                and isinstance(relevance, (int, float))
                and float(relevance) < self.budget.min_relevance
            ):
                relevance_pruned += 1
                continue
            if not is_source and float(node.get("confidence", 0)) < self.budget.min_confidence:
                confidence_pruned += 1
                continue
            keep.append(node)

        if len(keep) > self.budget.max_nodes:
            sources = [n for n in keep if n.get("kind") in self.SOURCE_KINDS]
            derived = [n for n in keep if n not in sources]
            derived.sort(
                key=lambda n: (
                    float((n.get("metadata") or {}).get("relevance", 1.0)),
                    float(n.get("confidence", 0)),
                    -int((n.get("metadata") or {}).get("depth", 0)),
                ),
                reverse=True,
            )
            keep = (sources + derived)[: self.budget.max_nodes]
            diagnostics.append({
                "type": "reasoning_budget_pruned",
                "max_nodes": self.budget.max_nodes,
            })

        if depth_pruned:
            diagnostics.append({"type": "reasoning_depth_pruned", "count": depth_pruned})
        if relevance_pruned:
            diagnostics.append({"type": "reasoning_relevance_pruned", "count": relevance_pruned})
        if confidence_pruned:
            diagnostics.append({"type": "reasoning_confidence_pruned", "count": confidence_pruned})

        ids = {n.get("id") for n in keep}
        graph["nodes"] = keep
        graph["edges"] = [
            e for e in edges
            if e.get("from") in ids and e.get("to") in ids
        ]
        reasoning["inference_graph"] = graph
        reasoning["diagnostics"] = diagnostics
        reasoning["reasoning_budget"] = {
            "version": self.VERSION,
            "max_depth": self.budget.max_depth,
            "max_nodes": self.budget.max_nodes,
            "min_confidence": self.budget.min_confidence,
            "min_relevance": self.budget.min_relevance,
            "kept_nodes": len(keep),
            "pruned_by_depth": depth_pruned,
            "pruned_by_relevance": relevance_pruned,
            "pruned_by_confidence": confidence_pruned,
        }
        return reasoning
