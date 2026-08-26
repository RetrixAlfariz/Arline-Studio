import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  AtSign,
  Check,
  Pin,
  Pencil,
  Ban,
  BrainCircuit,
  ChevronDown,
  Copy,
  CornerUpRight,
  FolderKanban,
  GitFork,
  GitBranch,
  Globe2,
  Image as ImageIcon,
  LoaderCircle,
  MessageSquareText,
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
  X,
} from "lucide-react";
import { runtimePayload, streamGeneration, studioApi } from "../api";
import type {
  CommandDefinition,
  GenerationResult,
  ReferenceItem,
  RuntimeConfig,
  Session,
  Turn,
  JsonMap,
  ModelInfo,
} from "../types";

interface ChatAttachment {
  id: string;
  name: string;
  size: number;
  type: string;
  dataUrl: string;
  saved: boolean;
}

interface ChatViewProps {
  config: RuntimeConfig;
  activeProjectId: string;
  activeWorldId: string;
  activeBranchId: string;
  projectName: string;
  worldName: string;
  branchName: string;
  activeSession: Session | null;
  commands: CommandDefinition[];
  onConfig: (config: RuntimeConfig) => void;
  onSession: (session: Session | null) => void;
  onSessionsChanged: () => Promise<void> | void;
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
  activeSession,
  commands,
  onConfig,
  onSession,
  onSessionsChanged,
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
  const [mentions, setMentions] = useState<Array<Record<string, unknown>>>([]);
  const [commandMatches, setCommandMatches] = useState<CommandDefinition[]>([]);
  const [scratchMode, setScratchMode] = useState(Boolean(activeSession?.scratch_mode));
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
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const imageInputRef = useRef<HTMLInputElement | null>(null);

  const turns = useMemo(() => activeSession?.turns || [], [activeSession]);

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
  }, [activeSession?.id]);

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
    if (!followLatest) return;
    const viewport = viewportRef.current;
    if (!viewport) return;
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
    const lastToken = prompt.split(/\s+/).at(-1) || "";
    if (lastToken.startsWith("/") && lastToken.length > 1) {
      const needle = lastToken.slice(1).toLowerCase();
      setCommandMatches(commands.filter((command) => command.id.toLowerCase().includes(needle) || command.aliases?.some((alias) => alias.toLowerCase().includes(needle))).slice(0, 8));
    } else {
      setCommandMatches([]);
    }
    const match = lastToken.match(/^@([^\s@]{1,40})$/);
    if (!match) {
      setMentions([]);
      return;
    }
    const timer = window.setTimeout(() => {
      void studioApi.mentions(match[1], activeProjectId, activeWorldId, activeBranchId)
        .then((result) => setMentions(result.results || []))
        .catch(() => setMentions([]));
    }, 180);
    return () => window.clearTimeout(timer);
  }, [prompt, commands, activeProjectId, activeWorldId, activeBranchId]);

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
    const payload = runtimePayload(config, {
      projectId: activeProjectId,
      worldId: activeWorldId,
      branchId: activeBranchId,
      sessionId: activeSession?.id,
    }, prompt.trim(), references);
    payload.scratch_mode = scratchMode;
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
      if (finalSessionId) await refreshSession(finalSessionId);
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
    onSession(await studioApi.updateSession(activeSession.id, payload));
    await onSessionsChanged();
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

  const showReferencePicker = async () => {
    const result = await studioApi.mentions("", activeProjectId, activeWorldId, activeBranchId);
    setMentions(result.results || []);
    setPrompt((value) => `${value}${value && !value.endsWith(" ") ? " " : ""}@`);
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

  return (
    <div className="chat-workspace">
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
          {analysis && <button onClick={() => onInspect("Last analysis", analysis)}><BrainCircuit size={14} />Context</button>}
          {activeSession && <button onClick={() => void renameSession()}><Pencil size={14} />Rename</button>}
          {activeSession && <button onClick={() => void patchActiveSession({ pinned: !activeSession.pinned })}><Pin size={14} />{activeSession.pinned ? "Unpin" : "Pin"}</button>}
          {activeSession && <button onClick={fork}><GitFork size={14} />Fork</button>}
          {activeSession && <button className="danger" onClick={() => setDeleteConfirmOpen(true)}><Trash2 size={14} />Trash</button>}
          <div className="chat-mode-control">
            <span>Context mode</span>
            <div className="chat-mode-switch" aria-label="Conversation mode">
              <button aria-pressed={!scratchMode} className={!scratchMode ? "active" : ""} onClick={() => scratchMode && void toggleScratch()}><BrainCircuit size={13} />Canon-aware</button>
              <button aria-pressed={scratchMode} className={scratchMode ? "active" : ""} onClick={() => !scratchMode && void toggleScratch()}><Ban size={13} />Scratch</button>
            </div>
          </div>
        </div>
      </section>

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
            <span className="brand-mark chat-empty-brand-mark" aria-hidden="true" />
            <span className="chat-empty-scope"><Target size={12} />{worldName} / {branchName}</span>
            <h2>Start inside your story scope</h2>
            <p>Continue the active scene, inspect canon, or give Arline an explicit direction. References and memory stay grounded in this world and branch.</p>
            <div className="starter-grid">
              <button onClick={() => setPrompt("Continue the current scene while preserving established character behavior.")}><PenLine size={18} /><span><strong>Continue the scene</strong><small>Move the active scene forward without breaking established behavior.</small></span></button>
              <button onClick={() => setPrompt("/intuition What is the strongest unresolved narrative pressure right now?")}><BrainCircuit size={18} /><span><strong>Inspect story pressure</strong><small>Surface unresolved tension, likely beats, and uncertainty.</small></span></button>
              <button onClick={() => setPrompt("Summarize the active scene state and identify likely continuity risks.")}><Check size={18} /><span><strong>Check continuity</strong><small>Review the current scope for contradictions before writing.</small></span></button>
            </div>
          </div>
        ) : (
          <div className="turn-list">
            {turns.map((turn, index) => (
              <article className="turn-block" key={turnKey(turn, index)}>
                <div className="user-turn"><div>{turn.user_prompt || ""}</div></div>
                <div className="assistant-turn">
                  <div className="assistant-meta"><span>Arline</span><small>{turn.model || "local model"}</small><em>{turn.run_id || ""}</em></div>
                  <StoryText text={turn.story || ""} />
                  <div className="turn-actions">
                    <button onClick={() => void navigator.clipboard.writeText(turn.story || "")}><Copy size={13} />Copy</button>
                    <button onClick={() => onInspect("Turn data", turn)}><CornerUpRight size={13} />Inspect</button>
                    <button onClick={() => void reviewTurn(turn, "accepted")}><Check size={13} />Accept</button>
                    <button onClick={() => void reviewTurn(turn, "rejected")}><Ban size={13} />Reject</button>
                    <button onClick={() => void stageTurn(turn)}><Sparkles size={13} />Stage canon</button>
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
                  <div className="assistant-meta"><span>Arline</span><small>{stage || "Generating"}</small><LoaderCircle size={13} className="spin" /></div>
                  {liveText ? <StoryText text={liveText} /> : <div className="generation-placeholder">{stage || "Preparing generation…"}</div>}
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
        <div className="context-strip" aria-label="Active conversation context">
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
          {(commandMatches.length > 0 || mentions.length > 0) && (
            <div className="composer-popup">
              {commandMatches.map((command) => (
                <button key={command.id} onMouseDown={(event) => event.preventDefault()} onClick={() => selectCommand(command)}>
                  <span className="popup-symbol">/</span><span><strong>/{command.id}</strong><small>{command.description || command.help || command.label || "Command"}</small></span>
                </button>
              ))}
              {mentions.map((item) => (
                <button key={`${String(item.type)}:${String(item.id)}`} onMouseDown={(event) => event.preventDefault()} onClick={() => selectMention(item)}>
                  <span className="popup-symbol">@</span><span><strong>{String(item.label || item.name || item.id)}</strong><small>{String(item.subtitle || item.type || "reference")}</small></span>
                </button>
              ))}
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
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void generate();
              }
            }}
            onPaste={(event) => {
              const files = Array.from(event.clipboardData.files).filter((file) => file.type.startsWith("image/"));
              if (files.length) void addImages(files);
            }}
            placeholder="Message Arline…"
            spellCheck
            rows={1}
          />

          <div className="composer-toolbar">
            <div className="composer-left">
              <input ref={imageInputRef} type="file" accept="image/png,image/jpeg,image/webp,image/gif" multiple hidden onChange={(event) => { void addImages(Array.from(event.target.files || [])); event.currentTarget.value = ""; }} />
              <button title="Attach image" onClick={() => imageInputRef.current?.click()}><Paperclip size={15} /><span>Image</span></button>
              <button title="Reference canon" onClick={() => void showReferencePicker()}><AtSign size={15} /><span>Reference</span></button>
              <button className="profile-button" onClick={() => setSettingsOpen((value) => !value)}>
                <Sparkles size={13} /><span>{config.input_mode === "smart_hybrid" ? "Smart Hybrid" : config.input_mode} · {Math.round((config.visible_output_tokens || 4096) / 1024)}K</span><ChevronDown size={12} />
              </button>
              <button className="context-button" onClick={() => void analyze()}><BrainCircuit size={14} /><span>Context</span></button>
            </div>
            <div className="composer-right">
              {generating ? (
                <button className="stop-button" onClick={() => abortRef.current?.abort()} title="Stop generation"><span /></button>
              ) : (
                <button className="send-button" disabled={!prompt.trim()} onClick={() => void generate()} title="Generate"><Send size={15} /></button>
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

              <div className="run-settings-grid">
                <section className="run-settings-section compact">
                  <div className="run-setting-heading"><span><Sparkles size={13} />Reasoning</span><small>Model deliberation</small></div>
                  <select aria-label="Reasoning mode" value={config.reasoning} onChange={(event) => onConfig({ ...config, reasoning: event.target.value })}>{(config.reasoning_modes || ["off", "on", "low", "medium", "high"]).map((value) => <option key={value} value={value}>{value === "off" ? "Off" : value.charAt(0).toUpperCase() + value.slice(1)}</option>)}</select>
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
                <label><span>Run profile</span><select value={selectedProfileId} onChange={(event) => { setSelectedProfileId(event.target.value); const profile = runProfiles.find((item) => String(item.id) === event.target.value); const values = (profile?.profile || {}) as Partial<RuntimeConfig>; if (profile) onConfig({ ...config, ...values }); }}><option value="">Current settings</option>{runProfiles.map((item) => <option key={String(item.id)} value={String(item.id)}>{String(item.name || item.id)}</option>)}</select></label>
                <label><span>Context recipe</span><select value={selectedRecipeId} onChange={(event) => setSelectedRecipeId(event.target.value)}><option value="">Default recipe</option>{recipes.map((item) => <option key={String(item.id)} value={String(item.id)}>{String(item.name || item.id)}</option>)}</select></label>
              </div>

              {profileSaveOpen ? (
                <div className="profile-save-row"><input autoFocus value={profileName} onChange={(event) => setProfileName(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void saveRunProfile(); if (event.key === "Escape") setProfileSaveOpen(false); }} placeholder="Profile name" /><button onClick={() => setProfileSaveOpen(false)}>Cancel</button><button className="primary" disabled={!profileName.trim() || savingProfile} onClick={() => void saveRunProfile()}>{savingProfile ? <LoaderCircle size={13} className="spin" /> : <Save size={13} />}Save</button></div>
              ) : (
                <footer className="run-settings-footer"><span>Changes apply to the next response.</span><button aria-label="Save current run profile" onClick={() => setProfileSaveOpen(true)}><Save size={13} />Save as profile</button><button className="primary" onClick={() => setSettingsOpen(false)}><Check size={13} />Done</button></footer>
              )}
            </div>
          )}
        </div>
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
      {previewAttachment && (
        <div className="attachment-lightbox" role="dialog" aria-modal="true" aria-label={`Preview ${previewAttachment.name}`} onClick={() => setPreviewAttachment(null)}>
          <div onClick={(event) => event.stopPropagation()}><img src={previewAttachment.dataUrl} alt={previewAttachment.name} /><footer><span>{previewAttachment.name}</span><button onClick={() => setPreviewAttachment(null)}><X size={15} />Close</button></footer></div>
        </div>
      )}
    </div>
  );
}

function branchIdForCanon(branchId: string) { return branchId || null; }

function StoryText({ text }: { text: string }) {
  return (
    <div className="story-text">
      {text.split(/\n\s*\n/).filter(Boolean).map((paragraph, index) => <p key={`${index}-${paragraph.slice(0, 24)}`}>{paragraph}</p>)}
    </div>
  );
}
