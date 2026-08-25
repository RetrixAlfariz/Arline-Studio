import type { ReactNode } from "react";
import {
  BookOpenText,
  Boxes,
  ChevronDown,
  Command,
  FileText,
  Home,
  MessageSquareText,
  Moon,
  Plus,
  Search,
  Settings2,
  Sun,
  Clock3,
} from "lucide-react";
import type { AppView, Project, Session, ThemeMode, World, WorldBible } from "../types";

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
  bible: WorldBible | null;
  connectionLabel: string;
  onView: (view: AppView) => void;
  onProject: (id: string) => void;
  onWorld: (id: string) => void;
  onBranch: (id: string) => void;
  onSession: (id: string) => void;
  onNewChat: () => void;
  onQuickCreate: () => void;
  onSettings: () => void;
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
  bible,
  connectionLabel,
  onView,
  onProject,
  onWorld,
  onBranch,
  onSession,
  onNewChat,
  onQuickCreate,
  onSettings,
  onTheme,
}: ShellProps) {
  const activeProject = projects.find((item) => item.id === activeProjectId);
  const activeWorld = worlds.find((item) => item.id === activeWorldId);
  const branches = activeWorld?.branches || [];
  const families = bible?.families || [];
  const characterCount = families.filter((item) => item.entity_type === "character").length;
  const locationCount = families.filter((item) => item.entity_type === "location").length;
  const itemCount = families.filter((item) => item.entity_type === "item").length;

  return (
    <div className="studio-shell" data-theme={theme}>
      <header className="studio-topbar">
        <div className="topbar-brand compact-brand">
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

        <button className="global-command" onClick={() => onView("commands")}>
          <Search size={14} />
          <span>Search or command</span>
          <kbd>Ctrl K</kbd>
        </button>

        <div className="topbar-tools">
          <span className="connection-pill"><i />{connectionLabel}</span>
          <button className="icon-control" onClick={onTheme} title="Toggle theme">
            {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
          </button>
          <button className="icon-control" onClick={onSettings} title="Settings"><Settings2 size={16} /></button>
        </div>
      </header>

      <aside className="studio-sidebar">
        <div className="sidebar-brand">
          <img src="/static/assets/brand/arline-primary.svg" alt="Arline" />
          <div><strong>Arline Studio</strong><small>React workspace</small></div>
        </div>

        <div className="sidebar-actions">
          <button className="sidebar-primary" onClick={onNewChat}><Plus size={15} /><span>New chat</span></button>
          <button onClick={onQuickCreate}><Plus size={14} /><span>Quick create</span></button>
        </div>

        <nav className="sidebar-nav">
          {navItems.map((item) => (
            <button key={item.view} className={view === item.view ? "active" : ""} onClick={() => onView(item.view)}>
              {item.icon}<span>{item.label}</span>
            </button>
          ))}
        </nav>

        <section className="sidebar-section">
          <div className="sidebar-section-title"><span>Library</span><BookOpenText size={13} /></div>
          <button className="metric-nav" onClick={() => onView("library")}><span>Characters</span><em>{characterCount}</em></button>
          <button className="metric-nav" onClick={() => onView("library")}><span>Locations</span><em>{locationCount}</em></button>
          <button className="metric-nav" onClick={() => onView("library")}><span>Items</span><em>{itemCount}</em></button>
          <button className="metric-nav" onClick={() => onView("library")}><span>Relationships</span><em>{bible?.relationships?.length || 0}</em></button>
          <button className="metric-nav" onClick={() => onView("library")}><span>Lore & rules</span><em>{families.filter((item) => item.entity_type === "lore").length}</em></button>
          <button className="metric-nav" onClick={() => onView("library")}><span>Timeline</span><em><Clock3 size={12} /></em></button>
        </section>

        <section className="sidebar-section recent-section">
          <div className="sidebar-section-title"><span>Recent chats</span><MessageSquareText size={13} /></div>
          <div className="recent-list">
            {sessions.slice(0, 14).map((session) => (
              <button key={session.id} onClick={() => onSession(session.id)}>
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
