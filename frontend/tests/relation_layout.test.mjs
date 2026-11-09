// Run: node tests/relation_layout.test.mjs  (Node 22+ strips the TypeScript types)
import assert from "node:assert/strict";
import { buildGraph, familyLayout, neighborhood, relationKind, webLayout } from "../src/components/relationLayout.ts";

assert.equal(relationKind("parent of"), "parent");
assert.equal(relationKind("Mother of"), "parent");
assert.equal(relationKind("grandparent of"), "other", "grandparent is not a direct generation step");
assert.equal(relationKind("daughter of"), "child");
assert.equal(relationKind("married to"), "partner");
assert.equal(relationKind("twin sister of"), "sibling");
assert.equal(relationKind("old friend"), "other");

// Relationships that only carry variant ids resolve to their families; unknown ends are dropped.
const bible = {
  families: ["Ada", "Ben", "Cal", "Dee", "Eve", "Inn"].map((name) => ({ id: name, name, entity_type: name === "Inn" ? "location" : "character" })),
  variants: [{ id: "v-ada", family_id: "Ada" }, { id: "v-cal", family_id: "Cal" }],
  relationships: [
    { id: "r1", subject_variant_id: "v-ada", object_variant_id: "v-cal", relation_type: "parent of" },
    { id: "r2", subject_family_id: "Ben", object_family_id: "Cal", relation_type: "father of" },
    { id: "r3", subject_family_id: "Ada", object_family_id: "Ben", relation_type: "spouse of" },
    { id: "r4", subject_family_id: "Dee", object_family_id: "Cal", relation_type: "sister of" },
    { id: "r5", subject_family_id: "Eve", object_family_id: "Cal", relation_type: "daughter of" },
    { id: "r6", subject_family_id: "Cal", object_family_id: "Inn", relation_type: "lives in" },
    { id: "r7", subject_family_id: "Cal", object_family_id: "Gone", relation_type: "friend of" },
  ],
};
const graph = buildGraph(bible);
assert.equal(graph.edges.length, 6, "edge to a missing sheet is dropped");

const { positions, nodes } = familyLayout(graph, "Cal");
const y = (id) => positions.get(id).y;
assert.ok(!positions.has("Inn"), "non-family links stay out of the tree");
assert.equal(nodes.length, 5);
assert.ok(y("Ada") < y("Cal") && y("Ben") < y("Cal"), "parents sit above the child");
assert.equal(y("Ada"), y("Ben"), "partners share a generation");
assert.equal(y("Dee"), y("Cal"), "siblings share a generation");
assert.ok(y("Eve") > y("Cal"), "a daughter sits below her parent");
const row = [...positions.entries()].filter(([, p]) => p.y === y("Ada")).sort((a, b) => a[1].x - b[1].x).map(([id]) => id);
assert.equal(Math.abs(row.indexOf("Ada") - row.indexOf("Ben")), 1, "partners are adjacent");

const web = webLayout(graph, "Cal");
assert.deepEqual(web.get("Cal"), { x: 0, y: 0 }, "focus stays centred");
for (const [id, p] of web) assert.ok(Number.isFinite(p.x) && Number.isFinite(p.y), `${id} has a finite position`);
const ids = [...web.keys()];
for (let i = 0; i < ids.length; i++) for (let j = i + 1; j < ids.length; j++) {
  const a = web.get(ids[i]); const b = web.get(ids[j]);
  assert.ok(Math.hypot(a.x - b.x, a.y - b.y) > 40, `${ids[i]} and ${ids[j]} do not overlap`);
}

const near = neighborhood(graph, "Eve", 1);
assert.deepEqual(near.nodes.map((node) => node.id).sort(), ["Cal", "Eve"]);

console.log("relation layout: ok");
