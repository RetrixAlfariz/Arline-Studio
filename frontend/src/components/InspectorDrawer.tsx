import { X } from "lucide-react";
import type { Selection } from "../types";

interface InspectorDrawerProps {
  selection: Selection | null;
  onClose: () => void;
}

export function InspectorDrawer({ selection, onClose }: InspectorDrawerProps) {
  if (!selection) return null;
  return (
    <aside className="data-inspector">
      <header><div><span className="eyebrow">Inspector</span><h2>{selection.title}</h2><p>{selection.subtitle || selection.kind}</p></div><button className="icon-control" onClick={onClose}><X size={15} /></button></header>
      <div className="data-inspector-body">
        <div className="property-row"><span>Kind</span><strong>{selection.kind}</strong></div>
        {selection.id ? <div className="property-row"><span>ID</span><strong className="mono">{selection.id}</strong></div> : null}
        <section><span className="eyebrow">Structured data</span><pre>{JSON.stringify(selection.data ?? {}, null, 2)}</pre></section>
      </div>
    </aside>
  );
}
