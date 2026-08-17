from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class V11ReleasePolishTests(unittest.TestCase):
    def test_compact_composer_is_session_adaptive(self):
        css = (ROOT / "src/interface/web/static/arline.css").read_text(encoding="utf-8")
        js = (ROOT / "src/interface/web/static/arline.js").read_text(encoding="utf-8")
        self.assertIn("body.chat-session-active", css)
        self.assertIn("updateComposerSessionMode", js)
        self.assertIn("resizeComposerInput", js)
        self.assertIn("details-open", css)

    def test_release_safety_and_onboarding_surfaces_exist(self):
        html = (ROOT / "src/interface/web/static/index.html").read_text(encoding="utf-8")
        js = (ROOT / "src/interface/web/static/arline.js").read_text(encoding="utf-8")
        for token in ("welcomeDialog", "startupRecovery", "runDataDoctorBtn", "developerToolsToggle", "aboutCard"):
            self.assertIn(f'id="{token}"', html)
        self.assertIn("runWorkspaceDoctor", js)
        self.assertIn("maybeShowOnboarding", js)
        self.assertIn("showStartupRecovery", js)

    def test_feedback_lab_has_no_direct_main_navigation_callers(self):
        js = (ROOT / "src/interface/web/static/arline.js").read_text(encoding="utf-8")
        self.assertNotIn('data: () => setView("data")', js)
        self.assertNotIn('data-home-view="data"', js)
        self.assertIn('openInspector("review")', js)

    def test_chat_rendering_has_performance_guardrail(self):
        js = (ROOT / "src/interface/web/static/arline.js").read_text(encoding="utf-8")
        self.assertIn("conversationRenderLimit", js)
        self.assertIn("load-earlier-turns", js)

    def test_settings_search_scans_panel_content(self):
        js = (ROOT / "src/interface/web/static/arline.js").read_text(encoding="utf-8")
        self.assertIn('panel?.textContent', js)
        self.assertIn('developer-tools-hidden', (ROOT / "src/interface/web/static/arline.css").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
