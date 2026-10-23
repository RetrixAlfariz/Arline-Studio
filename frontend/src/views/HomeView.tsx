import { AlertTriangle, ArrowRight, BookOpenText, CheckCircle2, GitBranch, MapPinned, MessageSquareText, PenLine, Sparkles, Users } from "lucide-react";
import type { ReactNode } from "react";
import type { DocumentItem, Project, ProjectTree, Session, WorldBible } from "../types";

interface HomeViewProps {
  project?: Project;
  documents: DocumentItem[];
  sessions: Session[];
  bible: WorldBible | null;
  tree: ProjectTree | null;
  onOpenChat: (id?: string) => void;
  onOpenDocument: (id: string) => void;
  onManuscript: () => void;
  onLibrary: () => void;
  onQuickCreate: () => void;
  onStartPrompt: (prompt: string) => void;
}

export function HomeView({ project, documents, sessions, bible, tree, onOpenChat, onOpenDocument, onManuscript, onLibrary, onQuickCreate, onStartPrompt }: HomeViewProps) {
  const recentDocs = [...documents].sort((a, b) => String(b.updated_at || b.created_at || "").localeCompare(String(a.updated_at || a.created_at || ""))).slice(0, 4);
  const recentSessions = sessions.slice(0, 4);
  const families = bible?.families || [];
  const entityCount = families.length;
  const relationCount = bible?.relationships?.length || 0;
  const conflicts = tree?.conflicts || [];

  return (
    <div className="page home-view">
      <section className="hero-panel home-hero">
        <div><span className="eyebrow">Story workspace</span><h1>{project?.name || "Arline Studio"}</h1><p>{project?.description || "Build the next scene while Arline keeps your manuscript, world, and narrative context connected."}</p></div>
        <div className="home-hero-actions"><button className="primary-action" onClick={onQuickCreate}><Sparkles size={15} />Quick create</button><button className="secondary-action" onClick={() => onOpenChat()}><MessageSquareText size={15} />New conversation</button><button className="secondary-action" onClick={onManuscript}><PenLine size={15} />Manuscript</button></div>
      </section>

      <section className="home-section" aria-labelledby="overview-title">
        <div className="home-section-heading"><div><span className="eyebrow">Overview</span><h2 id="overview-title">Your story at a glance</h2></div><small>Live workspace totals</small></div>
        <div className="home-metrics">
          <Metric icon={<MessageSquareText size={17} />} value={sessions.length} label="Conversations" support={sessions.length ? "Continue a recent thread" : "Start your first scoped chat"} onClick={() => onOpenChat()} />
          <Metric icon={<PenLine size={17} />} value={documents.length} label="Manuscript files" support={documents.length ? "Scenes, chapters, and notes" : "Create a scene or chapter"} onClick={() => recentDocs[0] ? onOpenDocument(recentDocs[0].id) : onManuscript()} />
          <Metric icon={<Users size={17} />} value={entityCount} label="Library sheets" support={entityCount ? "Characters, places, and lore" : "Build your world reference"} onClick={onLibrary} />
          <Metric icon={<GitBranch size={17} />} value={relationCount} label="Relationships" support={relationCount ? "Connections in this world" : "Map story connections"} onClick={onLibrary} />
        </div>
      </section>

      <section className="home-section" aria-labelledby="continue-title">
        <div className="home-section-heading"><div><span className="eyebrow">Continue</span><h2 id="continue-title">Pick up where you left off</h2></div></div>
        <div className="home-grid">
          <section className="panel"><div className="panel-heading"><div><span className="eyebrow">Manuscript</span><h2>Recent writing</h2></div><PenLine size={15} /></div><div className="stack-list">
            {recentDocs.map((doc) => <button className="stack-row" key={doc.id} onClick={() => onOpenDocument(doc.id)}><span className="row-glyph"><PenLine size={14} /></span><span><strong>{doc.title}</strong><small>{doc.document_type || "document"} · {doc.status || "planned"}</small></span><ArrowRight size={13} /></button>)}
            {!recentDocs.length && <ActionEmpty icon={<PenLine size={17} />} title="No manuscript files yet" copy="Begin with a scene, chapter, note, or outline." action="Create writing" onAction={onQuickCreate} />}
          </div></section>
          <section className="panel"><div className="panel-heading"><div><span className="eyebrow">Chat</span><h2>Recent conversations</h2></div><MessageSquareText size={15} /></div><div className="stack-list">
            {recentSessions.map((session) => <button className="stack-row" key={session.id} onClick={() => onOpenChat(session.id)}><span className="row-glyph"><MessageSquareText size={14} /></span><span><strong>{session.title}</strong><small>{session.parent_session_id ? "fork" : "canon-aware chat"}{session.scratch_mode ? " · scratch" : ""}</small></span><ArrowRight size={13} /></button>)}
            {!recentSessions.length && <ActionEmpty icon={<MessageSquareText size={17} />} title="No conversations yet" copy="Start a conversation inside the active story scope." action="Start conversation" onAction={() => onOpenChat()} />}
          </div></section>
        </div>
      </section>

      <section className="home-section" aria-labelledby="world-title">
        <div className="home-section-heading"><div><span className="eyebrow">World state</span><h2 id="world-title">Canon and continuity</h2></div><button className="text-action" onClick={onLibrary}>Open Library <ArrowRight size={13} /></button></div>
        <div className="home-grid home-world-grid">
          <section className="panel"><div className="panel-heading"><div><span className="eyebrow">Continuity</span><h2>Workspace review</h2></div>{conflicts.length ? <AlertTriangle size={15} /> : <CheckCircle2 size={15} />}</div><div className="stack-list">
            {conflicts.slice(0, 4).map((item, index) => <button className="stack-row" key={String(item.id || index)} onClick={onLibrary}><span className="row-glyph">!</span><span><strong>{String(item.title || item.path || "Canon conflict")}</strong><small>{String(item.conflict_class || "needs review")}</small></span><ArrowRight size={13} /></button>)}
            {!conflicts.length && <ActionEmpty icon={<CheckCircle2 size={17} />} title="No unresolved conflicts" copy="Run a focused continuity pass before your next major scene." action="Run continuity check" onAction={() => onStartPrompt("Review the active world and branch for continuity risks before I continue writing.")} />}
          </div></section>
          <section className="panel"><div className="panel-heading"><div><span className="eyebrow">Pinned</span><h2>Fast access</h2></div><MapPinned size={15} /></div><div className="quick-links">
            <QuickLink icon={<MessageSquareText size={15} />} title="New conversation" copy="Open a scoped writing chat" onClick={() => onOpenChat()} /><QuickLink icon={<Sparkles size={15} />} title="Quick create" copy="Add a scene, chapter, or entity" onClick={onQuickCreate} /><QuickLink icon={<PenLine size={15} />} title="Manuscript" copy="Open the writing workspace" onClick={onManuscript} /><QuickLink icon={<BookOpenText size={15} />} title="Library" copy="Inspect canon and relationships" onClick={onLibrary} />
          </div></section>
          <section className="panel span-two"><div className="panel-heading"><div><span className="eyebrow">Library</span><h2>World at a glance</h2></div><BookOpenText size={15} /></div><div className="library-summary-grid">
            {families.slice(0, 8).map((family) => <button key={family.id} onClick={onLibrary}><span>{family.entity_type || "entity"}</span><strong>{family.name}</strong><small>{family.description || "Shared Library sheet"}</small></button>)}
            {!entityCount && <ActionEmpty icon={<BookOpenText size={18} />} title="Your Library is ready to grow" copy="Create a character, location, item, or lore sheet to anchor future scenes." action="Quick create" onAction={onQuickCreate} />}
          </div></section>
        </div>
      </section>
    </div>
  );
}

function Metric({ icon, value, label, support, onClick }: { icon: ReactNode; value: number; label: string; support: string; onClick: () => void }) { return <button onClick={onClick}>{icon}<span><strong>{value}</strong><small>{label}</small><em>{support}</em></span></button>; }
function ActionEmpty({ icon, title, copy, action, onAction }: { icon: ReactNode; title: string; copy: string; action: string; onAction: () => void }) { return <div className="action-empty"><span>{icon}</span><div><strong>{title}</strong><small>{copy}</small></div><button onClick={onAction}>{action}<ArrowRight size={12} /></button></div>; }
function QuickLink({ icon, title, copy, onClick }: { icon: ReactNode; title: string; copy: string; onClick: () => void }) { return <button onClick={onClick}>{icon}<span><strong>{title}</strong><small>{copy}</small></span><ArrowRight size={12} /></button>; }
