from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SettingsStackLayoutTests(unittest.TestCase):
    def test_feedback_lab_is_not_a_main_workspace_view(self):
        html = (ROOT / "src/interface/web/static/index.html").read_text(encoding="utf-8")
        self.assertNotIn('data-view-panel="data"', html)
        review_at = html.index('data-inspector-panel="review"')
        self.assertGreater(html.index('id="datasetCards"'), review_at)
        self.assertGreater(html.index('id="feedbackQueue"'), review_at)
        self.assertGreater(html.index('id="feedbackAdvanced"'), review_at)

    def test_settings_navigation_is_top_to_down(self):
        css = (ROOT / "src/interface/web/static/arline.css").read_text(encoding="utf-8")
        self.assertIn("v1.1 settings stack hotfix", css)
        self.assertIn("flex-direction:column!important", css)
        self.assertIn(".inspector .inspector-tabs", css)

    def test_legacy_feedback_route_redirects_to_settings(self):
        js = (ROOT / "src/interface/web/static/arline.js").read_text(encoding="utf-8")
        self.assertIn('if (view === "data")', js)
        self.assertIn('openInspector("review")', js)
        self.assertNotIn('data: () => setView("data")', js)
        self.assertNotIn('data-home-view="data"', js)
        self.assertIn('data-home-review="1"', js)

    def test_static_assets_are_versioned_together(self):
        html = (ROOT / "src/interface/web/static/index.html").read_text(encoding="utf-8")
        versions = re.findall(r'(?:arline\.css|stream\.js|arline\.js)\?v=([^"\s]+)', html)
        self.assertEqual(len(versions), 3)
        self.assertEqual(len(set(versions)), 1, versions)


if __name__ == "__main__":
    unittest.main()
