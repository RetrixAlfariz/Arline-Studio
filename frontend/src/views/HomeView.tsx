import { ArrowRight, BookOpenText, MessageSquareText, PenLine, Sparkles } from "lucide-react";
import type { DocumentItem, Project, Session, WorldBible } from "../types";

interface HomeViewProps {
  project?: Project;
  documents: DocumentItem[];
  sessions: Session[];
  bible: WorldBible | null;
  onOpenChat: (id?: string) => void;
  onOpenDocument: (id: string) => void;
  onLibrary: () => void;
  onQuickCreate: () => void;
}

export function HomeView({ project, documents, sessions, bible, onOpenChat, onOpenDocument, onLibrary, onQuickCreate }: HomeViewProps) {
  const recentDocs = [...documents].sort((a, b) => String(b.updated_at || b.created_at || "").localeCompare(String(a.updated_at || a.created_at || ""))).slice(0, 5);
  const recentSessions = sessions.slice(0, 5);
  const entityCount = bible?.families?.length || 0;
  const relationCount = bible?.relationships?.length || 0;

  return (
    <div className="page home-view">
      <section className="hero-panel">
        <div>
          <span className="eyebrow">Workspace</span>
          <h1>{project?.name || "Arline Studio"}</h1>
          <p>{project?.description || "Write, inspect your world, and keep narrative context deliberate."}</p>
        </div>
        <button className="primary-action" onClick={onQuickCreate}><Sparkles size={15} />Quick create</button>
      </section>

      <div className="home-metrics">
        <button onClick={() => onOpenChat()}><MessageSquareText size={16} /><span><strong>{sessions.length}</strong><small>Chats</small></span></button>
        <button onClick={() => recentDocs[0] && onOpenDocument(recentDocs[0].id)}><PenLine size={16} /><span><strong>{documents.length}</strong><small>Manuscript files</small></span></button>
        <button onClick={onLibrary}><BookOpenText size={16} /><span><strong>{entityCount}</strong><small>Library sheets</small></span></button>
        <button onClick={onLibrary}><ArrowRight size={16} /><span><strong>{relationCount}</strong><small>Relations</small></span></button>
      </div>

      <div className="home-grid">
        <section className="panel">
          <div className="panel-heading"><div><span className="eyebrow">Continue</span><h2>Recent manuscript</h2></div><PenLine size={15} /></div>
          <div className="stack-list">
            {recentDocs.map((doc) => (
              <button className="stack-row" key={doc.id} onClick={() => onOpenDocument(doc.id)}>
                <span className="row-glyph"><PenLine size={14} /></span>
                <span><strong>{doc.title}</strong><small>{doc.document_type || "document"} · {doc.status || "planned"}</small></span>
                <ArrowRight size={13} />
              </button>
            ))}
            {!recentDocs.length && <div className="empty-state">No manuscript files yet. Quick Create can make the first one without asking you to manually worship a schema.</div>}
          </div>
        </section>

        <section className="panel">
          <div className="panel-heading"><div><span className="eyebrow">Continue</span><h2>Recent conversations</h2></div><MessageSquareText size={15} /></div>
          <div className="stack-list">
            {recentSessions.map((session) => (
              <button className="stack-row" key={session.id} onClick={() => onOpenChat(session.id)}>
                <span className="row-glyph"><MessageSquareText size={14} /></span>
                <span><strong>{session.title}</strong><small>{session.parent_session_id ? "fork" : "chat"}{session.scratch_mode ? " · scratch" : ""}</small></span>
                <ArrowRight size={13} />
              </button>
            ))}
            {!recentSessions.length && <div className="empty-state">No conversations in the current scope.</div>}
          </div>
        </section>

        <section className="panel span-two">
          <div className="panel-heading"><div><span className="eyebrow">World state</span><h2>Library at a glance</h2></div><BookOpenText size={15} /></div>
          <div className="library-summary-grid">
            {(bible?.families || []).slice(0, 8).map((family) => (
              <button key={family.id} onClick={onLibrary}>
                <span>{family.entity_type || "entity"}</span>
                <strong>{family.name}</strong>
                <small>{family.description || "Shared Library sheet"}</small>
              </button>
            ))}
            {!entityCount && <div className="empty-state">The Library is empty in this scope.</div>}
          </div>
        </section>
      </div>
    </div>
  );
}
