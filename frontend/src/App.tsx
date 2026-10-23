import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, LoaderCircle } from "lucide-react";
import { studioApi } from "./api";
import { browserStorage, createClientId } from "./browserStorage";
import { InspectorDrawer } from "./components/InspectorDrawer";
import { GlobalPalette } from "./components/GlobalPalette";
import { QuickCreateDialog } from "./components/QuickCreateDialog";
import { SettingsDrawer } from "./components/SettingsDrawer";
import { StudioToolsDrawer } from "./components/StudioToolsDrawer";
import { WelcomeDialog } from "./components/WelcomeDialog";
import { Shell } from "./components/Shell";
import { appearanceVariables, DEFAULT_ACCENT } from "./theme";
import { ChatView } from "./views/ChatView";
import { CommandCenterView } from "./views/CommandCenterView";
import { HomeView } from "./views/HomeView";
import { LibraryView } from "./views/LibraryView";
import { ManuscriptView } from "./views/ManuscriptView";
import type {
  AppView,
  AppearanceSettings,
  CommandPayload,
  ProjectTree,
  RuntimeConfig,
  Selection,
  Session,
  ThemeMode,
  WorkspaceBootstrap,
  WorldBible,
} from "./types";

const STACK_ID = createClientId("react");

function scopeKey(projectId: string, worldId: string, branchId: string) {
  return JSON.stringify([projectId, worldId, branchId]);
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === "AbortError";
}

const DEFAULT_CONFIG: RuntimeConfig = {
  studio_version: "unknown",
  server_url: "http://127.0.0.1:1234",
  model: "",
  gpu_ratio: 1,
  context_length: 32768,
  input_mode: "smart_hybrid",
  reasoning: "off",
  planning_enabled: false,
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
  const [appearance, setAppearance] = useState<AppearanceSettings>(() => {
    const storedMode = browserStorage.get("arline:theme");
    const storedContrast = browserStorage.get("arline:contrast");
    return {
      mode: storedMode === "dark" || storedMode === "light" || storedMode === "system" ? storedMode : "system",
      accent: browserStorage.get("arline:accent") || DEFAULT_ACCENT,
      contrast: storedContrast === "high" ? "high" : "standard",
    };
  });
  const [systemTheme, setSystemTheme] = useState<ThemeMode>(() => window.matchMedia?.("(prefers-color-scheme: light)").matches ? "light" : "dark");
  const [view, setView] = useState<AppView>(() => (browserStorage.get("arline:react:view") as AppView) || "home");
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
  const [toolsOpen, setToolsOpen] = useState(false);
  const [welcomeOpen, setWelcomeOpen] = useState(() => browserStorage.get("arline:react:welcomed") !== "yes");
  const [quickCreateOpen, setQuickCreateOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [seedPrompt, setSeedPrompt] = useState("");
  const [booting, setBooting] = useState(true);
  const [scopeLoading, setScopeLoading] = useState(false);
  const [hydratedScopeKey, setHydratedScopeKey] = useState("");
  const [fatalError, setFatalError] = useState("");
  const scopeRequestRef = useRef<{ version: number; controller: AbortController | null }>({ version: 0, controller: null });
  const activeScopeKeyRef = useRef("");

  const projects = bootstrap?.projects || [];
  const worlds = bible?.worlds || bootstrap?.worlds || [];
  const activeProject = projects.find((item) => item.id === activeProjectId);
  const activeWorld = worlds.find((item) => item.id === activeWorldId);
  const activeBranch = activeWorld?.branches?.find((item) => item.id === activeBranchId);
  const theme: ThemeMode = appearance.mode === "system" ? systemTheme : appearance.mode;
  const appearanceStyle = useMemo(() => appearanceVariables(appearance, theme), [appearance, theme]);

  useEffect(() => {
    const query = window.matchMedia?.("(prefers-color-scheme: light)");
    if (!query) return;
    const update = () => setSystemTheme(query.matches ? "light" : "dark");
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  const setThemeAndPersist = () => {
    const next = theme === "dark" ? "light" : "dark";
    browserStorage.set("arline:theme", next);
    setAppearance((current) => ({ ...current, mode: next }));
  };

  const setViewAndPersist = (next: AppView) => {
    browserStorage.set("arline:react:view", next);
    setView(next);
  };

  const refreshBootstrap = useCallback(async () => {
    const fresh = await studioApi.bootstrap(STACK_ID);
    setBootstrap(fresh);
    return fresh;
  }, []);

  const currentScopeKey = scopeKey(activeProjectId, activeWorldId, activeBranchId);
  activeScopeKeyRef.current = currentScopeKey;

  const loadScope = useCallback(async (projectId: string, worldId: string, branchId: string) => {
    if (!projectId) return true;
    const requestKey = scopeKey(projectId, worldId, branchId);
    const version = scopeRequestRef.current.version + 1;
    scopeRequestRef.current.controller?.abort();
    const controller = new AbortController();
    scopeRequestRef.current = { version, controller };
    setScopeLoading(true);
    try {
      const [projectTree, worldBible, sessionResult] = await Promise.all([
        studioApi.projectTree(projectId, worldId || undefined, branchId || undefined, controller.signal),
        studioApi.worldBible(projectId, worldId || undefined, branchId || undefined, controller.signal),
        studioApi.sessions(projectId, worldId || undefined, branchId || undefined, controller.signal),
      ]);
      if (controller.signal.aborted || scopeRequestRef.current.version !== version) return false;
      setTree(projectTree);
      setBible(worldBible);
      setSessions(sessionResult.sessions || []);
      setHydratedScopeKey(requestKey);
      setFatalError("");
      return true;
    } catch (error) {
      if (isAbortError(error) || controller.signal.aborted) return false;
      if (scopeRequestRef.current.version === version) setFatalError((error as Error).message);
      return false;
    } finally {
      if (scopeRequestRef.current.version === version) {
        scopeRequestRef.current.controller = null;
        setScopeLoading(false);
      }
    }
  }, []);

  const refreshSessions = useCallback(async () => {
    if (!activeProjectId) { setSessions([]); return; }
    const requestKey = scopeKey(activeProjectId, activeWorldId, activeBranchId);
    const result = await studioApi.sessions(activeProjectId, activeWorldId || undefined, activeBranchId || undefined);
    if (activeScopeKeyRef.current === requestKey) setSessions(result.sessions || []);
  }, [activeProjectId, activeWorldId, activeBranchId]);

  const refreshScope = useCallback(async () => {
    if (!activeProjectId) return;
    await loadScope(activeProjectId, activeWorldId, activeBranchId);
  }, [activeProjectId, activeWorldId, activeBranchId, loadScope]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      setBooting(true);
      try {
        const [runtime, boot, commandPayload] = await Promise.all([
          studioApi.config(),
          studioApi.bootstrap(STACK_ID),
          studioApi.commands().catch(() => ({ commands: [], command_registry_version: "frontend-fallback" })),
        ]);
        if (cancelled) return;
        const rememberedProject = browserStorage.get("arline:react:project");
        const project = boot.projects.find((item) => item.id === rememberedProject) || boot.projects[0];
        let world = undefined;
        let branch = undefined;
        if (project) {
          const rememberedWorld = browserStorage.get("arline:react:world");
          world = boot.worlds.find((item) => item.id === rememberedWorld)
            || boot.worlds.find((item) => item.id === project.default_world_id)
            || boot.worlds[0];
          if (world) {
            const rememberedBranch = browserStorage.get("arline:react:branch");
            branch = world.branches?.find((item) => item.id === rememberedBranch)
              || world.branches?.find((item) => item.kind === "main")
              || world.branches?.[0];
          }
          const loaded = await loadScope(project.id, world?.id || "", branch?.id || "");
          if (cancelled || !loaded) return;
        } else {
          setTree(null);
          setBible(null);
          setSessions([]);
          setHydratedScopeKey(scopeKey("", "", ""));
        }
        setConfig(runtime);
        setBootstrap(boot);
        setCommands(commandPayload);
        setActiveProjectId(project?.id || "");
        setActiveWorldId(world?.id || "");
        setActiveBranchId(branch?.id || "");
      } catch (error) {
        if (!cancelled) setFatalError((error as Error).message);
      } finally {
        if (!cancelled) setBooting(false);
      }
    })();
    return () => {
      cancelled = true;
      scopeRequestRef.current.controller?.abort();
    };
  }, [loadScope]);

  useEffect(() => {
    const openPalette = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((value) => !value);
      }
    };
    window.addEventListener("keydown", openPalette);
    return () => window.removeEventListener("keydown", openPalette);
  }, []);

  useEffect(() => {
    if (!activeProjectId) return;
    browserStorage.set("arline:react:project", activeProjectId);
    if (hydratedScopeKey !== currentScopeKey) void loadScope(activeProjectId, activeWorldId, activeBranchId);
  }, [activeProjectId, activeWorldId, activeBranchId, currentScopeKey, hydratedScopeKey, loadScope]);

  const chooseProject = (projectId: string) => {
    setActiveProjectId(projectId);
    const project = projects.find((item) => item.id === projectId);
    const world = worlds.find((item) => item.id === project?.default_world_id) || worlds[0];
    setActiveWorldId(world?.id || "");
    setActiveBranchId(world?.branches?.find((item) => item.kind === "main")?.id || world?.branches?.[0]?.id || "");
    setActiveSession(null);
  };

  const chooseWorld = (worldId: string) => {
    browserStorage.set("arline:react:world", worldId);
    setActiveWorldId(worldId);
    const world = worlds.find((item) => item.id === worldId);
    setActiveBranchId(world?.branches?.find((item) => item.kind === "main")?.id || world?.branches?.[0]?.id || "");
    setActiveSession(null);
  };

  const chooseBranch = (branchId: string) => {
    browserStorage.set("arline:react:branch", branchId);
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
  const closeWelcome = () => { browserStorage.set("arline:react:welcomed", "yes"); setWelcomeOpen(false); };

  const connectionLabel = config.model ? `LM Studio · ${config.model}` : "LM Studio · no model";
  const documentTypes = bootstrap?.document_types || ["scene", "chapter", "note", "research", "outline"];
  const entityTypes = bootstrap?.entity_types || ["character", "location", "item", "organization", "lore"];
  const documents = tree?.documents || [];
  const scopeReady = !activeProjectId || hydratedScopeKey === currentScopeKey;

  const mainContent = useMemo(() => {
    if (view === "home") return <HomeView project={activeProject} documents={documents} sessions={sessions} bible={bible} tree={tree} onOpenChat={(id) => id ? void openSession(id) : newChat()} onOpenDocument={openDocument} onManuscript={() => setViewAndPersist("manuscript")} onLibrary={() => setViewAndPersist("library")} onQuickCreate={() => setQuickCreateOpen(true)} onStartPrompt={(prompt) => { setSeedPrompt(prompt); setViewAndPersist("chat"); }} />;
    if (view === "chat") return <ChatView config={config} activeProjectId={activeProjectId} activeWorldId={activeWorldId} activeBranchId={activeBranchId} projectName={activeProject?.name || "Project"} worldName={activeWorld?.name || "World"} branchName={activeBranch?.name || "Main"} worldBible={bible} activeSession={activeSession} commands={commands.commands || []} onConfig={setConfig} onSession={setActiveSession} onSessionsChanged={refreshSessions} onLibraryChanged={refreshScope} onInspect={inspect} seedPrompt={seedPrompt} onSeedConsumed={() => setSeedPrompt("")} />;
    if (view === "manuscript") return <ManuscriptView projectId={activeProjectId} worldId={activeWorldId} branchId={activeBranchId} documents={documents} folders={tree?.folders || tree?.folder_tree || []} initialDocumentId={activeDocumentId} documentTypes={documentTypes} onDocumentsChanged={refreshScope} onInspect={inspect} />;
    if (view === "library") return <LibraryView projectId={activeProjectId} worldId={activeWorldId} branchId={activeBranchId} bible={bible} entityTypes={entityTypes} onChanged={async () => { await refreshBootstrap(); await refreshScope(); }} onSelect={setSelection} />;
    return <CommandCenterView projectId={activeProjectId} commands={commands.commands || []} registryVersion={commands.command_registry_version} dynamicReferences={commands.dynamic_references} referenceSelectors={commands.reference_selectors} onUse={(command, compiledText) => { setSeedPrompt(compiledText || `/${command.id} `); setViewAndPersist("chat"); }} />;
  }, [view, activeProject, activeWorld, activeBranch, documents, sessions, bible, tree, config, activeProjectId, activeWorldId, activeBranchId, activeSession, commands, seedPrompt, activeDocumentId, documentTypes, entityTypes, refreshSessions, refreshScope, refreshBootstrap]);

  if (booting) return <div className="boot-screen" data-theme={theme} style={appearanceStyle}><span className="brand-mark boot-brand-mark" aria-hidden="true" /><LoaderCircle className="spin" size={20} /><span>Starting Arline Studio…</span></div>;

  if (fatalError && !bootstrap) return (
    <div className="fatal-screen"><AlertTriangle size={28} /><h1>Studio failed to start</h1><p>{fatalError}</p><button onClick={() => location.reload()}>Reload</button></div>
  );

  return (
    <div className="arline-app-theme" data-theme={theme} data-contrast={appearance.contrast} style={appearanceStyle} aria-busy={!scopeReady || scopeLoading}>
      <Shell
        view={view}
        theme={theme}
        contrast={appearance.contrast}
        appearanceStyle={appearanceStyle}
        projects={projects}
        worlds={worlds}
        activeProjectId={activeProjectId}
        activeWorldId={activeWorldId}
        activeBranchId={activeBranchId}
        sessions={sessions}
        connectionLabel={connectionLabel}
        onView={setViewAndPersist}
        onProject={chooseProject}
        onWorld={chooseWorld}
        onBranch={chooseBranch}
        onSession={(id) => void openSession(id)}
        onNewChat={newChat}
        onQuickCreate={() => setQuickCreateOpen(true)}
        onPalette={() => setPaletteOpen(true)}
        onSettings={() => setSettingsOpen(true)}
        onTools={() => setToolsOpen(true)}
        onTheme={setThemeAndPersist}
      >
        {scopeLoading ? <div className="scope-progress"><span /></div> : null}
        {fatalError ? <div className="global-error"><AlertTriangle size={13} /><span>{fatalError}</span><button onClick={() => setFatalError("")}>×</button></div> : null}
        {scopeReady ? mainContent : <div className="scope-loading-state" role="status" aria-live="polite"><LoaderCircle className="spin" size={20} /><strong>{scopeLoading ? "Loading workspace…" : "Workspace data unavailable"}</strong>{!scopeLoading ? <button onClick={() => void refreshScope()}>Retry</button> : null}</div>}
      </Shell>
      <GlobalPalette
        open={paletteOpen}
        commands={commands.commands || []}
        sessions={sessions}
        documents={documents}
        families={bible?.families || []}
        worlds={worlds}
        canonFacts={bible?.canon_facts || []}
        onClose={() => setPaletteOpen(false)}
        onView={setViewAndPersist}
        onSession={(id) => void openSession(id)}
        onDocument={openDocument}
        onWorld={chooseWorld}
        onCommand={(command) => { setSeedPrompt(`/${command.id} `); setViewAndPersist("chat"); }}
        onInspect={inspect}
        onAddToChat={(text) => { setSeedPrompt(text); setViewAndPersist("chat"); }}
      />
      <SettingsDrawer open={settingsOpen} config={config} onConfig={setConfig} appearance={appearance} onAppearance={setAppearance} activeProjectId={activeProjectId} activeWorldId={activeWorldId} activeBranchId={activeBranchId} worldBible={bible} onLibraryChanged={refreshScope} onClose={() => setSettingsOpen(false)} />
      <StudioToolsDrawer open={toolsOpen} projectId={activeProjectId} worldId={activeWorldId} branchId={activeBranchId} config={config} onClose={() => setToolsOpen(false)} onChanged={refreshScope} />
      <WelcomeDialog open={welcomeOpen && !booting} onClose={closeWelcome} onStory={() => { closeWelcome(); setViewAndPersist("manuscript"); }} onLibrary={() => { closeWelcome(); setViewAndPersist("library"); setQuickCreateOpen(true); }} onImport={() => { closeWelcome(); setToolsOpen(true); }} />
      <InspectorDrawer selection={selection} projectId={activeProjectId} worldId={activeWorldId} branchId={activeBranchId} onChanged={refreshScope} onClose={() => setSelection(null)} />
      <QuickCreateDialog open={quickCreateOpen} projectId={activeProjectId} worldId={activeWorldId} branchId={activeBranchId} onClose={() => setQuickCreateOpen(false)} onCreated={async () => { await refreshBootstrap(); await refreshScope(); }} />
    </div>
  );
}
