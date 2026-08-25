import { useEffect, useMemo, useRef, useState } from "react";
import { FilePlus2, FileText, Save, Trash2 } from "lucide-react";
import { studioApi } from "../api";
import type { DocumentItem } from "../types";

interface ManuscriptViewProps {
  projectId: string;
  documents: DocumentItem[];
  initialDocumentId?: string;
  documentTypes: string[];
  onDocumentsChanged: () => Promise<void> | void;
  onInspect: (title: string, data: unknown) => void;
}

export function ManuscriptView({ projectId, documents, initialDocumentId, documentTypes, onDocumentsChanged, onInspect }: ManuscriptViewProps) {
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
  const recoveryTimer = useRef<number | null>(null);

  useEffect(() => {
    if (initialDocumentId) setSelectedId(initialDocumentId);
  }, [initialDocumentId]);

  useEffect(() => {
    if (!selectedId && documents[0]) setSelectedId(documents[0].id);
  }, [documents, selectedId]);

  useEffect(() => {
    if (!selectedId) {
      setDoc(null);
      return;
    }
    void studioApi.document(selectedId).then((loaded) => {
      const recovery = localStorage.getItem(`arline:react:draft:${loaded.id}`);
      setDoc(loaded);
      setTitle(loaded.title || "Untitled");
      setContent(recovery ?? loaded.content ?? "");
      setStatus(loaded.status || "planned");
      setSaveLabel(recovery ? "Recovered local draft" : "Loaded");
    }).catch((error: Error) => setSaveLabel(error.message));
  }, [selectedId]);

  useEffect(() => {
    if (!doc) return;
    if (recoveryTimer.current) window.clearTimeout(recoveryTimer.current);
    recoveryTimer.current = window.setTimeout(() => {
      localStorage.setItem(`arline:react:draft:${doc.id}`, content);
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

  const save = async () => {
    if (!doc) return;
    setSaving(true);
    try {
      const updated = await studioApi.updateDocument(doc.id, { title, content, status, note: "react checkpoint" });
      setDoc(updated);
      localStorage.removeItem(`arline:react:draft:${doc.id}`);
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
    localStorage.removeItem(`arline:react:draft:${doc.id}`);
    setSelectedId("");
    setDoc(null);
    await onDocumentsChanged();
  };

  const wordCount = content.trim() ? content.trim().split(/\s+/).length : 0;

  return (
    <div className="manuscript-layout">
      <aside className="manuscript-rail">
        <div className="pane-heading"><div><span className="eyebrow">Manuscript</span><h2>Binder</h2></div><button className="icon-control" onClick={() => setCreating(true)}><FilePlus2 size={15} /></button></div>
        <div className="filter-strip">
          {["all", "scene", "chapter", "note", "research", "outline"].map((value) => <button key={value} className={filter === value ? "active" : ""} onClick={() => setFilter(value)}>{value}</button>)}
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

      <section className="editor-pane">
        {doc ? (
          <>
            <div className="editor-toolbar">
              <input className="document-title-input" value={title} onChange={(event) => setTitle(event.target.value)} />
              <div>
                <select value={status} onChange={(event) => setStatus(event.target.value)}><option>planned</option><option>writing</option><option>revising</option><option>final</option></select>
                <button onClick={() => onInspect("Document metadata", doc)}>Inspect</button>
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
      </section>

      <aside className="manuscript-inspector">
        <div className="pane-heading"><div><span className="eyebrow">Inspector</span><h2>Scene</h2></div></div>
        {doc ? <>
          <Property label="Type" value={doc.document_type || "document"} />
          <Property label="Status" value={status} />
          <Property label="Words" value={String(wordCount)} />
          <Property label="ID" value={doc.id} mono />
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
