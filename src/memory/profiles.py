from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import ContextLens


@dataclass(frozen=True, slots=True)
class MemoryTaskProfile:
    """Isolated task contract for one use of the primary generative model.

    Profiles share model weights, never hidden task history. Every invocation is
    expected to build a fresh request from this contract + an explicit Context
    Recipe/evidence bundle. v1.2 never permits a model profile to commit canon.
    """

    id: str
    task_type: str
    system_contract: str
    context_recipe_id: str
    context_lens: ContextLens
    output_mode: str
    output_schema_id: str | None = None
    temperature: float = 0.1
    max_output_tokens: int = 2048
    reasoning_mode: str = "off"
    allow_creative_inference: bool = False
    allow_cross_scope_evidence: bool = False
    may_create_proposal: bool = False
    may_commit_canon: bool = False
    inherit_hidden_history: bool = False
    retry_policy: str = "validate_once_then_retry_once"
    validation_policy: str = "scope_identity_time_provenance"

    def __post_init__(self) -> None:
        if self.may_commit_canon:
            raise ValueError("v1.2 task profiles may never commit canon")
        if self.inherit_hidden_history:
            raise ValueError("task profiles must not inherit hidden history from another task")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_type": self.task_type,
            "system_contract": self.system_contract,
            "context_recipe_id": self.context_recipe_id,
            "context_lens": self.context_lens.value,
            "output_mode": self.output_mode,
            "output_schema_id": self.output_schema_id,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            "reasoning_mode": self.reasoning_mode,
            "allow_creative_inference": self.allow_creative_inference,
            "allow_cross_scope_evidence": self.allow_cross_scope_evidence,
            "may_create_proposal": self.may_create_proposal,
            "may_commit_canon": self.may_commit_canon,
            "inherit_hidden_history": self.inherit_hidden_history,
            "retry_policy": self.retry_policy,
            "validation_policy": self.validation_policy,
        }


TASK_PROFILES: dict[str, MemoryTaskProfile] = {
    "story_writer": MemoryTaskProfile(
        id="story_writer",
        task_type="story",
        system_contract=(
            "Write narrative prose from the supplied active scene and admitted evidence. "
            "Treat retrieved material as evidence, preserve uncertainty, and never alter canon directly."
        ),
        context_recipe_id="RECIPE-STORY",
        context_lens=ContextLens.SCENE,
        output_mode="prose",
        temperature=0.85,
        max_output_tokens=8192,
        allow_creative_inference=True,
        may_create_proposal=True,
    ),
    "dialogue_writer": MemoryTaskProfile(
        id="dialogue_writer",
        task_type="dialogue",
        system_contract=(
            "Write dialogue using only admitted speaker voice, relationship state, scene facts, and "
            "knowledge available to the participating characters."
        ),
        context_recipe_id="RECIPE-DIALOGUE",
        context_lens=ContextLens.POV,
        output_mode="prose",
        temperature=0.9,
        max_output_tokens=4096,
        allow_creative_inference=True,
        may_create_proposal=True,
    ),
    "structure_extractor": MemoryTaskProfile(
        id="structure_extractor",
        task_type="extract",
        system_contract=(
            "Extract only claims explicitly supported by the supplied source spans. "
            "Do not complete missing detail; return empty arrays when nothing is supported."
        ),
        context_recipe_id="RECIPE-EXTRACT",
        context_lens=ContextLens.SCENE,
        output_mode="structured",
        output_schema_id="memory_proposals_v1",
        temperature=0.05,
        max_output_tokens=4096,
        may_create_proposal=True,
    ),
    "memory_summarizer": MemoryTaskProfile(
        id="memory_summarizer",
        task_type="summarize",
        system_contract=(
            "Summarize only supplied evidence. Keep explicit facts separate from inference and uncertainty, "
            "and return the source chunk IDs used."
        ),
        context_recipe_id="RECIPE-SUMMARY",
        context_lens=ContextLens.SCENE,
        output_mode="structured",
        output_schema_id="memory_summary_v1",
        temperature=0.15,
        max_output_tokens=3072,
    ),
    "evidence_analyst": MemoryTaskProfile(
        id="evidence_analyst",
        task_type="analysis",
        system_contract=(
            "Analyze admitted evidence, separate fact from inference, preserve disagreements, "
            "cite provenance, and abstain when support is insufficient."
        ),
        context_recipe_id="RECIPE-ANALYSIS",
        context_lens=ContextLens.AUTHOR,
        output_mode="analysis",
        temperature=0.15,
        max_output_tokens=4096,
        reasoning_mode="optional",
        allow_cross_scope_evidence=True,
    ),
    "continuity_explainer": MemoryTaskProfile(
        id="continuity_explainer",
        task_type="explain_issue",
        system_contract=(
            "Explain a deterministic continuity issue already detected by Arline. "
            "Do not create, dismiss, or resolve the issue yourself."
        ),
        context_recipe_id="RECIPE-CONTINUITY",
        context_lens=ContextLens.SCENE,
        output_mode="explanation",
        temperature=0.1,
        max_output_tokens=2048,
    ),
    "branch_comparison": MemoryTaskProfile(
        id="branch_comparison",
        task_type="branch_compare",
        system_contract=(
            "Explain deterministic differences between explicitly supplied branches. "
            "Never merge branches; any suggested reconciliation remains a proposal."
        ),
        context_recipe_id="RECIPE-BRANCH-COMPARE",
        context_lens=ContextLens.AUTHOR,
        output_mode="analysis",
        temperature=0.1,
        max_output_tokens=3072,
        allow_cross_scope_evidence=True,
        may_create_proposal=True,
    ),
    "ambiguous_query_router": MemoryTaskProfile(
        id="ambiguous_query_router",
        task_type="route",
        system_contract=(
            "Choose exactly one supported query route and resolved anchors. "
            "Do not retrieve evidence and do not answer the user."
        ),
        context_recipe_id="RECIPE-ROUTER",
        context_lens=ContextLens.SCENE,
        output_mode="route",
        temperature=0.0,
        max_output_tokens=256,
    ),
}


def get_task_profile(profile_id: str) -> MemoryTaskProfile:
    try:
        return TASK_PROFILES[profile_id]
    except KeyError as exc:
        raise KeyError(f"Unknown memory task profile: {profile_id}") from exc
