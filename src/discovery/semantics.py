from __future__ import annotations

from typing import Any


SPATIAL_PREDICATES = {
    "located_in", "located_on", "part_of", "inside", "stored_in",
    "adjacent_to", "connected_to", "entrance_to", "opens_into",
}
SPATIAL_SCALARS = {"floor_number", "area_m2", "room_count"}


def value_kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "any"


def describe_claim(proposition: dict[str, Any]) -> dict[str, Any]:
    """Return stable claim semantics used by UI, promotion and projections.

    Truth authority remains on the proposition/fact/timeline records. This
    descriptor only tells consumers what a claim *means* structurally.
    """
    predicate = str(proposition.get("predicate") or "")
    operation = str(proposition.get("operation") or "update")
    object_type = str(proposition.get("object_type") or "")
    subject_type = str(proposition.get("subject_type") or "")
    value = proposition.get("value")

    result = {
        "group": "attributes",
        "value_kind": value_kind(value),
        "temporal": "current_or_unspecified",
        "canon_target": "fact",
        "canonizable": True,
        "projection": "variant.attributes",
        "projection_path": predicate,
    }

    if operation == "create" and predicate == "entity.exists":
        result.update({
            "group": "identity", "temporal": "static",
            "canon_target": "entity_identity", "projection": None,
            "projection_path": None,
        })
        return result

    if operation == "relation":
        lightweight = object_type == "spatial_zone"
        result.update({
            "group": "spatial" if predicate in SPATIAL_PREDICATES else "relationships",
            "temporal": "relation",
            "canon_target": "none" if lightweight else "relationship",
            "canonizable": not lightweight,
            "projection": None,
            "projection_path": None,
        })
        return result

    if operation == "transition":
        result.update({
            "group": "state", "temporal": "transition",
            "canon_target": "timeline_or_fact", "projection": None,
            "projection_path": None,
        })
        return result

    if predicate == "location.kind":
        result.update({
            "group": "identity", "temporal": "static",
            "projection": "family.shared_core", "projection_path": "kind",
        })
    elif predicate.startswith("identity."):
        result.update({
            "group": "identity", "temporal": "static",
            "projection": "family.shared_core", "projection_path": predicate,
        })
    elif predicate.startswith("voice."):
        result.update({
            "group": "voice", "projection": "variant.voice",
            "projection_path": predicate.removeprefix("voice."),
        })
    elif predicate.startswith("knowledge."):
        result.update({
            "group": "knowledge", "projection": "variant.knowledge",
            "projection_path": predicate.removeprefix("knowledge."),
        })
    elif predicate.startswith("beliefs."):
        result.update({
            "group": "beliefs", "projection": "variant.beliefs",
            "projection_path": predicate.removeprefix("beliefs."),
        })
    elif predicate.startswith("state."):
        result.update({
            "group": "state", "temporal": "current",
            "projection": "variant.current_state",
            "projection_path": predicate.removeprefix("state."),
        })
    elif subject_type == "garment" or predicate.startswith("garment."):
        namespaced = predicate if predicate.startswith("garment.") else f"garment.{predicate}"
        result.update({
            "group": "garment", "projection": "variant.attributes",
            "projection_path": namespaced,
        })
    elif predicate in SPATIAL_SCALARS or predicate.startswith("location."):
        result.update({"group": "spatial"})
    elif predicate.startswith("personality."):
        result.update({"group": "personality"})

    return result


def install_claim_semantics(service) -> None:
    """Annotate every evaluated discovery with a deterministic semantic contract."""
    if getattr(service, "_claim_semantics_installed", False):
        return
    original = service.evaluate_proposition

    def evaluate_with_semantics(proposition, context, *, include_instances: bool = False):
        item = original(proposition, context, include_instances=include_instances)
        item["semantics"] = describe_claim(item)
        return item

    service.evaluate_proposition = evaluate_with_semantics
    service._claim_semantics_installed = True
