import { useEffect, useMemo, useState } from "react";
import { Archive, Boxes, Camera, Check, GitBranch, Grid2X2, Image, List, Search, Sparkles, Waypoints, WandSparkles } from "lucide-react";
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

  const families = bible?.families || [];
  const variants = bible?.variants || [];
  const relationships = bible?.relationships || [];

  useEffect(() => {
    if (!worldId) return;
    void Promise.all([
      studioApi.media({ coverOnly: true }).catch(() => ({ items: [] })),
      studioApi.timeline(worldId, branchId).catch(() => ({ items: [] })),
    ]).then(([mediaResult, timelineResult]) => { setMedia(mediaResult.items || []); setTimeline(timelineResult.items || []); });
  }, [worldId, branchId]);

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

  return (
    <div className="library-layout">
      <aside className="library-rail">
        <div className="pane-heading"><div><span className="eyebrow">Library</span><h2>Organize</h2></div><button className="icon-control" onClick={() => setNotice("Use Quick create to add a new Library entry.")}><Sparkles size={13} /></button></div>
        <button className="library-rail-root active" onClick={() => { setTab("all"); setQuery(""); }}>◇ All entries</button>
        <RailGroup title="Folders" items={(bible?.folder_tree || bible?.folders || []).map((item) => String(item.name || "Folder"))} empty="No Library folders yet." />
        <RailGroup title="Collections" items={(bible?.collections || []).map((item) => String(item.name || item.title || "Collection"))} empty="No collections yet." />
        <RailGroup title="Saved views" items={(bible?.saved_views || []).map((item) => String(item.name || item.title || "Saved view"))} empty="No saved views yet." />
      </aside>
      <section className="library-main">
        <div className="library-header">
          <div><span className="eyebrow">Shared knowledge</span><h1>Library</h1><p>Navigation and AI context stay separate. Opening a sheet does not silently inject it into generation.</p></div>
          <div className="library-actions"><button className="secondary-action" onClick={() => runLibraryAction("Continuity check", () => studioApi.continuity({ project_id: projectId, world_id: worldId, branch_id: branchId }))}><WandSparkles size={14} />Continuity</button><button className="secondary-action" onClick={() => runLibraryAction("Snapshot", () => studioApi.snapshot({ project_id: projectId, world_id: worldId, branch_id: branchId }))}><Camera size={14} />Snapshot</button><button className="primary-action" onClick={() => setQuickOpen(true)}><Sparkles size={14} />Quick create</button></div>
        </div>

        <div className="library-toolbar">
          <div className="library-tabs">
            {["all", "character", "location", "item", "organization", "lore", "relationships", "canon", "timeline", "worlds"].map((value) => <button key={value} className={tab === value ? "active" : ""} onClick={() => setTab(value)}>{value === "worlds" ? "worlds & branches" : value}</button>)}
          </div>
          <div className="library-tools"><label className="library-search"><Search size={13} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search Library" /></label><div className="view-toggle"><button className={layout === "list" ? "active" : ""} onClick={() => setLayout("list")} title="List view"><List size={14} /></button><button className={layout === "grid" ? "active" : ""} onClick={() => setLayout("grid")} title="Grid view"><Grid2X2 size={14} /></button><button className={layout === "gallery" ? "active" : ""} onClick={() => setLayout("gallery")} title="Gallery view"><Image size={14} /></button></div></div>
        </div>

        {notice && <div className="library-notice">{notice}</div>}
        {selected.length > 0 && <div className="bulk-bar"><strong>{selected.length} selected</strong><button disabled={busy} onClick={() => runLibraryAction("Archived", () => Promise.all(selected.map((id) => studioApi.lifecycle("archive", "entity_family", id))))}><Archive size={13} />Archive</button><button onClick={() => setSelected([])}>Clear</button></div>}

        {tab === "relationships" ? (
          <div className="relation-list">
            {relationships.map((relationship) => (
              <button key={relationship.id} onClick={() => inspectRelationship(relationship)}>
                <span className="relation-glyph"><Waypoints size={15} /></span>
                <span><strong>{relationship.subject_name || "Entity"} <em>→</em> {relationship.object_name || "Entity"}</strong><small>{relationship.relation_type || "relationship"}</small></span>
                <GitBranch size={13} />
              </button>
            ))}
            {!relationships.length && <div className="center-empty"><Waypoints size={26} /><h2>No relationships yet</h2></div>}
          </div>
        ) : tab === "timeline" ? (
          <div className="timeline-list">{timeline.map((event, index) => <article key={String(event.id || index)}><span>{String(event.time_label || `Event ${index + 1}`)}</span><strong>{String(event.summary || event.title || "Untitled event")}</strong><small>{String(event.event_type || "event")}</small></article>)}{!timeline.length && <div className="center-empty grid-empty"><Waypoints size={26} /><h2>No timeline events</h2><p>Timeline events will appear here for the active world and branch.</p></div>}</div>
        ) : tab === "worlds" ? (
          <div className="world-branch-list">{(bible?.worlds || []).map((world) => <article key={world.id}><div><strong>{world.name}</strong><p>{world.description || "No description"}</p></div><span>{world.branches?.length || 0} branches</span></article>)}</div>
        ) : (
          <div className={`entity-grid view-${layout}`}>
            {filteredFamilies.map((family) => {
              const variant = variantFor(family);
              const cover = coverFor(family);
              return (
                <button key={family.id} className={selected.includes(family.id) ? "selected" : ""} onClick={() => inspectEntity(family)} onContextMenu={(event) => { event.preventDefault(); toggleSelected(family.id); }}>
                  {layout === "gallery" && cover?.content_url ? <img className="entity-cover" src={cover.content_url} alt={cover.caption || family.name} /> : null}
                  <span className="entity-select" onClick={(event) => { event.stopPropagation(); toggleSelected(family.id); }}>{selected.includes(family.id) ? <Check size={12} /> : ""}</span>
                  <span className={`entity-type-mark ${family.entity_type || "entity"}`}><Boxes size={16} /></span>
                  <span className="entity-kind">{family.entity_type || "entity"}</span>
                  <strong>{variant?.display_name || family.name}</strong>
                  <p>{variant?.summary || family.description || "Shared Library sheet"}</p>
                  <div><small>{variant?.canon_status || "shared"}</small><em>{variant ? "world variant" : "base sheet"}</em></div>
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

function RailGroup({ title, items, empty }: { title: string; items: string[]; empty: string }) {
  return <section className="library-rail-group"><div className="library-rail-title"><span>{title}</span><button title={`Add ${title.toLowerCase()}`}>＋</button></div>{items.length ? items.slice(0, 8).map((item) => <button key={item} className="library-rail-item">{item}</button>) : <p>{empty}</p>}</section>;
}
