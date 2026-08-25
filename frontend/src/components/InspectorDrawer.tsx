import { useEffect, useState } from "react";
import { AtSign, FolderPlus, Image, Layers3, Link2, Pin, Star, Trash2, X } from "lucide-react";
import { studioApi } from "../api";
import type { Selection } from "../types";

interface InspectorDrawerProps {
  selection: Selection | null;
  onClose: () => void;
  projectId: string;
  worldId: string;
  branchId: string;
  onChanged: () => Promise<void> | void;
}

export function InspectorDrawer({ selection, onClose, projectId, worldId, branchId, onChanged }: InspectorDrawerProps) {
  const [related, setRelated] = useState<unknown>(null);
  const [status, setStatus] = useState("");
  const [media, setMedia] = useState<Array<Record<string, unknown>>>([]);
  useEffect(() => {
    setRelated(null); setStatus(""); setMedia([]);
    if (selection?.kind === "entity" && selection.id) void studioApi.media({ resourceType: "entity_family", resourceId: selection.id }).then((result) => setMedia(result.items || [])).catch(() => setMedia([]));
  }, [selection?.id, selection?.kind]);
  if (!selection) return null;
  const resourceType = selection.kind === "entity" ? "entity_family" : selection.kind;
  const resourceId = selection.id || "";
  return (
    <aside className="data-inspector">
      <header><div><span className="eyebrow">Inspector</span><h2>{selection.title}</h2><p>{selection.subtitle || selection.kind}</p></div><button className="icon-control" onClick={onClose}><X size={15} /></button></header>
      <div className="data-inspector-body">
        <div className="property-row"><span>Kind</span><strong>{selection.kind}</strong></div>
        {selection.id ? <div className="property-row"><span>ID</span><strong className="mono">{selection.id}</strong></div> : null}
        <section><span className="eyebrow">Structured data</span><pre>{JSON.stringify(selection.data ?? {}, null, 2)}</pre></section>
        {resourceId && selection.kind !== "analysis" && <section className="inspector-resource-actions"><span className="eyebrow">Resource actions</span><div><button onClick={async () => { setRelated(await studioApi.backlinks(resourceType, resourceId)); }}><Link2 size={12} />Where used</button><button onClick={async () => { await studioApi.pinContext({ project_id: projectId, world_id: worldId || null, branch_id: branchId || null, resource_type: resourceType, resource_id: resourceId, scope: "world", priority: 1 }); setStatus("Pinned to context"); }}><Pin size={12} />Pin context</button><button onClick={async () => { await studioApi.addFavorite({ project_id: projectId, resource_type: resourceType, resource_id: resourceId, label: selection.title }); setStatus("Added to favorites"); }}><Star size={12} />Favorite</button><button onClick={async () => { const alias = window.prompt("Alias"); if (alias) { await studioApi.createAlias({ resource_type: resourceType, resource_id: resourceId, alias }); setStatus("Alias added"); } }}><AtSign size={12} />Alias</button><button onClick={async () => { const collectionId = window.prompt("Collection ID"); if (collectionId) { await studioApi.linkCollection(collectionId, { resource_type: resourceType, resource_id: resourceId }); setStatus("Added to collection"); } }}><FolderPlus size={12} />Collection</button><button onClick={async () => { const path = window.prompt("Overlay semantic path"); if (!path) return; const value = window.prompt("Overlay value", ""); await studioApi.createOverlay(projectId, { owner_type: resourceType, owner_id: resourceId, path, value, world_id: worldId || null, branch_id: branchId || null }); setStatus("Project overlay created"); }}><Layers3 size={12} />Overlay</button><button className="danger" onClick={async () => { if (!window.confirm(`Move ${selection.title} to Trash?`)) return; await studioApi.trash(resourceType, resourceId); await onChanged(); onClose(); }}><Trash2 size={12} />Trash</button></div>{status && <p>{status}</p>}</section>}
        {media.length > 0 && <section className="inspector-media"><span className="eyebrow"><Image size={11} /> Media</span>{media.map((item) => <article key={String(item.id)}>{item.content_url ? <img src={String(item.content_url)} alt={String(item.caption || "Media")} /> : null}<div><strong>{String(item.caption || item.kind || "Media")}</strong><span><button onClick={async () => { await studioApi.updateMedia(String(item.id), { is_cover: true }); setStatus("Cover updated"); }}>Cover</button><button onClick={async () => { const caption = window.prompt("Caption", String(item.caption || "")); if (caption !== null) { await studioApi.updateMedia(String(item.id), { caption }); setMedia((items) => items.map((current) => current.id === item.id ? { ...current, caption } : current)); } }}>Edit</button><button onClick={async () => { await studioApi.deleteMedia(String(item.id)); setMedia((items) => items.filter((current) => current.id !== item.id)); }}>Delete</button></span></div></article>)}</section>}
        {related !== null && <section><span className="eyebrow">Backlinks</span><pre>{JSON.stringify(related, null, 2)}</pre></section>}
      </div>
    </aside>
  );
}
