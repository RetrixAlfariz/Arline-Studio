import { useEffect, useMemo, useRef, useState } from "react";
import { BookOpenText, Box, Command, FileText, Globe2, Home, Library, MessageSquareText, Search, Sparkles } from "lucide-react";
import type { AppView, CommandDefinition, DocumentItem, EntityFamily, JsonMap, Session, World } from "../types";

type PaletteKind = "navigation" | "command" | "chat" | "document" | "entity" | "world" | "canon";

interface PaletteItem {
  id: string;
  kind: PaletteKind;
  label: string;
  subtitle: string;
  description?: string;
  view?: AppView;
  data?: JsonMap;
}

interface Props {
  open: boolean;
  commands: CommandDefinition[];
  sessions: Session[];
  documents: DocumentItem[];
  families: EntityFamily[];
  worlds: World[];
  canonFacts: JsonMap[];
  onClose: () => void;
  onView: (view: AppView) => void;
  onSession: (id: string) => void;
  onDocument: (id: string) => void;
  onWorld: (id: string) => void;
  onCommand: (command: CommandDefinition) => void;
  onInspect: (title: string, data: unknown) => void;
  onAddToChat: (text: string) => void;
}

const NAVIGATION: PaletteItem[] = [
  { id: "nav-home", kind: "navigation", label: "Home", subtitle: "Workspace overview", view: "home" },
  { id: "nav-chat", kind: "navigation", label: "Chat", subtitle: "Write with Arline", view: "chat" },
  { id: "nav-manuscript", kind: "navigation", label: "Manuscript", subtitle: "Binder, Corkboard, and Outliner", view: "manuscript" },
  { id: "nav-library", kind: "navigation", label: "Library", subtitle: "Objects, canon, and relationships", view: "library" },
  { id: "nav-commands", kind: "navigation", label: "Command Center", subtitle: "Command documentation and workflows", view: "commands" },
];

export function GlobalPalette({ open, commands, sessions, documents, families, worlds, canonFacts, onClose, onView, onSession, onDocument, onWorld, onCommand, onInspect, onAddToChat }: Props) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const items = useMemo<PaletteItem[]>(() => [
    ...NAVIGATION,
    ...commands.map((item) => ({ id: `command:${item.id}`, kind: "command" as const, label: `/${item.id}`, subtitle: item.category || "Command", description: item.description || item.why_use, data: item })),
    ...sessions.map((item) => ({ id: `chat:${item.id}`, kind: "chat" as const, label: item.title || "Untitled chat", subtitle: "Chat", description: String(item.updated_at || item.created_at || "Recent conversation"), data: item })),
    ...documents.map((item) => ({ id: `document:${item.id}`, kind: "document" as const, label: item.title || "Untitled document", subtitle: `${item.document_type || "Document"} · ${item.status || "planned"}`, description: excerpt(item.content), data: item })),
    ...families.map((item) => ({ id: `entity:${item.id}`, kind: "entity" as const, label: item.name, subtitle: titleCase(item.entity_type || "Library object"), description: item.description || "Shared Library identity", data: item })),
    ...worlds.map((item) => ({ id: `world:${item.id}`, kind: "world" as const, label: item.name, subtitle: "World", description: item.description || "Workspace world", data: item })),
    ...canonFacts.slice(0, 40).map((item) => ({ id: `canon:${String(item.id)}`, kind: "canon" as const, label: String(item.path || item.title || item.id || "Canon fact"), subtitle: "Canon fact", description: String(item.value ?? item.content ?? item.statement ?? ""), data: item })),
  ], [commands, sessions, documents, families, worlds, canonFacts]);

  const results = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const matching = needle ? items.filter((item) => `${item.label} ${item.subtitle} ${item.description || ""}`.toLowerCase().includes(needle)) : items;
    return matching.slice(0, 60);
  }, [items, query]);
  const current = results[Math.min(selected, Math.max(0, results.length - 1))];

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setSelected(0);
    window.setTimeout(() => inputRef.current?.focus(), 0);
  }, [open]);

  const activate = (item: PaletteItem | undefined) => {
    if (!item) return;
    if (item.kind === "navigation" && item.view) onView(item.view);
    else if (item.kind === "command") onCommand(item.data as CommandDefinition);
    else if (item.kind === "chat") onSession(String(item.data?.id));
    else if (item.kind === "document") onDocument(String(item.data?.id));
    else if (item.kind === "world") onWorld(String(item.data?.id));
    else if (item.kind === "entity") { onView("library"); onInspect(item.label, item.data); }
    else onInspect(item.label, item.data);
    onClose();
  };

  const addToChat = (item: PaletteItem | undefined) => {
    if (!item) return;
    if (item.kind === "command") onAddToChat(`${item.label} `);
    else onAddToChat(`@${referenceName(item.label)} `);
    onClose();
  };

  if (!open) return null;
  return <div className="palette-backdrop" onMouseDown={onClose}>
    <section className="global-palette" role="dialog" aria-modal="true" aria-label="Search Arline" onMouseDown={(event) => event.stopPropagation()} onKeyDown={(event) => {
      if (event.key === "Escape") onClose();
      if (event.key === "ArrowDown") { event.preventDefault(); setSelected((value) => Math.min(value + 1, results.length - 1)); }
      if (event.key === "ArrowUp") { event.preventDefault(); setSelected((value) => Math.max(value - 1, 0)); }
      if (event.key === "Enter" && event.ctrlKey) { event.preventDefault(); addToChat(current); }
      else if (event.key === "Enter" && event.altKey) { event.preventDefault(); if (current) onInspect(current.label, current.data); }
      else if (event.key === "Enter") { event.preventDefault(); activate(current); }
    }}>
      <header className="palette-search"><Search size={18} /><input ref={inputRef} value={query} onChange={(event) => { setQuery(event.target.value); setSelected(0); }} placeholder="Search Arline…" /><kbd>Esc</kbd></header>
      <div className="palette-layout">
        <div className="palette-results">
          {results.map((item, index) => <button key={item.id} className={index === selected ? "active" : ""} onMouseEnter={() => setSelected(index)} onClick={() => activate(item)}>
            <span className="palette-icon"><ItemIcon item={item} /></span><span><strong>{item.label}</strong><small>{item.subtitle}</small></span><em>{titleCase(item.kind)}</em>
          </button>)}
          {!results.length && <div className="palette-empty"><Search size={22} /><strong>No matching resources</strong><span>Try a command, document, character, world, or view.</span></div>}
        </div>
        <aside className="palette-preview">
          {current ? <><span className="eyebrow">{current.subtitle}</span><h2>{current.label}</h2><p>{current.description || "Open this resource to continue working."}</p><div className="palette-preview-meta"><span>Resource</span><strong>{titleCase(current.kind)}</strong>{current.data?.status ? <><span>Status</span><strong>{String(current.data.status)}</strong></> : null}{current.data?.canon_status ? <><span>Canon</span><strong>{String(current.data.canon_status)}</strong></> : null}</div><div className="palette-preview-actions"><button onClick={() => activate(current)}>Open</button><button onClick={() => addToChat(current)}>Add to Chat</button><button onClick={() => onInspect(current.label, current.data)}>Inspect</button></div></> : <div className="palette-empty">Select a result to preview it.</div>}
        </aside>
      </div>
      <footer><span><kbd>↑</kbd><kbd>↓</kbd> Navigate</span><span><kbd>Enter</kbd> Open</span><span><kbd>Ctrl Enter</kbd> Add to Chat</span><span><kbd>Alt Enter</kbd> Inspect</span></footer>
    </section>
  </div>;
}

function ItemIcon({ item }: { item: PaletteItem }) {
  if (item.kind === "command") return <Command size={15} />;
  if (item.kind === "chat") return <MessageSquareText size={15} />;
  if (item.kind === "document") return <FileText size={15} />;
  if (item.kind === "entity") return <Box size={15} />;
  if (item.kind === "world") return <Globe2 size={15} />;
  if (item.kind === "canon") return <BookOpenText size={15} />;
  if (item.view === "home") return <Home size={15} />;
  if (item.view === "library") return <Library size={15} />;
  return <Sparkles size={15} />;
}

const excerpt = (value: unknown) => String(value || "").replace(/\s+/g, " ").trim().slice(0, 180) || "Open this manuscript item.";
const titleCase = (value: string) => value.replaceAll("_", " ").replace(/\b\w/g, (match) => match.toUpperCase());
const referenceName = (value: string) => value.trim().replace(/^\//, "").replace(/[^\w.:-]+/g, "_");
