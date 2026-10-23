from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/interface/web/static"
STREAM = STATIC / "js/stream.js"
MEMORY = STATIC / "js/memory.js"
INDEX = STATIC / "index.html"


class V121PerformanceFrontendTests(unittest.TestCase):
    def test_stream_transport_does_not_patch_or_boot_feature_modules(self):
        source = STREAM.read_text(encoding="utf-8")
        self.assertNotIn("globalThis.fetch =", source)
        self.assertNotIn("discoveryLoadPolicy", source)
        self.assertNotIn("deferredDiscoveryResponse", source)
        self.assertNotIn("loadQuickCreateEnhancements", source)
        self.assertNotIn("discovery-sheets.js", source)

    def test_existing_discovery_navigation_remains_explicit(self):
        memory = MEMORY.read_text(encoding="utf-8")
        self.assertIn('state.activeWorldTab="discoveries"', memory)
        self.assertIn("loadDiscoveries()", memory)
        self.assertIn("openDiscoveryView", memory)

    def test_stream_and_feature_modules_are_loaded_explicitly(self):
        source = STREAM.read_text(encoding="utf-8")
        html = INDEX.read_text(encoding="utf-8")
        self.assertIn("async function consume", source)
        self.assertIn("window.ArlineStream = { consume }", source)
        self.assertIn("/static/js/quick-create.js?v=1.2.5-brand", html)
        self.assertIn("/static/js/discovery-sheets.js?v=1.2.5-brand", html)
        self.assertNotIn("/static/js/compat.js", html)


if __name__ == "__main__":
    unittest.main()
