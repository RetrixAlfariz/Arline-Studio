from pathlib import Path
import json
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class V11QuickCreateFeatureTests(unittest.TestCase):
    def test_feature_module_exposes_required_quick_create_surfaces(self):
        html = (ROOT / "src/interface/web/static/index.html").read_text(encoding="utf-8")
        quick = (ROOT / "src/interface/web/static/js/quick-create.js").read_text(encoding="utf-8")
        main_js = (ROOT / "src/interface/web/static/arline.js").read_text(encoding="utf-8")
        app = (ROOT / "src/interface/web/app.py").read_text(encoding="utf-8")

        self.assertIn("/static/js/quick-create.js?v=1.2.2-hardening", html)
        self.assertNotIn("window.fetch =", quick)
        self.assertIn("preparePayload", quick)
        self.assertIn("previewOverride", quick)
        self.assertIn("ArlineQuickCreate?.preparePayload", main_js)
        self.assertIn("ArlineQuickCreate?.previewOverride", main_js)

        for token in (
            'value="entity:character"', 'value="entity:location"',
            'value="entity:item"', 'value="entity:organization"',
            'value="entity:lore"', 'value="entity:world_rule"',
            'value="relationship"', 'value="document:scene"',
            'value="document:chapter"', 'value="document:note"',
            'value="document:research"', 'value="document:outline"',
            'panel.id = "quickCreateDestination"', 'id="quickCreateProject"',
            'id="quickCreateWorld"', 'id="quickCreateBranch"',
            'id="quickCreateFolder"', 'id="quickCreateRelationSubject"',
            'id="quickCreateRelationType"', 'id="quickCreateRelationObject"',
            'originalFetch("/api/relationships"',
        ):
            self.assertIn(token, quick)

        # The UI enhancement deliberately reuses capability already exposed by
        # the backend instead of adding a parallel schema.
        self.assertIn("entity_type: str | None = None", app)
        self.assertIn("document_type: str | None = None", app)
        self.assertIn("folder_id: str | None = None", app)
        self.assertIn('@app.post("/api/relationships")', app)

    def test_create_as_mapping_and_relationship_inference_execute_in_node(self):
        quick_path = ROOT / "src/interface/web/static/js/quick-create.js"
        smoke = r'''
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync(process.argv[1], "utf8");
const context = { console };
context.window = context;
context.globalThis = context;
vm.createContext(context);
vm.runInContext(source, context, { filename: "quick-create.js" });

const api = context.ArlineQuickCreate;
if (!api) throw new Error("ArlineQuickCreate helpers were not exported");
if (typeof api.preparePayload !== "function") throw new Error("preparePayload missing");
if (typeof api.previewOverride !== "function") throw new Error("previewOverride missing");

const character = api.decodeCreateAs("entity:character");
const research = api.decodeCreateAs("document:research");
const relationship = api.decodeCreateAs("relationship");
const variants = [
  { id: "VAR-VIAN", display_name: "Vian" },
  { id: "VAR-FANO", display_name: "Fano" },
];
const inferred = api.inferRelationship("Vian dan Fano adalah saudara angkat", variants);

console.log(JSON.stringify({ character, research, relationship, inferred }));
'''
        result = subprocess.run(
            ["node", "-e", smoke, str(quick_path)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr or result.stdout)
        data = json.loads(result.stdout.strip())
        self.assertEqual(data["character"], {"kind": "entity", "entity_type": "character", "document_type": None})
        self.assertEqual(data["research"], {"kind": "document", "entity_type": None, "document_type": "research"})
        self.assertEqual(data["relationship"]["kind"], "relationship")
        self.assertEqual(data["inferred"]["subject_id"], "VAR-VIAN")
        self.assertEqual(data["inferred"]["object_id"], "VAR-FANO")
        self.assertEqual(data["inferred"]["relation_type"], "adopted_sibling")
        self.assertTrue(data["inferred"]["resolved"])


if __name__ == "__main__":
    unittest.main()
