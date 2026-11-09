import type { WorldBible } from "../types";

export type GraphLayout = "family" | "web";
export interface GraphNode { id: string; name: string; type: string }
export interface GraphEdge { id: string; from: string; to: string; label: string }
export interface Graph { nodes: GraphNode[]; edges: GraphEdge[] }

/** Suggestions for the relation field; any text is allowed. */
export const RELATION_PRESETS = ["parent of", "child of", "spouse of", "sibling of", "friend of", "rival of", "mentor of", "student of", "member of", "leader of", "ally of", "enemy of", "lives in", "owns"];

type Kind = "parent" | "child" | "partner" | "sibling" | "other";
/** Family-tree meaning of a free-text relation, read as "subject <relation> object". */
export function relationKind(label: string): Kind {
  const text = label.toLowerCase();
  if (/\b(parent|father|mother|mom|dad)\b/.test(text)) return "parent";
  if (/\b(child|son|daughter)\b/.test(text)) return "child";
  if (/\b(spouse|husband|wife|partner|married|consort)\b/.test(text)) return "partner";
  if (/\b(sibling|brother|sister|twin)\b/.test(text)) return "sibling";
  return "other";
}

/** Sheets and relationships of the loaded world. Relationships may carry only variant ids. */
export function buildGraph(bible: WorldBible | null): Graph {
  const families = bible?.families || [];
  const known = new Set(families.map((family) => family.id));
  const familyOfVariant = new Map((bible?.variants || []).map((variant) => [variant.id, variant.family_id || ""]));
  const edges: GraphEdge[] = [];
  for (const item of bible?.relationships || []) {
    const from = item.subject_family_id || familyOfVariant.get(String(item.subject_variant_id || "")) || "";
    const to = item.object_family_id || familyOfVariant.get(String(item.object_variant_id || "")) || "";
    if (known.has(from) && known.has(to) && from !== to) edges.push({ id: item.id, from, to, label: item.relation_type || "related to" });
  }
  return { nodes: families.map((family) => ({ id: family.id, name: family.name, type: family.entity_type || "lore" })), edges };
}

/** Nodes within `depth` hops of the focus, ignoring direction. */
export function neighborhood(graph: Graph, focusId: string, depth = 2): Graph {
  const keep = new Set([focusId]);
  let frontier = [focusId];
  for (let step = 0; step < depth; step++) {
    const next: string[] = [];
    for (const edge of graph.edges) {
      for (const [a, b] of [[edge.from, edge.to], [edge.to, edge.from]]) {
        if (frontier.includes(a) && !keep.has(b)) { keep.add(b); next.push(b); }
      }
    }
    frontier = next;
  }
  return { nodes: graph.nodes.filter((node) => keep.has(node.id)), edges: graph.edges.filter((edge) => keep.has(edge.from) && keep.has(edge.to)) };
}

type Point = { x: number; y: number };
const GAP_X = 168;
const GAP_Y = 104;

/** Generations top to bottom: parents above children, partners and siblings side by side. */
export function familyLayout(graph: Graph, focusId?: string): { positions: Map<string, Point>; nodes: GraphNode[]; edges: GraphEdge[] } {
  const edges = graph.edges.filter((edge) => relationKind(edge.label) !== "other");
  const ids = new Set<string>(edges.flatMap((edge) => [edge.from, edge.to]));
  if (focusId) ids.add(focusId);
  const links = new Map<string, Array<[string, number]>>();
  const link = (a: string, b: string, delta: number) => { if (!links.has(a)) links.set(a, []); links.get(a)!.push([b, delta]); };
  for (const edge of edges) {
    const kind = relationKind(edge.label);
    const delta = kind === "parent" ? 1 : kind === "child" ? -1 : 0; // object's level minus subject's level
    link(edge.from, edge.to, delta);
    link(edge.to, edge.from, -delta);
  }
  const level = new Map<string, number>();
  const discovery: string[] = [];
  for (const start of [...(focusId ? [focusId] : []), ...ids]) {
    if (level.has(start)) continue;
    level.set(start, 0);
    const queue = [start];
    while (queue.length) {
      const current = queue.shift()!;
      discovery.push(current);
      for (const [next, delta] of links.get(current) || []) {
        if (!level.has(next)) { level.set(next, level.get(current)! + delta); queue.push(next); }
      }
    }
  }
  const rows = new Map<number, string[]>();
  for (const id of discovery) {
    const row = level.get(id)!;
    rows.set(row, [...(rows.get(row) || []), id]);
  }
  const positions = new Map<string, Point>();
  const place = (row: number, order: string[]) => order.forEach((id, index) => positions.set(id, { x: (index - (order.length - 1) / 2) * GAP_X, y: row * GAP_Y }));
  const levels = [...rows.keys()].sort((a, b) => a - b);
  for (const row of levels) {
    let order = rows.get(row)!;
    // Children sit under the mean x of their parents (one barycentre pass).
    const anchor = (id: string) => {
      const xs = (links.get(id) || []).filter(([other, delta]) => delta === -1 && positions.has(other)).map(([other]) => positions.get(other)!.x);
      return xs.length ? xs.reduce((sum, x) => sum + x, 0) / xs.length : Number.NaN;
    };
    order = [...order].sort((a, b) => {
      const [ax, bx] = [anchor(a), anchor(b)];
      if (Number.isNaN(ax) || Number.isNaN(bx)) return 0;
      return ax - bx;
    });
    // Keep partners next to each other.
    for (const edge of edges) {
      if (relationKind(edge.label) !== "partner") continue;
      const [a, b] = [order.indexOf(edge.from), order.indexOf(edge.to)];
      if (a < 0 || b < 0 || Math.abs(a - b) === 1) continue;
      order.splice(b, 1);
      order.splice(order.indexOf(edge.from) + 1, 0, edge.to);
    }
    place(row, order);
  }
  const nodes = graph.nodes.filter((node) => positions.has(node.id));
  return { positions, nodes, edges };
}

/** Deterministic force-directed layout; the focus, if any, stays in the middle. */
export function webLayout(graph: Graph, focusId?: string): Map<string, Point> {
  const { nodes, edges } = graph;
  const count = nodes.length;
  const index = new Map(nodes.map((node, i) => [node.id, i]));
  const radius = Math.max(160, count * 26);
  const pos = nodes.map((node, i) => node.id === focusId ? { x: 0, y: 0 } : { x: Math.cos((2 * Math.PI * i) / count) * radius, y: Math.sin((2 * Math.PI * i) / count) * radius });
  const ideal = 190;
  const rounds = 320;
  for (let round = 0; round < rounds; round++) {
    const move = nodes.map(() => ({ x: 0, y: 0 }));
    for (let i = 0; i < count; i++) {
      for (let j = i + 1; j < count; j++) {
        const dx = pos[i].x - pos[j].x;
        const dy = pos[i].y - pos[j].y;
        const dist = Math.max(1, Math.hypot(dx, dy));
        const force = (ideal * ideal) / dist;
        move[i].x += (dx / dist) * force; move[i].y += (dy / dist) * force;
        move[j].x -= (dx / dist) * force; move[j].y -= (dy / dist) * force;
      }
    }
    for (const edge of edges) {
      const a = index.get(edge.from); const b = index.get(edge.to);
      if (a === undefined || b === undefined) continue;
      const dx = pos[a].x - pos[b].x;
      const dy = pos[a].y - pos[b].y;
      const dist = Math.max(1, Math.hypot(dx, dy));
      const force = (dist * dist) / ideal;
      move[a].x -= (dx / dist) * force; move[a].y -= (dy / dist) * force;
      move[b].x += (dx / dist) * force; move[b].y += (dy / dist) * force;
    }
    const temperature = 40 * (1 - round / rounds) + 1;
    for (let i = 0; i < count; i++) {
      move[i].x -= pos[i].x * 0.05; move[i].y -= pos[i].y * 0.05; // gentle pull to the centre keeps islands close
      const length = Math.max(1, Math.hypot(move[i].x, move[i].y));
      pos[i].x += (move[i].x / length) * Math.min(length, temperature);
      pos[i].y += (move[i].y / length) * Math.min(length, temperature);
      if (nodes[i].id === focusId) pos[i] = { x: 0, y: 0 };
    }
  }
  return new Map(nodes.map((node, i) => [node.id, pos[i]]));
}
