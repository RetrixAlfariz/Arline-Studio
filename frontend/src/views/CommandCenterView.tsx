import { useEffect, useMemo, useState } from "react";
import { Command, History, Plus, Search, Sparkles, Trash2 } from "lucide-react";
import { browserStorage, createClientId } from "../browserStorage";
import { studioApi } from "../api";
import type { CommandDefinition, JsonMap } from "../types";

interface Props { projectId: string; commands: CommandDefinition[]; registryVersion?: string; dynamicReferences?: string[]; referenceSelectors?: string[]; onUse: (command: CommandDefinition, compiledText?: string) => void; }
type Tab = "builtin" | "custom" | "profiles" | "references" | "history";
interface Recipe { id: string; command: string; name: string; description: string; steps: string; scope: string; project_id?: string; version: number; }
interface Store { recipes: Recipe[]; history: Array<{ id: string; command: string; compiled: string; created_at: string }>; }
const STORE_KEY = "arline.command-center.v1.2.5";
const loadStore = (): Store => { try { const parsed = JSON.parse(browserStorage.get(STORE_KEY) || "{}") as Store; return { history: parsed.history || [], recipes: (parsed.recipes || []).map((item) => ({ ...item, steps: Array.isArray(item.steps) ? item.steps.map((step: unknown) => String((step as JsonMap).value || "")).join("\n") : String(item.steps || "{{goal}}") })) }; } catch { return { recipes: [], history: [] }; } };

export function CommandCenterView({ projectId, commands, registryVersion, dynamicReferences, referenceSelectors, onUse }: Props) {
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<Tab>("builtin");
  const [store, setStore] = useState<Store>(loadStore);
  const [editing, setEditing] = useState<Recipe | null>(null);
  const [profiles, setProfiles] = useState<JsonMap[]>([]);
  const [recipes, setRecipes] = useState<JsonMap[]>([]);
  const [selectedCommandId, setSelectedCommandId] = useState("dia");
  const filtered = useMemo(() => { const needle = query.trim().toLowerCase(); return needle ? commands.filter((command) => [command.id, command.label, command.title, command.description, command.help, command.usage, ...(command.aliases || [])].filter(Boolean).some((value) => String(value).toLowerCase().includes(needle))) : commands; }, [commands, query]);
  const selectedCommand = useMemo(() => commands.find((command) => command.id === selectedCommandId) || filtered[0] || commands[0], [commands, filtered, selectedCommandId]);
  useEffect(() => { void Promise.all([studioApi.runProfiles(projectId).catch(() => ({ profiles: [] })), studioApi.contextRecipes(projectId).catch(() => ({ recipes: [] }))]).then(([a, b]) => { setProfiles(a.profiles || []); setRecipes(b.recipes || []); }); }, [projectId]);
  const persist = (next: Store) => { setStore(next); browserStorage.set(STORE_KEY, JSON.stringify(next)); };
  const saveRecipe = () => { if (!editing?.command.trim()) return; const normalized = { ...editing, command: editing.command.replace(/^\/+/, "").replace(/[^\w-]+/g, "-").toLowerCase(), project_id: editing.scope === "project" ? projectId : undefined }; persist({ ...store, recipes: [...store.recipes.filter((item) => item.id !== normalized.id), normalized] }); setEditing(null); };
  const compileRecipe = (recipe: Recipe, goal: string, depth = 0, trail: string[] = []): string => {
    if (depth >= 4 || trail.includes(recipe.id)) throw new Error("Recursive custom command detected");
    const lines = recipe.steps.split(/\r?\n/).filter(Boolean); if (lines.length > 32) throw new Error("Custom command exceeds 32 steps");
    return lines.map((line) => { const match = line.trim().match(/^\/([\w-]+)/); const nested = match ? store.recipes.find((item) => item.command === match[1]) : undefined; return nested ? compileRecipe(nested, goal, depth + 1, [...trail, recipe.id]) : line.replaceAll("{{goal}}", goal).replaceAll("{{project_id}}", projectId); }).join("\n");
  };
  const useCustom = (recipe: Recipe) => { try { const goal = window.prompt("Goal for this workflow", "") || ""; const compiled = compileRecipe(recipe, goal); persist({ ...store, history: [{ id: createClientId("command"), command: recipe.command, compiled, created_at: new Date().toISOString() }, ...store.history].slice(0, 100) }); onUse({ id: recipe.command, description: recipe.description }, compiled); } catch (error) { window.alert((error as Error).message); } };

  return <div className="page command-view">
    <section className="command-hero"><div><span className="eyebrow">Command Center</span><h1>Direct Arline explicitly</h1><p>Built-ins and reusable workflows compile into an ordinary generation request; they never grant Canon authority.</p></div><span className="version-chip">registry {registryVersion || "frontend fallback"}</span></section>
    <nav className="command-tabs">{(["builtin", "custom", "profiles", "references", "history"] as Tab[]).map((value) => <button key={value} className={tab === value ? "active" : ""} onClick={() => setTab(value)}>{value}</button>)}</nav>
    {tab === "builtin" && <>
      <label className="command-search"><Search size={16} /><input autoFocus value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search commands, operations, or references" /><kbd>Ctrl K</kbd></label>
      <div className="command-doc-layout">
        <section className="panel command-catalog"><div className="panel-heading"><div><span className="eyebrow">Built-in</span><h2>Commands</h2></div><Command size={15} /></div><div className="command-list">{filtered.map((command) => <button className={selectedCommand?.id === command.id ? "active" : ""} key={command.id} onClick={() => setSelectedCommandId(command.id)}><span className="command-slash">/</span><span><strong>/{command.id}</strong><small>{command.description || command.help || command.label || "Arline command"}</small></span><Sparkles size={13} /></button>)}{!filtered.length && <div className="empty-state">No commands match this search.</div>}</div></section>
        <CommandDocumentation command={selectedCommand} onUse={onUse} />
      </div>
    </>}
    {tab === "custom" && <section className="command-parity-panel"><header><div><span className="eyebrow">Reusable workflows</span><h2>Custom commands</h2></div><button className="primary-action small" onClick={() => setEditing({ id: createClientId("recipe"), command: "", name: "", description: "", steps: "{{goal}}", scope: "project", project_id: projectId, version: 1 })}><Plus size={13} />New</button></header>{editing && <div className="command-editor"><label>Name<input value={editing.name} onChange={(event) => setEditing({ ...editing, name: event.target.value })} /></label><label>Command<input value={editing.command} onChange={(event) => setEditing({ ...editing, command: event.target.value })} placeholder="scene-polish" /></label><label className="wide">Description<input value={editing.description} onChange={(event) => setEditing({ ...editing, description: event.target.value })} /></label><label className="wide">Compiled instruction<textarea value={editing.steps} onChange={(event) => setEditing({ ...editing, steps: event.target.value })} placeholder="Use {{goal}} inside a reusable instruction." /></label><div className="wide tools-actions"><button onClick={() => setEditing(null)}>Cancel</button><button className="primary-action small" onClick={saveRecipe}>Save recipe</button></div></div>}<div className="custom-command-list">{store.recipes.filter((item) => !item.project_id || item.project_id === projectId).map((recipe) => <article key={recipe.id}><button onClick={() => useCustom(recipe)}><code>/{recipe.command}</code><span><strong>{recipe.name || recipe.command}</strong><small>{recipe.description || "Custom workflow"}</small></span></button><button onClick={() => setEditing(recipe)}>Edit</button><button onClick={() => persist({ ...store, recipes: store.recipes.filter((item) => item.id !== recipe.id) })}><Trash2 size={12} /></button></article>)}</div></section>}
    {tab === "profiles" && <section className="command-parity-panel"><header><div><span className="eyebrow">Runtime</span><h2>Profiles & context recipes</h2></div></header><div className="profile-cards">{profiles.map((item) => <article key={String(item.id)}><strong>{String(item.name || item.id)}</strong><small>{String(item.description || "Run profile")}</small><pre>{JSON.stringify(item.profile || {}, null, 2)}</pre></article>)}{recipes.map((item) => <article key={String(item.id)}><strong>{String(item.name || item.id)}</strong><small>{String(item.description || "Context recipe")}</small><pre>{JSON.stringify(item.recipe || {}, null, 2)}</pre></article>)}</div></section>}
    {tab === "references" && <section className="command-parity-panel"><header><div><span className="eyebrow">Reference language</span><h2>Dynamic references & selectors</h2></div></header><div className="command-reference-grid"><div><h3>References</h3>{(dynamicReferences || []).map((value) => <code key={value}>@{value}</code>)}</div><div><h3>Selectors</h3>{(referenceSelectors || []).map((value) => <code key={value}>{value}</code>)}</div></div></section>}
    {tab === "history" && <section className="command-parity-panel"><header><div><span className="eyebrow"><History size={12} /> Local history</span><h2>Compiled workflows</h2></div></header><div className="history-list">{store.history.map((item) => <button key={item.id} onClick={() => onUse({ id: item.command }, item.compiled)}><strong>/{item.command}</strong><small>{item.created_at}</small><pre>{item.compiled}</pre></button>)}</div></section>}
  </div>;
}

function CommandDocumentation({ command, onUse }: { command?: CommandDefinition; onUse: Props["onUse"] }) {
  if (!command) return <section className="panel command-detail"><div className="empty-state">Select a command to inspect how it is used.</div></section>;
  const contract = command.execution_contract || {};
  const weights = Object.entries(contract.retrieval_weights || {}).sort((a, b) => b[1] - a[1]);
  const examples = command.examples || [];
  const syntax = command.syntax || command.usage || command.text || command.label || `/${command.id}`;
  return <article className="panel command-detail">
    <header><div><span className="eyebrow">{command.category || "Command"} · {command.role || "operation"}</span><h2>{command.label || `/${command.id}`}</h2><p>{command.description || "Arline command"}</p></div><button className="primary-action small" onClick={() => onUse(command, syntax)}><Sparkles size={13} />Use command</button></header>
    <section><h3>Why use this?</h3><p>{command.why_use || "Use this typed command when you want Arline to apply a known runtime profile instead of relying only on prose instructions."}</p></section>
    <section><h3>Syntax</h3><code className="command-syntax">{syntax}</code></section>
    {!!command.arguments?.length && <section><h3>Arguments</h3>{command.arguments.map((argument, index) => <div className="command-schema-row" key={`${argument.name}-${index}`}><code>{argument.name || "argument"}</code><span>{argument.kind || "text"}{argument.required ? " · required" : ""}{argument.variadic ? " · multiple" : ""}</span><span>{argument.description || "Semantic command input"}</span></div>)}</section>}
    {!!command.options?.length && <section><h3>Options</h3>{command.options.map((option, index) => <div className="command-schema-row" key={`${option.name}-${index}`}><code>{option.name || "option"}</code><span>{option.kind || "value"}</span><span>{option.choices?.length ? option.choices.map(String).join(" · ") : option.description || "Free value"}{option.default !== undefined && option.default !== null ? ` · default: ${String(option.default)}` : ""}</span></div>)}</section>}
    <section><h3>What Arline does</h3>{weights.length ? weights.map(([name, value]) => <div className="command-weight" key={name}><span>{name.replaceAll("_", " ")}</span><span><i style={{ width: `${Math.round(value * 100)}%` }} /></span><strong>{value.toFixed(2)}</strong></div>) : <p>No custom retrieval weighting is required.</p>}<div className="command-schema-row"><code>deliberation</code><span>profile</span><span>{contract.deliberation_profile || command.deliberation_mode || "auto"}</span></div><div className="command-schema-row"><code>realization</code><span>profile</span><span>{contract.realization_profile || command.output_mode || "fiction"}</span></div></section>
    <section><h3>Authority</h3><div className="command-authority"><span className="allowed">✓ Temporary request steering</span><span className="allowed">✓ Context grounding within scope</span><span className="denied">✕ Cannot overwrite Canon</span><span className="denied">✕ Cannot silently resolve conflicts</span></div></section>
    {!!examples.length && <section><h3>Examples</h3><div className="command-examples">{examples.map((example) => <div key={example}><code>{example}</code><button onClick={() => onUse(command, example)}>Use</button></div>)}</div></section>}
  </article>;
}
