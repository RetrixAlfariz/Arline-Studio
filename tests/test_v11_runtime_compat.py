from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class V11RuntimeCompatibilityTests(unittest.TestCase):
    def test_compatibility_prelude_loads_before_main_frontend(self):
        html = (ROOT / "src/interface/web/static/index.html").read_text(encoding="utf-8")
        js = (ROOT / "src/interface/web/static/arline.js").read_text(encoding="utf-8")

        self.assertLess(html.index("static/js/stream.js"), html.index("static/arline.js"))
        self.assertIn("renderScopeSelectors();", js)
        self.assertIn("clearComposerDraftKey(sentDraftKey)", js)

    def test_runtime_prelude_restores_scope_nodes_and_generation_binding(self):
        stream_path = ROOT / "src/interface/web/static/js/stream.js"
        smoke = r'''
const fs = require("fs");
const vm = require("vm");

const source = fs.readFileSync(process.argv[1], "utf8");
const nodes = new Map();

function makeNode(tagName) {
  return {
    tagName: String(tagName).toUpperCase(),
    id: "",
    hidden: false,
    tabIndex: 0,
    children: [],
    attributes: {},
    setAttribute(name, value) { this.attributes[name] = String(value); },
    appendChild(child) {
      this.children.push(child);
      if (child.id) nodes.set(child.id, child);
      return child;
    },
  };
}

const document = {
  body: makeNode("body"),
  createElement: makeNode,
  getElementById(id) { return nodes.get(id) || null; },
};

const context = {
  console,
  document,
  TextDecoder,
  setTimeout,
  clearTimeout,
};
context.window = context;
context.globalThis = context;

vm.createContext(context);
vm.runInContext(source, context, { filename: "stream.js" });

for (const id of ["projectSelect", "worldSelect", "branchSelect"]) {
  const node = document.getElementById(id);
  if (!node) throw new Error(`missing compatibility node: ${id}`);
  if (node.tagName !== "SELECT") throw new Error(`${id} is not a select`);
  if (!node.hidden) throw new Error(`${id} is not hidden`);
}

context.composerDraftKey = () => "arline:composer:test";
const resolved = vm.runInContext('"use strict"; sentDraftKey', context);
if (resolved !== "arline:composer:test") {
  throw new Error(`sentDraftKey resolved to ${resolved}`);
}

if (typeof context.ArlineStream?.consume !== "function") {
  throw new Error("stream consumer was not preserved");
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


if __name__ == "__main__":
    unittest.main()
