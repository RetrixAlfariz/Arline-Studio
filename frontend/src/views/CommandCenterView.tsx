import { useMemo, useState } from "react";
import { Command, Search, Sparkles } from "lucide-react";
import type { CommandDefinition } from "../types";

interface CommandCenterViewProps {
  commands: CommandDefinition[];
  registryVersion?: string;
  dynamicReferences?: string[];
  referenceSelectors?: string[];
  onUse: (command: CommandDefinition) => void;
}

export function CommandCenterView({ commands, registryVersion, dynamicReferences, referenceSelectors, onUse }: CommandCenterViewProps) {
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return commands;
    return commands.filter((command) => [command.id, command.label, command.title, command.description, command.help, command.usage, ...(command.aliases || [])]
      .filter(Boolean).some((value) => String(value).toLowerCase().includes(needle)));
  }, [commands, query]);

  return (
    <div className="page command-view">
      <section className="command-hero">
        <div><span className="eyebrow">Command Center</span><h1>Direct Arline explicitly</h1><p>Commands are typed execution contracts, not magic prompt incantations. Civilization advances one schema at a time.</p></div>
        <span className="version-chip">registry {registryVersion || "frontend fallback"}</span>
      </section>
      <label className="command-search"><Search size={16} /><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search commands, operations, or references" /><kbd>Ctrl K</kbd></label>

      <div className="command-grid">
        <section className="panel command-catalog">
          <div className="panel-heading"><div><span className="eyebrow">Built-in</span><h2>Commands</h2></div><Command size={15} /></div>
          <div className="command-list">
            {filtered.map((command) => (
              <button key={command.id} onClick={() => onUse(command)}>
                <span className="command-slash">/</span>
                <span><strong>/{command.id}</strong><small>{command.description || command.help || command.label || "Arline command"}</small>{command.usage ? <code>{command.usage}</code> : null}</span>
                <Sparkles size={13} />
              </button>
            ))}
            {!filtered.length && <div className="empty-state">No commands match this search.</div>}
          </div>
        </section>

        <aside className="command-reference">
          <section className="panel compact-panel"><div className="panel-heading"><div><span className="eyebrow">Dynamic</span><h2>References</h2></div></div><div className="token-cloud">{(dynamicReferences || []).map((value) => <code key={value}>@{value}</code>)}</div></section>
          <section className="panel compact-panel"><div className="panel-heading"><div><span className="eyebrow">Selectors</span><h2>Reference depth</h2></div></div><div className="token-cloud">{(referenceSelectors || []).map((value) => <code key={value}>{value}</code>)}</div></section>
          <section className="panel compact-panel"><div className="panel-heading"><div><span className="eyebrow">How it works</span><h2>Composition</h2></div></div><p className="panel-copy">Multiple compatible directives can compose into one execution contract before generation. Invalid combinations are rejected by the Python directive engine rather than becoming decorative prompt text.</p></section>
        </aside>
      </div>
    </div>
  );
}
