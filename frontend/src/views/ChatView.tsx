import { useEffect, useMemo, useRef, useState } from "react";
import {
  AtSign,
  Check,
  Pin,
  Pencil,
  Ban,
  BrainCircuit,
  ChevronDown,
  Copy,
  CornerUpRight,
  GitFork,
  LoaderCircle,
  Paperclip,
  Send,
  Sparkles,
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
} from "../types";

interface ChatViewProps {
  config: RuntimeConfig;
  activeProjectId: string;
  activeWorldId: string;
  activeBranchId: string;
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
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement | null>(null);

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
    if (!generating) return;
    bottomRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [liveText, generating]);

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
    const sentPrompt = prompt.trim();
    setPrompt("");

    try {
      const result = await streamGeneration(payload, async (event) => {
        if (event.type === "run.start") {
          runSessionId = String(event.data.session_id || runSessionId || "");
          setStage("Generating");
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
    } catch (generationError) {
      if ((generationError as Error).name !== "AbortError") {
        setError((generationError as Error).message || "Generation failed");
        setPrompt(sentPrompt);
      }
    } finally {
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
    if (!activeSession || !window.confirm(`Delete chat “${activeSession.title}”?`)) return;
    await studioApi.deleteSession(activeSession.id);
    onSession(null);
    await onSessionsChanged();
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
        <div>
          <span className="eyebrow">Chat</span>
          <h1>{activeSession?.title || "New conversation"}</h1>
          <small>{activeSession?.parent_session_id ? "Forked conversation" : "Project-scoped conversation"}</small>
        </div>
        <div className="chat-header-actions">
          <button className={scratchMode ? "active" : ""} onClick={() => void toggleScratch()}><Ban size={14} />{scratchMode ? "Scratch on" : "Scratch"}</button>
          {analysis && <button onClick={() => onInspect("Last analysis", analysis)}><BrainCircuit size={14} />Context</button>}
          {activeSession && <button onClick={() => void renameSession()}><Pencil size={14} />Rename</button>}
          {activeSession && <button onClick={() => void patchActiveSession({ pinned: !activeSession.pinned })}><Pin size={14} />{activeSession.pinned ? "Unpin" : "Pin"}</button>}
          {activeSession && <button onClick={fork}><GitFork size={14} />Fork</button>}
          {activeSession && <button className="danger" onClick={removeSession}><Trash2 size={14} />Trash</button>}
        </div>
      </section>

      <div className="chat-viewport">
        {!turns.length && !liveText ? (
          <div className="chat-empty">
            <img src="/static/assets/brand/arline-primary.svg" alt="" />
            <h2>Ready when you are</h2>
            <p>Reference canon with <kbd>@</kbd>, use <kbd>/</kbd> directives, or continue the current scene. The new frontend talks to the same Python context and generation engine underneath.</p>
            <div className="starter-grid">
              <button onClick={() => setPrompt("Continue the current scene while preserving established character behavior.")}>Continue current scene</button>
              <button onClick={() => setPrompt("/intuition What is the strongest unresolved narrative pressure right now?")}>Inspect narrative intuition</button>
              <button onClick={() => setPrompt("Summarize the active scene state and likely continuity risks.")}>Check continuity</button>
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
          </div>
        )}
      </div>

      <div className="composer-zone">
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
        <div className="composer-shell">
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

          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void generate();
              }
            }}
            placeholder="Message Arline…"
            spellCheck
            rows={1}
          />

          <div className="composer-toolbar">
            <div className="composer-left">
              <button title="Attach/reference" onClick={() => void showReferencePicker()}><Paperclip size={15} /></button>
              <button title="Reference canon" onClick={() => void showReferencePicker()}><AtSign size={15} /></button>
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
            <div className="composer-settings">
              <label><span>Generation</span><select value={config.generation_mode} onChange={(event) => onConfig({ ...config, generation_mode: event.target.value })}><option value="single">Single response</option><option value="beats">Beats</option></select></label>
              <label><span>Reasoning</span><select value={config.reasoning} onChange={(event) => onConfig({ ...config, reasoning: event.target.value })}>{(config.reasoning_modes || ["off", "on", "low", "medium", "high"]).map((value) => <option key={value}>{value}</option>)}</select></label>
              <label><span>Response</span><select value={config.visible_output_tokens} onChange={(event) => onConfig({ ...config, visible_output_tokens: Number(event.target.value) })}><option value={1024}>Short · 1K</option><option value={2048}>Medium · 2K</option><option value={4096}>Long · 4K</option><option value={8192}>Extended · 8K</option><option value={16384}>Max · 16K</option></select></label>
              <label className="wide"><span>Model</span><input value={config.model || ""} onChange={(event) => onConfig({ ...config, model: event.target.value })} placeholder="LM Studio model key" /></label>
              <label><span>Run profile</span><select defaultValue="" onChange={(event) => { const profile = runProfiles.find((item) => String(item.id) === event.target.value); const values = (profile?.profile || {}) as Partial<RuntimeConfig>; if (profile) onConfig({ ...config, ...values }); }}><option value="">Current settings</option>{runProfiles.map((item) => <option key={String(item.id)} value={String(item.id)}>{String(item.name || item.id)}</option>)}</select></label>
              <label><span>Context recipe</span><select value={selectedRecipeId} onChange={(event) => setSelectedRecipeId(event.target.value)}><option value="">Default recipe</option>{recipes.map((item) => <option key={String(item.id)} value={String(item.id)}>{String(item.name || item.id)}</option>)}</select></label>
              <button className="wide" onClick={async () => { const name = window.prompt("Run profile name"); if (name) { await studioApi.saveRunProfile({ name, project_id: activeProjectId, profile: config }); const result = await studioApi.runProfiles(activeProjectId); setRunProfiles(result.profiles || []); } }}>Save current run profile</button>
            </div>
          )}
        </div>
      </div>
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
