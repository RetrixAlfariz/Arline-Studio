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
    """Resolve an existing Library identity without fuzzy auto-merging.

    Resolution order is deliberately conservative:
      1. exact normalized family name;
      2. exact normalized alias;
      3. exact normalized *unique* variant display name.

    Ambiguous matches return ``None``. Narrative Discovery must never guess that
    two identities are the same merely because their names are similar.
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


def install_identity_resolution(service_module, provisional_module) -> None:
    """Make Discovery capture and provisional materialization share one resolver."""
    if getattr(service_module.DiscoveryService, "_identity_resolution_v2", False):
        return

    def service_existing_family(self, label: str, entity_type: str):
        mapped = service_module.LIBRARY_ENTITY_TYPE.get(entity_type, entity_type)
        return resolve_existing_family(self.workspace, self.foundation, label, mapped)

    def provisional_existing_family(service, label: str, entity_type: str):
        return resolve_existing_family(service.workspace, service.foundation, label, entity_type)

    service_module.DiscoveryService._existing_family = service_existing_family
    service_module.DiscoveryService._identity_resolution_v2 = True
    provisional_module._existing_family = provisional_existing_family
