from __future__ import annotations

from typing import Any


def _garment_type(label: str, subject_key: str) -> str:
    clean = str(label or "").strip().casefold().replace(" ", "_")
    key = str(subject_key or "")
    if key.startswith("garment:"):
        tail = key.split(":", 1)[1]
        if tail.endswith("_1"):
            tail = tail[:-2]
        if tail:
            return tail
    return clean or "garment"


def _display_label(label: str) -> str:
    raw = str(label or "").strip()
    if raw and raw == raw.lower():
        return raw.title()
    return raw or "Garment"


def install_garment_materialization(provisional_module) -> None:
    """Materialize semantic garment entities as callable Library Item sheets."""
    if getattr(provisional_module, "_GARMENT_MATERIALIZATION_INSTALLED", False):
        return

    original = provisional_module._ensure_sheet_for
    provisional_module.SUPPORTED_SHEET_TYPES.add("garment")

    def ensure_sheet_for(
        service,
        *,
        project_id: str | None,
        world_id: str | None,
        branch_id: str | None,
        subject_type: str,
        subject_key: str,
        subject_label: str,
        location_kind: str | None = None,
    ):
        if subject_type != "garment":
            return original(
                service,
                project_id=project_id,
                world_id=world_id,
                branch_id=branch_id,
                subject_type=subject_type,
                subject_key=subject_key,
                subject_label=subject_label,
                location_kind=location_kind,
            )

        family, variant, created = original(
            service,
            project_id=project_id,
            world_id=world_id,
            branch_id=branch_id,
            subject_type="item",
            subject_key=subject_key,
            subject_label=_display_label(subject_label),
            location_kind=None,
        )
        if family:
            current = service.workspace.get_entity_family(family["id"])
            core: dict[str, Any] = dict(current.get("shared_core") or {})
            changed = False
            if not core.get("kind"):
                core["kind"] = "garment"
                changed = True
            garment = dict(core.get("garment") or {})
            if not garment.get("type"):
                garment["type"] = _garment_type(subject_label, subject_key)
                changed = True
            core["garment"] = garment
            discovery = dict(core.get("_discovery") or {})
            if discovery.get("semantic_type") != "garment":
                discovery["semantic_type"] = "garment"
                changed = True
            core["_discovery"] = discovery
            if changed:
                service.workspace.update_entity_family(
                    family["id"],
                    shared_core=core,
                    note="discovery: garment item projection",
                )
                family = service.workspace.get_entity_family(family["id"])
        return family, variant, created

    provisional_module._ensure_sheet_for = ensure_sheet_for
    provisional_module._GARMENT_MATERIALIZATION_INSTALLED = True
