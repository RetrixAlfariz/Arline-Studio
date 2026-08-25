import { useEffect, useState } from "react";
import { Activity, ArchiveRestore, BrainCircuit, Database, Download, FlaskConical, Search, ShieldCheck, Upload, X } from "lucide-react";
import { runtimePayload, studioApi } from "../api";
import type { JsonMap, RuntimeConfig } from "../types";

type ToolTab = "workspace" | "review" | "data" | "developer" | "memory";

interface StudioToolsDrawerProps {
  open: boolean;
  projectId: string;
  worldId: string;
  branchId: string;
  config: RuntimeConfig;
  onClose: () => void;
  onChanged: () => Promise<void> | void;
}

const asItems = (value: unknown, ...keys: string[]): JsonMap[] => {
  if (Array.isArray(value)) return value as JsonMap[];
  const object = (value || {}) as JsonMap;
  for (const key of keys) if (Array.isArray(object[key])) return object[key] as JsonMap[];
  return [];
};

const labelOf = (item: JsonMap) => String(item.title || item.name || item.label || item.summary || item.id || "Untitled");

export function StudioToolsDrawer({ open, projectId, worldId, branchId, config, onClose, onChanged }: StudioToolsDrawerProps) {
  const [tab, setTab] = useState<ToolTab>("workspace");
  const [status, setStatus] = useState("");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<JsonMap[]>([]);
  const [activity, setActivity] = useState<JsonMap[]>([]);
  const [issues, setIssues] = useState<JsonMap[]>([]);
  const [staged, setStaged] = useState<JsonMap[]>([]);
  const [conflicts, setConflicts] = useState<JsonMap[]>([]);
  const [queue, setQueue] = useState<JsonMap[]>([]);
  const [comparisons, setComparisons] = useState<JsonMap[]>([]);
  const [stats, setStats] = useState<JsonMap>({});
  const [backups, setBackups] = useState<JsonMap[]>([]);
  const [trash, setTrash] = useState<JsonMap[]>([]);
  const [importTitle, setImportTitle] = useState("Imported manuscript");
  const [importText, setImportText] = useState("");
  const [importPreview, setImportPreview] = useState<JsonMap | null>(null);
  const [contract, setContract] = useState("");
  const [ablationPrompt, setAblationPrompt] = useState("");
  const [developerOutput, setDeveloperOutput] = useState<unknown>(null);
  const [traceCacheId, setTraceCacheId] = useState("");
  const [traceId, setTraceId] = useState("");
  const [memoryQuery, setMemoryQuery] = useState("");
  const [memoryOutput, setMemoryOutput] = useState<unknown>(null);
  const [contextStack, setContextStack] = useState("");

  const refreshWorkspace = async () => {
    const [activityResult, issueResult, stackResult, stagedResult, conflictResult] = await Promise.all([
      studioApi.activity(projectId).catch(() => ({ items: [] })),
      studioApi.issues(projectId).catch(() => ({ issues: [] })),
      studioApi.contextStack().catch(() => ({})),
      studioApi.stagedChanges(projectId).catch(() => ({ changes: [] })),
      studioApi.conflicts(projectId).catch(() => ({ conflicts: [] })),
    ]);
    setActivity(asItems(activityResult, "items", "activity"));
    setIssues(asItems(issueResult, "issues", "items"));
    setContextStack(JSON.stringify(stackResult, null, 2));
    setStaged(asItems(stagedResult, "changes", "items"));
    setConflicts(asItems(conflictResult, "conflicts", "items"));
  };

  const refreshReview = async () => {
    const [queueResult, comparisonsResult, statsResult] = await Promise.all([
      studioApi.feedbackQueue(projectId).catch(() => ({ items: [] })),
      studioApi.feedbackComparisons(projectId).catch(() => ({ items: [] })),
      studioApi.datasetStats().catch(() => ({})),
    ]);
    setQueue(asItems(queueResult, "items", "queue"));
    setComparisons(asItems(comparisonsResult, "items", "comparisons"));
    setStats(statsResult);
  };

  const refreshData = async () => {
    const [backupResult, trashResult] = await Promise.all([studioApi.backups().catch(() => ({ backups: [] })), studioApi.trashItems().catch(() => ({ items: [] }))]);
    setBackups(asItems(backupResult, "backups", "items"));
    setTrash(asItems(trashResult, "items", "trash"));
  };

  useEffect(() => {
    if (!open) return;
    setStatus("");
    if (tab === "workspace") void refreshWorkspace();
    if (tab === "review") void refreshReview();
    if (tab === "data") void refreshData();
    if (tab === "developer") void studioApi.contract().then((result) => setContract(result.content || "")).catch((error: Error) => setStatus(error.message));
    if (tab === "memory") void studioApi.memoryStatus().then(setMemoryOutput).catch((error: Error) => setStatus(error.message));
  }, [open, tab, projectId]);

  if (!open) return null;

  const search = async () => {
    if (!query.trim()) return setResults([]);
    const result = await studioApi.search(query.trim(), projectId);
    setResults(asItems(result, "results", "items"));
  };

  const reviewTurn = async (item: JsonMap, reviewStatus: "accepted" | "rejected") => {
    const turnId = String(item.turn_id || item.id || "");
    if (!turnId) return;
    await studioApi.feedback(turnId, { status: reviewStatus, issues: [], note: "Reviewed in React Studio", edited_story: "" });
    await refreshReview();
  };

  const previewImport = async () => setImportPreview(await studioApi.importPreview({ project_id: projectId, title: importTitle, text: importText, split_headings: true, default_type: "scene" }));
  const commitImport = async () => {
    await studioApi.importManuscript({ project_id: projectId, title: importTitle, text: importText, split_headings: true, default_type: "scene" });
    setStatus("Manuscript imported"); setImportText(""); setImportPreview(null); await onChanged();
  };

  const saveStack = async () => {
    const parsed = JSON.parse(contextStack) as Record<string, unknown>;
    await studioApi.saveContextStack({ ...parsed, stack_id: String(parsed.stack_id || "default"), project_id: projectId, world_id: worldId || null, branch_id: branchId || null });
    setStatus("Context stack saved");
  };

  const runAblation = async () => {
    const payload = runtimePayload(config, { projectId, worldId, branchId }, ablationPrompt, []);
    setDeveloperOutput(await studioApi.ablation(payload));
  };

  return <>
    <div className="drawer-scrim" onMouseDown={onClose} />
    <aside className="studio-tools-drawer">
      <header><div><span className="eyebrow">Parity workspace</span><h2>Studio tools</h2></div><button className="icon-control" onClick={onClose}><X size={16} /></button></header>
      <nav>
        <button className={tab === "workspace" ? "active" : ""} onClick={() => setTab("workspace")}><Activity size={14} />Workspace</button>
        <button className={tab === "review" ? "active" : ""} onClick={() => setTab("review")}><ShieldCheck size={14} />Review & Evals</button>
        <button className={tab === "data" ? "active" : ""} onClick={() => setTab("data")}><Database size={14} />Data</button>
        <button className={tab === "developer" ? "active" : ""} onClick={() => setTab("developer")}><FlaskConical size={14} />Developer</button>
        <button className={tab === "memory" ? "active" : ""} onClick={() => setTab("memory")}><BrainCircuit size={14} />Memory</button>
      </nav>
      <main>
        {tab === "workspace" && <div className="tools-stack">
          <ToolHeading title="Search everything" copy="Search chats, documents, Library resources, worlds, and commands." />
          <div className="tools-search"><Search size={14} /><input value={query} onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void search(); }} placeholder="Search workspace" /><button onClick={() => void search()}>Search</button></div>
          <ToolList title="Results" items={results} />
          <div className="tools-columns"><ToolList title="Activity" items={activity} /><section className="tools-list"><h3>Issues</h3>{issues.map((item) => <article key={String(item.id)}><div><strong>{labelOf(item)}</strong><small>{String(item.severity || item.issue_type || "issue")}</small></div><button onClick={async () => { await studioApi.resolveIssue(String(item.id)); await refreshWorkspace(); }}>Resolve</button></article>)}{!issues.length && <p>No unresolved issues.</p>}</section></div>
          <div className="tools-columns"><section className="tools-list"><h3>Staged canon changes</h3>{staged.map((item) => <article key={String(item.id)}><div><strong>{String(item.path || item.title || item.id)}</strong><small>{JSON.stringify(item.proposed_value)}</small></div><span><button onClick={async () => { await studioApi.resolveStagedChange(String(item.id), true); await refreshWorkspace(); }}>Accept</button><button onClick={async () => { await studioApi.resolveStagedChange(String(item.id), false); await refreshWorkspace(); }}>Reject</button></span></article>)}{!staged.length && <p>No staged changes.</p>}</section><section className="tools-list"><h3>Canon conflicts</h3>{conflicts.map((item) => <article key={String(item.id)}><div><strong>{String(item.path || item.title || item.id)}</strong><small>{String(item.conflict_class || "conflict")}</small></div><button onClick={async () => { await studioApi.resolveConflict(String(item.id), { resolution_type: "choose_right", chosen_value: item.right, note: "resolved in React Studio" }); await refreshWorkspace(); }}>Use right</button></article>)}{!conflicts.length && <p>No unresolved conflicts.</p>}</section></div>
          <label className="tools-field"><span>Context stack JSON</span><textarea value={contextStack} onChange={(event) => setContextStack(event.target.value)} /></label><button className="primary-action small" onClick={() => void saveStack()}>Save context stack</button>
        </div>}
        {tab === "review" && <div className="tools-stack">
          <ToolHeading title="Feedback Lab" copy="Generated output remains reviewable before it becomes evaluation data." />
          <pre className="tools-json compact">{JSON.stringify(stats, null, 2)}</pre>
          <section className="tools-list"><h3>Review queue</h3>{queue.map((item) => <article key={String(item.turn_id || item.id)}><div><strong>{labelOf(item)}</strong><small>{String(item.model || item.status || "pending")}</small></div><span><button onClick={() => void reviewTurn(item, "accepted")}>Accept</button><button onClick={() => void reviewTurn(item, "rejected")}>Reject</button></span></article>)}{!queue.length && <p>Nothing waiting for review.</p>}</section>
          <ToolList title="Comparisons" items={comparisons} />
          <div className="tools-actions">{["master", "sft", "preference", "eval"].map((kind) => <a key={kind} href={studioApi.exportDatasetUrl(kind)}><Download size={13} />Export {kind}</a>)}</div>
        </div>}
        {tab === "data" && <div className="tools-stack">
          <ToolHeading title="Import & export" copy="Preview heading splits before importing an existing manuscript." />
          <label className="tools-field"><span>Import title</span><input value={importTitle} onChange={(event) => setImportTitle(event.target.value)} /></label>
          <label className="tools-field"><span>Markdown or plain text</span><textarea value={importText} onChange={(event) => setImportText(event.target.value)} /></label>
          <div className="tools-actions"><button onClick={() => void previewImport()}><Upload size={13} />Preview</button><button className="primary-action small" disabled={!importText.trim()} onClick={() => void commitImport()}>Import</button><a href={studioApi.exportProjectUrl(projectId)}><Download size={13} />Project</a><a href={studioApi.exportWorldBibleUrl(projectId, worldId)}><Download size={13} />World Bible</a></div>
          {importPreview && <pre className="tools-json compact">{JSON.stringify(importPreview, null, 2)}</pre>}
          <div className="tools-columns"><ToolList title="Migration backups" items={backups} /><section className="tools-list"><h3>Trash</h3>{trash.map((item) => <article key={`${String(item.resource_type)}:${String(item.resource_id || item.id)}`}><div><strong>{labelOf(item)}</strong><small>{String(item.resource_type || item.kind || "resource")}</small></div><button onClick={async () => { await studioApi.lifecycle("restore", String(item.resource_type), String(item.resource_id || item.id)); await refreshData(); await onChanged(); }}><ArchiveRestore size={13} />Restore</button></article>)}{!trash.length && <p>Trash is empty.</p>}</section></div>
        </div>}
        {tab === "developer" && <div className="tools-stack">
          <ToolHeading title="Contract & diagnostics" copy="Edit the writer contract and run the backend ablation pipeline." />
          <label className="tools-field"><span>Writer contract</span><textarea value={contract} onChange={(event) => setContract(event.target.value)} /></label><button onClick={async () => { await studioApi.saveContract(contract); setStatus("Contract saved"); }}>Save contract</button>
          <label className="tools-field"><span>Ablation prompt</span><textarea value={ablationPrompt} onChange={(event) => setAblationPrompt(event.target.value)} /></label><button disabled={!ablationPrompt.trim()} onClick={() => void runAblation()}>Run ablation</button>
          <div className="tools-columns"><label className="tools-field"><span>Trace cache ID</span><input value={traceCacheId} onChange={(event) => setTraceCacheId(event.target.value)} /></label><label className="tools-field"><span>Trace ID</span><input value={traceId} onChange={(event) => setTraceId(event.target.value)} /></label></div><button disabled={!traceCacheId || !traceId} onClick={async () => setDeveloperOutput(await studioApi.trace(traceCacheId, traceId))}>Load trace</button>
          {developerOutput !== null && <pre className="tools-json">{JSON.stringify(developerOutput, null, 2)}</pre>}
        </div>}
        {tab === "memory" && <div className="tools-stack">
          <ToolHeading title="Memory & discovery" copy="Inspect status, query memory, or schedule a backend backfill." />
          <label className="tools-field"><span>Query</span><input value={memoryQuery} onChange={(event) => setMemoryQuery(event.target.value)} /></label>
          <div className="tools-actions"><button onClick={async () => setMemoryOutput(await studioApi.memoryQuery({ query: memoryQuery, project_id: projectId, world_id: worldId, branch_id: branchId }))}>Query</button><button onClick={async () => setMemoryOutput(await studioApi.memoryBackfill({ project_id: projectId }))}>Backfill</button></div>
          <pre className="tools-json">{JSON.stringify(memoryOutput, null, 2)}</pre>
        </div>}
      </main>
      <footer>{status || "Backend-owned operations remain explicit and reviewable."}</footer>
    </aside>
  </>;
}

function ToolHeading({ title, copy }: { title: string; copy: string }) { return <div className="tools-heading"><span className="eyebrow">Studio tools</span><h2>{title}</h2><p>{copy}</p></div>; }
function ToolList({ title, items }: { title: string; items: JsonMap[] }) { return <section className="tools-list"><h3>{title}</h3>{items.map((item, index) => <article key={String(item.id || index)}><div><strong>{labelOf(item)}</strong><small>{String(item.kind || item.type || item.created_at || "")}</small></div></article>)}{!items.length && <p>Nothing here yet.</p>}</section>; }
