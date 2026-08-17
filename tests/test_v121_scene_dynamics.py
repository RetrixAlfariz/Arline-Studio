from __future__ import annotations

import unittest

from src.narrative import CharacterRailParser, SceneDynamicsPlanner


class V121SceneDynamicsTests(unittest.TestCase):
    def test_slow_dialogue_gets_adaptive_multi_beat_shape(self):
        compilation = CharacterRailParser.parse('/dia @vian@fano slow "main game"')
        plan = SceneDynamicsPlanner.plan(compilation)[0]
        self.assertEqual(plan.speaker_order, "adaptive")
        self.assertGreaterEqual(plan.beat_budget.minimum, 4)
        self.assertGreater(plan.beat_budget.maximum, plan.beat_budget.target)
        self.assertIn("speech", plan.allowed_channels)
        self.assertIn("silence", plan.allowed_channels)
        self.assertIn("internal", plan.allowed_channels)
        self.assertEqual(plan.internal_access, "active_pov_only")

    def test_fast_and_slow_are_not_just_length_aliases(self):
        fast = SceneDynamicsPlanner.plan(CharacterRailParser.parse('/dia @vian@fano fast "topic"'))[0]
        slow = SceneDynamicsPlanner.plan(CharacterRailParser.parse('/dia @vian@fano slow "topic"'))[0]
        self.assertLess(fast.beat_budget.target, slow.beat_budget.target)
        self.assertTrue(any("Move quickly" in rule for rule in fast.narrative_rules))
        self.assertTrue(any("intermediate reactions" in rule for rule in slow.narrative_rules))

    def test_length_modifies_soft_budget_without_creating_turn_quota(self):
        short = SceneDynamicsPlanner.plan(CharacterRailParser.parse('/dia @vian@fano slow length=short "topic"'))[0]
        long = SceneDynamicsPlanner.plan(CharacterRailParser.parse('/dia @vian@fano slow length=long "topic"'))[0]
        self.assertLess(short.beat_budget.target, long.beat_budget.target)
        self.assertTrue(any("soft narrative-shape bound" in rule for rule in long.narrative_rules))

    def test_internal_monologue_has_private_internal_access(self):
        plan = SceneDynamicsPlanner.plan(CharacterRailParser.parse('/mono @vian slow "embarrassed"'))[0]
        self.assertIn("internal", plan.allowed_channels)
        self.assertNotIn("speech", plan.allowed_channels)
        self.assertEqual(plan.internal_access, "active_pov_only")
        self.assertTrue(any("remains private" in rule for rule in plan.narrative_rules))

    def test_whisper_monologue_changes_allowed_channel_to_speech(self):
        plan = SceneDynamicsPlanner.plan(CharacterRailParser.parse('/mono @vian whisper "embarrassed"'))[0]
        self.assertIn("speech", plan.allowed_channels)
        self.assertNotIn("internal", plan.allowed_channels)
        self.assertEqual(plan.internal_access, "none")

    def test_intimacy_uses_same_shared_expression_channels(self):
        plan = SceneDynamicsPlanner.plan(CharacterRailParser.parse('/intimacy @vian solo lingering "vulnerability"'))[0]
        self.assertEqual(plan.speaker_order, "adaptive")
        self.assertIn("action", plan.allowed_channels)
        self.assertIn("vocalization", plan.allowed_channels)
        self.assertIn("ambience", plan.allowed_channels)
        self.assertGreaterEqual(plan.beat_budget.target, 8)

    def test_rendered_plan_is_explicitly_shape_only(self):
        compilation = CharacterRailParser.parse('/dia @vian@fano slow curve=wave "main game"')
        rendered = SceneDynamicsPlanner.render(compilation)
        self.assertIn("planner: deterministic_shape_only", rendered)
        self.assertIn("prose_authority: writer", rendered)
        self.assertIn("speaker_order: adaptive", rendered)
        self.assertIn("intensity_curve: wave", rendered)


if __name__ == "__main__":
    unittest.main()
