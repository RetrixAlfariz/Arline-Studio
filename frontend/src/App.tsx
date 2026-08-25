import { useCallback, useEffect, useMemo, useState } from "react";
import { AlertTriangle, LoaderCircle } from "lucide-react";
import { studioApi } from "./api";
import { InspectorDrawer } from "./components/InspectorDrawer";
import { QuickCreateDialog } from "./components/QuickCreateDialog";
import { SettingsDrawer } from "./components/SettingsDrawer";
import { Shell } from "./components/Shell";
import { ChatView } from "./views/ChatView";
import { CommandCenterView } from "./views/CommandCenterView";
import { HomeView } from "./views/HomeView";
import { LibraryView } from "./views/LibraryView";
import { ManuscriptView } from "./views/ManuscriptView";
import type {
  AppView,
  CommandPayload,
  ProjectTree,
  RuntimeConfig,
  Selection,
  Session,
  ThemeMode,
  WorkspaceBootstrap,
  WorldBible,
} from "./types";

const STACK_ID = `react-${crypto.randomUUID()}`;

const DEFAULT_CONFIG: RuntimeConfig = {
  studio_version: "unknown",
  server_url: "http://127.0.0.1:1234",
  model: "",
  gpu_ratio: 1,
  context_length: 32768,
  input_mode: "smart_hybrid",
  reasoning: "off",
  projection_mode: "balanced",
  temperature: 0.8,
  top_p: 0.95,
  top_k: 40,
  min_p: 0,
  repeat_penalty: 1.05,
  visible_output_tokens: 4096,
  reasoning_reserve_tokens: 4096,
  generation_mode: "single",
  beat_count: 4,
  beat_tokens: 2048,
  total_story_target_tokens: 8192,
};

export default function App() {
  const [theme, setTheme] = useState<ThemeMode>(() => (localStorage.getItem("arline:theme") === "light" ? "light" : "dark"));
  const [view, setView] = useState<AppView>(() => (localStorage.getItem("arline:react:view") as AppView) || "home");
  const [config, setConfig] = useState<RuntimeConfig>(DEFAULT_CONFIG);
  const [bootstrap, setBootstrap] = useState<WorkspaceBootstrap | null>(null);
  const [commands, setCommands] = useState<CommandPayload>({ commands: [] });
  const [activeProjectId, setActiveProjectId] = useState("");
  const [activeWorldId, setActiveWorldId] = useState("");
  const [activeBranchId, setActiveBranchId] = useState("");
  const [tree, setTree] = useState<ProjectTree | null>(null);
  const [bible, setBible] = useState<WorldBible | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [activeSession, setActiveSession] = useState<Session | null>(null);
  const [activeDocumentId, setActiveDocumentId] = useState("");
  const [selection, setSelection] = useState<Selection | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [quickCreateOpen, setQuickCreateOpen] = useState(false);
  const [seedPrompt, setSeedPrompt] = useState("");
  const [booting, setBooting] = useState(true);
  const [scopeLoading, setScopeLoading] = useState(false);
  const [fatalError, setFatalError] = useState("");

  const projects = bootstrap?.projects || [];
  const worlds = bible?.worlds || bootstrap?.worlds || [];
  const activeProject = projects.find((item) => item.id === activeProjectId);

  const setThemeAndPersist = () => {
    const next = theme === "dark" ? "light" : "dark";
    localStorage.setItem("arline:theme", next);
    setTheme(next);
  };

  const setViewAndPersist = (next: AppView) => {
    localStorage.setItem("arline:react:view", next);
    setView(next);
  };

  const refreshBootstrap = useCallback(async () => {
    const fresh = await studioApi.bootstrap(STACK_ID);
    setBootstrap(fresh);
    return fresh;
  }, []);

  const refreshSessions = useCallback(async () => {
    if (!activeProjectId) { setSessions([]); return; }
    const result = await studioApi.sessions(activeProjectId, activeWorldId || undefined, activeBranchId || undefined);
    setSessions(result.sessions || []);
  }, [activeProjectId, activeWorldId, activeBranchId]);

  const refreshScope = useCallback(async () => {
    if (!activeProjectId) return;
    setScopeLoading(true);
    try {
      const [projectTree, worldBible, sessionResult] = await Promise.all([
        studioApi.projectTree(activeProjectId, activeWorldId || undefined, activeBranchId || undefined),
        studioApi.worldBible(activeProjectId, activeWorldId || undefined, activeBranchId || undefined),
        studioApi.sessions(activeProjectId, activeWorldId || undefined, activeBranchId || undefined),
      ]);
      setTree(projectTree);
      setBible(worldBible);
      setSessions(sessionResult.sessions || []);
    } catch (error) {
      setFatalError((error as Error).message);
    } finally {
      setScopeLoading(false);
    }
  }, [activeProjectId, activeWorldId, activeBranchId]);

  useEffect(() => {
    void (async () => {
      setBooting(true);
      try {
        const [runtime, boot, commandPayload] = await Promise.all([
          studioApi.config(),
          studioApi.bootstrap(STACK_ID),
          studioApi.commands().catch(() => ({ commands: [], command_registry_version: "frontend-fallback" })),
        ]);
        setConfig(runtime);
        setBootstrap(boot);
        setCommands(commandPayload);
        const rememberedProject = localStorage.getItem("arline:react:project");
        const project = boot.projects.find((item) => item.id === rememberedProject) || boot.projects[0];
        if (project) {
          setActiveProjectId(project.id);
          const rememberedWorld = localStorage.getItem("arline:react:world");
          const world = boot.worlds.find((item) => item.id === rememberedWorld)
            || boot.worlds.find((item) => item.id === project.default_world_id)
            || boot.worlds[0];
          if (world) {
            setActiveWorldId(world.id);
            const rememberedBranch = localStorage.getItem("arline:react:branch");
            const branch = world.branches?.find((item) => item.id === rememberedBranch)
              || world.branches?.find((item) => item.kind === "main")
              || world.branches?.[0];
            if (branch) setActiveBranchId(branch.id);
          }
        }
      } catch (error) {
        setFatalError((error as Error).message);
      } finally {
        setBooting(false);
      }
    })();
  }, []);

  useEffect(() => {
    if (!activeProjectId) return;
    localStorage.setItem("arline:react:project", activeProjectId);
    void refreshScope();
  }, [activeProjectId, activeWorldId, activeBranchId, refreshScope]);

  const chooseProject = (projectId: string) => {
    setActiveProjectId(projectId);
    const project = projects.find((item) => item.id === projectId);
    const world = worlds.find((item) => item.id === project?.default_world_id) || worlds[0];
    setActiveWorldId(world?.id || "");
    setActiveBranchId(world?.branches?.find((item) => item.kind === "main")?.id || world?.branches?.[0]?.id || "");
    setActiveSession(null);
  };

  const chooseWorld = (worldId: string) => {
    localStorage.setItem("arline:react:world", worldId);
    setActiveWorldId(worldId);
    const world = worlds.find((item) => item.id === worldId);
    setActiveBranchId(world?.branches?.find((item) => item.kind === "main")?.id || world?.branches?.[0]?.id || "");
    setActiveSession(null);
  };

  const chooseBranch = (branchId: string) => {
    localStorage.setItem("arline:react:branch", branchId);
    setActiveBranchId(branchId);
    setActiveSession(null);
  };

  const openSession = async (sessionId: string) => {
    try {
      const session = await studioApi.session(sessionId);
      setActiveSession(session);
      setViewAndPersist("chat");
    } catch (error) {
      setFatalError((error as Error).message);
    }
  };

  const newChat = () => {
    setActiveSession(null);
    setSeedPrompt("");
    setViewAndPersist("chat");
  };

  const openDocument = (id: string) => {
    setActiveDocumentId(id);
    setViewAndPersist("manuscript");
  };

  const inspect = (title: string, data: unknown) => setSelection({ kind: "analysis", title, data });

  const connectionLabel = config.model ? `LM Studio · ${config.model}` : "LM Studio · no model";
  const documentTypes = bootstrap?.document_types || ["scene", "chapter", "note", "research", "outline"];
  const entityTypes = bootstrap?.entity_types || ["character", "location", "item", "organization", "lore"];
  const documents = tree?.documents || [];

  const mainContent = useMemo(() => {
    if (view === "home") return <HomeView project={activeProject} documents={documents} sessions={sessions} bible={bible} onOpenChat={(id) => id ? void openSession(id) : newChat()} onOpenDocument={openDocument} onLibrary={() => setViewAndPersist("library")} onQuickCreate={() => setQuickCreateOpen(true)} />;
    if (view === "chat") return <ChatView config={config} activeProjectId={activeProjectId} activeWorldId={activeWorldId} activeBranchId={activeBranchId} activeSession={activeSession} commands={commands.commands || []} onConfig={setConfig} onSession={setActiveSession} onSessionsChanged={refreshSessions} onInspect={inspect} seedPrompt={seedPrompt} onSeedConsumed={() => setSeedPrompt("")} />;
    if (view === "manuscript") return <ManuscriptView projectId={activeProjectId} documents={documents} initialDocumentId={activeDocumentId} documentTypes={documentTypes} onDocumentsChanged={refreshScope} onInspect={inspect} />;
    if (view === "library") return <LibraryView projectId={activeProjectId} worldId={activeWorldId} branchId={activeBranchId} bible={bible} entityTypes={entityTypes} onChanged={async () => { await refreshBootstrap(); await refreshScope(); }} onSelect={setSelection} />;
    return <CommandCenterView commands={commands.commands || []} registryVersion={commands.command_registry_version} dynamicReferences={commands.dynamic_references} referenceSelectors={commands.reference_selectors} onUse={(command) => { setSeedPrompt(`/${command.id} `); setViewAndPersist("chat"); }} />;
  }, [view, activeProject, documents, sessions, bible, config, activeProjectId, activeWorldId, activeBranchId, activeSession, commands, seedPrompt, activeDocumentId, documentTypes, entityTypes, refreshSessions, refreshScope, refreshBootstrap]);

  if (booting) return <div className="boot-screen"><img src="/static/assets/brand/arline-primary.svg" alt="" /><LoaderCircle className="spin" size={20} /><span>Starting Arline Studio…</span></div>;

  if (fatalError && !bootstrap) return (
    <div className="fatal-screen"><AlertTriangle size={28} /><h1>Studio failed to start</h1><p>{fatalError}</p><button onClick={() => location.reload()}>Reload</button></div>
  );

  return (
    <>
      <Shell
        view={view}
        theme={theme}
        projects={projects}
        worlds={worlds}
        activeProjectId={activeProjectId}
        activeWorldId={activeWorldId}
        activeBranchId={activeBranchId}
        sessions={sessions}
        bible={bible}
        connectionLabel={connectionLabel}
        onView={setViewAndPersist}
        onProject={chooseProject}
        onWorld={chooseWorld}
        onBranch={chooseBranch}
        onSession={(id) => void openSession(id)}
        onNewChat={newChat}
        onQuickCreate={() => setQuickCreateOpen(true)}
        onSettings={() => setSettingsOpen(true)}
        onTheme={setThemeAndPersist}
      >
        {scopeLoading ? <div className="scope-progress"><span /></div> : null}
        {fatalError ? <div className="global-error"><AlertTriangle size={13} /><span>{fatalError}</span><button onClick={() => setFatalError("")}>×</button></div> : null}
        {mainContent}
      </Shell>
      <SettingsDrawer open={settingsOpen} config={config} onConfig={setConfig} onClose={() => setSettingsOpen(false)} />
      <InspectorDrawer selection={selection} onClose={() => setSelection(null)} />
      <QuickCreateDialog open={quickCreateOpen} projectId={activeProjectId} worldId={activeWorldId} branchId={activeBranchId} onClose={() => setQuickCreateOpen(false)} onCreated={async () => { await refreshBootstrap(); await refreshScope(); }} />
    </>
  );
}
