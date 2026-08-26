import { useEffect, useMemo, useRef, useState } from "react";
import { FilePlus2, FileText, Focus, History, LayoutGrid, Link2, ListTree, Rows3, Save, Target, Trash2 } from "lucide-react";
import { studioApi } from "../api";
import { browserStorage } from "../browserStorage";
import type { DocumentItem, FolderNode, JsonMap } from "../types";

interface ManuscriptViewProps {
  projectId: string;
  worldId: string;
  branchId: string;
  documents: DocumentItem[];
  folders: FolderNode[];
  initialDocumentId?: string;
  documentTypes: string[];
  onDocumentsChanged: () => Promise<void> | void;
  onInspect: (title: string, data: unknown) => void;
}

type ManuscriptMode = "editor" | "corkboard" | "outliner";

export function ManuscriptView({ projectId, worldId, branchId, documents, folders, initialDocumentId, documentTypes, onDocumentsChanged, onInspect }: ManuscriptViewProps) {
  const [selectedId, setSelectedId] = useState(initialDocumentId || documents[0]?.id || "");
  const [doc, setDoc] = useState<DocumentItem | null>(null);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [status, setStatus] = useState("planned");
  const [filter, setFilter] = useState("all");
  const [saving, setSaving] = useState(false);
  const [saveLabel, setSaveLabel] = useState("No document selected");
  const [creating, setCreating] = useState(false);
  const [newTitle, setNewTitle] = useState("");
  const [newType, setNewType] = useState("scene");
  const [revisions, setRevisions] = useState<JsonMap[]>([]);
  const [dependencies, setDependencies] = useState<JsonMap[]>([]);
  const [focusMode, setFocusMode] = useState(false);
  const [mode, setMode] = useState<ManuscriptMode>(() => (browserStorage.get("arline:manuscript:mode") as ManuscriptMode) || "editor");
  const [sceneCards, setSceneCards] = useState<JsonMap[]>([]);
  const [draggedId, setDraggedId] = useState("");
  const recoveryTimer = useRef<number | null>(null);

  useEffect(() => {
    if (initialDocumentId) setSelectedId(initialDocumentId);
  }, [initialDocumentId]);

  useEffect(() => {
    if (!selectedId && documents[0]) setSelectedId(documents[0].id);
  }, [documents, selectedId]);

  useEffect(() => {
    if (!projectId) return;
    void studioApi.sceneCards(projectId).then((result) => setSceneCards(result.scene_cards || [])).catch(() => setSceneCards([]));
  }, [projectId, documents]);

  useEffect(() => {
    if (!selectedId) {
      setDoc(null);
      return;
    }
    void Promise.all([studioApi.document(selectedId), studioApi.revisions("document", selectedId).catch(() => ({ revisions: [] })), studioApi.sceneDependencies(selectedId).catch(() => ({ dependencies: [] }))]).then(([loaded, revisionResult, dependencyResult]) => {
      const recovery = browserStorage.get(`arline:react:draft:${loaded.id}`);
      setDoc(loaded);
      setTitle(loaded.title || "Untitled");
      setContent(recovery ?? loaded.content ?? "");
      setStatus(loaded.status || "planned");
      setSaveLabel(recovery ? "Recovered local draft" : "Loaded");
      setRevisions(revisionResult.revisions || []);
      setDependencies(dependencyResult.dependencies || []);
    }).catch((error: Error) => setSaveLabel(error.message));
  }, [selectedId]);

  useEffect(() => {
    if (!doc) return;
    if (recoveryTimer.current) window.clearTimeout(recoveryTimer.current);
    recoveryTimer.current = window.setTimeout(() => {
      browserStorage.set(`arline:react:draft:${doc.id}`, content);
      setSaveLabel("Local recovery saved");
    }, 650);
    return () => {
      if (recoveryTimer.current) window.clearTimeout(recoveryTimer.current);
    };
  }, [content, title, status, doc]);

  const filtered = useMemo(() => {
    if (filter === "all") return documents;
    return documents.filter((item) => item.document_type === filter);
  }, [documents, filter]);

  const cardByDocument = useMemo(() => new Map(sceneCards.map((card) => [String(card.document_id), card])), [sceneCards]);
  const planningDocuments = useMemo(() => filtered.filter((item) => item.document_type === "scene").sort((a, b) => {
    const aOrder = Number(cardByDocument.get(a.id)?.sort_order ?? a.sort_order ?? 0);
    const bOrder = Number(cardByDocument.get(b.id)?.sort_order ?? b.sort_order ?? 0);
    return aOrder - bOrder || a.title.localeCompare(b.title);
  }), [filtered, cardByDocument]);

  const changeMode = (next: ManuscriptMode) => { browserStorage.set("arline:manuscript:mode", next); setMode(next); };

  const reorderScene = async (targetId: string) => {
    if (!draggedId || draggedId === targetId) return;
    const reordered = [...planningDocuments];
    const from = reordered.findIndex((item) => item.id === draggedId);
    const to = reordered.findIndex((item) => item.id === targetId);
    if (from < 0 || to < 0) return;
    const [moved] = reordered.splice(from, 1); reordered.splice(to, 0, moved);
    const updated = await Promise.all(reordered.map((item, index) => studioApi.saveSceneCard(projectId, item.id, sceneCardPayload(cardByDocument.get(item.id), item, worldId, branchId, index * 100))));
    setSceneCards(updated);
    setDraggedId("");
  };

  const save = async () => {
    if (!doc) return;
    setSaving(true);
    try {
      const updated = await studioApi.updateDocument(doc.id, { title, content, status, note: "react checkpoint" });
      setDoc(updated);
      browserStorage.remove(`arline:react:draft:${doc.id}`);
      setSaveLabel("Checkpoint saved");
      await onDocumentsChanged();
    } catch (error) {
      setSaveLabel((error as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const create = async () => {
    if (!newTitle.trim()) return;
    const created = await studioApi.createDocument({
      project_id: projectId,
      folder_id: null,
      title: newTitle.trim(),
      document_type: newType,
      status: "planned",
      content: "",
    });
    setCreating(false);
    setNewTitle("");
    await onDocumentsChanged();
    setSelectedId(created.id);
  };

  const trash = async () => {
    if (!doc || !window.confirm(`Move “${doc.title}” to Trash?`)) return;
    await studioApi.trash("document", doc.id);
    browserStorage.remove(`arline:react:draft:${doc.id}`);
    setSelectedId("");
    setDoc(null);
    await onDocumentsChanged();
  };

  const wordCount = content.trim() ? content.trim().split(/\s+/).length : 0;

  const setActiveScene = async () => {
    if (!doc) return;
    await studioApi.setActiveScene(projectId, { document_id: doc.id, world_id: worldId || null, branch_id: branchId || null });
    setSaveLabel("Active scene updated");
  };

  const restoreRevision = async (revision: JsonMap) => {
    if (!doc || !window.confirm("Restore this revision as a new checkpoint?")) return;
    await studioApi.restoreRevision(String(revision.id));
    setSelectedId(""); setTimeout(() => setSelectedId(doc.id), 0); await onDocumentsChanged();
  };

  const addDependency = async () => {
    if (!doc) return;
    const targetId = window.prompt("Required target resource ID");
    if (!targetId) return;
    const created = await studioApi.createSceneDependency({ project_id: projectId, scene_document_id: doc.id, requirement_type: "requires", target_type: "document", target_id: targetId, world_id: worldId || null, branch_id: branchId || null, condition: {} });
    setDependencies((items) => [...items, created]);
  };

  return (
    <div className={`manuscript-layout ${focusMode ? "focus-mode" : ""}`}>
      <aside className="manuscript-rail">
        <div className="pane-heading"><div><span className="eyebrow">Manuscript</span><h2>Binder</h2></div><button className="icon-control" onClick={() => setCreating(true)}><FilePlus2 size={15} /></button></div>
        <div className="filter-strip">
          {["all", "scene", "chapter", "note", "research", "outline"].map((value) => <button key={value} className={filter === value ? "active" : ""} onClick={() => setFilter(value)}>{value}</button>)}
        </div>
        <div className="manuscript-mode-switch" aria-label="Manuscript view">
          <button className={mode === "editor" ? "active" : ""} onClick={() => changeMode("editor")}><FileText size={13} /><span>Editor</span></button>
          <button className={mode === "corkboard" ? "active" : ""} onClick={() => changeMode("corkboard")}><LayoutGrid size={13} /><span>Corkboard</span></button>
          <button className={mode === "outliner" ? "active" : ""} onClick={() => changeMode("outliner")}><Rows3 size={13} /><span>Outliner</span></button>
        </div>
        <div className="document-list">
          {filtered.map((item) => (
            <button key={item.id} className={selectedId === item.id ? "active" : ""} onClick={() => setSelectedId(item.id)}>
              <FileText size={14} />
              <span><strong>{item.title}</strong><small>{item.document_type || "document"} · {item.status || "planned"}</small></span>
            </button>
          ))}
          {!filtered.length && <div className="empty-state">Nothing in this binder filter.</div>}
        </div>
      </aside>

      {mode === "editor" ? <section className="editor-pane">
        {doc ? (
          <>
            <div className="editor-toolbar">
              <input className="document-title-input" value={title} onChange={(event) => setTitle(event.target.value)} />
              <div>
                <select value={status} onChange={(event) => setStatus(event.target.value)}><option>planned</option><option>writing</option><option>revising</option><option>final</option></select>
                <select value={doc.folder_id || ""} onChange={async (event) => { const updated = await studioApi.updateDocument(doc.id, { folder_id: event.target.value || null }); setDoc(updated); await onDocumentsChanged(); }} title="Move document"><option value="">No folder</option>{folders.map((folder) => <option key={folder.id} value={folder.id}>{folder.name}</option>)}</select>
                <button onClick={() => onInspect("Document metadata", doc)}>Inspect</button>
                <button onClick={() => void setActiveScene()}><Target size={13} />Set active</button>
                <button onClick={() => setFocusMode((value) => !value)}><Focus size={13} />Focus</button>
                <button className="danger" onClick={() => void trash()}><Trash2 size={13} />Trash</button>
                <button className="primary-action small" disabled={saving} onClick={() => void save()}><Save size={13} />{saving ? "Saving" : "Checkpoint"}</button>
              </div>
            </div>
            <textarea className="manuscript-editor" value={content} onChange={(event) => setContent(event.target.value)} spellCheck placeholder="Write the scene here…" />
            <div className="editor-status"><span>{saveLabel}</span><span>{wordCount.toLocaleString()} words</span></div>
          </>
        ) : (
          <div className="center-empty"><FileText size={28} /><h2>Your manuscript is empty</h2><p>Create a scene, chapter, note, research file, or outline.</p><button className="primary-action" onClick={() => setCreating(true)}><FilePlus2 size={14} />Create first document</button></div>
        )}
      </section> : <section className="planning-pane">
        <header className="planning-header"><div><span className="eyebrow">Scene planning</span><h1>{mode === "corkboard" ? "Corkboard" : "Outliner"}</h1><p>{mode === "corkboard" ? "Arrange scenes spatially. Drag cards to change their planning order." : "Review scene status, perspective, location, length, and continuity at a glance."}</p></div><button className="primary-action small" onClick={() => setCreating(true)}><FilePlus2 size={13} />New scene</button></header>
        {mode === "corkboard" ? <div className="scene-corkboard">
          {planningDocuments.map((item, index) => { const card = cardByDocument.get(item.id); return <article key={item.id} draggable onDragStart={() => setDraggedId(item.id)} onDragOver={(event) => event.preventDefault()} onDrop={() => void reorderScene(item.id)} className={`${selectedId === item.id ? "selected" : ""} ${draggedId === item.id ? "dragging" : ""}`} onClick={() => setSelectedId(item.id)} onDoubleClick={() => { setSelectedId(item.id); changeMode("editor"); }}>
            <div className="scene-card-index"><span>Scene {String(index + 1).padStart(2, "0")}</span><ListTree size={14} /></div><h2>{item.title}</h2><p>{String(card?.target_outcome || excerpt(item.content) || "Add a scene objective in the Inspector.")}</p><div className="scene-card-meta"><span>POV<strong>{String(card?.pov_name || card?.pov_variant_id || "—")}</strong></span><span>Status<strong>{String(card?.status || item.status || "planned")}</strong></span></div><footer><span>{wordCountOf(item.content).toLocaleString()} words</span>{card?.notes ? <em>Context notes</em> : <em>No warnings</em>}</footer>
          </article>; })}
          {!planningDocuments.length && <div className="planning-empty"><LayoutGrid size={28} /><h2>No scenes on the Corkboard</h2><p>Create a scene or switch the Binder filter to All or Scene.</p><button className="primary-action" onClick={() => setCreating(true)}>Create scene</button></div>}
        </div> : <div className="scene-outliner-wrap"><table className="scene-outliner"><thead><tr><th>#</th><th>Scene</th><th>Status</th><th>POV</th><th>Location</th><th>Words</th><th>Continuity</th></tr></thead><tbody>{planningDocuments.map((item, index) => { const card = cardByDocument.get(item.id); return <tr key={item.id} className={selectedId === item.id ? "selected" : ""} onClick={() => setSelectedId(item.id)} onDoubleClick={() => { setSelectedId(item.id); changeMode("editor"); }}><td>{String(index + 1).padStart(2, "0")}</td><td><strong>{item.title}</strong><small>{String(card?.target_outcome || excerpt(item.content) || "No objective yet")}</small></td><td><span className={`status-pill ${String(card?.status || item.status || "planned")}`}>{String(card?.status || item.status || "planned")}</span></td><td>{String(card?.pov_name || card?.pov_variant_id || "—")}</td><td>{String(card?.location_name || card?.location_variant_id || "—")}</td><td>{wordCountOf(item.content).toLocaleString()}</td><td>{card?.notes ? "Review notes" : "Clear"}</td></tr>; })}</tbody></table>{!planningDocuments.length && <div className="planning-empty"><Rows3 size={28} /><h2>No scenes to outline</h2><p>Create a scene or switch the Binder filter.</p></div>}</div>}
      </section>}

      <aside className="manuscript-inspector">
        <div className="pane-heading"><div><span className="eyebrow">Inspector</span><h2>Scene</h2></div></div>
        {doc ? <>
          <Property label="Type" value={doc.document_type || "document"} />
          <Property label="Status" value={status} />
          <Property label="Words" value={String(wordCount)} />
          <Property label="ID" value={doc.id} mono />
          <section className="inspector-note"><strong><History size={12} /> Checkpoints</strong>{revisions.slice(0, 8).map((revision) => <button className="inspector-row-action" key={String(revision.id)} onClick={() => void restoreRevision(revision)}><span>{String(revision.note || revision.created_at || "Revision")}</span><em>Restore</em></button>)}{!revisions.length && <p>No durable revisions yet.</p>}</section>
          <section className="inspector-note"><strong><Link2 size={12} /> Scene dependencies</strong>{dependencies.map((dependency) => <button className="inspector-row-action" key={String(dependency.id)} onClick={async () => { await studioApi.deleteSceneDependency(String(dependency.id)); setDependencies((items) => items.filter((item) => item.id !== dependency.id)); }}><span>{String(dependency.target_id || dependency.requirement_type || "Dependency")}</span><em>Remove</em></button>)}<button className="inspector-add" onClick={() => void addDependency()}>＋ Add dependency</button></section>
          <section className="inspector-note"><strong>Recovery</strong><p>Typing is saved to browser-local recovery state. Checkpoint writes a durable revision through the Python backend.</p></section>
        </> : <div className="empty-state">Select a document to inspect it.</div>}
      </aside>

      {creating && (
        <div className="modal-backdrop" onMouseDown={() => setCreating(false)}>
          <div className="modal" onMouseDown={(event) => event.stopPropagation()}>
            <span className="eyebrow">Project file</span><h2>New manuscript item</h2>
            <label><span>Title</span><input autoFocus value={newTitle} onChange={(event) => setNewTitle(event.target.value)} /></label>
            <label><span>Type</span><select value={newType} onChange={(event) => setNewType(event.target.value)}>{(documentTypes.length ? documentTypes : ["scene", "chapter", "note", "research", "outline"]).map((value) => <option key={value}>{value}</option>)}</select></label>
            <div className="modal-actions"><button onClick={() => setCreating(false)}>Cancel</button><button className="primary-action small" onClick={() => void create()}>Create</button></div>
          </div>
        </div>
      )}
    </div>
  );
}

function Property({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div className="property-row"><span>{label}</span><strong className={mono ? "mono" : ""}>{value}</strong></div>;
}

function sceneCardPayload(card: JsonMap | undefined, document: DocumentItem, worldId: string, branchId: string, sortOrder: number) {
  return {
    world_id: card?.world_id || worldId || null,
    branch_id: card?.branch_id || branchId || null,
    pov_variant_id: card?.pov_variant_id || null,
    location_variant_id: card?.location_variant_id || null,
    participants: Array.isArray(card?.participants) ? card.participants : [],
    narrative_time: String(card?.narrative_time || ""),
    target_outcome: String(card?.target_outcome || excerpt(document.content)),
    notes: String(card?.notes || ""),
    status: String(card?.status || document.status || "planned"),
    sort_order: sortOrder,
  };
}

const wordCountOf = (value: unknown) => { const text = String(value || "").trim(); return text ? text.split(/\s+/).length : 0; };
const excerpt = (value: unknown) => String(value || "").replace(/\s+/g, " ").trim().slice(0, 150);
