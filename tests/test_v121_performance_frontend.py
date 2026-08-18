from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
STREAM = ROOT / "src/interface/web/static/js/stream.js"
MEMORY = ROOT / "src/interface/web/static/js/memory.js"


class V121PerformanceFrontendTests(unittest.TestCase):
    def test_hidden_discovery_list_is_not_on_project_navigation_hot_path(self):
        source = STREAM.read_text(encoding="utf-8")
        self.assertIn("discoveryLoadPolicy", source)
        self.assertIn("deferredDiscoveryResponse", source)
        self.assertIn('url.pathname === "/api/memory/discoveries"', source)
        self.assertIn('state.activeWorldTab !== "discoveries"', source)
        self.assertIn("installLazyDiscoveryProjectLoad", source)
        self.assertIn("suppressDepth", source)

    def test_lazy_guard_never_blocks_an_explicit_discoveries_view(self):
        source = STREAM.read_text(encoding="utf-8")
        self.assertIn("hiddenView &&", source)
        self.assertIn("startupSkips = 0", source)
        memory = MEMORY.read_text(encoding="utf-8")
        self.assertIn('state.activeWorldTab="discoveries"', memory)
        self.assertIn("loadDiscoveries()", memory)

    def test_existing_streaming_and_dynamic_sheet_contracts_remain_loaded(self):
        source = STREAM.read_text(encoding="utf-8")
        self.assertIn("async function consume", source)
        self.assertIn("window.ArlineStream = { consume }", source)
        self.assertIn("/static/js/discovery-sheets.js?v=1.2.1-physical-items", source)
        self.assertIn("loadQuickCreateEnhancements", source)


if __name__ == "__main__":
    unittest.main()
