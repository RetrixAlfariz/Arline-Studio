from types import SimpleNamespace
import unittest

from src.context.intelligence import NarrativeContextPlanner
from src.directives import COMMAND_RUNTIME_VERSION, DirectiveEngine


class V125CommandRuntimeTests(unittest.TestCase):
    def test_catalog_is_schema_driven(self):
        rows = {row["id"]: row for row in DirectiveEngine.catalog()}
        self.assertEqual(COMMAND_RUNTIME_VERSION, "1.2.5a1")
        dia = rows["dia"]
        self.assertEqual(dia["execution_contract"]["retrieval_profile"], "character_interaction")
        self.assertTrue(dia["arguments"])
        self.assertTrue(dia["options"])
        self.assertFalse(dia["execution_contract"]["mutates_authority"])

    def test_multiple_commands_compile_to_one_execution_contract(self):
        refs = [
            {"type": "entity_variant", "id": "V-FILA", "label": "Fila", "mode": "context"},
            {"type": "entity_variant", "id": "V-MIRA", "label": "Mira", "mode": "context"},
        ]
        directive = DirectiveEngine.parse(
            '/pov @Fila\n/pace slow\n/dia @Fila @Mira tension=high "awkward apology"',
            explicit_references=refs,
        )
        self.assertEqual([row["id"] for row in directive.command_stack], ["pov", "pace", "dia"])
        self.assertEqual(directive.command["id"], "dia")
        self.assertEqual(directive.planner_intent, "dialogue")
        self.assertEqual(directive.options["pacing"], "slow")
        self.assertEqual(directive.options["tension"], "high")
        self.assertEqual(directive.options["pov_variant_id"], "V-FILA")
        self.assertEqual(directive.execution_contract["retrieval_profile"], "character_interaction")
        self.assertEqual(directive.execution_contract["writer_calls_hint"], 1)
        self.assertFalse(directive.execution_contract["mutates_authority"])
        self.assertIn("command_stack: /pov -> /pace -> /dia", directive.render())

    def test_invalid_options_do_not_survive_validation(self):
        refs = [
            {"type": "entity_variant", "id": "V-FILA", "label": "Fila", "mode": "context"},
            {"type": "entity_variant", "id": "V-MIRA", "label": "Mira", "mode": "context"},
        ]
        directive = DirectiveEngine.parse(
            '/dia @Fila @Mira tension=radioactive curve=banana "talk"',
            explicit_references=refs,
        )
        self.assertNotIn("tension", directive.options)
        self.assertNotIn("curve", directive.options)
        self.assertTrue(any("invalid" in row for row in directive.diagnostics))

    def test_alternative_count_is_bounded(self):
        directive = DirectiveEngine.parse('/alternatives @scene count=999 "next"', active_scene={"document_id": "DOC"})
        self.assertEqual(directive.options["count"], 8)

    def test_existing_planner_still_obeys_compiled_primary_intent(self):
        refs = [
            {"type": "entity_variant", "id": "V-FILA", "label": "Fila", "mode": "context"},
            {"type": "entity_variant", "id": "V-MIRA", "label": "Mira", "mode": "context"},
        ]
        directive = DirectiveEngine.parse('/pace slow\n/dia @Fila @Mira "talk"', explicit_references=refs)

        class Scope:
            explicit_references = refs
            pov_variant_id = "V-FILA"
            world_time = None
            story_order = None
            token_budget = 1600
            context_lens = "pov"
            allow_future_author_knowledge = False

        workspace_context = SimpleNamespace(
            scope={"directive": directive.to_dict(), "active_scene": {"pov_variant_id": "V-FILA", "participants": ["V-FILA", "V-MIRA"]}},
            auto_selected=[], explicit_references=refs,
        )
        plan = NarrativeContextPlanner().plan("talk", Scope(), workspace_context=workspace_context, route="STORY_CONTINUE")
        self.assertEqual(plan.intent, "dialogue")
        self.assertEqual(plan.dimensions["relationships"], 1.0)
        self.assertEqual(plan.dimensions["pov"], 1.0)


if __name__ == "__main__":
    unittest.main()
