import { useEffect, useState, type ReactNode } from "react";
import {
  Boxes,
  ChevronDown,
  Command,
  FileText,
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
import type { AppView, Project, Session, ThemeMode, World } from "../types";

interface ShellProps {
  children: ReactNode;
  view: AppView;
  theme: ThemeMode;
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

export function Shell({
  children,
  view,
  theme,
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
  const activeProject = projects.find((item) => item.id === activeProjectId);
  const activeWorld = worlds.find((item) => item.id === activeWorldId);
  const branches = activeWorld?.branches || [];
  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey)) return;
      if (event.key.toLowerCase() === "n") { event.preventDefault(); onQuickCreate(); }
    };
    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, [onQuickCreate]);

  const navigate = (nextView: AppView) => {
    onView(nextView);
    setMobileOpen(false);
  };

  return (
    <div className={`studio-shell ${sidebarCollapsed ? "sidebar-collapsed" : ""} ${mobileOpen ? "mobile-sidebar-open" : ""}`} data-theme={theme}>
      <header className="studio-topbar">
        <div className="topbar-brand compact-brand">
          <button className="mobile-menu-button" aria-label="Toggle navigation" onClick={() => setMobileOpen((value) => !value)}><Menu size={16} /></button>
          <img src="/static/assets/brand/arline-primary.svg" alt="" />
          <strong>Arline</strong>
        </div>

        <div className="scope-crumbs" aria-label="Workspace scope">
          <label className="scope-select">
            <span>Project</span>
            <select value={activeProjectId} onChange={(event) => onProject(event.target.value)}>
              {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
            </select>
            <ChevronDown size={12} />
          </label>
          <span className="scope-slash">/</span>
          <label className="scope-select">
            <span>World</span>
            <select value={activeWorldId} onChange={(event) => onWorld(event.target.value)}>
              {worlds.map((world) => <option key={world.id} value={world.id}>{world.name}</option>)}
            </select>
            <ChevronDown size={12} />
          </label>
          <span className="scope-slash">/</span>
          <label className="scope-select">
            <span>Branch</span>
            <select value={activeBranchId} onChange={(event) => onBranch(event.target.value)}>
              {branches.map((branch) => <option key={branch.id} value={branch.id}>{branch.name}</option>)}
            </select>
            <ChevronDown size={12} />
          </label>
        </div>

        <button className="global-command" aria-label="Search or command" onClick={onPalette}>
          <Search size={14} />
          <span>Search or command</span>
          <kbd>Ctrl K</kbd>
        </button>

        <div className="topbar-tools">
          <span className="connection-pill"><i />{connectionLabel}</span>
          <button className="icon-control" onClick={onTools} title="Activity, review, data, and developer tools"><LayoutDashboard size={16} /></button>
          <button className="icon-control" onClick={onTheme} title="Toggle theme">
            {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
          </button>
          <button className="icon-control" onClick={onSettings} title="Settings"><Settings2 size={16} /></button>
        </div>
      </header>

      <aside className="studio-sidebar">
        <div className="sidebar-brand">
          <img src="/static/assets/brand/arline-primary.svg" alt="Arline" />
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
