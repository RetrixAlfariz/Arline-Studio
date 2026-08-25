import { useEffect, useMemo, useState } from "react";
import { Archive, Boxes, Camera, Check, GitBranch, GitCompare, Grid2X2, Image, List, Pencil, Plus, Search, Sparkles, Trash2, Waypoints, WandSparkles } from "lucide-react";
import { studioApi } from "../api";
import type { EntityFamily, EntityVariant, JsonMap, MediaItem, Relationship, Selection, WorldBible } from "../types";

interface LibraryViewProps {
  projectId: string;
  worldId: string;
  branchId: string;
  bible: WorldBible | null;
  entityTypes: string[];
  onChanged: () => Promise<void> | void;
  onSelect: (selection: Selection) => void;
}

export function LibraryView({ projectId, worldId, branchId, bible, entityTypes, onChanged, onSelect }: LibraryViewProps) {
  const [tab, setTab] = useState("all");
  const [query, setQuery] = useState("");
  const [quickOpen, setQuickOpen] = useState(false);
  const [quickText, setQuickText] = useState("");
  const [quickKind, setQuickKind] = useState("");
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [layout, setLayout] = useState<"grid" | "list" | "gallery">("grid");
  const [selected, setSelected] = useState<string[]>([]);
  const [media, setMedia] = useState<MediaItem[]>([]);
  const [timeline, setTimeline] = useState<JsonMap[]>([]);
  const [notice, setNotice] = useState("");
  const [facts, setFacts] = useState<JsonMap[]>([]);
  const [snapshots, setSnapshots] = useState<JsonMap[]>([]);

  const families = bible?.families || [];
  const variants = bible?.variants || [];
  const relationships = bible?.relationships || [];

  useEffect(() => {
    if (!worldId) return;
    void Promise.all([
      studioApi.media({ coverOnly: true }).catch(() => ({ items: [] })),
      studioApi.timeline(worldId, branchId).catch(() => ({ events: [] })),
      studioApi.facts(projectId, worldId, branchId).catch(() => ({ facts: [] })),
      studioApi.snapshots(worldId).catch(() => ({ snapshots: [] })),
    ]).then(([mediaResult, timelineResult, factResult, snapshotResult]) => { setMedia(mediaResult.items || []); setTimeline(timelineResult.events || []); setFacts(factResult.facts || []); setSnapshots(snapshotResult.snapshots || []); });
  }, [projectId, worldId, branchId]);

  const filteredFamilies = useMemo(() => families.filter((family) => {
    if (tab !== "all" && tab !== "relationships" && tab !== "canon" && tab !== "timeline" && tab !== "worlds" && family.entity_type !== tab) return false;
    const needle = query.trim().toLowerCase();
    return !needle || family.name.toLowerCase().includes(needle) || family.description?.toLowerCase().includes(needle);
  }), [families, tab, query]);

  const variantFor = (family: EntityFamily): EntityVariant | undefined => variants.find((variant) => variant.family_id === family.id && (!worldId || variant.world_id === worldId));

  const inspectEntity = (family: EntityFamily) => {
    const variant = variantFor(family);
    onSelect({
      kind: "entity",
      id: family.id,
      title: variant?.display_name || family.name,
      subtitle: family.entity_type || "entity",
      data: { family, variant },
    });
  };

  const inspectRelationship = (relationship: Relationship) => {
    onSelect({
      kind: "relationship",
      id: relationship.id,
      title: `${relationship.subject_name || "Entity"} → ${relationship.object_name || "Entity"}`,
      subtitle: relationship.relation_type || "relationship",
      data: relationship,
    });
  };

  const previewQuickCreate = async () => {
    if (!quickText.trim()) return;
    setBusy(true);
    try {
      const result = await studioApi.quickCreatePreview({
        text: quickText.trim(),
        forced_kind: quickKind || null,
        project_id: projectId || null,
        world_id: worldId || null,
        branch_id: branchId || null,
        folder_id: null,
      });
      setPreview(result);
    } finally {
      setBusy(false);
    }
  };

  const createQuick = async () => {
    if (!quickText.trim()) return;
    setBusy(true);
    try {
      await studioApi.quickCreate({
        text: quickText.trim(),
        forced_kind: quickKind || null,
        project_id: projectId || null,
        world_id: worldId || null,
        branch_id: branchId || null,
        folder_id: null,
      });
      setQuickOpen(false);
      setQuickText("");
      setPreview(null);
      await onChanged();
    } finally {
      setBusy(false);
    }
  };

  const toggleSelected = (id: string) => setSelected((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  const runLibraryAction = async (label: string, action: () => Promise<unknown>) => {
    setBusy(true); setNotice("");
    try { await action(); setNotice(`${label} complete`); await onChanged(); }
    catch (error) { setNotice((error as Error).message); }
    finally { setBusy(false); }
  };
  const coverFor = (family: EntityFamily) => media.find((item) => item.resource_type === "entity_family" && item.resource_id === family.id);

  const createForTab = async () => {
    if (tab === "timeline") {
      const summary = window.prompt("Timeline event"); if (!summary) return;
      await runLibraryAction("Timeline event", () => studioApi.createTimelineEvent({ world_id: worldId, branch_id: branchId || null, summary, time_label: window.prompt("Time label", "") || "", order_key: timeline.length + 1, event_type: "event", state_patch: {}, status: "canon" }));
      const result = await studioApi.timeline(worldId, branchId); setTimeline(result.events || []); return;
    }
    if (tab === "canon") {
      const path = window.prompt("Semantic path", "world.rule"); if (!path) return;
      const value = window.prompt("Fact value", ""); if (value === null) return;
      await runLibraryAction("Canon fact", () => studioApi.createFact({ project_id: projectId, world_id: worldId, branch_id: branchId || null, owner_type: "world", owner_id: worldId, path, value, status: "canon", authority: "user_explicit" }));
      const result = await studioApi.facts(projectId, worldId, branchId); setFacts(result.facts || []); return;
    }
    if (tab === "worlds") {
      const name = window.prompt("World name"); if (!name) return;
      await runLibraryAction("World created", () => studioApi.createWorld({ project_id: projectId, name, description: "", canon_status: "draft", inheritance_mode: "snapshot", clone_parent: true })); return;
    }
    if (tab === "relationships") {
      const subject = window.prompt("Subject variant ID"); const object = window.prompt("Object variant ID"); const relationType = window.prompt("Relationship type", "related_to");
      if (!subject || !object || !relationType) return;
      await runLibraryAction("Relationship created", () => studioApi.createRelationship({ world_id: worldId, branch_id: branchId || null, subject_variant_id: subject, object_variant_id: object, relation_type: relationType, canon_status: "draft", attributes: {} })); return;
    }
    setQuickOpen(true);
  };

  const editFamily = async (family: EntityFamily) => {
    const name = window.prompt("Sheet name", family.name); if (!name) return;
    const description = window.prompt("Description", family.description || ""); if (description === null) return;
    await runLibraryAction("Sheet updated", () => studioApi.updateEntityFamily(family.id, { name, description, note: "edited in React Library" }));
  };

  const uploadCover = async (family: EntityFamily) => {
    const input = document.createElement("input"); input.type = "file"; input.accept = "image/*";
    input.onchange = () => { const file = input.files?.[0]; if (!file) return; const reader = new FileReader(); reader.onload = async () => { await studioApi.createMedia({ resource_type: "entity_family", resource_id: family.id, filename: file.name, data_url: String(reader.result), kind: "reference", caption: family.name, is_cover: true }); const result = await studioApi.media({ coverOnly: true }); setMedia(result.items || []); }; reader.readAsDataURL(file); };
    input.click();
  };

  const compareBranches = async () => {
    const world = (bible?.worlds || []).find((item) => item.id === worldId); const other = world?.branches?.find((item) => item.id !== branchId);
    if (!other) return setNotice("Create another branch before comparing.");
    onSelect({ kind: "analysis", title: "Branch comparison", data: await studioApi.compareBranches(branchId, other.id) });
  };
  const compareWorlds = async () => {
    const other = (bible?.worlds || []).find((item) => item.id !== worldId);
    if (!other) return setNotice("Create another world before comparing.");
    onSelect({ kind: "analysis", title: "World comparison", data: await studioApi.compareWorlds(worldId, other.id) });
  };

  return (
    <div className="library-layout">
      <aside className="library-rail">
        <div className="pane-heading"><div><span className="eyebrow">Library</span><h2>Organize</h2></div><button className="icon-control" onClick={() => setNotice("Use Quick create to add a new Library entry.")}><Sparkles size={13} /></button></div>
        <button className="library-rail-root active" onClick={() => { setTab("all"); setQuery(""); }}>◇ All entries</button>
        <RailGroup title="Folders" items={(bible?.folder_tree || bible?.folders || []).map((item) => String(item.name || "Folder"))} empty="No Library folders yet." onAdd={async () => { const name = window.prompt("Folder name"); if (name) { await studioApi.createFolder({ project_id: projectId, name, world_id: worldId || null, branch_id: branchId || null, kind: "world_bible" }); await onChanged(); } }} />
        <RailGroup title="Collections" items={(bible?.collections || []).map((item) => String(item.name || item.title || "Collection"))} empty="No collections yet." onAdd={async () => { const name = window.prompt("Collection name"); if (name) { await studioApi.createCollection({ name, scope_type: "world_bible", scope_id: worldId }); await onChanged(); } }} />
        <RailGroup title="Saved views" items={(bible?.saved_views || []).map((item) => String(item.name || item.title || "Saved view"))} empty="No saved views yet." onAdd={async () => { const name = window.prompt("Saved view name"); if (name) { await studioApi.createSavedView({ name, scope_type: "world_bible", scope_id: worldId, resource_type: tab, query: { text: query, tab, layout } }); await onChanged(); } }} />
      </aside>
      <section className="library-main">
        <div className="library-header">
          <div><span className="eyebrow">Shared knowledge</span><h1>Library</h1><p>Navigation and AI context stay separate. Opening a sheet does not silently inject it into generation.</p></div>
          <div className="library-actions"><button className="secondary-action" onClick={async () => onSelect({ kind: "analysis", title: "Continuity report", data: await studioApi.continuity(projectId, worldId, branchId) })}><WandSparkles size={14} />Continuity</button><button className="secondary-action" onClick={() => runLibraryAction("Snapshot", () => studioApi.snapshot({ project_id: projectId, world_id: worldId, branch_id: branchId }))}><Camera size={14} />Snapshot</button>{tab === "worlds" && <><button className="secondary-action" onClick={() => void compareBranches()}><GitCompare size={14} />Branches</button><button className="secondary-action" onClick={() => void compareWorlds()}><GitCompare size={14} />Worlds</button></>}<button className="primary-action" onClick={() => void createForTab()}><Plus size={14} />New</button></div>
        </div>

        <div className="library-toolbar">
          <div className="library-tabs">
            {["all", "character", "location", "item", "organization", "lore", "relationships", "canon", "timeline", "worlds"].map((value) => <button key={value} className={tab === value ? "active" : ""} onClick={() => setTab(value)}>{value === "worlds" ? "worlds & branches" : value}</button>)}
          </div>
          <div className="library-tools"><label className="library-search"><Search size={13} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search Library" /></label><div className="view-toggle"><button className={layout === "list" ? "active" : ""} onClick={() => setLayout("list")} title="List view"><List size={14} /></button><button className={layout === "grid" ? "active" : ""} onClick={() => setLayout("grid")} title="Grid view"><Grid2X2 size={14} /></button><button className={layout === "gallery" ? "active" : ""} onClick={() => setLayout("gallery")} title="Gallery view"><Image size={14} /></button></div></div>
        </div>

        {notice && <div className="library-notice">{notice}</div>}
        {selected.length > 0 && <div className="bulk-bar"><strong>{selected.length} selected</strong><button disabled={busy} onClick={async () => { const folderId = window.prompt("Destination folder ID (empty for root)", ""); if (folderId !== null) await runLibraryAction("Moved", () => Promise.all(selected.map((id) => studioApi.updateEntityFamily(id, { folder_id: folderId || null, note: "bulk move" })))); }}>Move</button><button disabled={busy} onClick={async () => { const collectionId = window.prompt("Collection ID"); if (collectionId) await runLibraryAction("Added to collection", () => Promise.all(selected.map((id) => studioApi.linkCollection(collectionId, { resource_type: "entity_family", resource_id: id })))); }}>Collection</button>{selected.length === 2 && <button onClick={async () => { const payload = { source_family_id: selected[0], target_family_id: selected[1] }; const preview = await studioApi.mergeEntityPreview(payload); onSelect({ kind: "analysis", title: "Entity merge preview", data: preview }); if (window.confirm("Apply this merge?")) { await studioApi.mergeEntity(payload); setSelected([]); await onChanged(); } }}>Merge</button>}<button disabled={busy} onClick={() => runLibraryAction("Archived", () => Promise.all(selected.map((id) => studioApi.lifecycle("archive", "entity_family", id))))}><Archive size={13} />Archive</button><button className="danger" disabled={busy} onClick={() => runLibraryAction("Moved to Trash", () => Promise.all(selected.map((id) => studioApi.trash("entity_family", id))))}><Trash2 size={13} />Trash</button><button onClick={() => setSelected([])}>Clear</button></div>}

        {tab === "relationships" ? (
          <div className="relation-list">
            {relationships.map((relationship) => (
              <button key={relationship.id} onClick={() => inspectRelationship(relationship)} onDoubleClick={async () => { const relation_type = window.prompt("Relationship type", relationship.relation_type || "related_to"); if (relation_type) await runLibraryAction("Relationship updated", () => studioApi.updateRelationship(relationship.id, { relation_type, note: "edited in React Library" })); }}>
                <span className="relation-glyph"><Waypoints size={15} /></span>
                <span><strong>{relationship.subject_name || "Entity"} <em>→</em> {relationship.object_name || "Entity"}</strong><small>{relationship.relation_type || "relationship"}</small></span>
                <GitBranch size={13} />
              </button>
            ))}
            {!relationships.length && <div className="center-empty"><Waypoints size={26} /><h2>No relationships yet</h2></div>}
          </div>
        ) : tab === "canon" ? (
          <div className="fact-list">{facts.map((fact) => <article key={String(fact.id)} onClick={() => onSelect({ kind: "analysis", id: String(fact.id), title: String(fact.path || "Canon fact"), data: fact })}><code>{String(fact.path || "fact")}</code><strong>{typeof fact.value === "string" ? fact.value : JSON.stringify(fact.value)}</strong><button onClick={async (event) => { event.stopPropagation(); const newValue = window.prompt("New value", typeof fact.value === "string" ? fact.value : JSON.stringify(fact.value)); if (newValue === null) return; const payload = { project_id: projectId, world_id: worldId, branch_id: branchId || null, owner_type: String(fact.owner_type), owner_id: String(fact.owner_id), path: String(fact.path), new_value: newValue, note: "retcon from React Library" }; onSelect({ kind: "analysis", title: "Retcon impact", data: await studioApi.retconPreview(payload) }); }}><Pencil size={12} />Retcon</button></article>)}{!facts.length && <div className="center-empty grid-empty"><Boxes size={26} /><h2>No canon facts</h2></div>}</div>
        ) : tab === "timeline" ? (
          <div className="timeline-list">{timeline.map((event, index) => <article key={String(event.id || index)}><span>{String(event.time_label || `Event ${index + 1}`)}</span><strong>{String(event.summary || event.title || "Untitled event")}</strong><small>{String(event.event_type || "event")}</small></article>)}{!timeline.length && <div className="center-empty grid-empty"><Waypoints size={26} /><h2>No timeline events</h2><p>Timeline events will appear here for the active world and branch.</p></div>}</div>
        ) : tab === "worlds" ? (
          <div className="world-branch-list">{(bible?.worlds || []).map((world) => <article key={world.id}><div><strong>{world.name}</strong><p>{world.description || "No description"}</p><div className="inline-mini-actions">{world.branches?.map((branch) => <button key={branch.id} onClick={() => onSelect({ kind: "world", id: world.id, title: `${world.name} · ${branch.name}`, data: { world, branch } })}>{branch.name}</button>)}</div></div><span>{world.branches?.length || 0} branches</span>{world.id === worldId && <button onClick={async () => { const name = window.prompt("Sandbox name", "What-if"); if (name) await runLibraryAction("Sandbox created", () => studioApi.createSandbox(world.id, name)); }}>Sandbox</button>}</article>)}<section className="snapshot-strip"><h3>Snapshots</h3>{snapshots.map((snapshot) => <article key={String(snapshot.id)}><span>{String(snapshot.name || snapshot.created_at)}</span><button onClick={async () => { await studioApi.restoreSnapshot(String(snapshot.id)); await onChanged(); }}>Restore</button><button onClick={async () => { await studioApi.deleteSnapshot(String(snapshot.id)); setSnapshots((items) => items.filter((item) => item.id !== snapshot.id)); }}><Trash2 size={12} /></button></article>)}</section></div>
        ) : (
          <div className={`entity-grid view-${layout}`}>
            {filteredFamilies.map((family) => {
              const variant = variantFor(family);
              const cover = coverFor(family);
              return (
                <button key={family.id} className={selected.includes(family.id) ? "selected" : ""} onClick={() => inspectEntity(family)} onDoubleClick={() => void editFamily(family)} onContextMenu={(event) => { event.preventDefault(); toggleSelected(family.id); }} title="Open · double-click to edit · right-click to select">
                  {layout === "gallery" && cover?.content_url ? <img className="entity-cover" src={cover.content_url} alt={cover.caption || family.name} /> : null}
                  <span className="entity-select" onClick={(event) => { event.stopPropagation(); toggleSelected(family.id); }}>{selected.includes(family.id) ? <Check size={12} /> : ""}</span>
                  <span className={`entity-type-mark ${family.entity_type || "entity"}`}><Boxes size={16} /></span>
                  <span className="entity-kind">{family.entity_type || "entity"}</span>
                  <strong>{variant?.display_name || family.name}</strong>
                  <p>{variant?.summary || family.description || "Shared Library sheet"}</p>
                  <div><small>{variant?.canon_status || "shared"}</small><em onClick={(event) => { event.stopPropagation(); void uploadCover(family); }}>{cover ? "replace cover" : "add cover"}</em></div>
                </button>
              );
            })}
            {!filteredFamilies.length && <div className="center-empty grid-empty"><Boxes size={26} /><h2>No matching sheets</h2><p>Create naturally and let Arline infer the underlying type.</p></div>}
          </div>
        )}
      </section>

      {quickOpen && (
        <div className="modal-backdrop" onMouseDown={() => setQuickOpen(false)}>
          <div className="modal quick-modal" onMouseDown={(event) => event.stopPropagation()}>
            <span className="eyebrow">Quick create</span><h2>Describe what you want</h2><p>Arline will infer whether this becomes a sheet, world, project file, or another supported resource.</p>
            <textarea autoFocus value={quickText} onChange={(event) => { setQuickText(event.target.value); setPreview(null); }} placeholder="Apartment on the third floor, unit A0325…" />
            <label><span>Force kind</span><select value={quickKind} onChange={(event) => setQuickKind(event.target.value)}><option value="">Auto detect</option><option value="entity">Entity</option><option value="document">Document</option><option value="project">Project</option><option value="world">World</option>{entityTypes.map((value) => <option key={value} value={`entity:${value}`}>Entity · {value}</option>)}</select></label>
            {preview ? <div className="quick-preview"><span>{String(preview.kind || "resource")}</span><strong>{String(preview.name || quickText)}</strong><pre>{JSON.stringify(preview, null, 2)}</pre></div> : null}
            <div className="modal-actions"><button onClick={() => setQuickOpen(false)}>Cancel</button><button onClick={() => void previewQuickCreate()} disabled={busy || !quickText.trim()}>Preview</button><button className="primary-action small" onClick={() => void createQuick()} disabled={busy || !quickText.trim()}>{busy ? "Working…" : "Create"}</button></div>
          </div>
        </div>
      )}
    </div>
  );
}

function RailGroup({ title, items, empty, onAdd }: { title: string; items: string[]; empty: string; onAdd: () => Promise<void> | void }) {
  return <section className="library-rail-group"><div className="library-rail-title"><span>{title}</span><button title={`Add ${title.toLowerCase()}`} onClick={() => void onAdd()}>＋</button></div>{items.length ? items.slice(0, 8).map((item) => <button key={item} className="library-rail-item">{item}</button>) : <p>{empty}</p>}</section>;
}
