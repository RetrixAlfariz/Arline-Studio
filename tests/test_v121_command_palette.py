from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "src/interface/web/static/index.html"
COMMANDS = ROOT / "src/interface/web/static/js/commands.js"
ARLINE = ROOT / "src/interface/web/static/arline.js"


class V121CommandPaletteTests(unittest.TestCase):
    def test_command_registry_loads_before_arline_runtime(self):
        html = INDEX.read_text(encoding="utf-8")
        commands_pos = html.find('/static/js/commands.js')
        arline_pos = html.find('/static/arline.js')
        self.assertGreaterEqual(commands_pos, 0, "commands.js must be loaded by index.html")
        self.assertGreaterEqual(arline_pos, 0, "arline.js must be loaded by index.html")
        self.assertLess(commands_pos, arline_pos, "commands.js must execute before arline.js captures ARLINE_COMMANDS")

    def test_character_rails_are_registered_for_ctrl_k(self):
        source = COMMANDS.read_text(encoding="utf-8")
        for command_id, label in (
            ("mono", "/mono"),
            ("dia", "/dia"),
            ("ambience", "/ambience"),
            ("intimacy", "/intimacy"),
        ):
            self.assertRegex(source, rf'id:\s*"{re.escape(command_id)}"[^\n]+label:\s*"{re.escape(label)}"')

    def test_ctrl_k_search_consumes_shared_command_registry(self):
        source = ARLINE.read_text(encoding="utf-8")
        self.assertIn("const COMMANDS = window.ARLINE_COMMANDS || [];", source)
        self.assertIn("const local = COMMANDS.filter", source)
        self.assertIn("state.commandResults = [...local.map", source)


if __name__ == "__main__":
    unittest.main()
