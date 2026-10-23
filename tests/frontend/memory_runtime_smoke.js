
"use strict";
const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const appState = {
  activeProject: {id: "P-ACTIVE"}, activeWorld: {id: "W-ACTIVE"}, activeBranch: {id: "B-ACTIVE"},
  activeSession: {id: "S-ACTIVE"}, activeScene: {document_id: "DOC-2", narrative_time: "Day 2", pov_variant_id: "POV-1"},
  sceneCards: [{document_id: "DOC-2", sort_order: 2, narrative_time: "Day 2", pov_variant_id: "POV-1"}],
};
global.window = {
  ArlineRuntime: {
    getState: () => appState,
    getScope: () => ({projectId: "P-ACTIVE", worldId: "W-ACTIVE", branchId: "B-ACTIVE", sessionId: "S-ACTIVE"}),
  },
  collectPromptReferences: () => [{type: "entity_family", id: "E-1"}],
};
global.localStorage = {getItem: () => null, setItem: () => {}};
global.document = {getElementById: () => null, querySelector: () => null, addEventListener: () => {}};
global.fetch = async () => { throw new Error("network should not be used by scope smoke"); };

vm.runInThisContext(fs.readFileSync("src/interface/web/static/js/memory.js", "utf8"), {filename: "memory.js"});
const scope = window.ArlineMemoryRuntime.currentScope("where is it?");
assert.deepStrictEqual(
  {project: scope.project_id, world: scope.world_id, branch: scope.branch_id, session: scope.session_id},
  {project: "P-ACTIVE", world: "W-ACTIVE", branch: "B-ACTIVE", session: "S-ACTIVE"},
);
assert.strictEqual(scope.story_order, 2);
assert.strictEqual(scope.world_time, "Day 2");
assert.strictEqual(scope.pov_variant_id, "POV-1");
assert.strictEqual(scope.explicit_references[0].id, "E-1");
assert.ok(!fs.readFileSync("src/interface/web/static/js/memory.js", "utf8").includes("window.state?."));
console.log("memory runtime scope bridge: ok");
