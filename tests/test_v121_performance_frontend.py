from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
STREAM = ROOT / "src/interface/web/static/js/stream.js"
MEMORY = ROOT / "src/interface/web/static/js/memory.js"


class V121PerformanceFrontendTests(unittest.TestCase):
    def test_stream_prelude_does_not_patch_global_fetch_on_startup(self):
        source = STREAM.read_text(encoding="utf-8")
        self.assertNotIn("globalThis.fetch =", source)
        self.assertNotIn("discoveryLoadPolicy", source)
        self.assertNotIn("deferredDiscoveryResponse", source)

    def test_existing_discovery_navigation_remains_explicit(self):
        memory = MEMORY.read_text(encoding="utf-8")
        self.assertIn('state.activeWorldTab="discoveries"', memory)
        self.assertIn("loadDiscoveries()", memory)
        self.assertIn("openDiscoveryView", memory)

    def test_existing_streaming_and_dynamic_sheet_contracts_remain_loaded(self):
        source = STREAM.read_text(encoding="utf-8")
        self.assertIn("async function consume", source)
        self.assertIn("window.ArlineStream = { consume }", source)
        self.assertIn("/static/js/discovery-sheets.js?v=1.2.1-physical-items", source)
        self.assertIn("loadQuickCreateEnhancements", source)


if __name__ == "__main__":
    unittest.main()
