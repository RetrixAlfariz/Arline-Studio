from __future__ import annotations

from typing import Any

from .models import ContextLens, MemoryCandidate, MemoryQueryContext, ScopeDecision, SemanticStatus, TrustLevel
from .security import inspect_retrieved_text


class ScopeGate:
    """One authoritative gate used by every retrieval lane."""

    def __init__(self, workspace, history=None):
        self.workspace = workspace
        self.history = history

    def visible_branches(self, branch_id: str | None) -> set[str | None]:
        visible: set[str | None] = {None}
        current = branch_id
        guard = 0
        while current and guard < 128:
            if current in visible:
                break
            visible.add(current)
            try:
                branch = self.workspace.get_branch(current)
            except KeyError:
                break
            current = branch.get("parent_branch_id")
            guard += 1
        return visible

    def visible_sessions(self, session_id: str | None) -> set[str | None]:
        visible: set[str | None] = {None}
        if not session_id or self.history is None:
            return visible
        current = session_id
        guard = 0
        while current and guard < 256:
            if current in visible:
                break
            visible.add(current)
            try:
                meta = self.history.get_session_meta(current)
            except KeyError:
                break
            current = meta.get("parent_session_id")
            guard += 1
        return visible

    @staticmethod
    def _explicitly_allowed(candidate: MemoryCandidate, context: MemoryQueryContext) -> bool:
        for item in context.explicit_cross_scope_sources:
            if item.get("source_type") == candidate.source_type and item.get("source_id") == candidate.source_id:
                return True
        return False

    def evaluate(self, candidate: MemoryCandidate, context: MemoryQueryContext) -> ScopeDecision:
        explicit_cross_scope = self._explicitly_allowed(candidate, context)

        if candidate.semantic_status not in {SemanticStatus.ACTIVE.value}:
            return ScopeDecision(False, f"semantic status is {candidate.semantic_status}", "semantic_status")

        hygiene = inspect_retrieved_text(candidate.text, trust_level=candidate.trust_level)
        if not hygiene.safe_for_automatic_context and not explicit_cross_scope:
            return ScopeDecision(False, ", ".join(hygiene.flags) or "source is quarantined", "trust")

        if candidate.authority == "scratch" and not context.allow_scratch and not explicit_cross_scope:
            return ScopeDecision(False, "scratch evidence is disabled", "scratch")

        if candidate.project_id and context.project_id and candidate.project_id != context.project_id and not explicit_cross_scope:
            return ScopeDecision(False, "different project", "project")

        if candidate.world_id and context.world_id and candidate.world_id != context.world_id and not explicit_cross_scope:
            return ScopeDecision(False, "different world", "world")

        if candidate.branch_id not in self.visible_branches(context.branch_id) and not explicit_cross_scope:
            return ScopeDecision(False, "sibling/descendant branch is not visible", "branch")

        if candidate.session_id not in self.visible_sessions(context.session_id) and not explicit_cross_scope:
            return ScopeDecision(False, "sibling/later chat fork is not visible", "session")

        if context.story_order is not None and candidate.story_order is not None:
            if candidate.story_order > context.story_order:
                if context.context_lens == ContextLens.AUTHOR and context.allow_future_author_knowledge:
                    pass
                elif not explicit_cross_scope:
                    return ScopeDecision(False, "future story-order evidence blocked by active lens", "story_order")

        if context.context_lens == ContextLens.POV and candidate.metadata.get("author_only") and not explicit_cross_scope:
            return ScopeDecision(False, "author-only evidence blocked by POV lens", "pov")

        if explicit_cross_scope:
            candidate.metadata["cross_scope_evidence"] = True
            return ScopeDecision(True, "explicit cross-scope comparison evidence", "explicit_override")
        return ScopeDecision(True, "visible in current scope", "allowed")

    def filter(self, candidates: list[MemoryCandidate], context: MemoryQueryContext) -> tuple[list[MemoryCandidate], list[dict[str, Any]]]:
        allowed: list[MemoryCandidate] = []
        excluded: list[dict[str, Any]] = []
        for candidate in candidates:
            decision = self.evaluate(candidate, context)
            if decision.allowed:
                allowed.append(candidate)
            else:
                excluded.append({"candidate": candidate.to_dict(), "decision": decision.to_dict()})
        return allowed, excluded
