import { useEffect, useState, type KeyboardEvent } from "react";
import { Braces, Copy, ImagePlus, Link2, Pin, Plus, Trash2, X } from "lucide-react";
import { renameSheet, studioApi } from "../api";
import { PageHeader, type Crumb } from "../components/PageHeader";
import { SheetRelations } from "./SheetRelations";
import type { EntityFamily, JsonMap, MediaItem, Selection, WorldBible } from "../types";

interface EntityPageProps {
  familyId: string;
  bible: WorldBible | null;
  projectId: string;
  worldId: string;
  branchId: string;
  crumbs: Crumb[];
  onOpenEntity: (id: string) => void;
  onInspect: (selection: Selection) => void;
  onChanged: () => Promise<void> | void;
  onTrash: () => void;
  onDuplicate: () => void;
}

/** A Library sheet as a full page: cover, editable title and summary, properties, relations. */
export function EntityPage({ familyId, bible, projectId, worldId, branchId, crumbs, onOpenEntity, onInspect, onChanged, onTrash, onDuplicate }: EntityPageProps) {
  const family = (bible?.families || []).find((item) => item.id === familyId);
  const variant = (bible?.variants || []).find((item) => item.family_id === familyId && (!worldId || item.world_id === worldId))
    || (bible?.variants || []).find((item) => item.family_id === familyId);
  const [name, setName] = useState("");
  const [summary, setSummary] = useState("");
  const [description, setDescription] = useState("");
  const [cover, setCover] = useState<MediaItem | null>(null);
  const [notice, setNotice] = useState("");
  const [backlinks, setBacklinks] = useState<JsonMap | null>(null);

  useEffect(() => {
    setName(family?.name || "");
    setDescription(family?.description || "");
    setSummary(variant?.summary || "");
    setBacklinks(null);
    setNotice("");
  }, [familyId, family?.name, family?.description, variant?.summary]);

  useEffect(() => {
    setCover(null);
    void studioApi.media({ resourceType: "entity_family", resourceId: familyId })
      .then((result) => setCover((result.items || []).find((item) => item.is_cover) || (result.items || [])[0] || null))
      .catch(() => setCover(null));
  }, [familyId]);

  if (!family) {
    return <div className="notion-page"><PageHeader crumbs={crumbs} /><div className="center-empty"><h2>Sheet not found</h2><p>It may have been moved to Trash or belong to another project.</p></div></div>;
  }

  const save = async (label: string, action: () => Promise<unknown>) => {
    try { await action(); setNotice(`${label} saved`); await onChanged(); }
    catch (error) { setNotice((error as Error).message); }
  };
  const saveFamily = (patch: Partial<EntityFamily>) => {
    const changed = Object.entries(patch).some(([key, value]) => (family as JsonMap)[key] !== value);
    if (changed) void save("Sheet", () => studioApi.updateEntityFamily(family.id, patch));
  };
  // Save from the field's own value: state may lag the final keystroke at blur time.
  const saveSummary = (value: string) => {
    if (variant && value !== (variant.summary || "")) void save("Summary", () => studioApi.updateVariant(variant.id, { summary: value }));
  };
  const uploadCover = () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.onchange = () => {
      const file = input.files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = async () => {
        await studioApi.createMedia({ resource_type: "entity_family", resource_id: family.id, filename: file.name, data_url: String(reader.result), kind: "reference", caption: family.name, is_cover: true });
        const result = await studioApi.media({ resourceType: "entity_family", resourceId: family.id });
        setCover((result.items || []).find((item) => item.is_cover) || null);
      };
      reader.readAsDataURL(file);
    };
    input.click();
  };

  // Fixed facts and nested data stay read-only; flat attributes are edited in place.
  const readOnly: Array<[string, string]> = [
    ["Type", family.entity_type || "entity"],
    ["World", (bible?.worlds || []).find((world) => world.id === variant?.world_id)?.name || "All worlds"],
    ...flatten(variant?.current_state, "Now: "),
    ...flatten(family.shared_core),
  ];
  const attributes = (variant?.attributes || {}) as JsonMap;
  const status = String(variant?.canon_status || "draft");
  const saveAttributes = (next: JsonMap) => {
    if (variant) void save("Properties", () => studioApi.updateVariant(variant.id, { attributes: next }));
  };
  const setAttribute = (key: string, raw: string) => {
    const previous = attributes[key];
    if (raw === String(previous ?? "")) return;
    const value = typeof previous === "number" && raw.trim() !== "" && Number.isFinite(Number(raw)) ? Number(raw) : raw;
    saveAttributes({ ...attributes, [key]: value });
  };
  const removeAttribute = (key: string) => {
    const next = { ...attributes };
    delete next[key];
    saveAttributes(next);
  };

  return (
    <div className="notion-page">
      <PageHeader crumbs={crumbs} actions={<>
        <button className="page-action" onClick={() => void save("Context pin", () => studioApi.pinContext({ project_id: projectId, world_id: worldId || null, branch_id: branchId || null, resource_type: "entity_family", resource_id: family.id, scope: "world", priority: 1 }))}><Pin size={14} />Add to chat context</button>
        <button className="page-action" onClick={async () => setBacklinks(await studioApi.backlinks("entity_family", family.id))}><Link2 size={14} />Where used</button>
        <button className="page-action" title="Raw data" onClick={() => onInspect({ kind: "entity", id: family.id, title: family.name, subtitle: family.entity_type, data: { family, variant } })}><Braces size={14} /></button>
        <button className="page-action" title="Duplicate" aria-label="Duplicate" onClick={onDuplicate}><Copy size={14} /></button>
        <button className="page-action danger" title="Move to Trash" aria-label="Move to Trash" onClick={onTrash}><Trash2 size={14} /></button>
      </>} />
      <div className="notion-page-scroll">
        {cover?.content_url ? <div className="page-cover"><img src={String(cover.content_url)} alt={String(cover.caption || family.name)} /></div> : null}
        <article className="page-body">
          {!cover?.content_url && <button className="page-ghost-action" onClick={uploadCover}><ImagePlus size={14} />Add cover</button>}
          <input className="page-title" aria-label="Sheet name" value={name} placeholder="Untitled" onChange={(event) => setName(event.target.value)} onBlur={(event) => { const next = event.currentTarget.value.trim(); if (next && next !== family.name) void save("Name", () => renameSheet(family.id, family.name, next, bible?.variants || [])); }} />
          <dl className="page-properties">
            {readOnly.slice(0, 1).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
            <div><dt>Canon status</dt><dd>
              <select className="page-prop-input" aria-label="Canon status" value={status} disabled={!variant} onChange={(event) => variant && void save("Status", () => studioApi.updateVariant(variant.id, { canon_status: event.target.value }))}>
                {Array.from(new Set(["draft", "canon", "what_if", status])).map((option) => <option key={option} value={option}>{option.replace("_", "-")}</option>)}
              </select>
            </dd></div>
            {readOnly.slice(1, 2).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
            {Object.entries(attributes).map(([key, value]) => (
              <div key={key} className="page-prop-row"><dt>{key.replace(/[_.]+/g, " ")}</dt><dd>
                {value !== null && typeof value === "object"
                  ? <span className="page-prop-static">{JSON.stringify(value)}</span>
                  : <input key={`${variant?.id}:${key}:${String(value)}`} className="page-prop-input" aria-label={key} defaultValue={String(value ?? "")} placeholder="Empty" onBlur={(event) => setAttribute(key, event.currentTarget.value)} onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); }} />}
                <button className="page-prop-remove" aria-label={`Remove ${key}`} title="Remove property" onClick={() => removeAttribute(key)}><X size={13} /></button>
              </dd></div>
            ))}
            {readOnly.slice(2).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
          </dl>
          {variant && <AddProperty existing={Object.keys(attributes)} onAdd={(key, value) => saveAttributes({ ...attributes, [key]: value })} />}
          <section className="page-block">
            <h2>Summary</h2>
            <textarea className="page-text" value={summary} placeholder={variant ? "Who or what is this, in this world?" : "No world variant yet"} disabled={!variant} onChange={(event) => setSummary(event.target.value)} onBlur={(event) => saveSummary(event.currentTarget.value)} rows={3} />
          </section>
          <section className="page-block">
            <h2>Description</h2>
            <textarea className="page-text" value={description} placeholder="Shared notes that apply in every world" onChange={(event) => setDescription(event.target.value)} onBlur={(event) => saveFamily({ description: event.currentTarget.value })} rows={4} />
          </section>
          <SheetRelations family={family} bible={bible} worldId={worldId} branchId={branchId} onOpenEntity={onOpenEntity} onChanged={onChanged} onNotice={setNotice} />
          {backlinks && <section className="page-block"><h2>Where used</h2>{usages(backlinks).length ? <ul className="page-links">{usages(backlinks).map((text, index) => <li key={index}><span>{text}</span></li>)}</ul> : <p className="page-muted">Not used anywhere yet.</p>}</section>}
          {notice && <p className="page-notice" role="status">{notice}</p>}
        </article>
      </div>
    </div>
  );
}

/** "+ Add property": a name and value pair; Enter in either field saves. */
function AddProperty({ existing, onAdd }: { existing: string[]; onAdd: (key: string, value: string) => void }) {
  const [open, setOpen] = useState(false);
  const [key, setKey] = useState("");
  const [value, setValue] = useState("");
  const clean = key.trim().toLowerCase().replace(/\s+/g, "_");
  const submit = () => {
    if (!clean) return;
    if (existing.includes(clean)) { setKey(""); return; }
    onAdd(clean, value.trim());
    setKey(""); setValue(""); setOpen(false);
  };
  if (!open) return <button className="page-ghost-action page-add-prop" onClick={() => setOpen(true)}><Plus size={14} />Add property</button>;
  const keys = (event: KeyboardEvent) => { if (event.key === "Enter") submit(); if (event.key === "Escape") setOpen(false); };
  return (
    <div className="page-add-prop-form">
      <input autoFocus className="page-prop-input" placeholder="Property (e.g. age)" aria-label="New property name" value={key} onChange={(event) => setKey(event.target.value)} onKeyDown={keys} />
      <input className="page-prop-input" placeholder="Value" aria-label="New property value" value={value} onChange={(event) => setValue(event.target.value)} onKeyDown={keys} />
      <button className="page-action" onClick={submit} disabled={!clean}>Add</button>
      <button className="page-action" onClick={() => setOpen(false)}>Cancel</button>
      {clean && existing.includes(clean) && <small className="page-muted">That property already exists.</small>}
    </div>
  );
}

/** Backlink rows come from several tables; describe each by the columns it carries. */
function usages(result: JsonMap): string[] {
  return ((result.links || []) as JsonMap[]).map((link) =>
    link.scene_document_id ? `Scene requirement (${String(link.requirement_type || "needed")})`
      : link.tag_id ? "Tagged"
      : "label" in link ? `Pinned to chat context${link.label ? `: ${String(link.label)}` : ""}`
      : link.relation_type ? `Relationship: ${String(link.relation_type)}`
      : "Reference");
}

function flatten(value: unknown, prefix = ""): Array<[string, string]> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return [];
  return Object.entries(value as JsonMap)
    .filter(([, item]) => item !== null && item !== undefined && item !== "")
    .slice(0, 12)
    .map(([key, item]) => [prefix + key.replace(/[_.]+/g, " "), typeof item === "object" ? JSON.stringify(item) : String(item)]);
}
