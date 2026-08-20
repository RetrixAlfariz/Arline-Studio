from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class V125CommandCenterUITests(unittest.TestCase):
    def test_command_center_is_loaded_after_runtime(self):
        stream = (ROOT / "src/interface/web/static/js/stream.js").read_text(encoding="utf-8")
        self.assertIn("command-center.js?v=1.2.5-command-center", stream)
        self.assertIn('window.addEventListener("load"', stream)
        self.assertIn("data-arline-command-center", stream)

    def test_command_center_has_first_class_navigation_and_sections(self):
        center = (ROOT / "src/interface/web/static/js/command-center.js").read_text(encoding="utf-8")
        self.assertIn('button.dataset.view = "commands"', center)
        self.assertIn('button.innerHTML = "<span>⌘</span><b>Commands</b>"', center)
        self.assertIn('button.textContent = "Commands & Recipes"', center)
        self.assertIn('data-cc-launch="custom"', center)
        for tab in ("overview", "builtin", "custom", "profiles", "references", "history"):
            self.assertIn(f'"{tab}"', center)

    def test_custom_commands_compile_before_generation(self):
        center = (ROOT / "src/interface/web/static/js/command-center.js").read_text(encoding="utf-8")
        self.assertIn("function expandCustomPrompt()", center)
        self.assertIn("compileRecipe(recipe, invocation)", center)
        self.assertIn('["generateBtn", "analyzeBtn"]', center)
        self.assertIn("MAX_DEPTH = 4", center)
        self.assertIn("MAX_STEPS = 32", center)
        self.assertIn("Does not grant Canon authority", center)


if __name__ == "__main__":
    unittest.main()
