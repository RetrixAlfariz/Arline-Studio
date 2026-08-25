import { useMemo, useState } from "react";
import { Boxes, GitBranch, Search, Sparkles, Waypoints } from "lucide-react";
import { studioApi } from "../api";
import type { EntityFamily, EntityVariant, Relationship, Selection, WorldBible } from "../types";

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

  const families = bible?.families || [];
  const variants = bible?.variants || [];
  const relationships = bible?.relationships || [];

  const filteredFamilies = useMemo(() => families.filter((family) => {
    if (tab !== "all" && tab !== "relationships" && family.entity_type !== tab) return false;
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

  return (
    <div className="library-layout">
      <section className="library-main">
        <div className="library-header">
          <div><span className="eyebrow">Shared knowledge</span><h1>Library</h1><p>Navigation and AI context stay separate. Opening a sheet does not silently inject it into generation.</p></div>
          <button className="primary-action" onClick={() => setQuickOpen(true)}><Sparkles size={14} />Quick create</button>
        </div>

        <div className="library-toolbar">
          <div className="library-tabs">
            {["all", "character", "location", "item", "organization", "lore", "relationships"].map((value) => <button key={value} className={tab === value ? "active" : ""} onClick={() => setTab(value)}>{value}</button>)}
          </div>
          <label className="library-search"><Search size={13} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search Library" /></label>
        </div>

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
        ) : (
          <div className="entity-grid">
            {filteredFamilies.map((family) => {
              const variant = variantFor(family);
              return (
                <button key={family.id} onClick={() => inspectEntity(family)}>
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
