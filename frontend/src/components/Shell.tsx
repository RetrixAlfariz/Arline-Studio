import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import {
  BookOpen,
  Boxes,
  Building2,
  Check,
  ChevronDown,
  ChevronRight,
  Command,
  Copy,
  FileText,
  Folder,
  Gem,
  GitBranch,
  Globe2,
  Home,
  LayoutDashboard,
  MapPin,
  Menu,
  MessageSquareText,
  Moon,
  MoreHorizontal,
  Network,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  Plus,
  Search,
  Settings2,
  Sparkles,
  Sun,
  Trash2,
  UserRound,
} from "lucide-react";
import { browserStorage } from "../browserStorage";
import type { AppView, ContrastMode, DocumentItem, EntityFamily, FolderNode, Project, Session, ThemeMode, World } from "../types";

interface ShellProps {
  children: ReactNode;
  view: AppView;
  theme: ThemeMode;
  contrast: ContrastMode;
  appearanceStyle: CSSProperties;
  projects: Project[];
  worlds: World[];
  activeProjectId: string;
  activeWorldId: string;
  activeBranchId: string;
  sessions: Session[];
  activeSessionId?: string;
  documents: DocumentItem[];
  folders: FolderNode[];
  families: EntityFamily[];
  entityTypes: string[];
  activeDocumentId: string;
  activeEntityId: string;
  connectionLabel: string;
  onView: (view: AppView) => void;
  onProject: (id: string) => void;
  onWorld: (id: string) => void;
  onBranch: (id: string) => void;
  onSession: (id: string) => void;
  onNewChat: () => void;
  onNewDocument: () => void;
  onOpenDocument: (id: string) => void;
  onOpenEntity: (id: string) => void;
  onLibrary: (entityType: string) => void;
  onNewEntity: (entityType: string, name: string) => void;
  onRenameEntity: (id: string, name: string) => void;
  onTrashEntity: (id: string, name: string) => void;
  onDuplicateEntity: (id: string) => void;
  onQuickCreate: () => void;
  onPalette: () => void;
  onSettings: () => void;
  onTools: () => void;
  onTheme: () => void;
}

type ScopeKind = "project" | "world" | "branch";
type ScopeOption = { id: string; name: string };

const TYPE_META: Record<string, { label: string; icon: ReactNode }> = {
  character: { label: "Characters", icon: <UserRound size={14} /> },
  location: { label: "Locations", icon: <MapPin size={14} /> },
  item: { label: "Items", icon: <Gem size={14} /> },
  organization: { label: "Organizations", icon: <Building2 size={14} /> },
  lore: { label: "Lore", icon: <BookOpen size={14} /> },
};
const singular = (type: string) => type.replace(/[_-]+/g, " ").trim().toLowerCase() || "sheet";
const typeMeta = (type: string) => {
  if (TYPE_META[type]) return TYPE_META[type];
  const words = type.replace(/[_-]+/g, " ").trim();
  return { label: words.charAt(0).toUpperCase() + words.slice(1), icon: <Boxes size={14} /> };
};

/** Remembered open/closed state for sidebar sections and tree nodes. */
function useExpanded(defaults: Record<string, boolean>) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>(() => {
    try { return { ...defaults, ...JSON.parse(browserStorage.get("arline:sidebar:expanded") || "{}") }; } catch { return defaults; }
  });
  const toggle = (key: string) => setExpanded((current) => {
    const next = { ...current, [key]: !current[key] };
    browserStorage.set("arline:sidebar:expanded", JSON.stringify(next));
    return next;
  });
  return [expanded, toggle] as const;
}

export function Shell(props: ShellProps) {
  const {
    children, view, theme, contrast, appearanceStyle, projects, worlds, activeProjectId, activeWorldId, activeBranchId,
    sessions, activeSessionId, documents, folders, families, entityTypes, activeDocumentId, activeEntityId, connectionLabel,
    onView, onProject, onWorld, onBranch, onSession, onNewChat, onNewDocument, onOpenDocument, onOpenEntity, onLibrary, onNewEntity, onRenameEntity, onTrashEntity, onDuplicateEntity,
    onQuickCreate, onPalette, onSettings, onTools, onTheme,
  } = props;
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => browserStorage.get("arline:sidebar:collapsed") === "yes");
  const [mobileOpen, setMobileOpen] = useState(false);
  const [openScope, setOpenScope] = useState<ScopeKind | null>(null);
  const [expanded, toggle] = useExpanded({ chats: true, manuscript: true, library: true });
  const [addingType, setAddingType] = useState<string | null>(null);
  const [sheetFilter, setSheetFilter] = useState("");
  const filterText = sheetFilter.trim().toLowerCase();
  const scopeRef = useRef<HTMLDivElement | null>(null);
  const activeWorld = worlds.find((item) => item.id === activeWorldId);
  const branches = activeWorld?.branches || [];
  const [runtimeLabel, ...runtimeModelParts] = connectionLabel.split(" · ");
  const runtimeModel = runtimeModelParts.join(" · ") || "No model selected";

  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey)) return;
      if (event.key.toLowerCase() === "n") { event.preventDefault(); onQuickCreate(); }
      if (event.key === "\\") { event.preventDefault(); collapse(!sidebarCollapsed); }
    };
    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, [onQuickCreate, sidebarCollapsed]);

  useEffect(() => {
    if (!openScope) return;
    const closeScope = (event: PointerEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent && event.key === "Escape") return setOpenScope(null);
      if (event instanceof PointerEvent && !scopeRef.current?.contains(event.target as Node)) setOpenScope(null);
    };
    window.addEventListener("pointerdown", closeScope);
    window.addEventListener("keydown", closeScope);
    return () => {
      window.removeEventListener("pointerdown", closeScope);
      window.removeEventListener("keydown", closeScope);
    };
  }, [openScope]);

  const collapse = (value: boolean) => {
    browserStorage.set("arline:sidebar:collapsed", value ? "yes" : "no");
    setSidebarCollapsed(value);
  };
  // Every sidebar action also closes the mobile drawer.
  const go = (action: () => void) => () => { action(); setMobileOpen(false); };

  const documentsByFolder = useMemo(() => {
    const map = new Map<string, DocumentItem[]>();
    for (const doc of documents) {
      const key = doc.folder_id || "";
      map.set(key, [...(map.get(key) || []), doc]);
    }
    return map;
  }, [documents]);
  const folderIds = useMemo(() => {
    const ids = new Set<string>();
    const walk = (nodes: FolderNode[]) => nodes.forEach((node) => { ids.add(node.id); walk(node.children || []); });
    walk(folders);
    return ids;
  }, [folders]);
  // Documents whose folder no longer exists still show at the root.
  const rootDocuments = documents.filter((doc) => !doc.folder_id || !folderIds.has(doc.folder_id));
  const familiesByType = useMemo(() => {
    const map = new Map<string, EntityFamily[]>();
    for (const family of families) {
      const key = family.entity_type || "lore";
      map.set(key, [...(map.get(key) || []), family]);
    }
    for (const list of map.values()) list.sort((a, b) => a.name.localeCompare(b.name));
    return map;
  }, [families]);
  const libraryTypes = Array.from(new Set([...entityTypes, ...familiesByType.keys()]));

  const docRow = (doc: DocumentItem, depth: number) => (
    <button key={doc.id} className={`tree-row ${view === "manuscript" && activeDocumentId === doc.id ? "active" : ""}`} style={{ paddingLeft: 8 + depth * 14 }} onClick={go(() => onOpenDocument(doc.id))} title={doc.title}>
      <span className="tree-toggle" aria-hidden="true" /><FileText size={14} /><span className="tree-label">{doc.title || "Untitled"}</span>
    </button>
  );
  const folderRows = (nodes: FolderNode[], depth: number): ReactNode => nodes.map((node) => {
    const key = `folder:${node.id}`;
    const open = Boolean(expanded[key]);
    const docs = documentsByFolder.get(node.id) || [];
    return (
      <div key={node.id}>
        <button className="tree-row" style={{ paddingLeft: 8 + depth * 14 }} aria-expanded={open} onClick={() => toggle(key)} title={node.name}>
          <span className="tree-toggle">{open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}</span><Folder size={14} /><span className="tree-label">{node.name}</span>
          <small className="tree-count">{docs.length || ""}</small>
        </button>
        {open && <>{folderRows(node.children || [], depth + 1)}{docs.map((doc) => docRow(doc, depth + 1))}</>}
      </div>
    );
  });

  return (
    <div className={`studio-shell notion-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""} ${mobileOpen ? "mobile-sidebar-open" : ""}`} data-theme={theme} data-contrast={contrast} style={appearanceStyle}>
      <aside className="studio-sidebar" aria-label="Workspace navigation">
        <div ref={scopeRef} className="sidebar-workspace">
          <div className="workspace-row">
            <ScopeMenu kind="project" label="Project" icon={<span className="brand-mark sidebar-brand-mark" aria-hidden="true" />} value={activeProjectId} options={projects} open={openScope === "project"} onToggle={() => setOpenScope((value) => value === "project" ? null : "project")} onSelect={onProject} />
            <button className="icon-control sidebar-collapse" aria-label="Collapse sidebar" title="Collapse sidebar (Ctrl+\)" onClick={() => { collapse(true); setMobileOpen(false); }}><PanelLeftClose size={15} /></button>
          </div>
          <div className="scope-row">
            <ScopeMenu kind="world" label="World" icon={<Globe2 size={13} />} value={activeWorldId} options={worlds} open={openScope === "world"} onToggle={() => setOpenScope((value) => value === "world" ? null : "world")} onSelect={onWorld} />
            <ScopeMenu kind="branch" label="Branch" icon={<GitBranch size={13} />} value={activeBranchId} options={branches} open={openScope === "branch"} onToggle={() => setOpenScope((value) => value === "branch" ? null : "branch")} onSelect={onBranch} />
          </div>
        </div>

        <nav className="sidebar-quick" aria-label="Quick actions">
          <button className="tree-row" onClick={go(onPalette)}><span className="tree-toggle" /><Search size={14} /><span className="tree-label">Search</span><kbd>Ctrl K</kbd></button>
          <button className={`tree-row ${view === "home" ? "active" : ""}`} onClick={go(() => onView("home"))}><span className="tree-toggle" /><Home size={14} /><span className="tree-label">Home</span></button>
          <button className={`tree-row ${view === "chat" && !activeSessionId ? "active" : ""}`} onClick={go(onNewChat)}><span className="tree-toggle" /><MessageSquareText size={14} /><span className="tree-label">New chat</span></button>
          <button className="tree-row" onClick={go(onQuickCreate)}><span className="tree-toggle" /><Sparkles size={14} /><span className="tree-label">Quick create</span><kbd>Ctrl N</kbd></button>
        </nav>

        <div className="sidebar-scroll">
          <SidebarSection title="Chats" open={expanded.chats} onToggle={() => toggle("chats")} onAdd={go(onNewChat)} addLabel="New chat">
            {sessions.slice(0, 12).map((session) => (
              <button key={session.id} className={`tree-row ${view === "chat" && activeSessionId === session.id ? "active" : ""}`} onClick={go(() => onSession(session.id))} title={session.title || "Untitled chat"}>
                <span className="tree-toggle" /><MessageSquareText size={14} /><span className="tree-label">{session.title || "Untitled chat"}</span>
              </button>
            ))}
            {!sessions.length && <p className="tree-empty">No chats yet</p>}
          </SidebarSection>

          <SidebarSection title="Manuscript" open={expanded.manuscript} onToggle={() => toggle("manuscript")} onAdd={go(onNewDocument)} addLabel="New document" onTitle={go(() => onView("manuscript"))}>
            {folderRows(folders, 0)}
            {rootDocuments.map((doc) => docRow(doc, 0))}
            {!documents.length && <p className="tree-empty">No documents yet</p>}
          </SidebarSection>

          <SidebarSection title="Library" open={expanded.library} onToggle={() => toggle("library")} onAdd={go(onQuickCreate)} addLabel="New sheet" onTitle={go(() => onLibrary("all"))}>
            <button className={`tree-row ${view === "graph" ? "active" : ""}`} onClick={go(() => onView("graph"))}><span className="tree-toggle" /><Network size={14} /><span className="tree-label">Relation graph</span></button>
            {families.length >= 6 && <label className="tree-filter"><Search size={13} /><input value={sheetFilter} placeholder="Filter sheets" aria-label="Filter Library sheets" onChange={(event) => setSheetFilter(event.target.value)} onKeyDown={(event) => { if (event.key === "Escape") setSheetFilter(""); }} /></label>}
            {libraryTypes.map((type) => {
              const key = `type:${type}`;
              const allItems = familiesByType.get(type) || [];
              const items = filterText ? allItems.filter((family) => family.name.toLowerCase().includes(filterText)) : allItems;
              if (filterText && !items.length) return null;
              const open = Boolean(expanded[key]) || Boolean(filterText);
              const meta = typeMeta(type);
              return (
                <div key={type}>
                  <div className="tree-row tree-split">
                    <button className="tree-toggle" aria-label={`${open ? "Collapse" : "Expand"} ${meta.label}`} aria-expanded={open} onClick={() => toggle(key)}>{open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}</button>
                    <button className="tree-main" aria-expanded={open} onClick={() => toggle(key)} title={`${open ? "Collapse" : "Expand"} ${meta.label}`}>{meta.icon}<span className="tree-label">{meta.label}</span><small className="tree-count">{items.length || ""}</small></button>
                    <button className="tree-more" aria-label={`New ${singular(type)}`} title={`New ${singular(type)}`} onClick={() => { if (!open) toggle(key); setAddingType(type); }}><Plus size={13} /></button>
                  </div>
                  {open && items.map((family) => (
                    <SheetRow key={family.id} name={family.name} icon={meta.icon} active={view === "entity" && activeEntityId === family.id} onOpen={go(() => onOpenEntity(family.id))} onRename={(name) => onRenameEntity(family.id, name)} onDuplicate={() => onDuplicateEntity(family.id)} onTrash={() => onTrashEntity(family.id, family.name)} />
                  ))}
                  {open && !filterText && (addingType === type
                    ? <NewSheetRow icon={meta.icon} placeholder={`Name the new ${singular(type)}`} onDone={(name) => { setAddingType(null); if (name) { setMobileOpen(false); onNewEntity(type, name); } }} />
                    : <button className="tree-row tree-add-row" style={{ paddingLeft: 22 }} onClick={() => setAddingType(type)}><span className="tree-toggle" /><Plus size={13} /><span className="tree-label">New {singular(type)}</span></button>)}
                </div>
              );
            })}
            {filterText && !families.some((family) => family.name.toLowerCase().includes(filterText)) && <p className="tree-empty">No sheets match</p>}
          </SidebarSection>
        </div>

        <footer className="sidebar-footer">
          <button className={`tree-row ${view === "commands" ? "active" : ""}`} onClick={go(() => onView("commands"))}><span className="tree-toggle" /><Command size={14} /><span className="tree-label">Commands</span></button>
          <button className="tree-row" onClick={go(onTools)}><span className="tree-toggle" /><LayoutDashboard size={14} /><span className="tree-label">Import &amp; tools</span></button>
          <div className="sidebar-footer-row">
            <button className="runtime-chip" onClick={go(onSettings)} title={`${runtimeLabel} · ${runtimeModel}. Open settings`}>
              <span className="runtime-status-dot" /><span className="tree-label">{runtimeModel}</span>
            </button>
            <button className="icon-control" onClick={onTheme} title={theme === "dark" ? "Use light theme" : "Use dark theme"} aria-label="Toggle theme">{theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}</button>
            <button className="icon-control" onClick={go(onSettings)} title="Settings" aria-label="Settings"><Settings2 size={15} /></button>
          </div>
        </footer>
      </aside>

      <button className="sidebar-expand" aria-label="Expand sidebar" title="Expand sidebar (Ctrl+\)" onClick={() => collapse(false)}><PanelLeftOpen size={15} /></button>
      <div className="mobile-bar">
        <button className="icon-control" aria-label="Open navigation" onClick={() => setMobileOpen(true)}><Menu size={17} /></button>
        <span className="brand-mark" aria-hidden="true" /><strong>Arline</strong>
        <button className="icon-control" aria-label="Search" onClick={onPalette}><Search size={16} /></button>
      </div>
      {mobileOpen && <div className="mobile-scrim" onClick={() => setMobileOpen(false)} />}

      <main className="studio-main">{children}</main>
    </div>
  );
}

/** Inline name field for a new Library sheet: Enter creates, Esc or an empty blur cancels. */
function NewSheetRow({ icon, placeholder, onDone }: { icon: ReactNode; placeholder: string; onDone: (name: string) => void }) {
  return (
    <div className="tree-row tree-split tree-item" style={{ paddingLeft: 22 }}>
      <span className="tree-toggle" />{icon}
      <input className="tree-rename" autoFocus placeholder={placeholder} aria-label={placeholder} onBlur={(event) => onDone(event.currentTarget.value.trim())} onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); if (event.key === "Escape") { event.currentTarget.value = ""; event.currentTarget.blur(); } }} />
    </div>
  );
}

/** A Library sheet in the tree: click opens; double-click, F2 or the menu renames; right-click or "..." opens the menu. */
function SheetRow({ name, icon, active, onOpen, onRename, onDuplicate, onTrash }: { name: string; icon: ReactNode; active: boolean; onOpen: () => void; onRename: (name: string) => void; onDuplicate: () => void; onTrash: () => void }) {
  const [renaming, setRenaming] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!menuOpen) return;
    const close = (event: PointerEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent ? event.key === "Escape" : !ref.current?.contains(event.target as Node)) setMenuOpen(false);
    };
    window.addEventListener("pointerdown", close);
    window.addEventListener("keydown", close);
    return () => { window.removeEventListener("pointerdown", close); window.removeEventListener("keydown", close); };
  }, [menuOpen]);
  const commit = (value: string) => {
    setRenaming(false);
    const next = value.trim();
    if (next && next !== name) onRename(next);
  };
  return (
    <div ref={ref} className={`tree-row tree-split tree-item ${active ? "active" : ""}`} style={{ paddingLeft: 22 }}>
      <span className="tree-toggle" />
      {renaming
        ? <>{icon}<input className="tree-rename" autoFocus defaultValue={name} aria-label="Sheet name" onFocus={(event) => event.currentTarget.select()} onBlur={(event) => commit(event.currentTarget.value)} onKeyDown={(event) => { if (event.key === "Enter") event.currentTarget.blur(); if (event.key === "Escape") { event.currentTarget.value = name; event.currentTarget.blur(); } }} /></>
        : <button className="tree-main" onClick={onOpen} onDoubleClick={() => setRenaming(true)} onContextMenu={(event) => { event.preventDefault(); setMenuOpen(true); }} onKeyDown={(event) => { if (event.key === "F2") { event.preventDefault(); setRenaming(true); } }} title={`${name} \u2014 double-click or F2 to rename, right-click for more`}>{icon}<span className="tree-label">{name}</span></button>}
      {!renaming && <button className="tree-more" aria-label={`More actions for ${name}`} aria-haspopup="menu" aria-expanded={menuOpen} onClick={() => setMenuOpen((value) => !value)}><MoreHorizontal size={14} /></button>}
      {menuOpen && <div className="tree-menu" role="menu">
        <button role="menuitem" onClick={() => { setMenuOpen(false); onOpen(); }}><FileText size={13} />Open</button>
        <button role="menuitem" onClick={() => { setMenuOpen(false); setRenaming(true); }}><Pencil size={13} />Rename<kbd>F2</kbd></button>
        <button role="menuitem" onClick={() => { setMenuOpen(false); onDuplicate(); }}><Copy size={13} />Duplicate</button>
        <button role="menuitem" className="danger-item" onClick={() => { setMenuOpen(false); onTrash(); }}><Trash2 size={13} />Move to Trash</button>
      </div>}
    </div>
  );
}

function SidebarSection({ title, open, onToggle, onAdd, addLabel, onTitle, children }: { title: string; open: boolean; onToggle: () => void; onAdd: () => void; addLabel: string; onTitle?: () => void; children: ReactNode }) {
  return (
    <section className="sidebar-tree-section">
      <div className="sidebar-section-head">
        <button className="section-title" aria-expanded={open} onClick={onTitle || onToggle}>{title}</button>
        <button className="section-chevron" aria-label={`${open ? "Collapse" : "Expand"} ${title}`} onClick={onToggle}>{open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}</button>
        <button className="section-add" aria-label={addLabel} title={addLabel} onClick={onAdd}><Plus size={13} /></button>
      </div>
      {open && <div className="sidebar-tree">{children}</div>}
    </section>
  );
}

function ScopeMenu({ kind, label, icon, value, options, open, onToggle, onSelect }: { kind: ScopeKind; label: string; icon: ReactNode; value: string; options: ScopeOption[]; open: boolean; onToggle: () => void; onSelect: (id: string) => void }) {
  const selected = options.find((option) => option.id === value);
  const fallbackName = value ? humanizeScopeId(value, label) : `No ${label.toLowerCase()}`;
  const visibleOptions = selected || !value ? options : [{ id: value, name: fallbackName }, ...options];
  return <div className={`scope-control scope-${kind} ${open ? "open" : ""}`}>
    <button className="scope-trigger" aria-haspopup="listbox" aria-expanded={open} aria-label={`${label}: ${selected?.name || fallbackName}`} title={`${label}: ${selected?.name || fallbackName}`} onClick={onToggle}>
      <span className="scope-control-icon">{icon}</span>
      <span className="scope-control-copy">{kind !== "project" && <small>{label}</small>}<strong>{selected?.name || fallbackName}</strong></span>
      <ChevronDown className="scope-chevron" size={12} />
    </button>
    {open && <div className="scope-menu" role="listbox" aria-label={`Choose ${label.toLowerCase()}`}>
      <small className="scope-menu-label">{label}</small>
      <div className="scope-menu-options">
        {visibleOptions.map((option) => <button key={option.id} role="option" aria-selected={option.id === value} onClick={() => { onSelect(option.id); onToggle(); }}><span><strong>{option.name}</strong><small>{kind === "project" ? "Story workspace" : kind === "world" ? "World bible" : "Narrative branch"}</small></span>{option.id === value ? <Check size={14} /> : null}</button>)}
        {!visibleOptions.length && <p>No {label.toLowerCase()} options available.</p>}
      </div>
    </div>}
  </div>;
}

function humanizeScopeId(value: string, label: string) {
  const stripped = value.replace(new RegExp(`^${label}[-_: ]*`, "i"), "").replace(/[-_:]+/g, " ").trim();
  return (stripped || value).replace(/\b\w/g, (letter) => letter.toUpperCase());
}
