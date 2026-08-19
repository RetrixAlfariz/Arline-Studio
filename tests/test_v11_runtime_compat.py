from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/interface/web/static"


class V11RuntimeCompatibilityTests(unittest.TestCase):
    def test_transport_and_compatibility_have_explicit_load_boundaries(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        js = (STATIC / "arline.js").read_text(encoding="utf-8")

        self.assertLess(html.index("static/js/stream.js"), html.index("static/arline.js"))
        self.assertLess(html.index("static/arline.js"), html.index("static/js/compat.js"))
        self.assertLess(html.index("static/js/compat.js"), html.index("static/js/memory.js"))
        self.assertIn("const sentDraftKey = composerDraftKey();", js)
        self.assertIn("clearComposerDraftKey(sentDraftKey)", js)

    def test_stream_module_is_transport_only_and_executes_standalone(self):
        stream_path = STATIC / "js/stream.js"
        stream = stream_path.read_text(encoding="utf-8")

        for forbidden in (
            "legacyScopeCompatibility",
            "bulkTrashSelectedCompat",
            "installBulkUndoBridge",
            "quick-create.js",
            "discovery-sheets.js",
            "sentDraftKey",
        ):
            self.assertNotIn(forbidden, stream)

        smoke = r'''
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(process.argv[1], "utf8");
const context = { console, TextDecoder, setTimeout, clearTimeout };
context.window = context;
context.globalThis = context;
vm.createContext(context);
vm.runInContext(source, context, { filename: "stream.js" });
if (typeof context.ArlineStream?.consume !== "function") {
  throw new Error("stream consumer was not exported");
}
'''
        result = subprocess.run(
            ["node", "-e", smoke, str(stream_path)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)

    def test_compatibility_module_no_longer_fabricates_scope_or_draft_bindings(self):
        compat = (STATIC / "js/compat.js").read_text(encoding="utf-8")
        quick = (STATIC / "js/quick-create.js").read_text(encoding="utf-8")

        # Transitional bulk-trash behavior may remain here, but streaming owns
        # no UI repair work and compatibility must not recreate removed scope
        # controls or invent missing lexical variables.
        self.assertIn("bulkTrashSelectedCompat", compat)
        self.assertNotIn("legacyScopeCompatibility", compat)
        self.assertNotIn('Object.defineProperty(globalThis, "sentDraftKey"', compat)
        self.assertNotIn('for (const id of ["projectSelect", "worldSelect", "branchSelect"])', compat)

        self.assertIn("window.ArlineRuntime?.getScope?.()", quick)
        self.assertNotIn('currentScopeValue("projectSelect")', quick)
        self.assertNotIn('currentScopeValue("worldSelect")', quick)
        self.assertNotIn('currentScopeValue("branchSelect")', quick)


if __name__ == "__main__":
    unittest.main()
