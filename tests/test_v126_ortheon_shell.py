import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "interface" / "web" / "static"
INDEX = STATIC / "index.html"
SHELL = STATIC / "chat-runtime-v125.css"
BASE = STATIC / "chat-runtime-v125-base.css"


class OrtheonShellContractTests(unittest.TestCase):
    def test_ortheon_shell_preserves_existing_runtime_stylesheet(self):
        shell = SHELL.read_text(encoding="utf-8")
        base = BASE.read_text(encoding="utf-8")

        self.assertTrue(
            shell.lstrip().startswith(
                '@import url("/static/chat-runtime-v125-base.css?v=1.2.5-scroll");'
            )
        )
        self.assertTrue(base.strip(), "The preserved v1.2.5 chat runtime stylesheet must not be empty.")
        self.assertIn("--ortheon-surface-0", shell)
        self.assertIn("--ortheon-core:#2f9b81", shell)
        self.assertIn(".workspace-sidebar", shell)
        self.assertIn(".composer-card", shell)
        self.assertIn(".inspector", shell)
        self.assertIn(".sheet-panel", shell)

    def test_html_keeps_critical_runtime_ids_singleton(self):
        html = INDEX.read_text(encoding="utf-8")

        # These IDs are hard runtime contracts used by the existing vanilla-JS UI.
        # The shell redesign must never replace them with a parallel React-only DOM.
        critical_ids = (
            "workspaceSidebar",
            "workbench",
            "mainStage",
            "chatView",
            "conversationFeed",
            "composerDock",
            "promptInput",
            "generateBtn",
            "inspector",
            "sheetPanel",
        )
        for element_id in critical_ids:
            with self.subTest(element_id=element_id):
                self.assertEqual(html.count(f'id="{element_id}"'), 1)

    def test_html_still_loads_final_runtime_layer(self):
        html = INDEX.read_text(encoding="utf-8")
        expected = '/static/chat-runtime-v125.css?v=1.2.5-scroll'
        self.assertEqual(html.count(expected), 1)

        # Basic document guards for the brittle monolithic static shell.
        self.assertTrue(html.lstrip().lower().startswith("<!doctype html>"))
        self.assertEqual(html.count("<html"), 1)
        self.assertEqual(html.count("</html>"), 1)
        self.assertEqual(html.count("<body"), 1)
        self.assertEqual(html.count("</body>"), 1)


if __name__ == "__main__":
    unittest.main()
