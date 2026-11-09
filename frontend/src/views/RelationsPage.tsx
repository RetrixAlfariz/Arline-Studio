import { useMemo, useState } from "react";
import { GitFork, Network } from "lucide-react";
import { browserStorage } from "../browserStorage";
import { PageHeader, type Crumb } from "../components/PageHeader";
import { buildGraph, RelationGraph, type GraphLayout } from "../components/RelationGraph";
import type { WorldBible } from "../types";

/** Whole-world relation graph: every sheet that has at least one relationship. */
export function RelationsPage({ bible, crumbs, onOpenEntity }: { bible: WorldBible | null; crumbs: Crumb[]; onOpenEntity: (id: string) => void }) {
  const [layout, setLayout] = useState<GraphLayout>(() => (browserStorage.get("arline:graph:layout") as GraphLayout) || "web");
  const graph = useMemo(() => {
    const full = buildGraph(bible);
    const linked = new Set(full.edges.flatMap((edge) => [edge.from, edge.to]));
    return { nodes: full.nodes.filter((node) => linked.has(node.id)), edges: full.edges };
  }, [bible]);
  const unlinked = (bible?.families || []).length - graph.nodes.length;
  const choose = (next: GraphLayout) => { browserStorage.set("arline:graph:layout", next); setLayout(next); };

  return (
    <div className="page-frame">
      <PageHeader crumbs={crumbs} actions={
        <div className="page-segment" role="group" aria-label="Graph layout">
          <button aria-pressed={layout === "family"} onClick={() => choose("family")}><GitFork size={14} />Family tree</button>
          <button aria-pressed={layout === "web"} onClick={() => choose("web")}><Network size={14} />Web</button>
        </div>
      } />
      <div className="graph-page">
        <div className="graph-page-head">
          <h1>Relation graph</h1>
          <p>{graph.edges.length} relationships between {graph.nodes.length} sheets{unlinked > 0 ? ` · ${unlinked} sheets have no relationships yet` : ""}. Click a sheet to open it; add relationships from its page.</p>
        </div>
        <RelationGraph graph={graph} layout={layout} height="100%" onOpen={onOpenEntity} />
      </div>
    </div>
  );
}
