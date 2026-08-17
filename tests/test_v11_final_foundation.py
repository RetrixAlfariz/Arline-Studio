from __future__ import annotations

from pathlib import Path
import unittest

from src.runtime.run_state import RunState
from src.writer.quality import ProseQualityAnalyzer

ROOT = Path(__file__).resolve().parents[1]


class V11FinalFoundationTests(unittest.TestCase):
    def test_run_lifecycle_has_terminal_states(self):
        self.assertEqual(RunState.COMPLETED.value, "completed")
        self.assertEqual(RunState.CANCELLED.value, "cancelled")
        self.assertEqual(RunState.FAILED.value, "failed")

    def test_quality_analyzer_flags_pov_and_repetition_without_rewriting(self):
        text = "Aku melihat kamar itu. Aku masuk perlahan. Aku sangat kagum. Aku sangat kagum. Kamu lalu melihatku pada malam hari setelah sore yang sunyi."
        report = ProseQualityAnalyzer().analyze(text)
        self.assertIn("issues", report)
        self.assertEqual(report["policy"], "flag_surface_and_narrative_suspicion_without_rewriting_story_facts")
        self.assertGreaterEqual(report["issue_count"], 1)

    def test_primary_nav_excludes_feedback_lab_and_context_card(self):
        html = (ROOT / "src/interface/web/static/index.html").read_text(encoding="utf-8")
        nav = html.split('<nav class="workspace-nav"', 1)[1].split('</nav>', 1)[0]
        self.assertIn('data-view="chat"', nav)
        self.assertIn('data-view="draft"', nav)
        self.assertIn('data-view="world"', nav)
        self.assertNotIn('data-view="data"', nav)
        self.assertNotIn('data-view="home"', nav)
        self.assertNotIn('id="contextStackCard"', html)
        self.assertIn('data-inspector-tab="review"', html)

    def test_streaming_frontend_and_endpoint_are_wired(self):
        html = (ROOT / "src/interface/web/static/index.html").read_text(encoding="utf-8")
        js = (ROOT / "src/interface/web/static/arline.js").read_text(encoding="utf-8")
        app = (ROOT / "src/interface/web/app.py").read_text(encoding="utf-8")
        self.assertIn('/static/js/stream.js', html)
        self.assertIn('/api/generate/stream', js)
        self.assertIn('@app.post("/api/generate/stream")', app)
        self.assertNotIn('loading(true,payload.generation_mode', js)

    def test_writer_contract_contains_surface_quality_rules(self):
        prompt = (ROOT / "config/writer_system.txt").read_text(encoding="utf-8")
        self.assertIn("Preserve the requested narrative person", prompt)
        self.assertIn("silent surface-language check", prompt)

    def test_grouped_settings_include_storage_and_developer_review(self):
        html = (ROOT / "src/interface/web/static/index.html").read_text(encoding="utf-8")
        self.assertIn('data-inspector-tab="storage"', html)
        self.assertIn('data-inspector-tab="review"', html)
        self.assertIn('id="settingsSearch"', html)


if __name__ == "__main__":
    unittest.main()
