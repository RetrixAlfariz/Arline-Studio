import { useMemo, useState } from "react";
import { GitFork, List, Network, Plus, X } from "lucide-react";
import { ensureVariant, studioApi } from "../api";
import { browserStorage } from "../browserStorage";
import { buildGraph, neighborhood, RELATION_PRESETS, RelationGraph, type GraphLayout } from "../components/RelationGraph";
import type { EntityFamily, WorldBible } from "../types";

interface SheetRelationsProps {
  family: EntityFamily;
  bible: WorldBible | null;
  worldId: string;
  branchId: string;
  onOpenEntity: (id: string) => void;
  onChanged: () => Promise<void> | void;
  onNotice: (text: string) => void;
}

type RelView = "list" | GraphLayout;

/** Relationships block of a sheet page: list or graph (family tree / web), add and remove. */
export function SheetRelations({ family, bible, worldId, branchId, onOpenEntity, onChanged, onNotice }: SheetRelationsProps) {
  const [mode, setMode] = useState<RelView>(() => (browserStorage.get("arline:entity:relview") as RelView) || "list");
  const graph = useMemo(() => buildGraph(bible), [bible]);
  const local = useMemo(() => neighborhood(graph, family.id, 2), [graph, family.id]);
  const names = useMemo(() => new Map(graph.nodes.map((node) => [node.id, node.name])), [graph]);
  const mine = graph.edges.filter((edge) => edge.from === family.id || edge.to === family.id);
  const choose = (next: RelView) => { browserStorage.set("arline:entity:relview", next); setMode(next); };

  const remove = async (id: string) => {
    try { await studioApi.deleteRelationship(id); onNotice("Relationship removed"); await onChanged(); }
    catch (error) { onNotice((error as Error).message); }
  };

  return (
    <section className="page-block">
      <div className="page-block-head">
        <h2>Relationships</h2>
        <div className="page-segment" role="group" aria-label="Relationship view">
          <button aria-pressed={mode === "list"} onClick={() => choose("list")}><List size={13} />List</button>
          <button aria-pressed={mode === "family"} onClick={() => choose("family")}><GitFork size={13} />Family tree</button>
          <button aria-pressed={mode === "web"} onClick={() => choose("web")}><Network size={13} />Web</button>
        </div>
      </div>
      {mode === "list"
        ? (mine.length ? <ul className="page-links relation-rows">{mine.map((edge) => {
          const outgoing = edge.from === family.id;
          const otherId = outgoing ? edge.to : edge.from;
          const other = <button onClick={() => onOpenEntity(otherId)}>{names.get(otherId) || "Unknown"}</button>;
          return <li key={edge.id}>
            {outgoing ? <><span className="relation-verb">{edge.label}</span>{other}</> : <>{other}<span className="relation-verb">{edge.label} {family.name}</span></>}
            <button className="page-prop-remove" aria-label={`Remove relationship ${edge.label}`} title="Remove relationship" onClick={() => void remove(edge.id)}><X size={13} /></button>
          </li>;
        })}</ul> : <p className="page-muted">No relationships yet.</p>)
        : <RelationGraph graph={local} layout={mode} focusId={family.id} height={380} onOpen={onOpenEntity} />}
      <AddRelationship family={family} bible={bible} worldId={worldId} branchId={branchId} onChanged={onChanged} onNotice={onNotice} />
    </section>
  );
}

function AddRelationship({ family, bible, worldId, branchId, onChanged, onNotice }: Omit<SheetRelationsProps, "onOpenEntity">) {
  const [open, setOpen] = useState(false);
  const [relation, setRelation] = useState("");
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const others = (bible?.families || []).filter((item) => item.id !== family.id).sort((a, b) => a.name.localeCompare(b.name));
  if (!worldId) return <p className="page-muted">Choose a world to add relationships.</p>;
  if (!open) return <button className="page-ghost-action" onClick={() => setOpen(true)}><Plus size={14} />Add relationship</button>;

  const submit = async () => {
    const type = relation.trim().toLowerCase();
    const other = others.find((item) => item.id === target);
    if (!type || !other) return;
    setBusy(true);
    try {
      const variants = bible?.variants || [];
      // Relationships link world variants; a sheet without one in this world gets it now.
      const subject = await ensureVariant(family.id, family.name, worldId, branchId, variants);
      const object = await ensureVariant(other.id, other.name, worldId, branchId, variants);
      await studioApi.createRelationship({ world_id: worldId, branch_id: branchId || null, subject_variant_id: subject, object_variant_id: object, relation_type: type, canon_status: "draft" });
      onNotice(`${family.name} ${type} ${other.name}`);
      setRelation(""); setTarget(""); setOpen(false);
      await onChanged();
    } catch (error) {
      onNotice((error as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relation-form" onKeyDown={(event) => { if (event.key === "Escape") setOpen(false); }}>
      <strong>{family.name}</strong>
      <input autoFocus className="page-prop-input" list="relation-presets" placeholder="is… (e.g. parent of)" aria-label="Relationship" value={relation} onChange={(event) => setRelation(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void submit(); }} />
      <datalist id="relation-presets">{RELATION_PRESETS.map((item) => <option key={item} value={item} />)}</datalist>
      <select className="page-prop-input" aria-label="Related sheet" value={target} onChange={(event) => setTarget(event.target.value)}>
        <option value="">Choose a sheet…</option>
        {others.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.entity_type}</option>)}
      </select>
      <button className="page-action" disabled={busy || !relation.trim() || !target} onClick={() => void submit()}>{busy ? "Adding…" : "Add"}</button>
      <button className="page-action" onClick={() => setOpen(false)}>Cancel</button>
    </div>
  );
}
