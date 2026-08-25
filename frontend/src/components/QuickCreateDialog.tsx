import { useState } from "react";
import { Sparkles, X } from "lucide-react";
import { studioApi } from "../api";

interface QuickCreateDialogProps {
  open: boolean;
  projectId: string;
  worldId: string;
  branchId: string;
  onClose: () => void;
  onCreated: () => Promise<void> | void;
}

export function QuickCreateDialog({ open, projectId, worldId, branchId, onClose, onCreated }: QuickCreateDialogProps) {
  const [text, setText] = useState("");
  const [kind, setKind] = useState("");
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (!open) return null;

  const payload = () => ({ text: text.trim(), forced_kind: kind || null, project_id: projectId || null, world_id: worldId || null, branch_id: branchId || null, folder_id: null });

  const doPreview = async () => {
    if (!text.trim()) return;
    setBusy(true); setError("");
    try { setPreview(await studioApi.quickCreatePreview(payload())); }
    catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  };

  const create = async () => {
    if (!text.trim()) return;
    setBusy(true); setError("");
    try {
      await studioApi.quickCreate(payload());
      setText(""); setKind(""); setPreview(null); onClose(); await onCreated();
    } catch (reason) { setError((reason as Error).message); }
    finally { setBusy(false); }
  };

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className="modal quick-modal" onMouseDown={(event) => event.stopPropagation()}>
        <button className="modal-close icon-control" onClick={onClose}><X size={15} /></button>
        <span className="eyebrow">Quick create</span><h2>Describe it naturally</h2><p>Schema inference stays in Python. TSX just gives it a less prehistoric interface.</p>
        <textarea autoFocus value={text} onChange={(event) => { setText(event.target.value); setPreview(null); }} placeholder="A character, place, document, project, world, relationship…" />
        <label><span>Force kind</span><select value={kind} onChange={(event) => setKind(event.target.value)}><option value="">Auto detect</option><option value="entity">Entity</option><option value="document">Document</option><option value="project">Project</option><option value="world">World</option></select></label>
        {preview ? <div className="quick-preview"><span>{String(preview.kind || "resource")}</span><strong>{String(preview.name || text)}</strong><pre>{JSON.stringify(preview, null, 2)}</pre></div> : null}
        {error ? <div className="inline-error">{error}</div> : null}
        <div className="modal-actions"><button onClick={onClose}>Cancel</button><button disabled={busy || !text.trim()} onClick={() => void doPreview()}>Preview</button><button className="primary-action small" disabled={busy || !text.trim()} onClick={() => void create()}><Sparkles size={13} />{busy ? "Working…" : "Create"}</button></div>
      </div>
    </div>
  );
}
