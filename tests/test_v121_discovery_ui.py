from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
MEMORY_JS = ROOT / "src/interface/web/static/js/memory.js"
DISCOVERY_WEB = ROOT / "src/discovery/web.py"
DISCOVERY_SERVICE = ROOT / "src/discovery/service.py"


def compact_js(source: str) -> str:
    return re.sub(r"\s+", "", source)


class V121DiscoveryUITests(unittest.TestCase):
    def test_library_gets_progressive_discovery_tab(self):
        source = MEMORY_JS.read_text(encoding="utf-8")
        compact = compact_js(source)
        self.assertIn('button.id="discoveryWorldTab"', compact)
        self.assertIn('button.dataset.worldTab="discoveries"', compact)
        self.assertIn('Discoveries<spanid="discoveryTabCount"', compact)
        self.assertIn('state.activeWorldTab="discoveries"', compact)
        self.assertIn("discoverySidebarBtn", source)

    def test_discovery_cards_show_all_knowledge_states(self):
        source = MEMORY_JS.read_text(encoding="utf-8")
        self.assertIn('detected:"◌"', source)
        self.assertIn('reviewed:"◇"', source)
        self.assertIn('canon:"◆"', source)
        self.assertIn('dismissed:"×"', source)
        self.assertIn("qualified_support_count", source)
        self.assertIn("provenance_state", source)

    def test_canon_requires_explicit_user_confirmation(self):
        source = MEMORY_JS.read_text(encoding="utf-8")
        compact = compact_js(source)
        self.assertIn("Make Canon", source)
        self.assertIn("explicit user authority decision", source)
        self.assertIn("Source frequency alone never performs this action", source)
        self.assertIn('/canon`,{method:"POST"', compact)

    def test_evidence_ui_is_message_provenance_aware(self):
        source = MEMORY_JS.read_text(encoding="utf-8")
        self.assertIn("source_turn_id", source)
        self.assertIn("visible_instance_ids", source)
        self.assertIn("out_of_scope_support_count", source)
        self.assertIn("source instance(s) were invalidated", source)

    def test_review_api_exposes_separate_canon_dismiss_reset_actions(self):
        source = DISCOVERY_WEB.read_text(encoding="utf-8")
        self.assertIn('@router.post("/discoveries/{proposition_id}/canon")', source)
        self.assertIn('@router.post("/discoveries/{proposition_id}/dismiss")', source)
        self.assertIn('@router.post("/discoveries/{proposition_id}/reset")', source)

    def test_memory_candidates_are_explicitly_non_canon(self):
        source = DISCOVERY_SERVICE.read_text(encoding="utf-8")
        self.assertIn("REVIEWED NON-CANON", source)
        self.assertIn("DETECTED NON-CANON", source)
        self.assertNotIn('authority_state"] == "reviewed"', source)


if __name__ == "__main__":
    unittest.main()
