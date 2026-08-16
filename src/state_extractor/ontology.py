from __future__ import annotations


PREDICATES = {
    # physical
    "physical.morphology.presentation",
    "physical.chest.reference_cup",
    "physical.chest.softness",
    "physical.chest.compliance",
    "hair.length_relative",
    "hair.density",
    # garments
    "garment.wearing",
    "garment.color",
    "garment.material",
    "garment.length",
    "garment.front_length",
    "garment.back_length",
    "garment.flowiness",
    "garment.size_class",
    "garment.purchased_for",
    # relationship/social
    "relationship.friend_of",
    "relationship.dating",
    "relationship.transition",
    "social.family_close",
    "social.aware_of",
    "social.approves_of",
    "social.arranged_relationship",
    # experience
    "experience.feminine_presentation",
    "experience.cosplay_outing",
    # normative/knowledge
    "norm.permission",
    "norm.prohibition",
    "knowledge.aware_of",
}


def canonical_predicate(value: str) -> str:
    aliases = {
        "friend": "relationship.friend_of",
        "friend_of": "relationship.friend_of",
        "pacar": "relationship.dating",
        "dating": "relationship.dating",
        "wearing": "garment.wearing",
        "wear": "garment.wearing",
        "bought_for": "garment.purchased_for",
        "purchased_for": "garment.purchased_for",
    }
    return aliases.get(value, value)
