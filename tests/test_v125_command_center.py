from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from src.context.intelligence import NarrativeContextPlanner
from src.directives import COMMAND_RUNTIME_VERSION, DirectiveEngine


ROOT = Path(__file__).resolve().parents[1]


class _Scope:
    explicit_references = []
    pov_variant_id = None
    world_time = None
    story_order = None
    token_budget = 1800
    context_lens = "scene"
    allow_future_author_knowledge = False


class V125CommandCenterTests(unittest.TestCase):
    def test_command_runtime_composes_modifiers_and_operation(self):
        refs = [
            {"type": "entity_variant", "id": "V-FILA", "label": "Fila", "mode": "context"},
            {"type": "entity_variant", "id": "V-MIRA", "label": "Mira", "mode": "context"},
        ]
        intent = DirectiveEngine.parse(
            '/pov @Fila\n/pace slow\n/dia @Fila @Mira tension=high "awkward apology"',
            explicit_references=refs,
        )
        self.assertEqual(COMMAND_RUNTIME_VERSION, "1.2.5a1")
        self.assertEqual([item["id"] for item in intent.command_stack], ["pov", "pace", "dia"])
        self.assertEqual(intent.command["id"], "dia")
        self.assertEqual(intent.options["pacing"], "slow")
        self.assertEqual(intent.options["tension"], "high")
        self.assertEqual(intent.options["pov_variant_id"], "V-FILA")
        self.assertFalse(intent.execution_contract["mutates_authority"])
        self.assertEqual(intent.execution_contract["authority"], "generation_only")
        self.assertEqual(intent.execution_contract["writer_calls_hint"], 1)

    def test_dialogue_execution_profile_reaches_context_planner(self):
        refs = [
            {"type": "entity_variant", "id": "V-FILA", "label": "Fila", "mode": "context"},
            {"type": "entity_variant", "id": "V-MIRA", "label": "Mira", "mode": "context"},
        ]
        intent = DirectiveEngine.parse('/dia @Fila @Mira pace=slow "apology"', explicit_references=refs)
        workspace = SimpleNamespace(
            scope={"directive": intent.to_dict()},
            auto_selected=[],
            explicit_references=[],
        )
        plan = NarrativeContextPlanner().plan("apology", _Scope(), workspace_context=workspace, route="STORY_CONTINUE")
        weights = intent.execution_contract["retrieval_weights"]
        self.assertEqual(plan.version, "1.2.5a1")
        self.assertEqual(plan.policies["command_runtime_version"], "1.2.5a1")
        self.assertEqual(plan.policies["retrieval_profile"], "character_interaction")
        self.assertEqual(plan.dimensions["continuity"], weights["continuity"])
        self.assertEqual(plan.dimensions["relationships"], weights["relationships"])
        self.assertEqual(plan.dimensions["state"], weights["state"])

    def test_command_center_is_loaded_and_exposes_first_class_surfaces(self):
        stream = (ROOT / "src/interface/web/static/js/stream.js").read_text(encoding="utf-8")
        commands = (ROOT / "src/interface/web/static/js/commands.js").read_text(encoding="utf-8")
        center = (ROOT / "src/interface/web/static/js/command-center.js").read_text(encoding="utf-8")
        self.assertNotIn("command-center.js", stream)
        self.assertIn("command-center.js?v=1.2.5-command-center", commands)
        self.assertIn('button.dataset.view = "commands"', center)
        self.assertIn('"overview", "builtin", "custom", "profiles", "references", "history"', center)
        self.assertIn("Custom command", center)
        self.assertIn("Dry Run", center)
        self.assertIn("Generation orchestration only", center)

    def test_custom_recipe_guardrails_exist(self):
        center = (ROOT / "src/interface/web/static/js/command-center.js").read_text(encoding="utf-8")
        self.assertIn("const MAX_DEPTH = 4", center)
        self.assertIn("const MAX_STEPS = 32", center)
        self.assertIn("recursive", center.casefold())
        self.assertIn("localStorage", center)


if __name__ == "__main__":
    unittest.main()
