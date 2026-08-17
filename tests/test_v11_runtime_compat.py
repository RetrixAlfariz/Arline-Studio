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

    def test_bulk_trash_is_wired_to_recoverable_lifecycle_and_bulk_undo(self):
        stream_path = ROOT / "src/interface/web/static/js/stream.js"
        smoke = r'''
const fs = require("fs");
const vm = require("vm");

(async () => {
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
      listeners: {},
      textContent: "",
      className: "",
      type: "",
      setAttribute(name, value) { this.attributes[name] = String(value); },
      addEventListener(name, handler) { (this.listeners[name] ||= []).push(handler); },
      appendChild(child) {
        this.children.push(child);
        if (child.id) nodes.set(child.id, child);
        return child;
      },
      insertBefore(child, reference) {
        const index = this.children.indexOf(reference);
        if (index < 0) return this.appendChild(child);
        this.children.splice(index, 0, child);
        if (child.id) nodes.set(child.id, child);
        return child;
      },
      async click() {
        for (const handler of this.listeners.click || []) await handler({ target: this });
      },
    };
  }

  const document = {
    body: makeNode("body"),
    createElement: makeNode,
    getElementById(id) { return nodes.get(id) || null; },
  };

  const bar = makeNode("div");
  bar.id = "worldBulkBar";
  const clear = makeNode("button");
  clear.id = "bulkClearBtn";
  bar.appendChild(clear);
  document.body.appendChild(bar);

  const context = {
    console,
    document,
    TextDecoder,
    setTimeout,
    clearTimeout,
    confirm: () => true,
  };
  context.window = context;
  context.globalThis = context;

  vm.createContext(context);
  vm.runInContext(source, context, { filename: "stream.js" });
  vm.runInContext(`
    const state = {
      worldSelection: new Set(["fam-1", "fam-2"]),
      families: [{id:"fam-1",name:"Alpha"},{id:"fam-2",name:"Beta"}],
      variants: [{id:"var-1",family_id:"fam-1"}],
      selectedReferences: [
        {type:"entity_family",id:"fam-1"},
        {type:"entity_variant",id:"var-1"},
      ],
    };
    let lastUndo = null;
    globalThis.calls = [];
    globalThis.reloadCount = 0;
    globalThis.toastMessage = "";
    async function api(path, options = {}) { globalThis.calls.push({path, body:options.body || null}); return {ok:true}; }
    function updateContextChipUI() {}
    function scheduleContextStackSync() {}
    async function loadProjectData() { globalThis.reloadCount += 1; }
    function updateWorldBulkBar() {}
    function toast(message) { globalThis.toastMessage = message; }
    async function undoLastAction() { globalThis.originalUndoCalled = true; }
  `, context, { filename: "arline-mock.js" });

  const button = document.getElementById("bulkTrashBtn");
  if (!button) throw new Error("bulk Trash button was not installed");
  if (button.textContent !== "Trash") throw new Error(`unexpected button label: ${button.textContent}`);
  if (bar.children.indexOf(button) > bar.children.indexOf(clear)) throw new Error("Trash button should appear before Clear");

  await button.click();

  const trashCalls = context.calls.filter((item) => item.path === "/api/lifecycle/trash");
  if (trashCalls.length !== 2) throw new Error(`expected 2 trash calls, got ${trashCalls.length}`);
  if (vm.runInContext("state.worldSelection.size", context) !== 0) throw new Error("selection was not cleared after successful bulk Trash");
  if (vm.runInContext("state.selectedReferences.length", context) !== 0) throw new Error("stale family/variant context references were not removed");
  if (vm.runInContext("lastUndo?.type", context) !== "restore_bulk") throw new Error("bulk undo state was not recorded");

  await context.undoLastAction();
  const restoreCalls = context.calls.filter((item) => item.path === "/api/lifecycle/restore");
  if (restoreCalls.length !== 2) throw new Error(`expected 2 restore calls, got ${restoreCalls.length}`);
  if (vm.runInContext("lastUndo", context) !== null) throw new Error("bulk undo state was not cleared after restore");
  if (context.originalUndoCalled) throw new Error("bulk undo fell through to the original single-resource undo");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
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
