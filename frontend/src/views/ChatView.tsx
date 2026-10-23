import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import writingIllustration from "../assets/writing-island.png";
import {
  AlertTriangle,
  AtSign,
  Check,
  Compass,
  Pin,
  Pencil,
  Ban,
  BrainCircuit,
  ChevronDown,
  ChevronRight,
  MoreHorizontal,
  PanelRight,
  Copy,
  CornerUpRight,
  FolderKanban,
  FlaskConical,
  GitFork,
  GitBranch,
  Globe2,
  Image as ImageIcon,
  LoaderCircle,
  MessageSquareText,
  Eye,
  Cpu,
  Gauge,
  Layers3,
  Paperclip,
  PenLine,
  Save,
  Send,
  Sparkles,
  SlidersHorizontal,
  Target,
  Trash2,
  UserRound,
  UsersRound,
  ShieldCheck,
  X,
} from "lucide-react";
import { runtimePayload, streamGeneration, studioApi } from "../api";
import { ArlineSelect, simpleOptions, type ArlineSelectOption } from "../components/ArlineSelect";
import type {
  CommandDefinition,
  GenerationResult,
  ReferenceItem,
  RuntimeConfig,
  Session,
  Turn,
  JsonMap,
  ModelInfo,
  ConversationMode,
  ConversationProfile,
  UserProfile,
  WorldBible,
} from "../types";

interface ChatAttachment {
  id: string;
  name: string;
  size: number;
  type: string;
  dataUrl: string;
  saved: boolean;
}

const MODE_META: Record<ConversationMode, { label: string; description: string; placeholder: string; icon: typeof PenLine; starters: Array<{ title: string; copy: string; prompt: string }> }> = {
  story_writer: { label: "Story Writer", description: "Write polished story prose", placeholder: "Describe what should happen next…", icon: PenLine, starters: [
    { title: "Continue the scene", copy: "Move forward while preserving established behavior.", prompt: "Continue the current scene while preserving established character behavior." },
    { title: "Rewrite a passage", copy: "Shape an existing moment into polished prose.", prompt: "Rewrite the current passage as polished story prose with stronger pacing and voice." },
    { title: "Check continuity", copy: "Review continuity risks before writing.", prompt: "Check continuity, then suggest the safest way to continue this scene." },
  ] },
  story_lab: { label: "Story Lab", description: "Brainstorm story and character design naturally", placeholder: "Talk through a story or character idea…", icon: FlaskConical, starters: [
    { title: "Talk through an idea", copy: "Develop the strongest part through natural conversation.", prompt: "I have a story idea I want to talk through. Help me understand what is strongest about it and where it may need work." },
    { title: "Develop a character", copy: "Discuss motivation, friction, and growth together.", prompt: "Help me think through this character naturally. Challenge weak assumptions, but do not write a scene unless I ask." },
    { title: "Untangle a story problem", copy: "Find what is not working without forcing a menu of options.", prompt: "I am stuck on part of the story. Talk it through with me and help identify the underlying design problem." },
    { title: "Design My Presence", copy: "Talk through who you want to be inside the story.", prompt: "I want to exist in this story. Talk with me naturally as we design My Presence without making it canon yet." },
  ] },
  interactive: { label: "Interactive", description: "Enter the story; Arline runs the world", placeholder: "What do you do?", icon: UserRound, starters: [
    { title: "Enter current scene", copy: "Step into the active scene with agency protected.", prompt: "Place my active Presence at the edge of the current scene and let me choose what to do." },
    { title: "Choose Presence", copy: "Decide whether to observe, enter as yourself, or play a character.", prompt: "Help me choose the right Presence for this interaction." },
    { title: "Resume interaction", copy: "Continue from the latest world state.", prompt: "Resume the interaction from the latest state. Do not invent my dialogue or decisions." },
  ] },
  analyst: { label: "Analyst", description: "Inspect without continuing the story", placeholder: "What should Arline inspect?", icon: BrainCircuit, starters: [
    { title: "Inspect motivation", copy: "Test whether character choices feel earned.", prompt: "Inspect the character motivations in the current scene without continuing it." },
    { title: "Trace continuity", copy: "Follow facts and state changes across turns.", prompt: "Trace the continuity of the current conversation and flag contradictions with evidence." },
    { title: "Explain state change", copy: "Diagnose how the scene reached its current state.", prompt: "Explain the important state changes that led to this point. Do not write new prose." },
  ] },
  character_room: { label: "Character Room", description: "Explore dialogue chemistry", placeholder: "Which characters should Arline bring into the room?", icon: UsersRound, starters: [
    { title: "Choose participants", copy: "Select voices for a non-canon room.", prompt: "Help me choose characters for an exploratory Character Room." },
    { title: "Test chemistry", copy: "Explore friction, warmth, and subtext.", prompt: "Test the chemistry between the selected characters as non-canon exploration." },
    { title: "Rehearse dialogue", copy: "Try a conversation before committing it.", prompt: "Rehearse a dialogue between the selected characters without changing canon." },
  ] },
};

const MODE_OPTIONS: ArlineSelectOption[] = (Object.entries(MODE_META) as Array<[ConversationMode, (typeof MODE_META)[ConversationMode]]>).map(([value, item]) => ({ value, label: item.label, description: item.description, icon: item.icon }));

const DEFAULT_CONVERSATION_PROFILE: ConversationProfile = {
  exploration: "open",
  story_lab_focus: "plot",
  presence: { mode: "observer", display_name: "", identity_style: "story_version", control_policy: "user_directed", persistence: "session" },
  perspective: { style: "scene_defined", pov_entity_id: null },
  blueprint: { wanted: [], flexible: [], suggested: [], avoid: [], open_questions: [] },
  living_session: { current_question: "", emerging_idea: "", decisions: [], open_threads: [], insights: [] },
};

function deriveLivingSession(prompt: string, response: string, current: JsonMap = {}): JsonMap {
  const paragraphs = response.split(/\n{2,}/).map((item) => item.replace(/^#+\s*/, "").trim()).filter(Boolean);
  const questions = Array.from(response.matchAll(/(?:^|[.!]\s+)([^.!?]{12,220}\?)/gm)).map((match) => match[1].trim()).slice(-3);
  const idea = paragraphs.find((item) => !item.endsWith("?") && item.length > 28)?.slice(0, 360) || prompt.slice(0, 360);
  return {
    ...current,
    current_question: questions.at(-1) || String(current.current_question || prompt),
    emerging_idea: idea,
    decisions: Array.isArray(current.decisions) ? current.decisions : [],
    open_threads: questions.length ? questions : (Array.isArray(current.open_threads) ? current.open_threads : []),
    insights: Array.isArray(current.insights) ? current.insights : [],
  };
}

interface ChatViewProps {
  config: RuntimeConfig;
  activeProjectId: string;
  activeWorldId: string;
  activeBranchId: string;
  projectName: string;
  worldName: string;
  branchName: string;
  worldBible: WorldBible | null;
  activeSession: Session | null;
  commands: CommandDefinition[];
  onConfig: (config: RuntimeConfig) => void;
  onSession: (session: Session | null) => void;
  onSessionsChanged: () => Promise<void> | void;
  onLibraryChanged?: () => Promise<void> | void;
  onInspect: (title: string, data: unknown) => void;
  seedPrompt?: string;
  onSeedConsumed?: () => void;
}

function turnKey(turn: Turn, index: number) {
  return turn.id || `${turn.run_id || "turn"}-${index}`;
}

export function ChatView({
  config,
  activeProjectId,
  activeWorldId,
  activeBranchId,
  projectName,
  worldName,
  branchName,
  worldBible,
  activeSession,
  commands,
  onConfig,
  onSession,
  onSessionsChanged,
  onLibraryChanged,
  onInspect,
  seedPrompt,
  onSeedConsumed,
}: ChatViewProps) {
  const [prompt, setPrompt] = useState("");
  const [references, setReferences] = useState<ReferenceItem[]>([]);
  const [generating, setGenerating] = useState(false);
  const [liveText, setLiveText] = useState("");
  const [liveReasoning, setLiveReasoning] = useState("");
  const [pendingPrompt, setPendingPrompt] = useState("");
  const [followLatest, setFollowLatest] = useState(true);
  const [stage, setStage] = useState("");
  const [error, setError] = useState("");
  const [analysis, setAnalysis] = useState<Record<string, unknown> | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [focusMode, setFocusMode] = useState(false);
  const [notebookOpen, setNotebookOpen] = useState(() => window.matchMedia("(min-width: 1200px)").matches);
  const [mentions, setMentions] = useState<Array<Record<string, unknown>>>([]);
  const [mentionsLoading, setMentionsLoading] = useState(false);
  const [mentionsFailed, setMentionsFailed] = useState(false);
  const [commandMatches, setCommandMatches] = useState<CommandDefinition[]>([]);
  const [scratchMode, setScratchMode] = useState(Boolean(activeSession?.scratch_mode));
  const [conversationMode, setConversationMode] = useState<ConversationMode>(activeSession?.conversation_mode || "story_writer");
  const [conversationProfile, setConversationProfile] = useState<ConversationProfile>({ ...DEFAULT_CONVERSATION_PROFILE, ...(activeSession?.conversation_profile || {}) });
  const [runProfiles, setRunProfiles] = useState<JsonMap[]>([]);
  const [recipes, setRecipes] = useState<JsonMap[]>([]);
  const [selectedRecipeId, setSelectedRecipeId] = useState("");
  const [selectedProfileId, setSelectedProfileId] = useState("");
  const [profileName, setProfileName] = useState("");
  const [profileSaveOpen, setProfileSaveOpen] = useState(false);
  const [savingProfile, setSavingProfile] = useState(false);
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [previewAttachment, setPreviewAttachment] = useState<ChatAttachment | null>(null);
  const [visionSupport, setVisionSupport] = useState<"checking" | "supported" | "unsupported">("checking");
  const [activeScene, setActiveScene] = useState("");
  const [memoryReady, setMemoryReady] = useState(false);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [deletingSession, setDeletingSession] = useState(false);
  const [presenceName, setPresenceName] = useState("");
  const [blueprintBusy, setBlueprintBusy] = useState(false);
  const [userProfile, setUserProfile] = useState<UserProfile | null>(null);
  const [identityOpen, setIdentityOpen] = useState(false);
  const [sheetProposal, setSheetProposal] = useState<JsonMap | null>(null);
  const [sheetProposalBusy, setSheetProposalBusy] = useState(false);
  const [sheetBranchName, setSheetBranchName] = useState("");
  const [activeSheetIndex, setActiveSheetIndex] = useState(0);
  const [selectedSheetIds, setSelectedSheetIds] = useState<string[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const imageInputRef = useRef<HTMLInputElement | null>(null);
  const composerInputRef = useRef<HTMLTextAreaElement | null>(null);
  const notebookToggleRef = useRef<HTMLButtonElement | null>(null);
  const presenceRequestRef = useRef(0);
  const closeNotebook = () => { setNotebookOpen(false); notebookToggleRef.current?.focus(); };

  const turns = useMemo(() => activeSession?.turns || [], [activeSession]);
  const lastPromptToken = prompt.split(/\s+/).at(-1) || "";
  const commandTrigger = lastPromptToken.match(/^\/([^\s/]*)$/);
  const mentionTrigger = lastPromptToken.match(/^@([^\s@]{0,40})$/);
  const commandQuery = commandTrigger?.[1] ?? null;
  const mentionQuery = mentionTrigger?.[1] ?? null;
  const composerPopupMode = commandTrigger ? "commands" : mentionTrigger ? "mentions" : null;
  const characterVariants = useMemo(() => {
    const characterFamilies = new Set((worldBible?.families || []).filter((family) => family.entity_type === "character").map((family) => family.id));
    return (worldBible?.variants || []).filter((variant) => characterFamilies.has(String(variant.family_id || "")) && (!variant.world_id || variant.world_id === activeWorldId));
  }, [worldBible, activeWorldId]);

  useEffect(() => {
    if (!seedPrompt) return;
    setPrompt(seedPrompt);
    onSeedConsumed?.();
  }, [seedPrompt, onSeedConsumed]);

  useEffect(() => {
    setLiveText("");
    setLiveReasoning("");
    setError("");
    setAnalysis(null);
    setReferences((activeSession?.workspace_refs as ReferenceItem[] | undefined) || []);
    setScratchMode(Boolean(activeSession?.scratch_mode));
    setConversationMode(activeSession?.conversation_mode || "story_writer");
    setConversationProfile({ ...DEFAULT_CONVERSATION_PROFILE, ...(activeSession?.conversation_profile || {}) });
  }, [activeSession?.id]);

  useEffect(() => {
    void studioApi.userProfile().then(setUserProfile).catch(() => setUserProfile(null));
  }, []);

  useEffect(() => {
    const syncProfile = (event: Event) => setUserProfile((event as CustomEvent<UserProfile>).detail);
    window.addEventListener("arline:user-profile-updated", syncProfile);
    return () => window.removeEventListener("arline:user-profile-updated", syncProfile);
  }, []);

  useEffect(() => {
    if (activeSession) return;
    void studioApi.userProfile().then((profile) => {
      setUserProfile(profile);
      setConversationMode(String(profile.collaboration?.default_conversation_mode || "story_writer") as ConversationMode);
      setConversationProfile({
        ...DEFAULT_CONVERSATION_PROFILE,
        exploration: String(profile.story_lab?.exploration || "open") as ConversationProfile["exploration"],
        story_lab_focus: String(profile.story_lab?.focus || "plot"),
        presence: { ...(DEFAULT_CONVERSATION_PROFILE.presence || {}), ...(profile.presence_defaults || {}), display_name: profile.display_name || "" },
        perspective: { ...(DEFAULT_CONVERSATION_PROFILE.perspective || {}), style: profile.presence_defaults?.perspective || "scene_defined" },
      });
    }).catch(() => undefined);
  }, [activeSession]);

  useEffect(() => {
    const requestId = presenceRequestRef.current + 1;
    presenceRequestRef.current = requestId;
    let cancelled = false;
    if (activeSession || (!activeBranchId && !activeWorldId)) return () => { cancelled = true; };
    const loadScopedPresence = async () => {
      const [branch, world] = await Promise.all([
        activeBranchId ? studioApi.presenceBinding("branch", activeBranchId).catch(() => ({} as JsonMap)) : {} as JsonMap,
        activeWorldId ? studioApi.presenceBinding("world", activeWorldId).catch(() => ({} as JsonMap)) : {} as JsonMap,
      ]);
      if (cancelled || presenceRequestRef.current !== requestId) return;
      const scoped = ((branch.profile as JsonMap | undefined) && Object.keys(branch.profile as JsonMap).length ? branch.profile : world.profile) as ConversationProfile | undefined;
      if (scoped && Object.keys(scoped).length) setConversationProfile((current) => ({ ...current, ...scoped }));
    };
    void loadScopedPresence();
    return () => { cancelled = true; };
  }, [activeSession, activeBranchId, activeWorldId]);

  useEffect(() => {
    if (!activeProjectId) return;
    void Promise.all([studioApi.runProfiles(activeProjectId).catch(() => ({ profiles: [] })), studioApi.contextRecipes(activeProjectId).catch(() => ({ recipes: [] }))])
      .then(([profilesResult, recipesResult]) => { setRunProfiles(profilesResult.profiles || []); setRecipes(recipesResult.recipes || []); });
  }, [activeProjectId]);

  useEffect(() => {
    let cancelled = false;
    setVisionSupport("checking");
    void studioApi.models(config.server_url)
      .then((result) => {
        if (cancelled) return;
        const model = (result.models || []).find((item: ModelInfo) => item.key === config.model);
        setVisionSupport(Boolean(model?.capabilities?.vision) ? "supported" : "unsupported");
      })
      .catch(() => { if (!cancelled) setVisionSupport("unsupported"); });
    return () => { cancelled = true; };
  }, [config.model, config.server_url]);

  useEffect(() => {
    if (!activeProjectId) return;
    void Promise.all([
      studioApi.activeScene(activeProjectId).catch(() => ({})),
      studioApi.memoryStatus().catch(() => ({})),
    ]).then(([scene, memory]) => {
      const sceneData = scene as JsonMap;
      const memoryData = memory as JsonMap;
      const sceneDocument = (sceneData.document || sceneData.active_scene || {}) as JsonMap;
      setActiveScene(String(sceneDocument.title || sceneData.title || ""));
      setMemoryReady(Boolean(memoryData.ready ?? memoryData.available ?? memoryData.enabled));
    });
  }, [activeProjectId, activeWorldId, activeBranchId]);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport) return;
    if (!turns.length && !pendingPrompt && !generating && !liveText) {
      viewport.scrollTo({ top: 0, behavior: "auto" });
      return;
    }
    if (!followLatest) return;
    viewport.scrollTo({ top: viewport.scrollHeight, behavior: "auto" });
  }, [liveText, generating, pendingPrompt, turns.length, followLatest]);

  useEffect(() => {
    if (!settingsOpen) return;
    const closeSettings = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setSettingsOpen(false);
        setProfileSaveOpen(false);
      }
    };
    window.addEventListener("keydown", closeSettings);
    return () => window.removeEventListener("keydown", closeSettings);
  }, [settingsOpen]);

  useEffect(() => {
    if (!deleteConfirmOpen) return;
    const closeDeleteConfirm = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !deletingSession) setDeleteConfirmOpen(false);
    };
    window.addEventListener("keydown", closeDeleteConfirm);
    return () => window.removeEventListener("keydown", closeDeleteConfirm);
  }, [deleteConfirmOpen, deletingSession]);

  useEffect(() => {
    if (commandQuery !== null) {
      const needle = commandQuery.toLowerCase();
      setCommandMatches(commands.filter((command) => {
        const searchable = [command.id, command.label, command.title, command.description, command.help, command.usage, ...(command.aliases || [])];
        return searchable.some((value) => String(value || "").toLowerCase().includes(needle));
      }).slice(0, 8));
    } else {
      setCommandMatches([]);
    }
    if (mentionQuery === null) {
      setMentions([]);
      setMentionsLoading(false);
      setMentionsFailed(false);
      return;
    }
    let cancelled = false;
    setMentionsLoading(true);
    setMentionsFailed(false);
    const timer = window.setTimeout(() => {
      void studioApi.mentions(mentionQuery, activeProjectId, activeWorldId, activeBranchId)
        .then((result) => { if (!cancelled) setMentions(result.results || []); })
        .catch(() => { if (!cancelled) { setMentions([]); setMentionsFailed(true); } })
        .finally(() => { if (!cancelled) setMentionsLoading(false); });
    }, mentionQuery ? 180 : 0);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [commandQuery, mentionQuery, commands, activeProjectId, activeWorldId, activeBranchId]);

  const selectCommand = (command: CommandDefinition) => {
    const chunks = prompt.split(/\s+/);
    chunks[chunks.length - 1] = `/${command.id}`;
    setPrompt(`${chunks.join(" ")} `);
    setCommandMatches([]);
  };

  const selectMention = (item: Record<string, unknown>) => {
    const chunks = prompt.split(/\s+/);
    const label = String(item.label || item.name || item.id || "reference");
    chunks[chunks.length - 1] = `@${label.replaceAll(" ", "_")}`;
    const ref: ReferenceItem = {
      type: String(item.type || "entity"),
      id: String(item.id || ""),
      label,
      mode: "context",
    };
    if (ref.id && !references.some((current) => current.type === ref.type && current.id === ref.id)) {
      setReferences((current) => [...current, ref]);
    }
    setPrompt(`${chunks.join(" ")} `);
    setMentions([]);
  };

  const refreshSession = async (sessionId?: string) => {
    if (!sessionId) return;
    const session = await studioApi.session(sessionId);
    onSession(session);
    await onSessionsChanged();
  };

  const generate = async () => {
    if (!prompt.trim() || generating) return;
    if (attachments.length && visionSupport !== "supported") {
      setError(visionSupport === "checking" ? "Still checking whether the selected model supports images." : "The selected model does not report vision support. Remove the image or choose a vision-capable model.");
      return;
    }
    if (attachments.length && config.generation_mode !== "single") {
      setError("Image context currently works with Single response mode. Change the run profile or remove the image.");
      return;
    }
    setGenerating(true);
    setError("");
    setLiveText("");
    setLiveReasoning("");
    setStage("Preparing context");
    const controller = new AbortController();
    abortRef.current = controller;
    let runSessionId = activeSession?.id;
    let streamedResponse = "";
    const payload = runtimePayload(config, {
      projectId: activeProjectId,
      worldId: activeWorldId,
      branchId: activeBranchId,
      sessionId: activeSession?.id,
    }, prompt.trim(), references);
    payload.scratch_mode = scratchMode;
    payload.conversation_mode = conversationMode;
    payload.conversation_profile = conversationProfile;
    payload.pov_variant_id = ((conversationProfile.perspective || {}) as JsonMap).pov_entity_id || null;
    const contextVariants = Array.from(new Set([
      String(((conversationProfile.presence || {}) as JsonMap).entity_variant_id || ""),
      ...(((conversationProfile.participants as string[] | undefined) || [])),
    ].filter(Boolean)));
    payload.references = [
      ...((payload.references as JsonMap[] | undefined) || []),
      ...contextVariants.map((id) => ({ type: "entity_variant", id, label: characterVariants.find((item) => item.id === id)?.display_name || id, mode: "deep" })),
    ];
    payload.context_recipe_id = selectedRecipeId || null;
    payload.images = attachments.map((attachment) => attachment.dataUrl);
    const sentPrompt = prompt.trim();
    setPendingPrompt(sentPrompt);
    setFollowLatest(true);
    setPrompt("");

    try {
      const result = await streamGeneration(payload, async (event) => {
        if (event.type === "run.start") {
          runSessionId = String(event.data.session_id || runSessionId || "");
          setStage("Generating");
          if (runSessionId && runSessionId !== activeSession?.id) {
            try {
              const startedSession = await studioApi.session(runSessionId);
              onSession(startedSession);
              await onSessionsChanged();
            } catch {
              // Streaming can continue even if the early session refresh races the backend commit.
            }
          }
        } else if (event.type === "answer.delta") {
          streamedResponse += String(event.data.content || "");
          setLiveText((value) => value + String(event.data.content || ""));
        } else if (event.type === "reasoning.delta") {
          setLiveReasoning((value) => value + String(event.data.content || ""));
        } else if (event.type.endsWith(".start")) {
          setStage(event.type.replaceAll(".", " "));
        } else if (event.type === "quality") {
          setStage("Finalizing");
        } else if (event.type === "done") {
          const final = event.data as GenerationResult;
          runSessionId = String(final.session_id || runSessionId || "");
          setStage("Done");
          setAnalysis({
            run_id: final.run_id,
            summary: final.summary,
            context_breakdown: final.context_breakdown,
            quality_report: final.quality_report,
            reasoning: final.reasoning,
          });
        }
      }, controller.signal);
      const finalSessionId = String(result?.session_id || runSessionId || "");
      if (finalSessionId && conversationMode === "story_lab") {
        const nextLivingSession = deriveLivingSession(
          sentPrompt,
          String(result?.story || streamedResponse),
          (conversationProfile.living_session || {}) as JsonMap,
        );
        const nextProfile = { ...conversationProfile, living_session: nextLivingSession };
        setConversationProfile(nextProfile);
        await studioApi.updateSession(finalSessionId, { conversation_profile: nextProfile });
        await refreshSession(finalSessionId);
      } else if (finalSessionId) {
        await refreshSession(finalSessionId);
      }
      setLiveText("");
      setLiveReasoning("");
      setAttachments([]);
    } catch (generationError) {
      if ((generationError as Error).name !== "AbortError") {
        setError((generationError as Error).message || "Generation failed");
        setPrompt(sentPrompt);
      }
    } finally {
      setPendingPrompt("");
      setGenerating(false);
      abortRef.current = null;
    }
  };

  const analyze = async () => {
    if (!prompt.trim()) return;
    setError("");
    try {
      setStage("Analyzing context");
      const result = await studioApi.analyze(runtimePayload(config, {
        projectId: activeProjectId,
        worldId: activeWorldId,
        branchId: activeBranchId,
        sessionId: activeSession?.id,
      }, prompt.trim(), references));
      setAnalysis(result);
      onInspect("Context analysis", result);
    } catch (analysisError) {
      setError((analysisError as Error).message);
    } finally {
      setStage("");
    }
  };

  const fork = async () => {
    if (!activeSession) return;
    const lastTurn = turns.at(-1);
    const forked = await studioApi.forkSession(activeSession.id, lastTurn?.id);
    await refreshSession(forked.id);
  };

  const removeSession = async () => {
    if (!activeSession || deletingSession) return;
    setDeletingSession(true);
    setError("");
    try {
      await studioApi.trash("session", activeSession.id);
      setDeleteConfirmOpen(false);
      onSession(null);
      await onSessionsChanged();
    } catch (deleteError) {
      setError((deleteError as Error).message || "Could not move this chat to Trash.");
    } finally {
      setDeletingSession(false);
    }
  };

  const patchActiveSession = async (payload: Record<string, unknown>) => {
    if (!activeSession) return;
    const updatedSession = await studioApi.updateSession(activeSession.id, payload);
    onSession(updatedSession);
    try {
      await onSessionsChanged();
    } catch (refreshError) {
      setError((refreshError as Error).message || "Session saved, but the session list could not be refreshed.");
    }
  };

  const renameSession = async () => {
    if (!activeSession) return;
    const title = window.prompt("Chat title", activeSession.title);
    if (title?.trim()) await patchActiveSession({ title: title.trim() });
  };

  const toggleScratch = async () => {
    const next = !scratchMode; setScratchMode(next);
    if (activeSession) await patchActiveSession({ scratch_mode: next });
  };

  const changeConversation = async (mode: ConversationMode) => {
    const previousMode = conversationMode;
    setConversationMode(mode);
    if (!activeSession) return;
    try {
      await patchActiveSession({ conversation_mode: mode, conversation_profile: conversationProfile });
    } catch (persistenceError) {
      setConversationMode(previousMode);
      setError((persistenceError as Error).message || "Could not save the conversation mode.");
    }
  };

  const patchConversationProfile = async (patch: ConversationProfile) => {
    const previousProfile = conversationProfile;
    const next = { ...conversationProfile, ...patch };
    setConversationProfile(next);
    if (!activeSession) return;
    try {
      await patchActiveSession({ conversation_profile: next });
    } catch (persistenceError) {
      setConversationProfile(previousProfile);
      setError((persistenceError as Error).message || "Could not save the conversation profile.");
    }
  };

  const patchLivingSession = async (patch: JsonMap) => {
    const current = (conversationProfile.living_session || {}) as JsonMap;
    await patchConversationProfile({ living_session: { ...current, ...patch } });
  };

  const persistPresence = async (scope: "world" | "branch") => {
    const scopeId = scope === "branch" ? activeBranchId : activeWorldId;
    if (!scopeId) return;
    const next = { ...conversationProfile, presence: { ...(conversationProfile.presence || {}), persistence: scope } };
    setConversationProfile(next);
    await studioApi.savePresenceBinding(scope, scopeId, next);
    if (activeSession) await patchActiveSession({ conversation_profile: next });
  };

  const extractPresenceBlueprint = async () => {
    if (!prompt.trim() || blueprintBusy) return;
    setBlueprintBusy(true);
    try {
      const result = await studioApi.extractBlueprint(prompt.trim(), (conversationProfile.blueprint || {}) as JsonMap);
      await patchConversationProfile({ blueprint: result.blueprint });
    } finally {
      setBlueprintBusy(false);
    }
  };

  const promotePresence = async () => {
    const name = presenceName.trim() || String((conversationProfile.presence as JsonMap | undefined)?.display_name || "My Presence");
    if (!activeProjectId || !activeWorldId) return;
    const result = await studioApi.promotePresence({ project_id: activeProjectId, world_id: activeWorldId, branch_id: activeBranchId || null, name, blueprint: conversationProfile.blueprint || {} });
    const variantId = String(result.variant.id || "");
    await patchConversationProfile({ presence: { ...(conversationProfile.presence || {}), mode: "linked_entity", display_name: name, entity_variant_id: variantId, identity_style: "canonical" } });
    setPresenceName("");
  };

  const approveSuggestion = async (value: string, target: "wanted" | "flexible") => {
    const current = (conversationProfile.blueprint || {}) as JsonMap;
    const suggested = ((current.suggested as string[] | undefined) || []).filter((item) => item !== value);
    const destination = Array.from(new Set([...(current[target] as string[] | undefined || []), value]));
    await patchConversationProfile({ blueprint: { ...current, suggested, [target]: destination } });
  };

  const showReferencePicker = () => {
    setPrompt((value) => {
      const activeToken = value.split(/\s+/).at(-1) || "";
      if (/^@[^\s@]{0,40}$/.test(activeToken)) return value;
      return `${value}${value && !value.endsWith(" ") ? " " : ""}@`;
    });
    window.setTimeout(() => composerInputRef.current?.focus(), 0);
  };

  const addImages = async (files: File[]) => {
    const available = Math.max(0, 4 - attachments.length);
    const images = files.filter((file) => file.type.startsWith("image/")).slice(0, available);
    if (!images.length) return;
    const oversized = images.find((file) => file.size > 20 * 1024 * 1024);
    if (oversized) {
      setError(`${oversized.name} is larger than the 20 MiB image limit.`);
      return;
    }
    const loaded = await Promise.all(images.map((file) => new Promise<ChatAttachment>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve({ id: `${file.name}-${file.lastModified}-${crypto.randomUUID()}`, name: file.name, size: file.size, type: file.type, dataUrl: String(reader.result), saved: false });
      reader.onerror = () => reject(reader.error || new Error(`Could not read ${file.name}`));
      reader.readAsDataURL(file);
    })));
    setAttachments((current) => [...current, ...loaded].slice(0, 4));
  };

  const saveAttachment = async (attachment: ChatAttachment) => {
    if (!activeWorldId) {
      setError("Choose a world before saving an image to the Library.");
      return;
    }
    try {
      await studioApi.createMedia({ resource_type: "world", resource_id: activeWorldId, filename: attachment.name, data_url: attachment.dataUrl, kind: "reference", caption: `Saved from Chat in ${projectName}` });
      setAttachments((items) => items.map((item) => item.id === attachment.id ? { ...item, saved: true } : item));
    } catch (saveError) {
      setError((saveError as Error).message || "Could not save image to the Library.");
    }
  };

  const saveRunProfile = async () => {
    if (!profileName.trim() || savingProfile) return;
    setSavingProfile(true);
    try {
      const created = await studioApi.saveRunProfile({ name: profileName.trim(), project_id: activeProjectId, profile: config });
      const result = await studioApi.runProfiles(activeProjectId);
      setRunProfiles(result.profiles || []);
      setSelectedProfileId(String(created.id || ""));
      setProfileName("");
      setProfileSaveOpen(false);
    } catch (profileError) {
      setError((profileError as Error).message || "Could not save the run profile.");
    } finally {
      setSavingProfile(false);
    }
  };

  const reviewTurn = async (turn: Turn, status: "accepted" | "rejected") => {
    await studioApi.feedback(turn.id, { status, issues: [], note: "Reviewed in React chat", edited_story: "" });
    await refreshSession(activeSession?.id);
  };

  const stageTurn = async (turn: Turn) => {
    const path = window.prompt("Canon semantic path", "current_state.note");
    if (!path || !activeProjectId) return;
    const ownerId = window.prompt("Owner resource ID", activeWorldId) || activeWorldId;
    await studioApi.createFact({ project_id: activeProjectId, world_id: activeWorldId || null, branch_id: branchIdForCanon(activeBranchId), owner_type: ownerId === activeWorldId ? "world" : "entity_family", owner_id: ownerId, path, value: turn.story || "", status: "draft", authority: "user_explicit", source_type: "turn", source_id: turn.id });
  };

  const proposeSheet = async (turn: Turn) => {
    if (!activeProjectId || sheetProposalBusy) return;
    setSheetProposalBusy(true);
    setError("");
    try {
      const result = await studioApi.createStoryLabSheetProposal({
        project_id: activeProjectId,
        world_id: activeWorldId || null,
        branch_id: branchIdForCanon(activeBranchId),
        session_id: activeSession?.id || null,
        turn_id: turn.id,
        source_text: turn.story || "",
        prompt_text: turn.user_prompt || "",
        kind: conversationProfile.story_lab_focus === "character" ? "character" : "plot",
      });
      setSheetProposal(result);
      const items = ((result.items || [result]) as JsonMap[]);
      setActiveSheetIndex(0);
      setSelectedSheetIds(items.map((item) => String(((item.change || {}) as JsonMap).id || "")).filter(Boolean));
      const proposal = ((items[0]?.proposal || result.proposal || {}) as JsonMap);
      setSheetBranchName(`${String(proposal.name || "Story Lab")} proposal`);
    } catch (proposalError) {
      setError((proposalError as Error).message || "Could not create the sheet proposal.");
    } finally {
      setSheetProposalBusy(false);
    }
  };

  const updateSheetDraft = (changes: JsonMap) => {
    setSheetProposal((current) => {
      if (!current) return current;
      const items = [...((current.items || [current]) as JsonMap[])];
      const item = items[activeSheetIndex] || items[0];
      items[activeSheetIndex] = { ...item, proposal: { ...((item.proposal || {}) as JsonMap), ...changes } };
      return { ...current, items, ...(activeSheetIndex === 0 ? { proposal: items[0].proposal } : {}) };
    });
  };

  const chooseSheetTarget = (targetId: string) => {
    const matches = activeSheetMatches;
    const target = matches.find((item) => String(item.id) === targetId);
    if (!target) {
      updateSheetDraft({ operation: "create", target_id: null, target_family_id: null, base_updated_at: null, base_revision: 0 });
      updateActiveSheetChange(null);
      return;
    }
    updateSheetDraft({
      operation: "update",
      target_id: target.id,
      target_family_id: target.family_id || null,
      base_updated_at: target.updated_at || null,
      base_revision: target.base_revision || 0,
    });
    updateActiveSheetChange(target.old_value || "");
  };

  const updateActiveSheetChange = (oldValue: unknown) => {
    setSheetProposal((current) => {
      if (!current) return current;
      const items = [...((current.items || [current]) as JsonMap[])];
      const item = items[activeSheetIndex] || items[0];
      items[activeSheetIndex] = { ...item, change: { ...((item.change || {}) as JsonMap), old_value: oldValue } };
      return { ...current, items, ...(activeSheetIndex === 0 ? { change: items[0].change } : {}) };
    });
  };

  const toggleSheetSelection = (item: JsonMap, checked: boolean) => {
    const id = String(((item.change || {}) as JsonMap).id || "");
    const proposal = (item.proposal || {}) as JsonMap;
    setSelectedSheetIds((current) => {
      const next = new Set(current);
      checked ? next.add(id) : next.delete(id);
      if (proposal.kind === "relationship" && checked) {
        const endpoints = new Set([String(proposal.subject_name || "").toLowerCase(), String(proposal.object_name || "").toLowerCase()]);
        sheetItems.forEach((candidate) => {
          const draft = (candidate.proposal || {}) as JsonMap;
          if (endpoints.has(String(draft.name || "").toLowerCase())) next.add(String(((candidate.change || {}) as JsonMap).id || ""));
        });
      } else if (proposal.kind !== "relationship" && !checked) {
        const name = String(proposal.name || "").toLowerCase();
        sheetItems.forEach((candidate) => {
          const draft = (candidate.proposal || {}) as JsonMap;
          if (draft.kind === "relationship" && [draft.subject_name, draft.object_name].some((value) => String(value || "").toLowerCase() === name)) next.delete(String(((candidate.change || {}) as JsonMap).id || ""));
        });
      }
      return Array.from(next).filter(Boolean);
    });
  };

  const applySheetProposal = async (action: "accept" | "reject" | "branch") => {
    const items = ((sheetProposal?.items || (sheetProposal ? [sheetProposal] : [])) as JsonMap[]);
    if (!items.length || sheetProposalBusy) return;
    setSheetProposalBusy(true);
    setError("");
    try {
      const result = await studioApi.applyStoryLabSheetBundle({
        action,
        items: items.map((item) => ({
          change_id: String(((item.change || {}) as JsonMap).id || ""),
          proposal: (item.proposal || {}) as JsonMap,
          selected: action === "reject" || selectedSheetIds.includes(String(((item.change || {}) as JsonMap).id || "")),
        })),
        branch_name: sheetBranchName.trim(),
      });
      setSheetProposal(null);
      if (action !== "reject") {
        await onLibraryChanged?.();
        onInspect(action === "branch" ? "Sheet saved to branch" : "Sheet proposal accepted", result);
      }
    } catch (proposalError) {
      setError((proposalError as Error).message || "Could not apply the sheet proposal.");
    } finally {
      setSheetProposalBusy(false);
    }
  };

  const modeMeta = MODE_META[conversationMode];
  const ModeIcon = modeMeta.icon;
  const presence = (conversationProfile.presence || DEFAULT_CONVERSATION_PROFILE.presence || {}) as JsonMap;
  const perspective = (conversationProfile.perspective || DEFAULT_CONVERSATION_PROFILE.perspective || {}) as JsonMap;
  const blueprint = (conversationProfile.blueprint || DEFAULT_CONVERSATION_PROFILE.blueprint || {}) as JsonMap;
  const livingSession = (conversationProfile.living_session || DEFAULT_CONVERSATION_PROFILE.living_session || {}) as JsonMap;
  const preferredName = userProfile?.preferred_names?.find((item) => item.context === "casual")?.value
    || userProfile?.preferred_names?.find((item) => item.primary)?.value
    || userProfile?.display_name
    || "You";
  const partnerName = String(userProfile?.collaboration?.partner_name || "Arline").trim() || "Arline";
  const linkedSelfName = String((userProfile?.presence_defaults || {}).display_name || preferredName);
  const presenceSuggestion = /\b(?:what if i was|i want to be in|put me in|play as|enter the story)\b/i.test(prompt);
  const timelineItems = [
    ...turns.map((turn, index) => ({ kind: "turn" as const, createdAt: String(turn.created_at || ""), key: turnKey(turn, index), turn, index })),
    ...(activeSession?.mode_events || []).map((event, index) => ({ kind: "mode" as const, createdAt: String(event.created_at || ""), key: String(event.id || `mode-${index}`), event })),
  ].sort((left, right) => left.createdAt.localeCompare(right.createdAt));
  const sheetItems = ((sheetProposal?.items || (sheetProposal ? [sheetProposal] : [])) as JsonMap[]);
  const activeSheetItem = sheetItems[activeSheetIndex] || sheetItems[0] || {};
  const activeSheetDraft = (activeSheetItem.proposal || {}) as JsonMap;
  const activeSheetChange = (activeSheetItem.change || {}) as JsonMap;
  const activeSheetMatches = (activeSheetItem.matches || []) as JsonMap[];

  return (
    <div data-mode={conversationMode} data-notebook-open={notebookOpen && !focusMode} data-focus={focusMode} data-empty={!turns.length && !pendingPrompt && !liveText} className={`chat-workspace writing-studio ${["story_lab", "interactive", "character_room"].includes(conversationMode) ? "has-conversation-context" : ""} ${conversationMode === "story_lab" ? "is-story-lab" : ""} ${conversationMode === "story_lab" && conversationProfile.story_lab_focus === "my_presence" ? "has-presence-studio" : ""}`}>
      <section className="chat-header">
        <div className="chat-header-identity">
          <span className="chat-header-glyph" aria-hidden="true"><MessageSquareText size={18} /></span>
          <div className="chat-title-block">
            <div className="chat-title-kicker"><span>Conversation</span><i />{activeSession ? "Saved chat" : "New draft"}</div>
            <h1>{activeSession?.title || "New conversation"}</h1>
            <div className="chat-scope-path" aria-label="Conversation scope">
              <span><FolderKanban size={11} />{projectName}</span><b>/</b>
              <span><Globe2 size={11} />{worldName}</span><b>/</b>
              <span><GitBranch size={11} />{branchName}</span>
              {activeSession?.parent_session_id && <em>Forked</em>}
            </div>
          </div>
        </div>
        <div className="chat-header-actions">
          <div className="writing-view-controls">
            <button aria-label="Focus writing" aria-pressed={focusMode} onClick={() => setFocusMode((value) => !value)}><Eye size={15} /><span>Focus</span></button>
            <button ref={notebookToggleRef} aria-label="Toggle context notebook" aria-expanded={notebookOpen && !focusMode} aria-controls="writing-context-notebook" onClick={() => { setNotebookOpen(focusMode || !notebookOpen); setFocusMode(false); }}><PanelRight size={15} /><span>Notes</span></button>
          </div>
          {(activeSession || analysis) && <details className="writing-session-menu" onKeyDown={(event) => { if (event.key === "Escape") { event.currentTarget.open = false; event.currentTarget.querySelector("summary")?.focus(); } }}>
            <summary aria-label="Conversation actions"><MoreHorizontal size={19} /></summary>
            <div>{analysis && <button onClick={() => onInspect("Last analysis", analysis)}><BrainCircuit size={14} />Context</button>}
          {activeSession && <button onClick={() => void renameSession()}><Pencil size={14} />Rename</button>}
          {activeSession && <button onClick={() => void patchActiveSession({ pinned: !activeSession.pinned })}><Pin size={14} />{activeSession.pinned ? "Unpin" : "Pin"}</button>}
          {activeSession && <button onClick={fork}><GitFork size={14} />Fork</button>}
          {activeSession && <button className="danger" onClick={() => setDeleteConfirmOpen(true)}><Trash2 size={14} />Trash</button>}</div>
          </details>}
        </div>
      </section>

      <section className="writing-modebar" aria-label="Writing modes">
        <nav className="writing-mode-tabs" aria-label="Quick writing modes">
          <button aria-pressed={conversationMode === "story_writer"} onClick={() => void changeConversation("story_writer")}><PenLine size={14} /><span>Writer</span></button>
          <button aria-pressed={conversationMode === "story_lab"} onClick={() => void changeConversation("story_lab")}><FlaskConical size={14} /><span>Story Lab</span></button>
          <button aria-pressed={conversationMode === "interactive"} onClick={() => void changeConversation("interactive")}><UserRound size={14} /><span>Interactive</span></button>
        </nav>
        <div className="writing-mode-options"><div className="conversation-mode-control">
            <span>Conversation</span>
            <ArlineSelect ariaLabel="Conversation mode" density="compact" value={conversationMode} options={MODE_OPTIONS} onValueChange={(value) => void changeConversation(value as ConversationMode)} menuMinWidth={330} />
          </div>
          <div className="chat-mode-control">
            <span>Context mode</span>
            <div className="chat-mode-switch" aria-label="Context mode">
              <button title="Canon-aware context" aria-pressed={!scratchMode} className={!scratchMode ? "active" : ""} onClick={() => scratchMode && void toggleScratch()}><BrainCircuit size={13} /><span>Canon-aware</span></button>
              <button title="Scratch context" aria-pressed={scratchMode} className={scratchMode ? "active" : ""} onClick={() => !scratchMode && void toggleScratch()}><Ban size={13} /><span>Scratch</span></button>
            </div>
          </div></div>
      </section>

      <div className="writing-context-tools">
      {(["story_lab", "interactive", "character_room"] as ConversationMode[]).includes(conversationMode) && <section className="conversation-context-bar" aria-label={`${modeMeta.label} controls`}>
        {conversationMode === "story_lab" ? <>
          <div className="story-lab-identity">
            <button className="story-lab-you" onClick={() => setIdentityOpen((value) => !value)}><UserRound size={13} /><span>You: {preferredName}</span><small>Author</small><ChevronDown size={12} /></button>
            <span>{partnerName} knows you from Personal profile; <strong>@{linkedSelfName.replaceAll(" ", "_")}</strong> is your story projection.</span>
            {identityOpen && <div className="identity-popover">
              <header><strong>What {partnerName} knows</strong><button onClick={() => setIdentityOpen(false)}><X size={13} /></button></header>
              <article><ShieldCheck size={15} /><span><strong>Private profile</strong><small>{userProfile?.about || "Personal details remain permission-controlled."}</small></span></article>
              <article><UserRound size={15} /><span><strong>Story projection · @{linkedSelfName.replaceAll(" ", "_")}</strong><small>{String((userProfile?.presence_defaults || {}).entity_variant_id ? "Connected to a Library entity" : "Create or link one in Personalization")}</small></span></article>
              <article><MessageSquareText size={15} /><span><strong>Current session</strong><small>Ideas and decisions from this Story Lab chat only.</small></span></article>
            </div>}
          </div>
          <label><span>Focus</span><ArlineSelect density="compact" ariaLabel="Story Lab focus" value={String(conversationProfile.story_lab_focus || "plot")} options={simpleOptions([["plot", "Plot"], ["character", "Character"], ["world", "World"], ["relationship", "Relationship"], ["scene", "Scene"], ["my_presence", "My Presence"]])} onValueChange={(story_lab_focus) => void patchConversationProfile({ story_lab_focus })} /></label>
          <label><span>Exploration</span><ArlineSelect density="compact" ariaLabel="Exploration" value={String(conversationProfile.exploration || "open")} options={simpleOptions([["grounded", "Grounded"], ["open", "Open"], ["unbound", "Unbound"]])} onValueChange={(exploration) => void patchConversationProfile({ exploration: exploration as ConversationProfile["exploration"] })} /></label>
          <p><FlaskConical size={12} />Ideas stay exploratory until you explicitly stage or promote them.</p>
        </> : conversationMode === "interactive" ? <>
          <label><span>Presence</span><ArlineSelect density="compact" ariaLabel="Presence" value={String(presence.mode || "observer")} options={simpleOptions([["observer", "Observer"], ["self", "As myself"], ["linked_entity", "Play as character"]])} onValueChange={(mode) => void patchConversationProfile({ presence: { ...presence, mode } })} /></label>
          {presence.mode === "self" && <label className="presence-name"><span>Playing as</span><input value={String(presence.display_name || "")} onChange={(event) => setConversationProfile((current) => ({ ...current, presence: { ...(current.presence || {}), display_name: event.target.value } }))} onBlur={() => void patchConversationProfile({ presence })} placeholder="Your story name" /></label>}
          {presence.mode === "linked_entity" && <label><span>Character</span><ArlineSelect density="compact" ariaLabel="Character" value={String(presence.entity_variant_id || "")} options={[{ value: "", label: "Choose from Library…" }, ...characterVariants.map((variant) => ({ value: variant.id, label: variant.display_name || variant.id }))]} onValueChange={(entity_variant_id) => { const variant = characterVariants.find((item) => item.id === entity_variant_id); void patchConversationProfile({ presence: { ...presence, entity_variant_id, display_name: variant?.display_name || "", identity_style: "canonical" } }); }} /></label>}
          {presence.mode === "linked_entity" && <label><span>Embodiment</span><ArlineSelect density="compact" ariaLabel="Embodiment" value={String(presence.identity_style || "canonical")} options={simpleOptions([["canonical", "Canonical"], ["blended", "Blended"], ["avatar", "Avatar"], ["loose", "Loose"]])} onValueChange={(identity_style) => void patchConversationProfile({ presence: { ...presence, identity_style } })} /></label>}
          <label><span>POV</span><ArlineSelect density="compact" ariaLabel="Point of view" value={String(perspective.style || "scene_defined")} options={simpleOptions([["scene_defined", "Scene-defined"], ["first", "First person"], ["second", "Second person"], ["third_limited", "Third limited"], ["omniscient", "Omniscient"]])} onValueChange={(style) => void patchConversationProfile({ perspective: { ...perspective, style } })} /></label>
          <label><span>POV entity</span><ArlineSelect density="compact" ariaLabel="POV entity" value={String(perspective.pov_entity_id || "")} options={[{ value: "", label: "Scene default" }, ...characterVariants.map((variant) => ({ value: variant.id, label: variant.display_name || variant.id }))]} onValueChange={(pov_entity_id) => void patchConversationProfile({ perspective: { ...perspective, pov_entity_id: pov_entity_id || null } })} /></label>
          <label><span>Remember</span><ArlineSelect density="compact" ariaLabel="Presence persistence" value={String(presence.persistence || "session")} options={simpleOptions([["session", "This chat"], ["branch", "This branch"], ["world", "This world"]])} onValueChange={(persistence) => persistence === "session" ? void patchConversationProfile({ presence: { ...presence, persistence: "session" } }) : void persistPresence(persistence as "world" | "branch")} /></label>
          <span className="agency-badge"><ShieldCheck size={12} />Agency: user-directed</span>
        </> : <><label><span>Participants</span><ArlineSelect density="compact" ariaLabel="Add participant" value="" options={[{ value: "", label: "Add from Library…" }, ...characterVariants.map((variant) => ({ value: variant.id, label: variant.display_name || variant.id }))]} onValueChange={(value) => { const participants = Array.from(new Set([...(conversationProfile.participants as string[] | undefined || []), value])).filter(Boolean); void patchConversationProfile({ participants }); }} /></label><span className="agency-badge"><FlaskConical size={12} />Non-canon rehearsal</span>{((conversationProfile.participants as string[] | undefined) || []).map((id) => <button className="participant-chip" key={id} onClick={() => void patchConversationProfile({ participants: ((conversationProfile.participants as string[]) || []).filter((item) => item !== id) })}>{characterVariants.find((item) => item.id === id)?.display_name || id}<X size={10} /></button>)}</>}
      </section>}

      {conversationMode === "story_lab" && conversationProfile.story_lab_focus === "my_presence" && <section className="presence-studio-panel">
        <header><div><strong>My Presence Blueprint</strong><small>Creative intent only — nothing here becomes canon automatically.</small></div><button disabled={!prompt.trim() || blueprintBusy} onClick={() => void extractPresenceBlueprint()}><Sparkles size={13} />{blueprintBusy ? "Extracting…" : "Extract from prompt"}</button></header>
        <div className="blueprint-columns">{(["wanted", "flexible", "suggested", "avoid"] as const).map((bucket) => <article key={bucket}><h3>{bucket}</h3>{((blueprint[bucket] as string[] | undefined) || []).map((item) => <div key={item}><span>{item}</span>{bucket === "suggested" && <><button onClick={() => void approveSuggestion(item, "wanted")} title="Move to wanted"><Check size={11} /></button><button onClick={() => void approveSuggestion(item, "flexible")} title="Move to flexible"><Compass size={11} /></button></>}</div>)}{!((blueprint[bucket] as string[] | undefined) || []).length && <p>None yet</p>}</article>)}</div>
        <footer><input value={presenceName} onChange={(event) => setPresenceName(event.target.value)} placeholder="Character name for promotion" /><button onClick={() => void promotePresence()}><UserRound size={13} />Save as Library character</button><button className="primary" onClick={() => { void patchConversationProfile({ presence: { ...presence, mode: "self", control_policy: "user_directed" } }); void changeConversation("interactive"); }}><Send size={13} />Enter the story</button></footer>
      </section>}

      </div>

      {conversationMode === "story_lab" && <aside className="living-session-panel" id="writing-context-notebook" aria-label="Living session" onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); closeNotebook(); } }}>
        <header><div><span>Living session</span><strong>{activeSession?.title || "Untitled exploration"}</strong></div><button aria-label="Close context notebook" onClick={closeNotebook}><X size={15} /></button></header>
        <section><label><Target size={13} />Current question</label><textarea aria-label="Current question" placeholder="What are we trying to understand?" value={String(livingSession.current_question || "")} onChange={(event) => setConversationProfile((current) => ({ ...current, living_session: { ...(current.living_session || {}), current_question: event.target.value } }))} onBlur={() => void patchLivingSession({ current_question: String(((conversationProfile.living_session || {}) as JsonMap).current_question || "") })} /></section>
        <section><label><Sparkles size={13} />Emerging idea</label><textarea aria-label="Emerging idea" placeholder="The strongest direction will appear here as you talk." value={String(livingSession.emerging_idea || "")} onChange={(event) => setConversationProfile((current) => ({ ...current, living_session: { ...(current.living_session || {}), emerging_idea: event.target.value } }))} onBlur={() => void patchLivingSession({ emerging_idea: String(((conversationProfile.living_session || {}) as JsonMap).emerging_idea || "") })} /></section>
        <section><label><Check size={13} />Decisions</label>{((livingSession.decisions as string[] | undefined) || []).map((item) => <p className="session-decision" key={item}><Check size={11} />{item}</p>)}{!((livingSession.decisions as string[] | undefined) || []).length && <p className="session-empty">Nothing locked in yet.</p>}</section>
        <section><label><Compass size={13} />Open threads</label>{((livingSession.open_threads as string[] | undefined) || []).map((item) => <button className="session-thread" key={item} onClick={() => setPrompt(item)}>{item}</button>)}{!((livingSession.open_threads as string[] | undefined) || []).length && <p className="session-empty">Questions will collect here.</p>}</section>
        <footer><small>Session notes are exploratory and never become canon automatically.</small></footer>
      </aside>}

      {conversationMode !== "story_lab" && <aside className="writing-notebook" id="writing-context-notebook" aria-label="Context notebook" onKeyDown={(event) => { if (event.key === "Escape") { event.stopPropagation(); closeNotebook(); } }}>
        <header className="notebook-heading"><div><span>Context notebook</span><strong>In this scene</strong></div><button aria-label="Close context notebook" onClick={closeNotebook}><X size={15} /></button></header>
        <dl className="notebook-scope">
          <dt>Project</dt><dd>{projectName}</dd>
          <dt>World</dt><dd>{worldName}</dd>
          <dt>Branch</dt><dd>{branchName}</dd>
          <dt>Scene</dt><dd>{activeScene || "None selected"}</dd>
        </dl>
        <section className="notebook-section"><h3><AtSign size={13} />Pinned references <span>{references.length}</span></h3>
          {references.length ? <ul className="notebook-reference-list">{references.map((ref) => <li key={ref.type + ":" + ref.id}><span>{ref.label}</span><button aria-label={"Remove reference " + ref.label} onClick={() => setReferences((items) => items.filter((item) => item !== ref))}><X size={12} /></button></li>)}</ul> : <p>No references pinned. Bring a character, scene, or document into this conversation.</p>}
          <button onClick={showReferencePicker}><AtSign size={13} />Add a reference</button>
        </section>
        <section className="notebook-section"><h3><BrainCircuit size={13} />Writing context</h3><p>{scratchMode ? "Scratch mode uses this conversation without canon retrieval." : "Canon-aware mode can retrieve context from the selected story scope."}</p><button onClick={() => void analyze()}><CornerUpRight size={13} />Inspect context</button></section>
        <p className="notebook-note">Drafts stay in this chat. Review and stage a response when you want to develop canon.</p>
      </aside>}

      <div
        ref={viewportRef}
        className="chat-viewport"
        onScroll={(event) => {
          const viewport = event.currentTarget;
          setFollowLatest(viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 96);
        }}
      >
        {!turns.length && !pendingPrompt && !liveText ? (
          <div className="chat-empty">
            <div className="writing-welcome">
              <div className="writing-welcome-copy">
                <span className="writing-eyebrow"><ModeIcon size={13} />A little space to write</span>
                <h2>{conversationMode === "story_writer" ? <>Find your <em>next line.</em></> : conversationMode === "story_lab" ? <>Give an idea <em>room to grow.</em></> : conversationMode === "interactive" ? <>The scene is set. <em>Step inside.</em></> : conversationMode === "analyst" ? <>Read between <em>the lines.</em></> : <>Let the characters <em>talk.</em></>}</h2>
                <p>{conversationMode === "story_writer" ? "Start something new, return to a scene, or follow a thought a little further." : modeMeta.description.replaceAll("Arline", partnerName) + ". Take your time. We can work it out together."}</p>
                <span className="chat-empty-scope"><Globe2 size={12} />{worldName}<i />{branchName}</span>
              </div>
              <img className="writing-illustration" src={writingIllustration} alt="" aria-hidden="true" />
            </div>
            <div className="starter-grid">
              {modeMeta.starters.map((starter, index) => <button key={starter.title} onClick={() => { setPrompt(starter.prompt); composerInputRef.current?.focus(); }}><span className="starter-number">{String(index + 1).padStart(2, "0")}</span><span><strong>{starter.title}</strong><small>{starter.copy}</small></span><ChevronRight size={14} /></button>)}
            </div>
          </div>
        ) : (
          <div className="turn-list">
            {timelineItems.map((item) => item.kind === "mode" ? <div className="mode-transition-marker" key={item.key}><span /><strong>{MODE_META[String(item.event.from || "story_writer") as ConversationMode]?.label || String(item.event.from || "Story Writer")}</strong><ChevronDown size={11} /><strong>{MODE_META[String(item.event.to || "story_writer") as ConversationMode]?.label || String(item.event.to || "Story Writer")}</strong><small>{item.createdAt}</small><span /></div> : (
              <article className="turn-block" key={item.key}>
                <div className="user-turn">{conversationMode === "story_lab" ? <div className="discussion-user-turn"><span>{preferredName.slice(0, 1).toUpperCase()}</span><div><strong>{preferredName}</strong><p>{item.turn.user_prompt || ""}</p></div></div> : <div>{item.turn.user_prompt || ""}</div>}</div>
                <div className="assistant-turn">
                  <div className="assistant-meta"><b className="draft-number">{conversationMode === "story_lab" ? "Note" : "Draft"} {String(item.index + 1).padStart(2, "0")}</b>{conversationMode === "story_lab" && <i className="brand-mark discussion-arline-mark" aria-hidden="true" />}<span>{partnerName}</span><small>{item.turn.model || "local model"}</small><em>{item.turn.run_id || ""}</em></div>
                  <StoryText text={item.turn.story || ""} discussion={conversationMode === "story_lab"} />
                  <div className="turn-actions">
                    <button onClick={() => void navigator.clipboard.writeText(item.turn.story || "")}><Copy size={13} />Copy</button>
                    <button onClick={() => onInspect("Turn data", item.turn)}><CornerUpRight size={13} />Inspect</button>
                    {conversationMode === "story_lab" ? <>
                      <button onClick={() => { const insight = (item.turn.story || "").split(/\n{2,}/)[0].slice(0, 300); void patchLivingSession({ emerging_idea: insight, insights: Array.from(new Set([...(livingSession.insights as string[] | undefined || []), insight])) }); }}><Sparkles size={13} />Keep as insight</button>
                      <button onClick={() => setPrompt(`Write a scene draft from this Story Lab direction:\n\n${String(livingSession.emerging_idea || item.turn.story || "")}`)}><PenLine size={13} />Draft from this</button>
                      <button disabled={sheetProposalBusy} onClick={() => void proposeSheet(item.turn)}>{sheetProposalBusy ? <LoaderCircle className="spin" size={13} /> : <Save size={13} />}Propose sheet</button>
                    </> : <>
                      <button onClick={() => void reviewTurn(item.turn, "accepted")}><Check size={13} />Accept</button>
                      <button onClick={() => void reviewTurn(item.turn, "rejected")}><Ban size={13} />Reject</button>
                      <button onClick={() => void stageTurn(item.turn)}><Sparkles size={13} />Stage canon</button>
                    </>}
                  </div>
                </div>
              </article>
            ))}
            {pendingPrompt && (
              <article className="turn-block pending-turn">
                <div className="user-turn"><div>{pendingPrompt}</div></div>
              </article>
            )}
            {(generating || liveText) && (
              <article className="turn-block live-turn">
                <div className="assistant-turn">
                  <div className="assistant-meta"><span>{partnerName}</span><small>{stage || "Generating"}</small><LoaderCircle size={13} className="spin" /></div>
                  {liveText ? <StoryText text={liveText} discussion={conversationMode === "story_lab"} /> : <div className="generation-placeholder">{stage || (conversationMode === "story_lab" ? "Preparing discussion…" : "Preparing generation…")}</div>}
                  {liveReasoning && <details><summary>Reasoning stream</summary><pre>{liveReasoning}</pre></details>}
                </div>
              </article>
            )}
            <div ref={bottomRef} />
            {generating && !followLatest && <button className="jump-latest" onClick={() => setFollowLatest(true)}>Jump to latest</button>}
          </div>
        )}
      </div>

      <div className="composer-zone">
        {presenceSuggestion && conversationMode !== "interactive" && <div className="presence-suggestion"><UserRound size={15} /><span><strong>It sounds like you want to enter the story.</strong><small>Switching is always your choice.</small></span><button onClick={() => { void patchConversationProfile({ presence: { ...presence, mode: "self", control_policy: "user_directed" } }); void changeConversation("interactive"); }}>Enter as myself</button><button onClick={() => { void patchConversationProfile({ presence: { ...presence, mode: "linked_entity", control_policy: "user_directed" } }); void changeConversation("interactive"); }}>Choose character</button></div>}
        <div className="context-strip" aria-label="Active conversation context">
          <span className="ready"><strong>Mode</strong>{modeMeta.label}</span>
          {conversationMode === "interactive" && <span><strong>Presence</strong>{presence.mode === "self" ? String(presence.display_name || "Myself") : presence.mode === "linked_entity" ? "Linked character" : "Observer"}</span>}
          <span><strong>Scope</strong>{worldName} / {branchName}</span>
          <span><strong>Scene</strong>{activeScene || "None selected"}</span>
          <span><strong>Pinned refs</strong>{references.length}</span>
          <span className={memoryReady ? "ready" : ""}><strong>Memory</strong>{memoryReady ? "Ready" : "Unavailable"}</span>
        </div>
        {error && <div className="composer-error"><span>{error}</span><button onClick={() => setError("")}><X size={13} /></button></div>}
        {references.length > 0 && (
          <div className="reference-chips">
            {references.map((ref) => (
              <button key={`${ref.type}:${ref.id}`} onClick={() => setReferences((items) => items.filter((item) => item !== ref))}>
                <AtSign size={11} /><span>{ref.label}</span><X size={10} />
              </button>
            ))}
          </div>
        )}
        <div
          className="composer-shell"
          onDragOver={(event) => { event.preventDefault(); event.currentTarget.classList.add("dragging"); }}
          onDragLeave={(event) => event.currentTarget.classList.remove("dragging")}
          onDrop={(event) => { event.preventDefault(); event.currentTarget.classList.remove("dragging"); void addImages(Array.from(event.dataTransfer.files)); }}
        >
          {composerPopupMode && (
            <div className="composer-popup" role="listbox" aria-label={composerPopupMode === "commands" ? "Command suggestions" : "Reference suggestions"}>
              {composerPopupMode === "commands" && commandMatches.map((command) => (
                <button key={command.id} onMouseDown={(event) => event.preventDefault()} onClick={() => selectCommand(command)}>
                  <span className="popup-symbol">/</span><span><strong>/{command.id}</strong><small>{command.description || command.help || command.label || "Command"}</small></span>
                </button>
              ))}
              {composerPopupMode === "mentions" && mentions.map((item) => (
                <button key={`${String(item.type)}:${String(item.id)}`} onMouseDown={(event) => event.preventDefault()} onClick={() => selectMention(item)}>
                  <span className="popup-symbol">@</span><span><strong>{String(item.label || item.name || item.id)}</strong><small>{String(item.subtitle || item.type || "reference")}</small></span>
                </button>
              ))}
              {composerPopupMode === "commands" && commandMatches.length === 0 && (
                <div className="composer-popup-status"><span className="popup-symbol">/</span><span><strong>No matching commands</strong><small>Try a command name such as /continue or /rewrite.</small></span></div>
              )}
              {composerPopupMode === "mentions" && mentionsLoading && mentions.length === 0 && (
                <div className="composer-popup-status"><LoaderCircle className="spin" size={15} /><span><strong>Finding references…</strong><small>Searching this story scope.</small></span></div>
              )}
              {composerPopupMode === "mentions" && !mentionsLoading && mentions.length === 0 && (
                <div className="composer-popup-status"><AtSign size={15} /><span><strong>{mentionsFailed ? "References could not be loaded" : "No matching references"}</strong><small>{mentionsFailed ? "Check the Studio connection and try again." : "Try another entity, scene, document, or world name."}</small></span></div>
              )}
            </div>
          )}

          {attachments.length > 0 && (
            <div className="attachment-tray">
              {attachments.map((attachment) => (
                <article key={attachment.id} className="attachment-card">
                  <button className="attachment-preview" onClick={() => setPreviewAttachment(attachment)} title="Preview image"><img src={attachment.dataUrl} alt="" /><ImageIcon size={13} /></button>
                  <span><strong>{attachment.name}</strong><small>{(attachment.size / 1024 / 1024).toFixed(1)} MiB · {attachment.saved ? "Saved to Library" : "Conversation only"}</small></span>
                  {!attachment.saved && <button onClick={() => void saveAttachment(attachment)} title="Save to Library"><Save size={13} /></button>}
                  <button onClick={() => setAttachments((items) => items.filter((item) => item.id !== attachment.id))} title="Remove image"><X size={13} /></button>
                </article>
              ))}
              <small className={`vision-status ${visionSupport}`}>{visionSupport === "supported" ? "Vision model ready" : visionSupport === "checking" ? "Checking vision support…" : "Selected model has no reported vision support"}</small>
            </div>
          )}

          <textarea
            ref={composerInputRef}
            aria-label={"Message " + partnerName}
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            onKeyDown={(event) => {
              if ((event.key === "Enter" || event.key === "Tab") && composerPopupMode === "commands" && commandMatches[0]) {
                event.preventDefault();
                selectCommand(commandMatches[0]);
                return;
              }
              if ((event.key === "Enter" || event.key === "Tab") && composerPopupMode === "mentions" && mentions[0]) {
                event.preventDefault();
                selectMention(mentions[0]);
                return;
              }
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void generate();
              }
            }}
            onPaste={(event) => {
              const files = Array.from(event.clipboardData.files).filter((file) => file.type.startsWith("image/"));
              if (files.length) void addImages(files);
            }}
            placeholder={modeMeta.placeholder.replaceAll("Arline", partnerName)}
            spellCheck
            rows={1}
          />

          <div className="composer-toolbar">
            <div className="composer-left">
              <input ref={imageInputRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif" multiple hidden onChange={(event) => { void addImages(Array.from(event.target.files || [])); event.currentTarget.value = ""; }} />
              <button title="Attach image" onClick={() => imageInputRef.current?.click()}><Paperclip size={15} /><span>Image</span></button>
              <button title="Reference canon" onClick={showReferencePicker}><AtSign size={15} /><span>Reference</span></button>
              <button className="profile-button" aria-label="Run settings" onClick={() => setSettingsOpen((value) => !value)}>
                <Sparkles size={13} /><span>{config.input_mode === "smart_hybrid" ? "Smart Hybrid" : config.input_mode} · {Math.round((config.visible_output_tokens || 4096) / 1024)}K</span><ChevronDown size={12} />
              </button>
              <button className="context-button" aria-label="Inspect writing context" onClick={() => void analyze()}><BrainCircuit size={14} /><span>Context</span></button>
            </div>
            <div className="composer-right">
              {generating ? (
                <button className="stop-button" onClick={() => abortRef.current?.abort()} title="Stop generation" aria-label="Stop generation"><span /></button>
              ) : (
                <button className="send-button" disabled={!prompt.trim()} onClick={() => void generate()} title="Generate" aria-label="Generate"><span>{conversationMode === "story_writer" ? "Write" : "Send"}</span><Send size={15} /></button>
              )}
            </div>
          </div>

          {settingsOpen && (
            <div className="composer-settings" role="dialog" aria-label="Run settings">
              <header className="run-settings-header">
                <span className="run-settings-icon"><SlidersHorizontal size={15} /></span>
                <div><strong>Run settings</strong><small>Shape this response without leaving the conversation.</small></div>
                <button onClick={() => setSettingsOpen(false)} title="Close run settings"><X size={14} /></button>
              </header>

              <section className="run-settings-section">
                <div className="run-setting-heading"><span><Layers3 size={13} />Generation</span><small>{config.generation_mode === "beats" ? `${config.beat_count || 4} sequential beats` : "One continuous response"}</small></div>
                <div className="setting-segments two">
                  <button className={config.generation_mode === "single" ? "active" : ""} onClick={() => onConfig({ ...config, generation_mode: "single" })}><strong>Single response</strong><small>Focused and continuous</small></button>
                  <button className={config.generation_mode === "beats" ? "active" : ""} onClick={() => onConfig({ ...config, generation_mode: "beats" })}><strong>Beats</strong><small>Long-form progression</small></button>
                </div>
              </section>

              <section className="run-settings-section">
                <div className="run-setting-heading"><span><BrainCircuit size={13} />Planning</span><small>Plan the scene before writing</small></div>
                <div className="setting-segments two" role="group" aria-label="Planning">
                  <button type="button" aria-pressed={!config.planning_enabled} className={!config.planning_enabled ? "active" : ""} onClick={() => onConfig({ ...config, planning_enabled: false })}><strong>Off</strong><small>Write right away</small></button>
                  <button type="button" aria-pressed={config.planning_enabled === true} className={config.planning_enabled ? "active" : ""} onClick={() => onConfig({ ...config, planning_enabled: true })}><strong>On</strong><small>Plan, then write</small></button>
                </div>
              </section>

              <div className="run-settings-grid">
                <section className="run-settings-section compact">
                  <div className="run-setting-heading"><span><Sparkles size={13} />Reasoning</span><small>Model thinking</small></div>
                  <ArlineSelect density="compact" ariaLabel="Reasoning mode" value={config.reasoning} options={(config.reasoning_modes || ["off", "on", "low", "medium", "high"]).map((value) => ({ value, label: value === "off" ? "Off" : value.charAt(0).toUpperCase() + value.slice(1) }))} onValueChange={(reasoning) => onConfig({ ...config, reasoning })} />
                </section>
                <section className="run-settings-section compact">
                  <div className="run-setting-heading"><span><Gauge size={13} />Response length</span><small>{Math.round((config.visible_output_tokens || 4096) / 1024)}K token target</small></div>
                  <div className="token-segments">{[1024, 2048, 4096, 8192, 16384].map((tokens) => <button key={tokens} className={config.visible_output_tokens === tokens ? "active" : ""} onClick={() => onConfig({ ...config, visible_output_tokens: tokens })}>{tokens / 1024}K</button>)}</div>
                </section>
              </div>

              <section className="run-settings-section model-section">
                <div className="run-setting-heading"><span><Cpu size={13} />Model</span><small>{visionSupport === "supported" ? "Vision capable" : "Text generation"}</small></div>
                <div className="model-field"><span className={`model-status ${config.model ? "online" : ""}`} /><input value={config.model || ""} onChange={(event) => onConfig({ ...config, model: event.target.value })} placeholder="Select a model in Settings" /><small>LM Studio</small></div>
              </section>

              <div className="run-settings-grid profile-grid">
                <label><span>Run profile</span><ArlineSelect density="compact" ariaLabel="Run profile" value={selectedProfileId} options={[{ value: "", label: "Current settings" }, ...runProfiles.map((item) => ({ value: String(item.id), label: String(item.name || item.id) }))]} onValueChange={(value) => { setSelectedProfileId(value); const profile = runProfiles.find((item) => String(item.id) === value); const values = (profile?.profile || {}) as Partial<RuntimeConfig>; if (profile) onConfig({ ...config, ...values }); }} /></label>
                <label><span>Context recipe</span><ArlineSelect density="compact" ariaLabel="Context recipe" value={selectedRecipeId} options={[{ value: "", label: "Default recipe" }, ...recipes.map((item) => ({ value: String(item.id), label: String(item.name || item.id) }))]} onValueChange={setSelectedRecipeId} /></label>
              </div>

              {profileSaveOpen ? (
                <div className="profile-save-row"><input autoFocus value={profileName} onChange={(event) => setProfileName(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void saveRunProfile(); if (event.key === "Escape") setProfileSaveOpen(false); }} placeholder="Profile name" /><button onClick={() => setProfileSaveOpen(false)}>Cancel</button><button className="primary" disabled={!profileName.trim() || savingProfile} onClick={() => void saveRunProfile()}>{savingProfile ? <LoaderCircle size={13} className="spin" /> : <Save size={13} />}Save</button></div>
              ) : (
                <footer className="run-settings-footer"><span>Changes apply to the next response.</span><button aria-label="Save current run profile" onClick={() => setProfileSaveOpen(true)}><Save size={13} />Save as profile</button><button className="primary" onClick={() => setSettingsOpen(false)}><Check size={13} />Done</button></footer>
              )}
            </div>
          )}
        </div>
        <div className="writing-composer-footnote"><span><kbd>Enter</kbd> to send <i>·</i> <kbd>Shift + Enter</kbd> for a new line</span><span>Draft first. Review when ready.</span></div>
      </div>
      {deleteConfirmOpen && activeSession && (
        <div className="modal-backdrop chat-delete-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !deletingSession) setDeleteConfirmOpen(false); }}>
          <section className="chat-delete-modal" role="alertdialog" aria-modal="true" aria-labelledby="delete-chat-title" aria-describedby="delete-chat-copy">
            <header>
              <span className="chat-delete-icon" aria-hidden="true"><Trash2 size={18} /></span>
              <div><span className="eyebrow">Conversation management</span><strong>Move to Trash</strong></div>
              <button className="chat-delete-close" aria-label="Close confirmation" disabled={deletingSession} onClick={() => setDeleteConfirmOpen(false)}><X size={16} /></button>
            </header>
            <div className="chat-delete-body">
              <h2 id="delete-chat-title">Move this chat to Trash?</h2>
              <p id="delete-chat-copy">It will disappear from Recent chats, but you can restore it later from Studio Tools.</p>
              <div className="chat-delete-target">
                <span aria-hidden="true"><MessageSquareText size={18} /></span>
                <div><small>Chat</small><strong>{activeSession.title || "Untitled chat"}</strong></div>
              </div>
              <div className="chat-delete-note"><AlertTriangle size={15} /><span>Only this conversation is affected. Your project, manuscript, and Library stay untouched.</span></div>
            </div>
            <footer>
              <button autoFocus disabled={deletingSession} onClick={() => setDeleteConfirmOpen(false)}>Keep chat</button>
              <button className="confirm-trash" disabled={deletingSession} onClick={() => void removeSession()}>
                {deletingSession ? <LoaderCircle size={15} className="spin" /> : <Trash2 size={15} />}
                {deletingSession ? "Moving…" : "Move to Trash"}
              </button>
            </footer>
          </section>
        </div>
      )}
      {sheetProposal && (
        <div className="modal-backdrop sheet-proposal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !sheetProposalBusy) void applySheetProposal("reject"); }}>
          <section className="sheet-proposal-modal" role="dialog" aria-modal="true" aria-labelledby="sheet-proposal-title">
            <header>
              <span className="sheet-proposal-icon"><GitBranch size={18} /></span>
              <div><span className="eyebrow">Story Lab · proposal bundle</span><strong id="sheet-proposal-title">Review {sheetItems.length} proposed item{sheetItems.length === 1 ? "" : "s"}</strong></div>
              <button aria-label="Close and reject sheet proposal" title="Close and reject proposal" disabled={sheetProposalBusy} onClick={() => void applySheetProposal("reject")}><X size={16} /></button>
            </header>
            <div className="sheet-proposal-body">
              {sheetItems.length > 1 && <nav className="sheet-bundle-items" aria-label="Proposed resources">
                {sheetItems.map((item, index) => {
                  const draft = (item.proposal || {}) as JsonMap;
                  const id = String(((item.change || {}) as JsonMap).id || "");
                  return <button key={id} className={index === activeSheetIndex ? "active" : ""} onClick={() => setActiveSheetIndex(index)}>
                    <input type="checkbox" checked={selectedSheetIds.includes(id)} onClick={(event) => event.stopPropagation()} onChange={(event) => toggleSheetSelection(item, event.target.checked)} />
                    <span><strong>{String(draft.name || "Untitled")}</strong><small>{String(draft.kind || "item").replace("_", " ")}</small></span>
                  </button>;
                })}
              </nav>}
              <div className="sheet-proposal-status">
                <span className="proposal-status pending">Pending</span>
                <small>{activeSheetDraft.kind === "relationship" ? "Links two distinct Library entities" : activeSheetDraft.operation === "update" ? `Updates an existing ${activeSheetDraft.kind === "plot" ? "Manuscript outline" : `Library ${activeSheetDraft.kind}`}` : `Creates a new ${activeSheetDraft.kind === "plot" ? "Manuscript outline" : `Library ${activeSheetDraft.kind}`}`}</small>
                <code>{String(activeSheetChange.id || "")}</code>
              </div>
              <div className="sheet-proposal-grid">
                <label><span>Item type</span><input value={activeSheetDraft.kind === "plot" ? "Plot outline" : String(activeSheetDraft.kind || "Item").replace(/^./, (value) => value.toUpperCase())} disabled /></label>
                {activeSheetDraft.kind !== "relationship" && <label><span>Change</span><select value={String(activeSheetDraft.target_id || "")} onChange={(event) => chooseSheetTarget(event.target.value)}><option value="">Create new sheet</option>{activeSheetMatches.map((match) => <option key={String(match.id)} value={String(match.id)}>Update {String(match.label)} · {Math.round(Number(match.score || 0) * 100)}% match</option>)}</select></label>}
              </div>
              {activeSheetDraft.kind === "relationship" ? <div className="sheet-proposal-grid relationship-fields">
                <label><span>From</span><input value={String(activeSheetDraft.subject_name || "")} onChange={(event) => updateSheetDraft({ subject_name: event.target.value })} /></label>
                <label><span>Relationship</span><input value={String(activeSheetDraft.relation_type || "related_to")} onChange={(event) => updateSheetDraft({ relation_type: event.target.value })} /></label>
                <label><span>To</span><input value={String(activeSheetDraft.object_name || "")} onChange={(event) => updateSheetDraft({ object_name: event.target.value })} /></label>
              </div> : <label className="sheet-proposal-field"><span>{activeSheetDraft.kind === "character" ? "Character name" : activeSheetDraft.kind === "location" ? "Location name" : "Plot title"}</span><input value={String(activeSheetDraft.name || "")} onChange={(event) => updateSheetDraft({ name: event.target.value })} /></label>}
              {activeSheetDraft.kind !== "relationship" && <div className="sheet-diff">
                {activeSheetDraft.operation === "update" && <section className="removed"><header><span>−</span>Current sheet</header><pre>{String(activeSheetChange.old_value || "No current summary")}</pre></section>}
                <section className="added"><header><span>+</span>Proposed content</header><textarea value={String(activeSheetDraft.content || "")} onChange={(event) => updateSheetDraft({ content: event.target.value })} /></section>
              </div>}
              <label className="sheet-proposal-field branch-name"><span>New branch name</span><input value={sheetBranchName} onChange={(event) => setSheetBranchName(event.target.value)} /><small>Used only by “Save to branch”.</small></label>
            </div>
            <footer>
              <button disabled={sheetProposalBusy} onClick={() => void applySheetProposal("reject")}><Ban size={14} />Reject</button>
              <span />
              <button disabled={sheetProposalBusy || !sheetBranchName.trim() || !selectedSheetIds.length} onClick={() => void applySheetProposal("branch")}><GitBranch size={14} />Save selected to branch</button>
              <button className="primary" title="Accept change bundle" disabled={sheetProposalBusy || !selectedSheetIds.length} onClick={() => void applySheetProposal("accept")}>{sheetProposalBusy ? <LoaderCircle className="spin" size={14} /> : <Check size={14} />}Accept selected</button>
            </footer>
          </section>
        </div>
      )}
      {previewAttachment && (
        <div className="attachment-lightbox" role="dialog" aria-modal="true" aria-label={`Preview ${previewAttachment.name}`} onClick={() => setPreviewAttachment(null)}>
          <div onClick={(event) => event.stopPropagation()}><img src={previewAttachment.dataUrl} alt={previewAttachment.name} /><footer><span>{previewAttachment.name}</span><button onClick={() => setPreviewAttachment(null)}><X size={15} />Close</button></footer></div>
        </div>
      )}
    </div>
  );
}

function branchIdForCanon(branchId: string) { return branchId || null; }

function StoryText({ text, discussion = false }: { text: string; discussion?: boolean }) {
  return (
    <div className={`story-text${discussion ? " discussion-text" : ""}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
}
