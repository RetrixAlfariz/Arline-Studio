from __future__ import annotations

import unittest

from src.memory import MemoryConfig, MemoryQueryContext, QueryCompiler, QueryRoute, RetrievalLane


class StubWorkspace:
    def list_entity_families(self, project_id):
        return [{"id": "FAM-VIAN", "name": "Vian"}]


class QueryCompilerTests(unittest.TestCase):
    def setUp(self):
        self.compiler = QueryCompiler(StubWorkspace(), config=MemoryConfig())

    def test_routes_specialized_questions(self):
        cases = {
            "Where is Vian's black dress stored?": QueryRoute.SPATIAL_LOOKUP,
            "What did Fano know before chapter five?": QueryRoute.EPISTEMIC_STATE,
            "Why did Vian stop trusting Fano?": QueryRoute.WHY_CAUSAL,
            "What promises remain unresolved?": QueryRoute.THREAD_LOOKUP,
            "Where was Vian before the departure?": QueryRoute.TEMPORAL_STATE,
            "Continue the current scene": QueryRoute.STORY_CONTINUE,
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                self.assertEqual(self.compiler.route(query), expected)

    def test_plan_does_not_ask_every_index(self):
        plan = self.compiler.compile("Where is Vian?", MemoryQueryContext(world_id="W", branch_id="B"))
        self.assertEqual(plan.route, QueryRoute.SPATIAL_LOOKUP)
        self.assertIn(RetrievalLane.SPATIAL, plan.required_lanes)
        self.assertNotIn(RetrievalLane.FTS_IMPORT, plan.required_lanes)
        self.assertTrue(any(item["id"] == "FAM-VIAN" for item in plan.resolved_entities))


if __name__ == "__main__":
    unittest.main()
