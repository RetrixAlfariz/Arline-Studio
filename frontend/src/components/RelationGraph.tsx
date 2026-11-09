import { useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { familyLayout, relationKind, webLayout, type Graph, type GraphLayout } from "./relationLayout";

export { buildGraph, neighborhood, RELATION_PRESETS, type Graph, type GraphLayout } from "./relationLayout";

const NODE_W = 132;
const NODE_H = 34;

interface RelationGraphProps {
  graph: Graph;
  layout: GraphLayout;
  focusId?: string;
  height?: number | string;
  onOpen: (id: string) => void;
}

/** SVG relation graph: click a sheet to open it, drag the background to pan, buttons to zoom. */
export function RelationGraph({ graph, layout, focusId, height = 420, onOpen }: RelationGraphProps) {
  const laid = useMemo(() => {
    if (layout === "family") return familyLayout(graph, focusId);
    return { positions: webLayout(graph, focusId), nodes: graph.nodes, edges: graph.edges };
  }, [graph, layout, focusId]);
  const box = useMemo(() => {
    const points = [...laid.positions.values()];
    if (!points.length) return { x: -200, y: -100, w: 400, h: 200 };
    const xs = points.map((p) => p.x); const ys = points.map((p) => p.y);
    const pad = 40;
    const x = Math.min(...xs) - NODE_W / 2 - pad; const y = Math.min(...ys) - NODE_H / 2 - pad;
    return { x, y, w: Math.max(...xs) - Math.min(...xs) + NODE_W + pad * 2, h: Math.max(...ys) - Math.min(...ys) + NODE_H + pad * 2 };
  }, [laid]);
  const [view, setView] = useState<{ key: string; zoom: number; dx: number; dy: number }>({ key: "", zoom: 1, dx: 0, dy: 0 });
  const key = `${layout}:${focusId}:${laid.nodes.length}:${laid.edges.length}`;
  const current = view.key === key ? view : { key, zoom: 1, dx: 0, dy: 0 };
  const drag = useRef<{ x: number; y: number; dx: number; dy: number } | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  if (laid.nodes.length < 2) {
    return <div className="graph-empty">{layout === "family"
      ? <>No family links yet. Add relationships such as <b>parent of</b>, <b>spouse of</b> or <b>sibling of</b> to grow the tree.</>
      : <>No relationships to draw yet. Add one to see the web.</>}</div>;
  }

  const w = box.w / current.zoom; const h = box.h / current.zoom;
  const vx = box.x + (box.w - w) / 2 + current.dx; const vy = box.y + (box.h - h) / 2 + current.dy;
  const zoomBy = (factor: number) => setView({ ...current, zoom: Math.min(4, Math.max(0.3, current.zoom * factor)) });
  const scale = () => (svgRef.current ? w / svgRef.current.clientWidth : 1);
  const onDown = (event: ReactPointerEvent<SVGSVGElement>) => {
    if ((event.target as Element).closest(".graph-node")) return;
    drag.current = { x: event.clientX, y: event.clientY, dx: current.dx, dy: current.dy };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const onMove = (event: ReactPointerEvent<SVGSVGElement>) => {
    if (!drag.current) return;
    const s = scale();
    setView({ ...current, dx: drag.current.dx - (event.clientX - drag.current.x) * s, dy: drag.current.dy - (event.clientY - drag.current.y) * s });
  };
  const onUp = () => { drag.current = null; };
  const at = (id: string) => laid.positions.get(id)!;
  // Index each edge among the edges joining the same pair, so they can be drawn side by side.
  const lanes = new Map<string, [number, number]>();
  const pairs = new Map<string, string[]>();
  for (const edge of laid.edges) {
    const pair = [edge.from, edge.to].sort().join("|");
    pairs.set(pair, [...(pairs.get(pair) || []), edge.id]);
  }
  for (const ids of pairs.values()) ids.forEach((id, index) => lanes.set(id, [index, ids.length]));
  const short = (text: string) => (text.length > 18 ? `${text.slice(0, 17)}…` : text);

  return (
    <div className={`relation-graph layout-${layout}`} style={{ height }}>
      <div className="graph-zoom" role="group" aria-label="Zoom">
        <button onClick={() => zoomBy(1.2)} aria-label="Zoom in">+</button>
        <button onClick={() => zoomBy(1 / 1.2)} aria-label="Zoom out">−</button>
        <button onClick={() => setView({ key, zoom: 1, dx: 0, dy: 0 })} aria-label="Fit graph">Fit</button>
      </div>
      <svg ref={svgRef} role="img" aria-label={`${layout === "family" ? "Family tree" : "Relationship web"} with ${laid.nodes.length} sheets`} viewBox={`${vx} ${vy} ${w} ${h}`} preserveAspectRatio="xMidYMid meet" onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerLeave={onUp}>
        <defs>
          <marker id="graph-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" className="graph-arrowhead" /></marker>
        </defs>
        {laid.edges.map((edge) => {
          const a = at(edge.from); const b = at(edge.to);
          if (!a || !b) return null;
          const kind = relationKind(edge.label);
          if (layout === "family" && (kind === "parent" || kind === "child")) {
            const [top, bottom] = kind === "parent" ? [a, b] : [b, a];
            const mid = (top.y + bottom.y) / 2;
            return <path key={edge.id} className="graph-edge kin" d={`M${top.x} ${top.y + NODE_H / 2} V${mid} H${bottom.x} V${bottom.y - NODE_H / 2}`}><title>{edge.label}</title></path>;
          }
          if (layout === "family") return <line key={edge.id} className={`graph-edge ${kind}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y}><title>{edge.label}</title></line>;
          // Web: arrow from subject to object; parallel relationships between one pair bow apart.
          const [slot, of] = lanes.get(edge.id) || [0, 1];
          const dx = b.x - a.x; const dy = b.y - a.y;
          const len = Math.max(1, Math.hypot(dx, dy));
          const sign = edge.from < edge.to ? 1 : -1; // same side regardless of direction
          const bend = (slot - (of - 1) / 2) * 90 * sign;
          const cx = (a.x + b.x) / 2 - (dy / len) * bend; const cy = (a.y + b.y) / 2 + (dx / len) * bend;
          const tx = b.x - cx; const ty = b.y - cy; const tl = Math.max(1, Math.hypot(tx, ty));
          const cut = Math.min(Math.abs((NODE_W / 2 + 4) / (tx / tl || 1e-9)), Math.abs((NODE_H / 2 + 4) / (ty / tl || 1e-9)));
          const ex = b.x - (tx / tl) * cut; const ey = b.y - (ty / tl) * cut;
          const lx = (a.x + 2 * cx + b.x) / 4; const ly = (a.y + 2 * cy + b.y) / 4; // curve midpoint
          return <g key={edge.id}>
            <path className="graph-edge" d={`M${a.x} ${a.y} Q${cx} ${cy} ${ex} ${ey}`} markerEnd="url(#graph-arrow)" />
            <text className="graph-edge-label" x={lx} y={ly - 4} textAnchor="middle">{edge.label}</text>
          </g>;
        })}
        {laid.nodes.map((node) => {
          const p = at(node.id);
          return (
            <g key={node.id} className={`graph-node type-${node.type} ${node.id === focusId ? "focus" : ""}`} transform={`translate(${p.x} ${p.y})`} role="button" tabIndex={0} aria-label={`Open ${node.name}`}
              onClick={() => onOpen(node.id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onOpen(node.id); } }}>
              <title>{`${node.name} (${node.type})`}</title>
              <rect x={-NODE_W / 2} y={-NODE_H / 2} width={NODE_W} height={NODE_H} rx={7} />
              <text y={4} textAnchor="middle">{short(node.name)}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
