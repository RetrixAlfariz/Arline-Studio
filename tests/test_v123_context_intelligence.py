from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.context.intelligence import NarrativeContextPlanner
from src.history.store import HistoryStore
from src.memory import MemoryCandidate, MemoryConfig, MemoryQueryContext, MemoryService, MemoryStore, RetrievalLane
from src.memory.web import create_memory_router
from src.workspace import FoundationStore, WorkspaceContext
from src.workspace.store import WorkspaceStore


class Fixture:
    def __init__(self, root: str):
        path = Path(root) / "arline.db"
        self.workspace = WorkspaceStore(path, backup_before_migration=False)
        self.history = HistoryStore(path, backup_before_migration=False)
        self.foundation = FoundationStore(path)
        self.project = self.workspace.create_project("v123 context")
        self.world_id = self.project["default_world_id"]
        self.branch = next(x for x in self.workspace.get_world(self.world_id)["branches"] if x["kind"] == "main")
        cfg = MemoryConfig(); cfg.dense_enabled = False; cfg.final_k = 16
        store = MemoryStore(path, backup_before_migration=False)
        self.memory = MemoryService(
            store=store, workspace=self.workspace, history=self.history,
            foundation=self.foundation, config=cfg,
            lmstudio_base_url="http://127.0.0.1:1234",
        )
        create_memory_router(service=self.memory, store=store, foundation=self.foundation)
        self.discovery = self.memory.discovery
        self.session = self.history.create_session(
            prompt="v123", project_id=self.project["id"], world_id=self.world_id,
            branch_id=self.branch["id"],
        )

    def context(self, **kwargs):
        return MemoryQueryContext(
            project_id=self.project["id"], world_id=self.world_id,
            branch_id=self.branch["id"], session_id=self.session["id"],
            token_budget=kwargs.pop("token_budget", 1800), **kwargs,
        )

    def ws(self, *, pov=None, location=None, participants=None, refs=None):
        active = {
            "pov_variant_id": pov, "location_variant_id": location,
            "participants": list(participants or []), "narrative_time": "now",
        }
        autos = []
        for rid, reason in [(pov, "active scene POV"), (location, "active scene location")]:
            if rid:
                autos.append({"type": "entity_variant", "id": rid, "label": rid, "reason": reason})
        autos.extend({"type": "entity_variant", "id": rid, "label": rid, "reason": "present in active scene"} for rid in participants or [])
        return WorkspaceContext(
            version="0.2", text="@ARLINE-WORKSPACE 0.1\n", scope={"active_scene": active},
            explicit_references=list(refs or []), auto_selected=autos, estimated_tokens=32,
        )

    def family_variant(self, name: str):
        family = self.workspace.create_entity_family(
            None, name, entity_type="character", create_variant_in_world=self.world_id,
            branch_id=self.branch["id"],
        )
        variant = self.workspace.resolve_variant(family["id"], self.world_id, self.branch["id"])
        return family, variant

    def add_claim(self, *, subject_key: str, label: str, predicate: str, value, suffix: str):
        turn = self.history.add_turn(
            self.session["id"], run_id=f"RUN-V123-{suffix}", user_prompt=f"{label} {predicate} {value}",
            story="Generated.", model="fixture", mode="smart_hybrid", reasoning="off", projection_mode="off",
        )
        prop = self.discovery.store.upsert_proposition(
            project_id=self.project["id"], world_id=self.world_id, subject_type="character",
            subject_key=subject_key, subject_label=label, predicate=predicate, value=value,
            operation="update",
        )
        self.discovery.store.add_instance(
            prop["id"], source_kind="user_prompt", source_session_id=self.session["id"], source_turn_id=turn["id"],
            origin_session_id=self.session["id"], origin_turn_id=turn["id"], source_revision=f"R-{suffix}",
            project_id=self.project["id"], world_id=self.world_id, branch_id=self.branch["id"],
            story_order=float(turn.get("ordinal") or 0), span_text=turn["user_prompt"], extraction_confidence=1,
            explicitness="explicit", qualifies_review=True,
        )
        return turn, prop


class V123ContextIntelligenceTests(unittest.TestCase):
    def test_dialogue_plan_prioritizes_pov_relationship_and_continuity(self):
        planner = NarrativeContextPlanner()
        scope = MemoryQueryContext(context_lens="pov", pov_variant_id="VAR-A", token_budget=2000)
        ws = WorkspaceContext(
            version="0.2", text="", scope={"active_scene": {"pov_variant_id": "VAR-A", "participants": ["VAR-B"]}},
            auto_selected=[{"type":"entity_variant","id":"VAR-A","label":"Alex"},{"type":"entity_variant","id":"VAR-B","label":"Mira"}],
        )
        plan = planner.plan("Continue their dialogue while Alex listens carefully.", scope, workspace_context=ws, route="STORY_CONTINUE")
        self.assertEqual(plan.intent, "dialogue")
        self.assertEqual(plan.dimensions["pov"], 1.0)
        self.assertGreaterEqual(plan.dimensions["relationships"], .95)
        self.assertIn("continuity", plan.preserve_lanes)
        self.assertIn("epistemic", plan.preserve_lanes)
        self.assertIn("relationships", plan.optional_lanes)

    def test_active_scene_anchors_become_focus_resources_without_prompt_names(self):
        planner = NarrativeContextPlanner()
        scope = MemoryQueryContext(token_budget=1200)
        ws = WorkspaceContext(version="0.2", text="", scope={"active_scene": {
            "pov_variant_id":"VAR-P", "location_variant_id":"VAR-L", "participants":["VAR-X"]
        }})
        plan = planner.plan("Continue.", scope, workspace_context=ws, route="STORY_CONTINUE")
        self.assertEqual({x["id"] for x in plan.focus_resources}, {"VAR-P", "VAR-L", "VAR-X"})

    def test_plan_allocates_lane_budget_but_keeps_hard_global_ceiling(self):
        plan = NarrativeContextPlanner().plan(
            "Continue the action scene.", MemoryQueryContext(token_budget=1000), route="STORY_CONTINUE"
        )
        self.assertTrue(plan.lane_token_budget)
        self.assertTrue(all(value >= 96 for value in plan.lane_token_budget.values()))
        self.assertIn("continuity", plan.preserve_lanes)

    def test_query_compiler_injects_scene_focus_and_plan_lanes(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(td)
            family, variant = fx.family_variant("Alex")
            ws = fx.ws(participants=[variant["id"]])
            ctx = fx.context()
            plan = fx.memory.context_planner.plan("Continue.", ctx, workspace_context=ws, route="STORY_CONTINUE")
            compiled = fx.memory.query_engine.compiler.compile("Continue.", ctx, context_plan=plan.to_dict())
            self.assertTrue(any(x["id"] == variant["id"] and x["method"] == "context_plan" for x in compiled.resolved_entities))
            self.assertIn(RetrievalLane.CONTINUITY, compiled.optional_lanes)
            self.assertIn(RetrievalLane.RELATIONSHIPS, compiled.optional_lanes)

    def test_continuity_lane_retrieves_current_head_for_active_scene_entity(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(td)
            family, variant = fx.family_variant("Alex")
            fx.discovery.store.upsert_subject_link(
                project_id=fx.project["id"], world_id=fx.world_id,
                subject_key="char:alex", resource_type="entity_family", resource_id=family["id"],
            )
            fx.add_claim(subject_key="char:alex", label="Alex", predicate="state.form", value="human", suffix="HEAD")
            ws = fx.ws(participants=[variant["id"]])
            result = fx.memory.retrieve("Continue Alex's scene.", fx.context(), workspace_context=ws)
            continuity = [x for x in result.selected if x.lane == RetrievalLane.CONTINUITY]
            self.assertTrue(any("CURRENT Alex.state.form" in x.text for x in continuity))
            self.assertIn("@ARLINE-NARRATIVE-CONTEXT 1.2.3", result.packed_text)

    def test_unresolved_continuity_is_surfaced_not_guessed(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(td)
            family, variant = fx.family_variant("Alex")
            fx.discovery.store.upsert_subject_link(
                project_id=fx.project["id"], world_id=fx.world_id,
                subject_key="char:alex", resource_type="entity_family", resource_id=family["id"],
            )
            _t1, p1 = fx.add_claim(subject_key="char:alex", label="Alex", predicate="state.form", value="human", suffix="AMB1")
            t2, p2 = fx.add_claim(subject_key="char:alex", label="Alex", predicate="state.form", value="wolf", suffix="AMB2")
            fx.discovery.continuity.resolve_turn(t2["id"])
            ws = fx.ws(participants=[variant["id"]])
            result = fx.memory.retrieve("Continue the scene.", fx.context(), workspace_context=ws)
            ambiguous = [x for x in result.selected if x.metadata.get("ambiguity")]
            self.assertTrue(ambiguous)
            self.assertIn("[UNRESOLVED CONTINUITY]", result.packed_text)
            self.assertEqual(fx.discovery.store.get_proposition(p1["id"])["authority_state"], "observed")
            self.assertEqual(fx.discovery.store.get_proposition(p2["id"])["authority_state"], "observed")

    def test_relationship_lane_uses_focused_variants(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(td)
            _fa, a = fx.family_variant("Alex")
            _fb, b = fx.family_variant("Mira")
            relationship = fx.workspace.create_relationship(
                fx.world_id, a["id"], b["id"], "friend_of",
                branch_id=fx.branch["id"], canon_status="canon",
            )
            ws = fx.ws(participants=[a["id"], b["id"]])
            result = fx.memory.retrieve("Continue their dialogue.", fx.context(), workspace_context=ws)
            rows = [x for x in result.selected if x.lane == RetrievalLane.RELATIONSHIPS]
            self.assertTrue(any(x.id == relationship["id"] for x in rows))
            self.assertIn("[RELATIONSHIPS]", result.packed_text)

    def test_tight_budget_preserves_semantic_lanes_before_verbose_source(self):
        candidates = [
            MemoryCandidate("SRC", RetrievalLane.FTS_MANUSCRIPT, "x" * 900, "document", "D"),
            MemoryCandidate("CONT", RetrievalLane.CONTINUITY, "current form human", "continuity_head", "P"),
            MemoryCandidate("POV", RetrievalLane.EPISTEMIC, "Alex knows secret A", "epistemic", "E"),
        ]
        fitted = fx_engine_fit(candidates, 190, {
            "preserve_lanes": ["continuity", "epistemic"],
            "lane_token_budget": {"continuity": 100, "epistemic": 100, "fts_manuscript": 100},
        })
        self.assertEqual([x.id for x in fitted], ["CONT", "POV"])

    def test_workspace_context_exposes_exact_context_plan(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(td)
            family, variant = fx.family_variant("Alex")
            ws = fx.ws(participants=[variant["id"]])
            result = fx.memory.retrieve("Continue.", fx.context(), workspace_context=ws)
            augmented = fx.memory.augment_workspace_context(ws, result)
            self.assertEqual(augmented.scope["context_intelligence"]["version"], "1.2.5a1")
            self.assertEqual(augmented.scope["memory"]["context_intelligence_version"], "1.2.5a1")
            self.assertIn("@ARLINE-NARRATIVE-CONTEXT 1.2.3", augmented.text)

    def test_memory_status_reports_context_intelligence_version(self):
        with tempfile.TemporaryDirectory() as td:
            fx = Fixture(td)
            self.assertEqual(fx.memory.status()["context_intelligence_version"], "1.2.5a1")


def fx_engine_fit(candidates, budget, plan):
    from src.memory.query import MemoryQueryEngine
    return MemoryQueryEngine._fit_token_budget(candidates, budget, plan)


if __name__ == "__main__":
    unittest.main()
