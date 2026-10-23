import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import {
  Boxes,
  Check,
  ChevronDown,
  ChevronRight,
  Command,
  FileText,
  FolderKanban,
  GitBranch,
  Globe2,
  Home,
  MessageSquareText,
  Moon,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Search,
  Settings2,
  LayoutDashboard,
  Sun,
} from "lucide-react";
import type { AppView, ContrastMode, Project, Session, ThemeMode, World } from "../types";

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
  connectionLabel: string;
  onView: (view: AppView) => void;
  onProject: (id: string) => void;
  onWorld: (id: string) => void;
  onBranch: (id: string) => void;
  onSession: (id: string) => void;
  onNewChat: () => void;
  onQuickCreate: () => void;
  onPalette: () => void;
  onSettings: () => void;
  onTools: () => void;
  onTheme: () => void;
}

const navItems: Array<{ view: AppView; label: string; icon: ReactNode }> = [
  { view: "home", label: "Home", icon: <Home size={15} /> },
  { view: "chat", label: "Chat", icon: <MessageSquareText size={15} /> },
  { view: "manuscript", label: "Manuscript", icon: <FileText size={15} /> },
  { view: "library", label: "Library", icon: <Boxes size={15} /> },
  { view: "commands", label: "Commands", icon: <Command size={15} /> },
];

type ScopeKind = "project" | "world" | "branch";
type ScopeOption = { id: string; name: string };

export function Shell({
  children,
  view,
  theme,
  contrast,
  appearanceStyle,
  projects,
  worlds,
  activeProjectId,
  activeWorldId,
  activeBranchId,
  sessions,
  connectionLabel,
  onView,
  onProject,
  onWorld,
  onBranch,
  onSession,
  onNewChat,
  onQuickCreate,
  onPalette,
  onSettings,
  onTools,
  onTheme,
}: ShellProps) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [openScope, setOpenScope] = useState<ScopeKind | null>(null);
  const scopeRef = useRef<HTMLDivElement | null>(null);
  const activeProject = projects.find((item) => item.id === activeProjectId);
  const activeWorld = worlds.find((item) => item.id === activeWorldId);
  const branches = activeWorld?.branches || [];
  const [runtimeLabel, ...runtimeModelParts] = connectionLabel.split(" · ");
  const runtimeModel = runtimeModelParts.join(" · ") || "No model selected";
  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey)) return;
      if (event.key.toLowerCase() === "n") { event.preventDefault(); onQuickCreate(); }
    };
    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, [onQuickCreate]);

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

  const navigate = (nextView: AppView) => {
    onView(nextView);
    setMobileOpen(false);
  };

  return (
    <div className={`studio-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""} ${mobileOpen ? "mobile-sidebar-open" : ""}`} data-theme={theme} data-contrast={contrast} style={appearanceStyle}>
      <header className="studio-topbar">
        <div className="topbar-brand compact-brand">
          <button className="mobile-menu-button" aria-label="Toggle navigation" onClick={() => setMobileOpen((value) => !value)}><Menu className="mobile-menu-icon" size={16} /><span className="brand-mark mobile-menu-brand" aria-hidden="true" /></button>
          <span className="brand-mark topbar-brand-mark" aria-hidden="true" />
          <strong>Arline</strong>
        </div>

        <div ref={scopeRef} className="scope-crumbs" aria-label="Workspace scope">
          <ScopeMenu kind="project" label="Project" icon={<FolderKanban size={13} />} value={activeProjectId} options={projects} open={openScope === "project"} onToggle={() => setOpenScope((value) => value === "project" ? null : "project")} onSelect={onProject} />
          <ChevronRight className="scope-divider" size={12} />
          <ScopeMenu kind="world" label="World" icon={<Globe2 size={13} />} value={activeWorldId} options={worlds} open={openScope === "world"} onToggle={() => setOpenScope((value) => value === "world" ? null : "world")} onSelect={onWorld} />
          <ChevronRight className="scope-divider" size={12} />
          <ScopeMenu kind="branch" label="Branch" icon={<GitBranch size={13} />} value={activeBranchId} options={branches} open={openScope === "branch"} onToggle={() => setOpenScope((value) => value === "branch" ? null : "branch")} onSelect={onBranch} />
        </div>

        <button className="global-command" aria-label="Search or command" onClick={onPalette}>
          <Search size={14} />
          <span>Search or command</span>
          <kbd>Ctrl K</kbd>
        </button>

        <div className="topbar-tools">
          <button className="runtime-control" onClick={onSettings} title={`${runtimeLabel || "LM Studio"} · ${runtimeModel}. Open settings`}>
            <span className="runtime-status-dot" />
            <span className="runtime-copy"><small>{runtimeLabel || "LM Studio"}</small><strong>{runtimeModel}</strong></span>
            <ChevronRight size={13} />
          </button>
          <div className="topbar-action-group" aria-label="Studio controls">
            <button className="icon-control" onClick={onTools} title="Studio tools" aria-label="Activity, review, data, and developer tools"><LayoutDashboard size={16} /></button>
            <button className="icon-control" onClick={onTheme} title={theme === "dark" ? "Use light theme" : "Use dark theme"} aria-label="Toggle theme">
              {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
            </button>
            <button className="icon-control" onClick={onSettings} title="Settings" aria-label="Settings"><Settings2 size={16} /></button>
          </div>
        </div>
      </header>

      <aside className="studio-sidebar">
        <div className="sidebar-brand">
          <span className="brand-mark sidebar-brand-mark" role="img" aria-label="Arline" />
          <div><strong>Arline Studio</strong><small>Story workspace</small></div>
          <button className="sidebar-collapse" aria-label={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"} onClick={() => setSidebarCollapsed((value) => !value)}>{sidebarCollapsed ? <PanelLeftOpen size={14} /> : <PanelLeftClose size={14} />}</button>
        </div>

        <div className="sidebar-actions">
          <button className="sidebar-primary" onClick={() => { onNewChat(); setMobileOpen(false); }}><Plus size={15} /><span>New chat</span></button>
          <button onClick={() => { onQuickCreate(); setMobileOpen(false); }}><Plus size={14} /><span>Quick create</span></button>
        </div>

        <nav className="sidebar-nav">
          {navItems.map((item) => (
            <button key={item.view} className={view === item.view ? "active" : ""} onClick={() => navigate(item.view)}>
              {item.icon}<span>{item.label}</span>
            </button>
          ))}
        </nav>

        <section className="sidebar-section recent-section">
          <div className="sidebar-section-title"><span>Recent chats</span><MessageSquareText size={13} /></div>
          <div className="recent-list">
            {sessions.slice(0, 14).map((session) => (
              <button key={session.id} onClick={() => { onSession(session.id); setMobileOpen(false); }}>
                <span>{session.title || "Untitled chat"}</span>
                {session.pinned ? <b>•</b> : null}
              </button>
            ))}
            {!sessions.length && <div className="sidebar-empty">No chats in this scope.</div>}
          </div>
        </section>

        <div className="sidebar-footer">
          <div><span>Project</span><strong>{activeProject?.name || "No project"}</strong></div>
          <button className="icon-control" onClick={onSettings}><Settings2 size={15} /></button>
        </div>
      </aside>

      <main className="studio-main">{children}</main>
    </div>
  );
}

function ScopeMenu({ kind, label, icon, value, options, open, onToggle, onSelect }: { kind: ScopeKind; label: string; icon: ReactNode; value: string; options: ScopeOption[]; open: boolean; onToggle: () => void; onSelect: (id: string) => void }) {
  const selected = options.find((option) => option.id === value);
  const fallbackName = value ? humanizeScopeId(value, label) : `No ${label.toLowerCase()}`;
  const visibleOptions = selected || !value ? options : [{ id: value, name: fallbackName }, ...options];
  return <div className={`scope-control scope-${kind} ${open ? "open" : ""}`}>
    <button className="scope-trigger" aria-haspopup="listbox" aria-expanded={open} aria-label={`${label}: ${selected?.name || fallbackName}`} onClick={onToggle}>
      <span className="scope-control-icon">{icon}</span>
      <span className="scope-control-copy"><small>{label}</small><strong>{selected?.name || fallbackName}</strong></span>
      <ChevronDown className="scope-chevron" size={12} />
    </button>
    {open && <div className="scope-menu" role="listbox" aria-label={`Choose ${label.toLowerCase()}`}>
      <header><span>{icon}</span><div><small>Workspace scope</small><strong>Choose {label.toLowerCase()}</strong></div></header>
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
