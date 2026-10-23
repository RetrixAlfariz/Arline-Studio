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
            self.assertRegex(source, rf'id:\s*"{re.escape(command_id)}"[\s\S]*?label:\s*"{re.escape(label)}"')

    def test_ctrl_k_search_consumes_shared_command_registry(self):
        source = ARLINE.read_text(encoding="utf-8")
        self.assertIn("const COMMANDS = window.ARLINE_COMMANDS || [];", source)
        self.assertIn("const local = COMMANDS.filter", source)
        self.assertIn("state.commandResults = [...local.map", source)

    def test_rich_help_uses_generic_placeholders_only(self):
        source = COMMANDS.read_text(encoding="utf-8")
        for token in ("@characterA", "@characterB", "@locationA"):
            self.assertIn(token, source)
        self.assertNotIn("@vian", source.lower())
        self.assertNotIn("@fano", source.lower())
        for command_id in ("mono", "dia", "ambience", "intimacy"):
            command_start = source.index(f'id: "{command_id}"')
            next_id = source.find('\n  { id:', command_start + 1)
            block = source[command_start: next_id if next_id >= 0 else len(source)]
            self.assertIn("help:", block)
            self.assertIn("syntax:", block)
            self.assertIn("examples:", block)
            self.assertIn("parameters:", block)
            self.assertIn("behavior:", block)
            self.assertIn("memory:", block)

    def test_ctrl_k_help_card_is_progressive_and_click_to_use(self):
        source = COMMANDS.read_text(encoding="utf-8")
        for token in (
            "command-info-button",
            "commandHelpCard",
            "showCommandHelp",
            "insertCommandHelpExample",
            'data-command-example',
            "Insert template",
            "command-body-layout",
            "MutationObserver",
        ):
            self.assertIn(token, source)
        self.assertIn('dialog.classList.add("has-command-help")', source)
        self.assertIn('dialog.classList.remove("has-command-help")', source)
        self.assertIn('input.dispatchEvent(new Event("input", { bubbles: true }))', source)

    def test_dialogue_help_explains_adaptive_beats_not_turn_quota(self):
        source = COMMANDS.read_text(encoding="utf-8")
        start = source.index('id: "dia"')
        end = source.index('id: "ambience"')
        block = source[start:end]
        self.assertIn("Speaker order is adaptive", block)
        self.assertIn("never a turn quota", block)
        self.assertIn("Actions, silence, interruptions", block)
        self.assertIn("POV-authorized characters", block)


if __name__ == "__main__":
    unittest.main()
