from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/interface/web/static"


class V11RuntimeCompatibilityTests(unittest.TestCase):
    def test_frontend_feature_modules_have_explicit_load_order(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        js = (STATIC / "arline.js").read_text(encoding="utf-8")

        self.assertLess(html.index("static/js/stream.js"), html.index("static/arline.js"))
        self.assertLess(html.index("static/arline.js"), html.index("static/js/quick-create.js"))
        self.assertLess(
            html.index("static/js/quick-create.js"),
            html.index("static/js/discovery-sheets.js"),
        )
        self.assertLess(
            html.index("static/js/discovery-sheets.js"),
            html.index("static/js/memory.js"),
        )
        self.assertNotIn("static/js/compat.js", html)
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

    def test_library_owns_bulk_trash_and_quick_create_uses_runtime_scope(self):
        js = (STATIC / "arline.js").read_text(encoding="utf-8")
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        quick = (STATIC / "js/quick-create.js").read_text(encoding="utf-8")

        self.assertIn('id="bulkTrashBtn"', html)
        self.assertIn("async function bulkTrashSelected()", js)
        self.assertIn('action.type === "restore_bulk"', js)
        self.assertIn('on("bulkTrashBtn", "click", bulkTrashSelected)', js)

        self.assertIn("window.ArlineRuntime?.getScope?.()", quick)
        self.assertNotIn('currentScopeValue("projectSelect")', quick)
        self.assertNotIn('currentScopeValue("worldSelect")', quick)
        self.assertNotIn('currentScopeValue("branchSelect")', quick)


if __name__ == "__main__":
    unittest.main()
