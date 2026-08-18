from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

from .service import DiscoveryService


@dataclass(slots=True)
class DiscoveryBackfillReport:
    sessions: int = 0
    turns: int = 0
    propositions: int = 0
    instances: int = 0
    skipped: int = 0
    errors: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def backfill_discoveries(discovery: DiscoveryService, *, project_id: str | None = None,
                         limit_sessions: int = 500) -> DiscoveryBackfillReport:
    """Idempotently scan existing chat turns into Narrative Discovery.

    This is intentionally explicit rather than an automatic startup migration:
    large workspaces may contain hundreds of long turns, so the user should opt
    into the scan from the Discovery UI / Memory settings.
    """
    report = DiscoveryBackfillReport()
    sessions = discovery.history.list_sessions(
        project_id=project_id,
        include_archived=True,
        limit=max(1, min(int(limit_sessions), 500)),
    )
    for session_meta in sessions:
        report.sessions += 1
        session_id = session_meta["id"]
        try:
            if discovery.foundation is not None and discovery.foundation.is_hidden("session", session_id, include_archived=True):
                discovery.set_session_active(session_id, active=False, reason="source_trashed")
                report.skipped += 1
                continue
            session = discovery.history.get_session(session_id, include_context=True)
        except Exception:
            report.errors += 1
            continue
        for turn in session.get("turns", []) or []:
            report.turns += 1
            try:
                user = discovery.capture_turn(turn["id"], source_kind="user_prompt")
                report.propositions += user.propositions
                report.instances += user.instances
                report.skipped += user.skipped

                status = turn.get("feedback_status") or "unreviewed"
                if status == "accepted":
                    generated = discovery.capture_turn(turn["id"], source_kind="accepted_generation")
                    report.propositions += generated.propositions
                    report.instances += generated.instances
                    report.skipped += generated.skipped
                elif status == "edited_accept":
                    edited = discovery.capture_turn(turn["id"], source_kind="user_edited_prose")
                    report.propositions += edited.propositions
                    report.instances += edited.instances
                    report.skipped += edited.skipped
            except Exception:
                report.errors += 1
    return report
