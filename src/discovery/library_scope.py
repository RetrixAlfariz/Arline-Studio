from __future__ import annotations

from typing import Any

from src.memory.models import MemoryQueryContext

from .service import DiscoveryService


_INSTALLED = False


def install_library_scope_lineage(service: DiscoveryService) -> None:
    """Allow Library browsing to inherit valid ancestor-branch discoveries.

    With no active chat, Discovery intentionally aggregates across chat sessions
    in the selected project/world while counting Reviewed support per session.
    The old shortcut only accepted exact branch IDs, so a child world branch could
    not see pre-fork discoveries from its parent branch. This wrapper keeps chat
    lineage out of the decision, but applies the authoritative world-branch
    ancestry and recorded-time cutoff.
    """
    global _INSTALLED
    if getattr(service, "_library_scope_lineage_installed", False):
        return

    original = service._instance_allowed

    def allowed(instance: dict[str, Any], context: MemoryQueryContext) -> bool:
        if context.session_id is not None:
            return original(instance, context)
        if not instance.get("active"):
            return False
        if context.project_id and instance.get("project_id") not in {None, context.project_id}:
            return False
        if context.world_id and instance.get("world_id") not in {None, context.world_id}:
            return False

        branches = service.gate.branch_cutoffs(context.branch_id)
        candidate_branch = instance.get("branch_id")
        if candidate_branch not in branches:
            return False
        cutoff = branches.get(candidate_branch)
        if candidate_branch is not None and cutoff:
            recorded_at = instance.get("updated_at") or instance.get("created_at")
            if not recorded_at:
                return False
            if service.gate._after(str(recorded_at), str(cutoff)):
                return False

        # Story-time filtering still applies while Library is opened at a
        # narrative cursor. This mirrors the normal gate without introducing a
        # fake chat session that would reject all cross-session Library evidence.
        if context.story_order is not None and instance.get("story_order") is not None:
            if float(instance["story_order"]) > float(context.story_order):
                return False
        return True

    service._instance_allowed = allowed
    service._library_scope_lineage_installed = True
    _INSTALLED = True
