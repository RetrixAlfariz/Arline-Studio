from __future__ import annotations

from typing import Any


def normalize_identity_label(value: str) -> str:
    return " ".join(str(value or "").casefold().strip().split())


def _visible_family(foundation, family: dict[str, Any] | None) -> dict[str, Any] | None:
    if not family:
        return None
    if foundation is not None:
        try:
            if foundation.is_hidden("entity_family", family["id"]):
                return None
        except Exception:
            pass
    return family


def resolve_existing_family(workspace, foundation, label: str, entity_type: str) -> dict[str, Any] | None:
    """Resolve exact Library identity without fuzzy auto-merging.

    The order is intentionally precision-first: exact family name, exact alias,
    then exact *unique* variant display name. Any ambiguity abstains.
    """
    needle = normalize_identity_label(label)
    if not needle:
        return None

    try:
        families = workspace.list_entity_families(None, entity_type=entity_type)
    except Exception:
        families = []
    family_by_id = {str(item.get("id")): item for item in families if item.get("id")}

    exact_names = [
        item for item in families
        if normalize_identity_label(item.get("name") or "") == needle
        and _visible_family(foundation, item) is not None
    ]
    if len(exact_names) == 1:
        return exact_names[0]
    if len(exact_names) > 1:
        return None

    if foundation is not None:
        try:
            aliases = foundation.alias_matches(label, limit=100)
        except Exception:
            aliases = []
        alias_ids = {
            str(item.get("resource_id"))
            for item in aliases
            if item.get("resource_type") == "entity_family"
            and normalize_identity_label(item.get("normalized_alias") or item.get("alias") or "") == needle
            and str(item.get("resource_id")) in family_by_id
        }
        visible_alias_ids = {
            family_id for family_id in alias_ids
            if _visible_family(foundation, family_by_id.get(family_id)) is not None
        }
        if len(visible_alias_ids) == 1:
            return family_by_id[next(iter(visible_alias_ids))]
        if len(visible_alias_ids) > 1:
            return None

    try:
        variants = workspace.list_variants(entity_type=entity_type)
    except Exception:
        variants = []
    display_ids = {
        str(item.get("family_id"))
        for item in variants
        if normalize_identity_label(item.get("display_name") or "") == needle
        and str(item.get("family_id")) in family_by_id
    }
    visible_display_ids = {
        family_id for family_id in display_ids
        if _visible_family(foundation, family_by_id.get(family_id)) is not None
    }
    if len(visible_display_ids) == 1:
        return family_by_id[next(iter(visible_display_ids))]
    return None


def linked_subject_keys(store, *, project_id: str | None, world_id: str | None, family_id: str) -> list[str]:
    """Return exact Discovery subject anchors already linked to a Library family."""
    with store.connection() as con:
        rows = con.execute(
            "SELECT subject_key FROM discovery_subject_links "
            "WHERE project_id=? AND world_id=? AND resource_type='entity_family' AND resource_id=? "
            "ORDER BY updated_at DESC,subject_key",
            (project_id or "", world_id or "", family_id),
        ).fetchall()
    return [str(row["subject_key"]) for row in rows if row["subject_key"]]


def install_identity_resolution(*_args, **_kwargs) -> None:
    """Deprecated compatibility shim.

    v1.2.2 resolves identity explicitly inside NarrativeSemanticOrchestrator.
    Keeping this callable avoids breaking old imports without mutating class or
    module methods at import time.
    """
    return None
