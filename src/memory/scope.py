
from __future__ import annotations

from datetime import datetime
from typing import Any

from .models import ContextLens, MemoryCandidate, MemoryQueryContext, ScopeDecision, SemanticStatus
from .security import inspect_retrieved_text


class ScopeGate:
    """One authoritative gate used by every retrieval lane."""

    def __init__(self, workspace, history=None):
        self.workspace = workspace
        self.history = history
        self._turn_cutoff_cache: dict[tuple[str, str], set[str]] = {}

    def branch_cutoffs(self, branch_id: str | None) -> dict[str | None, str | None]:
        visible: dict[str | None, str | None] = {None: None}
        current = branch_id
        running_cutoff: str | None = None
        guard = 0
        while current and guard < 128:
            if current in visible:
                break
            visible[current] = running_cutoff
            try:
                branch = self.workspace.get_branch(current)
            except KeyError:
                break
            created = branch.get("created_at")
            if created and (running_cutoff is None or str(created) < str(running_cutoff)):
                running_cutoff = str(created)
            current = branch.get("parent_branch_id")
            guard += 1
        return visible

    def session_cutoffs(self, session_id: str | None) -> dict[str | None, str | None]:
        visible: dict[str | None, str | None] = {None: None}
        if not session_id or self.history is None:
            return visible
        current = session_id
        guard = 0
        while current and guard < 256:
            if current in visible:
                break
            try:
                meta = self.history.get_session_meta(current)
            except KeyError:
                break
            visible[current] = None if current == session_id else visible.get(current)
            parent = meta.get("parent_session_id")
            if parent:
                visible[parent] = meta.get("forked_from_turn_id")
            current = parent
            guard += 1
        return visible

    def _turn_ids_through(self, session_id: str, cutoff_turn_id: str) -> set[str]:
        key = (session_id, cutoff_turn_id)
        cached = self._turn_cutoff_cache.get(key)
        if cached is not None:
            return cached
        allowed: set[str] = set()
        try:
            turns = self.history.get_session(session_id).get("turns", [])
        except Exception:
            turns = []
        for turn in turns:
            allowed.add(turn["id"])
            if turn["id"] == cutoff_turn_id:
                self._turn_cutoff_cache[key] = allowed
                return allowed
        self._turn_cutoff_cache[key] = set()
        return set()

    @staticmethod
    def _recorded_at(candidate: MemoryCandidate) -> str | None:
        direct = candidate.metadata.get("source_recorded_at")
        if direct:
            return str(direct)
        for key in ("event", "spatial_edge", "thread", "interval", "epistemic"):
            payload = candidate.metadata.get(key)
            if isinstance(payload, dict):
                value = payload.get("updated_at") or payload.get("created_at")
                if value:
                    return str(value)
        return None

    @staticmethod
    def _after(value: str, cutoff: str) -> bool:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")) > datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
        except ValueError:
            return value > cutoff

    @staticmethod
    def _explicitly_allowed(candidate: MemoryCandidate, context: MemoryQueryContext) -> bool:
        return any(
            item.get("source_type") == candidate.source_type and item.get("source_id") == candidate.source_id
            for item in context.explicit_cross_scope_sources
        )

    def evaluate(self, candidate: MemoryCandidate, context: MemoryQueryContext) -> ScopeDecision:
        explicit = self._explicitly_allowed(candidate, context)
        if candidate.semantic_status != SemanticStatus.ACTIVE.value:
            return ScopeDecision(False, f"semantic status is {candidate.semantic_status}", "semantic_status")
        hygiene = inspect_retrieved_text(candidate.text, trust_level=candidate.trust_level)
        if not hygiene.safe_for_automatic_context and not explicit:
            return ScopeDecision(False, ", ".join(hygiene.flags) or "source is quarantined", "trust")
        if candidate.authority == "scratch" and not context.allow_scratch and not explicit:
            return ScopeDecision(False, "scratch evidence is disabled", "scratch")
        if candidate.project_id and context.project_id and candidate.project_id != context.project_id and not explicit:
            return ScopeDecision(False, "different project", "project")
        if candidate.world_id and context.world_id and candidate.world_id != context.world_id and not explicit:
            return ScopeDecision(False, "different world", "world")

        branches = self.branch_cutoffs(context.branch_id)
        if candidate.branch_id not in branches and not explicit:
            return ScopeDecision(False, "sibling/descendant branch is not visible", "branch")
        branch_cutoff = branches.get(candidate.branch_id)
        if candidate.branch_id is not None and branch_cutoff and not explicit:
            recorded_at = self._recorded_at(candidate)
            if recorded_at is None:
                return ScopeDecision(False, "ancestor-branch evidence has no fork-cutoff timestamp", "branch_cutoff_unknown")
            if self._after(recorded_at, branch_cutoff):
                return ScopeDecision(False, "ancestor-branch evidence was recorded after this branch forked", "branch_cutoff")

        sessions = self.session_cutoffs(context.session_id)
        if candidate.session_id not in sessions and not explicit:
            return ScopeDecision(False, "sibling/later chat fork is not visible", "session")
        session_cutoff = sessions.get(candidate.session_id)
        if candidate.session_id is not None and session_cutoff and not explicit:
            if candidate.source_type not in {"chat_window", "turn"}:
                return ScopeDecision(False, "ancestor-chat evidence cannot be bounded to the fork point", "session_cutoff_unknown")
            allowed_turns = self._turn_ids_through(candidate.session_id, session_cutoff)
            if candidate.source_id not in allowed_turns:
                return ScopeDecision(False, "parent-chat turn was written after the child fork point", "session_cutoff")

        if context.story_order is not None and candidate.story_order is not None and candidate.story_order > context.story_order:
            if not (context.context_lens == ContextLens.AUTHOR and context.allow_future_author_knowledge) and not explicit:
                return ScopeDecision(False, "future story-order evidence blocked by active lens", "story_order")
        if context.context_lens == ContextLens.POV and candidate.metadata.get("author_only") and not explicit:
            return ScopeDecision(False, "author-only evidence blocked by POV lens", "pov")
        if explicit:
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
