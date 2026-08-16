from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.state_extractor import (
    StructuralParser,
    SemanticSegmenter,
    TextNormalizer,
    AnnotationResolver,
    EntityReferenceResolver,
    ScopeResolver,
    AspectResolver,
    DiscourseResolver,
    ClaimExtractor,
    StateExtractor,
    ScenarioBuilder,
    EventBuilder,
    StateTransitionResolver,
    CoverageAnalyzer,
)
from src.analytical_system import WorldModelBuilder, AnalyticalReasoner, SurfacePlanner
from src.analytical_system.rule_registry import RuleRegistry
from src.analytical_system.budget import ReasoningBudgetGuard
from src.core import SemanticCoreBuilder, WorldRuntimeBuilder
from src.narrative import NarrativeRuntimeBuilder

SYSTEM_VERSION = "0.6.4"


@dataclass(slots=True)
class PipelineResult:
    extracted_state: dict[str, Any]
    events: dict[str, Any]
    analysis: dict[str, Any]
    debug: dict[str, Any]
    semantic_core: dict[str, Any] | None = None
    narrative_runtime: dict[str, Any] | None = None
    world_runtime: dict[str, Any] | None = None


class ArlineAnalyticalPipeline:
    VERSION = SYSTEM_VERSION

    def __init__(self):
        self.structural_parser = StructuralParser.default()
        self.semantic_segmenter = SemanticSegmenter.default()
        self.normalizer = TextNormalizer.default()
        self.annotation_resolver = AnnotationResolver.default()
        self.reference_resolver = EntityReferenceResolver.default()
        self.scope_resolver = ScopeResolver.default()
        self.aspect_resolver = AspectResolver.default()
        self.discourse_resolver = DiscourseResolver.default()
        self.claim_extractor = ClaimExtractor.default()
        self.state_extractor = StateExtractor.default()
        self.scenario_builder = ScenarioBuilder.default()
        self.event_builder = EventBuilder.default()
        self.transition_resolver = StateTransitionResolver.default()
        self.coverage_analyzer = CoverageAnalyzer.default()
        self.world_builder = WorldModelBuilder.default()
        self.reasoner = AnalyticalReasoner.default()
        self.surface_planner = SurfacePlanner.default()
        self.rule_registry = RuleRegistry.default()
        self.reasoning_budget_guard = ReasoningBudgetGuard()
        self.semantic_core_builder = SemanticCoreBuilder.default()
        self.world_runtime_builder = WorldRuntimeBuilder.default()
        self.narrative_runtime_builder = NarrativeRuntimeBuilder.default()

    @classmethod
    def default(cls):
        return cls()

    def run(self, text: str, *, surface_history: list[str] | None = None):
        structure = self.structural_parser.parse(text)
        semantic = self.semantic_segmenter.segment(structure)
        normalized = self.normalizer.normalize(semantic)
        annotations = self.annotation_resolver.resolve(normalized)
        entity_resolution = self.reference_resolver.resolve(normalized, annotations)
        scoped = self.scope_resolver.resolve(normalized)
        aspect = self.aspect_resolver.resolve(scoped)
        discourse = self.discourse_resolver.resolve(aspect)
        claims = self.claim_extractor.extract(discourse, entity_resolution, annotations, discourse)
        state = self.state_extractor.extract(discourse, entity_resolution, claims)
        scenario = self.scenario_builder.build(claims, state)
        event_data = self.event_builder.build(discourse, state, scenario)
        transitions = self.transition_resolver.resolve(state, event_data)
        coverage = self.coverage_analyzer.analyze(discourse, claims, state, event_data, scenario)

        world = self.world_builder.build(state, transitions)
        reasoning = self.reasoner.analyze(state, event_data, transitions, world, scenario)
        reasoning = self.reasoning_budget_guard.apply(reasoning)
        surface = self.surface_planner.plan(
            reasoning,
            history=surface_history,
            scene_focus=scenario.get("scene_focus", {}),
        )

        extracted_state = {
            "system_version": self.VERSION,
            "component_version": state.get("version"),
            "entities": state.get("entities", []),
            "relations": state.get("relations", []),
            "experience": state.get("experience", []),
            "norms": state.get("norms", []),
            "knowledge": state.get("knowledge", []),
            "beliefs": state.get("beliefs", []),
            "relationship_timeline": state.get("relationship_timeline", []),
            "claim_conflicts": state.get("claim_conflicts", []),
            "claims": state.get("claims", []),
            "scenario": scenario,
            "directives": state.get("directives", []),
            "requests": state.get("requests", []),
            "unknowns": state.get("unknowns", []),
            "reference_resolutions": entity_resolution.get("resolutions", []),
            "entity_aliases": entity_resolution.get("aliases", []),
            "entity_lifecycle": entity_resolution.get("lifecycle", []),
            "discourse_relations": discourse.get("relations", []),
            "coverage": coverage,
            "diagnostics": (
                structure.get("diagnostics", [])
                + semantic.get("diagnostics", [])
                + normalized.get("diagnostics", [])
                + annotations.get("diagnostics", [])
                + entity_resolution.get("diagnostics", [])
                + scoped.get("diagnostics", [])
                + aspect.get("diagnostics", [])
                + discourse.get("diagnostics", [])
                + claims.get("diagnostics", [])
                + state.get("diagnostics", [])
                + scenario.get("diagnostics", [])
            ),
        }

        events = {
            "system_version": self.VERSION,
            "event_builder_version": event_data.get("version"),
            "transition_resolver_version": transitions.get("version"),
            "events": event_data.get("events", []),
            "scenario_events": event_data.get("scenario_events", []),
            "event_candidates": event_data.get("event_candidates", []),
            "state_patches": transitions.get("patches", []),
            "state_snapshots": transitions.get("snapshots", []),
            "conflicts": transitions.get("conflicts", []),
            "diagnostics": event_data.get("diagnostics", []) + transitions.get("diagnostics", []),
        }

        analysis = {
            "system_version": self.VERSION,
            "analytical_reasoner_version": reasoning.get("version"),
            "world_model_version": world.get("version"),
            "surface_planner_version": surface.get("version"),
            "scene_focus": scenario.get("scene_focus", {}),
            "derived_facts": reasoning.get("derived_facts", []),
            "constraints": reasoning.get("constraints", []),
            "interactions": reasoning.get("interactions", []),
            "consequences": reasoning.get("consequences", []),
            "blocked_inferences": reasoning.get("blocked_inferences", []),
            "uncertainties": reasoning.get("uncertainties", []),
            "surface_plan": surface,
            "inference_graph": reasoning.get("inference_graph", {}),
            "coverage": coverage,
            "reasoning_budget": reasoning.get("reasoning_budget", {}),
            "rule_registry": self.rule_registry.summary(),
            "diagnostics": world.get("diagnostics", []) + reasoning.get("diagnostics", []) + surface.get("diagnostics", []),
        }

        debug = {
            "structure": structure,
            "semantic_segments": semantic,
            "normalized_segments": normalized,
            "annotations": annotations,
            "entity_resolution": entity_resolution,
            "scoped_segments": scoped,
            "aspect_segments": aspect,
            "discourse": discourse,
            "claims": claims,
            "scenario": scenario,
            "world_model": world,
            "coverage": coverage,
        }
        result = PipelineResult(extracted_state, events, analysis, debug)
        semantic_core = self.semantic_core_builder.build(result)
        narrative = self.narrative_runtime_builder.build(
            text, result, surface_history=surface_history
        )
        world_runtime = self.world_runtime_builder.build(semantic_core, result)
        result.semantic_core = semantic_core.to_dict()
        result.world_runtime = world_runtime.to_dict()
        result.narrative_runtime = narrative.to_dict()
        result.debug["semantic_core"] = result.semantic_core
        result.debug["world_runtime"] = result.world_runtime
        result.debug["narrative_runtime"] = result.narrative_runtime
        return result
