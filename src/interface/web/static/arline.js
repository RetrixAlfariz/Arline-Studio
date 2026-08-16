"use strict";

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const byId = (id) => document.getElementById(id);

const state = {
  config: null,
  modelMap: new Map(),
  bootstrap: null,
  projects: [],
  activeProject: null,
  activeWorld: null,
  activeBranch: null,
  projectTree: null,
  families: [],
  variants: [],
  relationships: [],
  documents: [],
  facts: [],
  tags: [],
  snapshots: [],
  templates: [],
  conflicts: [],
  worlds: [],
  contextRecipes: [],
  runProfiles: [],
  activeRunProfileId: "PROFILE-STORY",
  contextStack: null,
  worldBibleFolders: [],
  worldBibleFolderTree: [],
  worldCollections: [],
  worldSavedViews: [],
  activeWorldFolderId: null,
  activeCollectionId: null,
  activeSavedViewId: null,
  feedbackQueue: [],
  feedbackComparisons: [],
  feedbackTab: "queue",
  homeData: null,
  activity: [],
  issues: [],
  favorites: [],
  navigationHistory: [],
  navigationIndex: -1,
  suppressNavigationRecord: false,
  layoutPrefs: {},
  manifestRefs: [],
  overlays: [],
  activeScene: null,
  sceneCards: [],
  stagedChanges: [],
  timelineEvents: [],
  continuity: null,
  forkGraph: null,
  scratchMode: false,
  lengthSteps: [1024, 2048, 4096],
  detectedReferences: [],
  quickCreatePreview: null,
  quickCreateTimer: null,
  sessions: [],
  activeSession: null,
  activeTurn: null,
  activeRunId: null,
  activeAnalysisId: null,
  activeDocument: null,
  sceneDependencies: [],
  activeWorldTab: "character",
  activeView: "chat",
  selectedReferences: [],
  mentionResults: [],
  mentionIndex: 0,
  slashResults: [],
  slashIndex: 0,
  commandResults: [],
  commandIndex: 0,
  formHandler: null,
  feedbackMode: null,
  feedbackTurnId: null,
  contextCache: {
    wcf: "",
    aif: "",
    brief: null,
    workspace: null,
    projections: [],
    traceChoices: [],
    contextBreakdown: null,
  },
  draftTimer: null,
};

const ISSUE_LABELS = [
  "hallucination", "too_formal", "translationese", "repetitive",
  "semantic_echo", "bad_projection", "state_error", "relationship_error",
  "wrong_voice", "too_short", "too_long", "internal_id_leakage", "other",
];

const ENTITY_ICONS = {
  character: "♙", location: "⌖", item: "◈", organization: "⌘",
  world_rule: "§", lore: "≡", relationship: "∞", document: "▤",
  world: "◎", command: "/", session: "◉", folder: "▱", project: "▣",
  entity_family: "◇", entity_variant: "◇", fact: "·", timeline: "◷",
};

const MODE_NOTES = {
  smart_hybrid: "WCF + compact request + only unresolved raw fragments.",
  wcf: "Writer Context Format only; no full raw prompt duplication.",
  raw: "Raw prompt baseline; no symbolic writer context is sent.",
  wcf_raw: "WCF plus full raw prompt. Useful for diagnosis, but redundant.",
  aif_core: "Internal AIF-Core projection for ablation and teacher-model tests.",
};

const COMMANDS = [
  { id: "continue", label: "/continue", description: "Continue the active scene", action: "insert", text: "/continue " },
  { id: "rewrite", label: "/rewrite", description: "Rewrite selected/current material", action: "insert", text: "/rewrite " },
  { id: "analyze", label: "/analyze", description: "Analyze the current prompt without generation", action: "analyze" },
  { id: "new-scene", label: "Create scene", description: "Create a new scene document", action: "new-document" },
  { id: "new-character", label: "Create character", description: "Create a character family and current-world variant", action: "new-character" },
  { id: "new-template", label: "Create entity template", description: "Create a reusable character/location/item sheet structure", action: "new-template" },
  { id: "conflicts", label: "Resolve conflicts", description: "Review contradictory facts in the active scope", action: "conflicts" },
  { id: "sandbox", label: "Open sandbox branch", description: "Create a non-canonical what-if branch", action: "sandbox" },
  { id: "snapshot", label: "Save world snapshot", description: "Checkpoint current world/branch state", action: "snapshot" },
  { id: "switch-world", label: "Switch world", description: "Choose another world or AU", action: "world-picker" },
  { id: "dataset", label: "Open Feedback Lab", description: "Review generated prose, comparisons, and advanced exports", action: "data" },
  { id: "inspector", label: "Open context/runtime inspector", description: "Inspect context assembly, trace, validator, and model runtime", action: "inspector" },
  { id: "new-any", label: "/new", description: "Create an entity, world, folder, document, or project from natural text", action: "quick-create" },
  { id: "scratch", label: "/scratch", description: "Toggle scratch mode; exploration does not enter canon staging", action: "scratch" },
  { id: "fork", label: "/fork", description: "Fork the active chat from its latest turn", action: "fork-chat" },
  { id: "context", label: "/context", description: "Open explainable context assembly", action: "context" },
  { id: "continuity", label: "/continuity", description: "Run continuity lint for this project and world", action: "continuity" },
  { id: "scene", label: "/scene", description: "Set or inspect the active narrative scene", action: "active-scene" },
  { id: "import", label: "Import manuscript", description: "Import Markdown/text into the current Project binder", action: "import-manuscript" },
  { id: "activity", label: "Open Activity Center", description: "Review issues, recover Trash, and inspect recent actions", action: "activity" },
];

function escapeHTML(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function pretty(value) {
  return JSON.stringify(value ?? {}, null, 2);
}

function parseJSON(value, fallback = {}) {
  if (typeof value !== "string") return value ?? fallback;
  const text = value.trim();
  if (!text) return fallback;
  try { return JSON.parse(text); }
  catch (error) { throw new Error(`Invalid JSON: ${error.message}`); }
}

function formatDate(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function formatRelative(value) {
  if (!value) return "";
  const date = new Date(value);
  const delta = Date.now() - date.valueOf();
  const minutes = Math.floor(delta / 60000);
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d`;
  return date.toLocaleDateString();
}

function storyHTML(text) {
  return String(text || "")
    .split(/\n\s*\n/)
    .filter(Boolean)
    .map((paragraph) => `<p>${escapeHTML(paragraph).replaceAll("\n", "<br>")}</p>`)
    .join("");
}

function wordCount(text) {
  return (String(text || "").trim().match(/\S+/g) || []).length;
}

function timezoneName() {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

async function api(path, options = {}) {
  const config = { ...options, headers: { ...(options.headers || {}) } };
  if (config.body && typeof config.body !== "string") {
    config.headers["Content-Type"] = "application/json";
    config.body = JSON.stringify(config.body);
  }
  const response = await fetch(path, config);
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      message = payload.detail || payload.message || message;
    } catch (_) {}
    throw new Error(message);
  }
  const type = response.headers.get("content-type") || "";
  if (type.includes("application/json")) return response.json();
  return response.text();
}

function toast(message, duration = 2800) {
  const node = byId("toast");
  node.textContent = message;
  node.classList.remove("hidden");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.classList.add("hidden"), duration);
}

function loading(show, title = "Arline is working…", detail = "Preparing context") {
  byId("loadingTitle").textContent = title;
  byId("loadingDetail").textContent = detail;
  byId("loadingOverlay").classList.toggle("hidden", !show);
}

function setConnection(online, detail = online ? "online" : "offline") {
  const badge = byId("connectionBadge");
  badge.classList.toggle("online", online);
  badge.classList.toggle("offline", !online);
  $("em", badge).textContent = detail;
}

function contextMenu(x, y, items) {
  closeContextMenu();
  const menu = document.createElement("div");
  menu.className = "context-menu";
  menu.id = "contextMenu";
  for (const item of items) {
    if (item.hidden) continue;
    const button = document.createElement("button");
    button.textContent = item.label;
    if (item.danger) button.classList.add("danger");
    button.addEventListener("click", async () => {
      closeContextMenu();
      await item.action();
    });
    menu.appendChild(button);
  }
  document.body.appendChild(menu);
  const rect = menu.getBoundingClientRect();
  menu.style.left = `${Math.min(x, innerWidth - rect.width - 8)}px`;
  menu.style.top = `${Math.min(y, innerHeight - rect.height - 8)}px`;
}

function closeContextMenu() {
  byId("contextMenu")?.remove();
}

function setView(view) {
  state.activeView = view;
  $$("[data-view-panel]").forEach((panel) => panel.classList.toggle("active", panel.dataset.viewPanel === view));
  $$("[data-view]").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  if (view === "draft") renderDocuments();
  if (view === "world") renderWorldGrid();
  if (view === "data") loadDatasetStats();
}

function openInspector(tab = null) {
  byId("inspector").classList.add("open");
  byId("inspector").setAttribute("aria-hidden", "false");
  byId("inspectorScrim").classList.remove("hidden");
  if (tab) activateInspectorTab(tab);
}

function closeInspector() {
  byId("inspector").classList.remove("open");
  byId("inspector").setAttribute("aria-hidden", "true");
  byId("inspectorScrim").classList.add("hidden");
}

function activateInspectorTab(tab) {
  $$("[data-inspector-tab]").forEach((node) => node.classList.toggle("active", node.dataset.inspectorTab === tab));
  $$("[data-inspector-panel]").forEach((node) => node.classList.toggle("active", node.dataset.inspectorPanel === tab));
}

function openSheet() {
  byId("sheetPanel").classList.add("open");
  byId("sheetPanel").setAttribute("aria-hidden", "false");
  byId("sheetScrim").classList.remove("hidden");
}

function closeSheet() {
  byId("sheetPanel").classList.remove("open");
  byId("sheetPanel").setAttribute("aria-hidden", "true");
  byId("sheetScrim").classList.add("hidden");
}

function updateBreadcrumbs() {
  const project = state.activeProject?.name || "No project";
  const world = state.activeWorld?.name || "No world";
  const branch = state.activeBranch?.name || "No branch";
  const buttons = $$("#breadcrumbs button");
  buttons[0].textContent = project;
  buttons[1].textContent = world;
  buttons[2].textContent = branch;
  const sandbox = ["sandbox", "what_if"].includes(state.activeBranch?.kind);
  byId("sandboxBadge").classList.toggle("hidden", !sandbox);
  byId("scopeStatus").innerHTML = `<span class="status-dot"></span><span>${escapeHTML(world)} · ${escapeHTML(branch)}</span>`;
  byId("worldTitle").textContent = world;
  byId("worldDescription").textContent = state.activeWorld?.description || "Canonical entities, variants, relationships, timeline, and lore.";
}

function updateContextChipUI() {
  const container = byId("contextChips");
  container.innerHTML = state.selectedReferences.map((ref) => `
    <span class="context-chip" data-ref-id="${escapeHTML(ref.id)}">
      ${escapeHTML(ENTITY_ICONS[ref.type] || "@")} <b>@${escapeHTML(ref.label)}</b>
      <button title="Remove context">×</button>
    </span>`).join("");
  container.classList.toggle("hidden", state.selectedReferences.length === 0);
  $$(".context-chip", container).forEach((chip) => {
    $("button", chip).addEventListener("click", () => {
      state.selectedReferences = state.selectedReferences.filter((ref) => ref.id !== chip.dataset.refId);
      updateContextChipUI();
      updateScopeVisualization();
    });
  });
  byId("contextScopeLabel").textContent = `${state.selectedReferences.length} refs`;
}

function runtimePayload() {
  const visible = Number(byId("visibleTokens").value || 4096);
  return {
    server_url: byId("serverUrl").value.trim(),
    api_key: byId("apiKey").value,
    model: byId("modelSelect").value,
    gpu_ratio: Number(byId("gpuRatio").value),
    context_length: Number(byId("contextLength").value),
    input_mode: byId("modeSelect").value,
    reasoning: byId("reasoningSelect").value,
    projection_mode: byId("projectionMode").value,
    temperature: Number(byId("temperature").value),
    top_p: Number(byId("topP").value),
    top_k: Number(byId("topK").value),
    min_p: Number(byId("minP").value),
    repeat_penalty: Number(byId("repeatPenalty").value),
    visible_output_tokens: visible,
    reasoning_reserve_tokens: Number(byId("reasoningReserve").value),
    generation_mode: byId("generationMode").value,
    beat_count: Number(byId("beatCount").value),
    beat_tokens: Number(byId("beatTokens").value),
    total_story_target_tokens: Number(byId("totalStoryTokens").value),
  };
}

function dynamicVisibleMaximum() {
  const model = state.modelMap.get(byId("modelSelect").value);
  const modelLimit = Number(model?.max_context_length || byId("contextLength").value || 32768);
  const estimatedInput = Number(state.contextCache.contextBreakdown?.estimated_total_tokens || Math.ceil(byId("promptInput").value.length / 4));
  const reasoning = byId("reasoningSelect").value === "off" ? 0 : Number(byId("reasoningReserve").value || 0);
  const safety = Number(byId("safetyReserve").value || 0);
  return Math.max(256, Math.floor((modelLimit - estimatedInput - reasoning - safety) / 256) * 256);
}

function syncDynamicLength() {
  const maximum = dynamicVisibleMaximum();
  const option = $('#lengthPreset option[value="maximum"]');
  if (option) option.textContent = `Maximum · ${maximum.toLocaleString()} tokens`;
  byId("visibleTokens").max = maximum;
  if (byId("lengthPreset").value === "maximum") byId("visibleTokens").value = maximum;
}

function promptPayload() {
  return {
    ...runtimePayload(),
    prompt: byId("promptInput").value,
    timezone: timezoneName(),
    session_id: state.activeSession?.id || null,
    project_id: state.activeProject?.id || null,
    world_id: state.activeWorld?.id || null,
    branch_id: state.activeBranch?.id || null,
    folder_id: state.activeSession?.folder_id || null,
    references: state.selectedReferences,
  };
}

function updateBudgetUI() {
  syncDynamicLength();
  const runtime = runtimePayload();
  const total = runtime.visible_output_tokens + (runtime.reasoning === "off" ? 0 : runtime.reasoning_reserve_tokens);
  byId("totalBudget").textContent = total.toLocaleString();
  byId("modeNote").textContent = MODE_NOTES[runtime.input_mode] || "";
  byId("beatControls").classList.toggle("hidden", runtime.generation_mode !== "beats");
  const estimatedInput = state.contextCache.contextBreakdown?.estimated_total_tokens || Math.ceil(byId("promptInput").value.length / 4);
  const contextMax = runtime.context_length || 32768;
  const pct = Math.min(100, ((estimatedInput + total) / contextMax) * 100);
  $("i", byId("contextBudgetBar")).style.width = `${pct}%`;
  $("i", byId("contextBudgetBar")).style.background = pct > 90 ? "var(--danger)" : pct > 75 ? "var(--warning)" : "var(--accent)";
  byId("tokenEstimate").textContent = `${estimatedInput.toLocaleString()} input est. · ${total.toLocaleString()} output ceiling`;
}

function applyConfig(config) {
  state.config = config;
  byId("serverUrl").value = config.server_url || "http://127.0.0.1:1234";
  byId("apiKey").value = config.api_key || "";
  byId("gpuRatio").value = config.gpu_ratio ?? 1;
  byId("contextLength").value = config.context_length ?? 32768;
  byId("modeSelect").value = config.input_mode || "smart_hybrid";
  byId("projectionMode").value = config.projection_mode || "balanced";
  byId("temperature").value = config.temperature ?? 0.8;
  byId("topP").value = config.top_p ?? 0.95;
  byId("topK").value = config.top_k ?? 40;
  byId("minP").value = config.min_p ?? 0;
  byId("repeatPenalty").value = config.repeat_penalty ?? 1.05;
  byId("visibleTokens").value = config.visible_output_tokens ?? 4096;
  byId("reasoningReserve").value = config.reasoning_reserve_tokens ?? 4096;
  byId("generationMode").value = config.generation_mode || "single";
  byId("beatCount").value = config.beat_count || 4;
  byId("beatTokens").value = config.beat_tokens || 2048;
  byId("totalStoryTokens").value = config.total_story_target_tokens || 8192;
  syncRangeOutputs();
  updateBudgetUI();
}

function syncRangeOutputs() {
  for (const [id, output, digits] of [
    ["gpuRatio", "gpuRatioOut", 2], ["temperature", "temperatureOut", 2],
    ["topP", "topPOut", 2], ["minP", "minPOut", 2], ["repeatPenalty", "repeatPenaltyOut", 2],
  ]) byId(output).textContent = Number(byId(id).value).toFixed(digits);
}

async function refreshModels() {
  const params = new URLSearchParams({ server_url: byId("serverUrl").value.trim(), api_key: byId("apiKey").value });
  try {
    const payload = await api(`/api/models?${params}`);
    state.modelMap.clear();
    const select = byId("modelSelect");
    const previous = select.value || state.config?.model || "";
    select.innerHTML = `<option value="">Select model…</option>`;
    for (const model of payload.models || []) {
      state.modelMap.set(model.key, model);
      const option = document.createElement("option");
      option.value = model.key;
      option.textContent = `${model.display_name}${model.loaded ? " · loaded" : ""}${model.max_context_length ? ` · ${Math.round(model.max_context_length / 1024)}K` : ""}`;
      select.appendChild(option);
    }
    if ([...select.options].some((option) => option.value === previous)) select.value = previous;
    else if (payload.models?.[0]) select.value = payload.models[0].key;
    setConnection(true, `${payload.models?.length || 0} models`);
    updateModelInfo();
  } catch (error) {
    setConnection(false, "offline");
    byId("modelInfo").textContent = error.message;
  }
}

function updateModelInfo() {
  const model = state.modelMap.get(byId("modelSelect").value);
  const reasoning = byId("reasoningSelect");
  const previous = reasoning.value;
  reasoning.innerHTML = "";
  const allowed = model?.reasoning_options?.length ? model.reasoning_options : ["off", "on"];
  for (const mode of allowed) {
    const option = document.createElement("option");
    option.value = mode;
    option.textContent = mode === "off" ? "Thinking Off" : `Thinking ${mode[0].toUpperCase()}${mode.slice(1)}`;
    reasoning.appendChild(option);
  }
  reasoning.value = allowed.includes(previous) ? previous : allowed.includes(state.config?.reasoning) ? state.config.reasoning : allowed[0];
  if (!model) {
    byId("modelInfo").textContent = "Select a model to inspect its capabilities.";
  } else {
    if (model.max_context_length) {
      byId("contextLength").value = model.max_context_length;
      byId("contextLength").max = model.max_context_length;
    }
    byId("modelInfo").innerHTML = `<b>${escapeHTML(model.display_name)}</b><br>Loaded: ${model.loaded ? "yes" : "no"}<br>Max context: ${(model.max_context_length || 0).toLocaleString()}<br>Reasoning: ${escapeHTML(allowed.join(", "))}`;
  }
  updateReasoningWarning();
  updateBudgetUI();
}

function updateReasoningWarning() {
  const mode = byId("reasoningSelect").value;
  const input = byId("modeSelect").value;
  const note = byId("reasoningNote");
  if (mode !== "off") {
    const risky = input === "wcf_raw" ? " WCF + Raw is especially redundant." : "";
    note.textContent = `Native reasoning is experimental for prose and may consume most output tokens.${risky}`;
    note.classList.remove("hidden");
  } else note.classList.add("hidden");
}

async function saveSettings() {
  try {
    await api("/api/settings", { method: "POST", body: runtimePayload() });
    toast("Settings saved");
  } catch (error) { toast(`Save failed: ${error.message}`); }
}

async function reloadModel() {
  loading(true, "Reloading local model…", "Applying GPU and context settings");
  try {
    const result = await api("/api/model/reload", { method: "POST", body: runtimePayload() });
    toast(`Model ${result.action || "reloaded"}`);
    await refreshModels();
  } catch (error) { toast(`Reload failed: ${error.message}`, 5000); }
  finally { loading(false); }
}

async function loadWorkspaceBootstrap() {
  const bootstrap = await api("/api/workspace/bootstrap");
  state.bootstrap = bootstrap;
  state.projects = bootstrap.projects || [];
  const active = bootstrap.active || {};
  const nextProjectId = active.project?.id || state.projects[0]?.id;
  if (nextProjectId) {
    await selectScope(nextProjectId, active.world?.id, active.branch?.id);
    return;
  }

  state.activeProject = null;
  state.activeWorld = null;
  state.activeBranch = null;
  state.activeDocument = null;
  state.activeSession = null;
  state.projectTree = { folders: [] };
  state.families = [];
  state.variants = [];
  state.relationships = [];
  state.documents = [];
  state.tags = [];
  state.facts = [];
  state.snapshots = [];
  state.templates = [];
  state.conflicts = [];
  state.sessions = [];
  state.selectedReferences = [];
  renderScopeSelectors();
  updateBreadcrumbs();
  updateContextChipUI();
  renderProjectTree();
  renderLibraryCounts();
  renderTags();
  renderDocuments();
  renderSessions();
  renderWorldGrid();
  updateScopeVisualization();
}

function applyProjectDefaults(project) {
  const settings = project?.settings || {};
  if (settings.preferred_model) byId("modelSelect").value = settings.preferred_model;
  if (settings.reasoning && [...byId("reasoningSelect").options].some((o) => o.value === settings.reasoning)) byId("reasoningSelect").value = settings.reasoning;
  if (settings.projection_mode && [...byId("projectionMode").options].some((o) => o.value === settings.projection_mode)) byId("projectionMode").value = settings.projection_mode;
  state.projectLanguage = settings.language || "follow_prompt";
  document.body.classList.toggle("advanced-mode", Boolean(settings.advanced));
}

async function selectScope(projectId, worldId = null, branchId = null) {
  if (!projectId) return;
  loading(true, "Opening workspace…", "Resolving world variants and folders");
  try {
    const project = await api(`/api/projects/${encodeURIComponent(projectId)}`);
    state.activeProject = project;
    applyProjectDefaults(project);
    state.projects = (await api("/api/projects")).projects || state.projects;
    const worlds = project.worlds || [];
    const world = worlds.find((item) => item.id === worldId) || worlds.find((item) => item.id === project.default_world_id) || worlds[0];
    state.activeWorld = world ? await api(`/api/worlds/${encodeURIComponent(world.id)}`) : null;
    const branches = state.activeWorld?.branches || [];
    state.activeBranch = branches.find((item) => item.id === branchId) || branches.find((item) => item.kind === "main") || branches[0] || null;
    state.selectedReferences = [];
    updateContextChipUI();
    renderScopeSelectors();
    updateBreadcrumbs();
    await Promise.all([loadProjectData(), loadSessions()]);
  } catch (error) { toast(`Workspace error: ${error.message}`, 5000); }
  finally { loading(false); }
}

function renderScopeSelectors() {
  const projectSelect = byId("projectSelect");
  projectSelect.innerHTML = state.projects.map((item) => `<option value="${escapeHTML(item.id)}">${escapeHTML(item.name)}</option>`).join("");
  if (state.activeProject) projectSelect.value = state.activeProject.id;
  const worldSelect = byId("worldSelect");
  worldSelect.innerHTML = (state.activeProject?.worlds || []).map((item) => `<option value="${escapeHTML(item.id)}">${escapeHTML(item.name)} · ${escapeHTML(item.canon_status)}</option>`).join("");
  if (state.activeWorld) worldSelect.value = state.activeWorld.id;
  const branchSelect = byId("branchSelect");
  branchSelect.innerHTML = (state.activeWorld?.branches || []).map((item) => `<option value="${escapeHTML(item.id)}">${escapeHTML(item.name)} · ${escapeHTML(item.kind)}</option>`).join("");
  if (state.activeBranch) branchSelect.value = state.activeBranch.id;
}

function scopeQuery(extra = {}) {
  return new URLSearchParams({
    ...(state.activeProject?.id ? { project_id: state.activeProject.id } : {}),
    ...(state.activeWorld?.id ? { world_id: state.activeWorld.id } : {}),
    ...(state.activeBranch?.id ? { branch_id: state.activeBranch.id } : {}),
    ...extra,
  });
}

async function loadProjectData() {
  if (!state.activeProject) return;
  const q = scopeQuery();
  const [tree, variants, relationships, documents, tags, facts, snapshots] = await Promise.all([
    api(`/api/projects/${state.activeProject.id}/tree?${q}`),
    state.activeWorld ? api(`/api/entities/variants?${q}`) : { variants: [] },
    state.activeWorld ? api(`/api/relationships?${q}`) : { relationships: [] },
    api(`/api/documents?${q}`),
    api(`/api/tags?project_id=${state.activeProject.id}`),
    api(`/api/facts?${q}`),
    state.activeWorld ? api(`/api/snapshots?world_id=${state.activeWorld.id}`) : { snapshots: [] },
  ]);
  state.projectTree = tree;
  state.families = tree.families || [];
  state.variants = variants.variants || [];
  state.relationships = relationships.relationships || [];
  state.documents = documents.documents || [];
  state.tags = tags.tags || [];
  state.facts = facts.facts || [];
  state.snapshots = snapshots.snapshots || [];
  state.templates = tree.templates || [];
  state.conflicts = tree.conflicts || [];
  renderProjectTree();
  renderLibraryCounts();
  renderTags();
  renderDocuments();
  renderWorldGrid();
  updateScopeVisualization();
}

function renderLibraryCounts() {
  const count = (type) => state.families.filter((item) => item.entity_type === type).length;
  byId("characterCount").textContent = count("character");
  byId("locationCount").textContent = count("location");
  byId("itemCount").textContent = count("item");
  byId("relationshipCount").textContent = state.relationships.length;
  byId("loreCount").textContent = count("lore") + count("world_rule") + state.documents.filter((item) => item.document_type === "lore").length;
}

function renderProjectTree() {
  const root = byId("projectTree");
  root.innerHTML = "";
  const documentsByFolder = new Map();
  const familiesByFolder = new Map();
  for (const doc of state.documents) {
    const key = doc.folder_id || "root";
    if (!documentsByFolder.has(key)) documentsByFolder.set(key, []);
    documentsByFolder.get(key).push(doc);
  }
  for (const family of state.families) {
    const key = family.folder_id || "root";
    if (!familiesByFolder.has(key)) familiesByFolder.set(key, []);
    familiesByFolder.get(key).push(family);
  }

  const appendDocuments = (container, folderId, depth) => {
    for (const doc of documentsByFolder.get(folderId || "root") || []) {
      container.appendChild(documentTreeNode(doc, depth));
    }
  };

  const appendEntities = (container, folderId, depth) => {
    for (const family of familiesByFolder.get(folderId || "root") || []) {
      container.appendChild(entityTreeNode(family, depth));
    }
  };

  const appendFolder = (container, folder, depth = 0) => {
    const wrapper = document.createElement("div");
    wrapper.className = "tree-folder-group";
    const row = document.createElement("div");
    row.className = "tree-node";
    row.style.paddingLeft = `${depth * 13}px`;
    row.innerHTML = `<button class="tree-toggle">⌄</button><span class="tree-icon">▱</span><button class="tree-main">${escapeHTML(folder.name)}</button><button class="row-menu">•••</button>`;
    const children = document.createElement("div");
    children.className = "tree-children";
    wrapper.append(row, children);
    container.appendChild(wrapper);

    $(".tree-toggle", row).addEventListener("click", () => {
      children.classList.toggle("hidden");
      $(".tree-toggle", row).textContent = children.classList.contains("hidden") ? "›" : "⌄";
    });
    $(".tree-main", row).addEventListener("click", () => { setView("draft"); filterDocumentsByFolder(folder.id); });
    $(".row-menu", row).addEventListener("click", (event) => contextMenu(event.clientX, event.clientY, [
      { label: "New document here", action: () => openDocumentForm(folder.id) },
      { label: "New character/entity here", action: () => openEntityForm("character", folder.id) },
      { label: "New subfolder", action: () => openFolderForm(folder.id) },
      { label: "Rename", action: () => renameFolder(folder) },
      { label: "Delete", danger: true, action: () => deleteFolder(folder) },
    ]));

    appendDocuments(children, folder.id, depth + 1);
    appendEntities(children, folder.id, depth + 1);
    for (const child of folder.children || []) appendFolder(children, child, depth + 1);
  };

  appendDocuments(root, null, 0);
  appendEntities(root, null, 0);
  for (const folder of state.projectTree?.folders || []) appendFolder(root, folder, 0);
  byId("projectTreeEmpty").classList.toggle("hidden", root.children.length > 0);
}

function entityTreeNode(family, depth) {
  const row = document.createElement("div");
  row.className = "tree-node";
  row.style.paddingLeft = `${depth * 13 + 4}px`;
  row.innerHTML = `<span class="tree-icon">${escapeHTML(ENTITY_ICONS[family.entity_type] || "◇")}</span><button class="tree-main">${escapeHTML(family.name)}</button><button class="row-menu">•••</button>`;
  $(".tree-main", row).addEventListener("click", () => openEntitySheet(family.id));
  $(".row-menu", row).addEventListener("click", (event) => contextMenu(event.clientX, event.clientY, [
    { label: "Open sheet", action: () => openEntitySheet(family.id) },
    { label: "Reference in chat", action: () => addReference({ type: "entity_family", id: family.id, label: family.name }) },
    { label: "Move to folder", action: () => moveEntityFamily(family) },
    { label: "Delete entity family", danger: true, action: () => deleteEntityFamily(family) },
  ]));
  return row;
}

function documentTreeNode(doc, depth) {
  const row = document.createElement("div");
  row.className = "tree-node";
  row.style.paddingLeft = `${depth * 13 + 4}px`;
  row.innerHTML = `<span class="tree-icon">${doc.document_type === "scene" ? "◫" : "▤"}</span><button class="tree-main">${escapeHTML(doc.title)}</button><button class="row-menu">•••</button>`;
  $(".tree-main", row).addEventListener("click", () => openDocument(doc.id));
  $(".row-menu", row).addEventListener("click", (event) => contextMenu(event.clientX, event.clientY, [
    { label: "Open", action: () => openDocument(doc.id) },
    { label: "Reference in chat", action: () => addReference({ type: "document", id: doc.id, label: doc.title }) },
    { label: "Scene card / outline metadata", hidden: !["scene", "draft", "chapter", "outline"].includes(doc.document_type), action: () => openSceneCardForm(doc) },
    { label: "Set as active scene", hidden: !["scene", "draft", "chapter"].includes(doc.document_type), action: () => openActiveSceneForm(doc.id) },
    { label: "Move to folder", action: () => moveDocument(doc) },
    { label: "Delete", danger: true, action: () => deleteDocument(doc) },
  ]));
  return row;
}

function renderTags() {
  const section = byId("tagSection");
  section.classList.toggle("hidden", state.tags.length === 0);
  byId("tagList").innerHTML = state.tags.map((tag) => `<button class="tag-chip" style="--tag-color:${escapeHTML(tag.color)}" data-tag="${escapeHTML(tag.name)}">#${escapeHTML(tag.name)}</button>`).join("");
  $$("#tagList .tag-chip").forEach((button) => {
    button.addEventListener("click", () => loadSessions(button.dataset.tag));
    button.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      const tag = state.tags.find((item) => item.name === button.dataset.tag);
      if (tag) contextMenu(event.clientX, event.clientY, [
        { label: `Delete #${tag.name}`, danger: true, action: () => deleteTag(tag) },
      ]);
    });
  });
  byId("worldTagFilters").innerHTML = state.tags.map((tag) => `<button class="tag-chip" style="--tag-color:${escapeHTML(tag.color)}" data-tag-id="${tag.id}">#${escapeHTML(tag.name)}</button>`).join("");
  $$("#worldTagFilters .tag-chip").forEach((button) => button.addEventListener("contextmenu", (event) => {
    event.preventDefault();
    const tag = state.tags.find((item) => item.id === button.dataset.tagId);
    if (tag) contextMenu(event.clientX, event.clientY, [
      { label: `Delete #${tag.name}`, danger: true, action: () => deleteTag(tag) },
    ]);
  }));
}

async function loadSessions(tag = "") {
  if (!state.activeProject) return;
  const q = scopeQuery({ limit: "150", ...(tag ? { tag } : {}) });
  const payload = await api(`/api/sessions?${q}`);
  state.sessions = payload.sessions || [];
  renderSessions();
}

function sessionGroups(sessions) {
  const groups = { Today: [], Yesterday: [], "Previous 7 days": [], "Previous 30 days": [], Older: [] };
  const now = new Date();
  for (const item of sessions) {
    const date = new Date(item.updated_at);
    const days = Math.floor((now - date) / 86400000);
    if (days <= 0) groups.Today.push(item);
    else if (days === 1) groups.Yesterday.push(item);
    else if (days <= 7) groups["Previous 7 days"].push(item);
    else if (days <= 30) groups["Previous 30 days"].push(item);
    else groups.Older.push(item);
  }
  return groups;
}

function renderSessions() {
  const pinned = state.sessions.filter((item) => item.pinned);
  const recent = state.sessions.filter((item) => !item.pinned);
  byId("pinnedSection").classList.toggle("hidden", pinned.length === 0);
  byId("pinnedList").innerHTML = pinned.map(sessionRowHTML).join("");
  const groups = sessionGroups(recent);
  byId("recentList").innerHTML = Object.entries(groups).filter(([, items]) => items.length).map(([label, items]) => `<div class="history-group-label">${label}</div>${items.map(sessionRowHTML).join("")}`).join("");
  byId("historyEmpty").classList.toggle("hidden", state.sessions.length > 0);
  bindSessionRows();
}

function sessionRowHTML(item) {
  return `<div class="session-row ${state.activeSession?.id === item.id ? "active" : ""}" data-session-id="${item.id}"><button class="session-main" title="${escapeHTML(item.title)}">${escapeHTML(item.title)}</button>${item.tags?.slice(0, 1).map((tag) => `<span class="tag-chip">#${escapeHTML(tag)}</span>`).join("") || ""}<button class="row-menu">•••</button></div>`;
}

function bindSessionRows() {
  $$(".session-row").forEach((row) => {
    const id = row.dataset.sessionId;
    $(".session-main", row).addEventListener("click", () => openSession(id));
    $(".row-menu", row).addEventListener("click", (event) => {
      const session = state.sessions.find((item) => item.id === id);
      contextMenu(event.clientX, event.clientY, [
        { label: "Rename", action: () => renameSession(session) },
        { label: session.pinned ? "Unpin" : "Pin", action: () => patchSession(id, { pinned: !session.pinned }) },
        { label: "Fork chat", action: () => forkSession(id) },
        { label: "Edit tags", action: () => editSessionTags(session) },
        { label: "Delete", danger: true, action: () => deleteSession(id) },
      ]);
    });
  });
}

async function openSession(id) {
  loading(true, "Opening chat…", "Loading history and feedback");
  try {
    const session = await api(`/api/sessions/${id}`);
    state.activeSession = session;
    byId("activeChatTitle").textContent = session.title || "Current chat";
    state.selectedReferences = session.workspace_refs || [];
    updateContextChipUI();
    byId("chatLanding").classList.add("hidden");
    byId("conversationSection").classList.remove("hidden");
    renderConversation(session.turns || []);
    setView("chat");
    renderSessions();
  } catch (error) { toast(error.message); }
  finally { loading(false); }
}

function renderConversation(turns) {
  const feed = byId("conversationFeed");
  feed.innerHTML = turns.map((turn) => turnHTML(turn)).join("");
  bindTurnActions();
  feed.lastElementChild?.scrollIntoView({ behavior: "smooth", block: "end" });
}

function turnHTML(turn) {
  const story = turn.feedback_status === "edited_accept" && turn.edited_story ? turn.edited_story : turn.story;
  const stats = turn.stats || {};
  const total = stats.total_output_tokens || 0;
  const reason = stats.reasoning_output_tokens || 0;
  const visible = Math.max(0, total - reason);
  return `<article class="turn" data-turn-id="${turn.id}">
    <div class="turn-user"><div class="user-bubble">${escapeHTML(turn.user_prompt)}</div></div>
    <div class="turn-assistant"><div class="assistant-head"><div class="assistant-meta"><span class="run-chip">${escapeHTML(turn.run_id)}</span><span>${escapeHTML(turn.model || "model")}</span><span>${escapeHTML(turn.mode)} · ${escapeHTML(turn.reasoning)}</span>${turn.feedback_status && turn.feedback_status !== "unreviewed" ? `<span class="feedback-badge ${turn.feedback_status}">${escapeHTML(turn.feedback_status)}</span>` : ""}</div><div class="assistant-actions"><button class="tiny-btn copy-turn">Copy</button><button class="tiny-btn inspect-turn">Inspect</button><button class="tiny-btn save-turn">Save run</button></div></div>
    ${turn.feedback_status === "edited_accept" ? `<div class="edited-marker">Human-edited accepted version</div>` : ""}
    <div class="story-output">${storyHTML(story)}</div>
    <div class="usage-strip">${stats.input_tokens ? `<span class="usage-pill">${stats.input_tokens} in</span>` : ""}${visible ? `<span class="usage-pill">${visible} story</span>` : ""}${reason ? `<span class="usage-pill warning">${reason} reasoning</span>` : ""}${stats.tokens_per_second ? `<span class="usage-pill">${Number(stats.tokens_per_second).toFixed(1)} tok/s</span>` : ""}</div>
    <div class="feedback-row"><button class="accept">✓ Accept</button><button class="edit-accept">✎ Edit & Accept</button><button class="reject">✕ Reject</button><button class="promote">＋ Promote line to canon</button></div></div>
  </article>`;
}

function bindTurnActions() {
  $$(".turn").forEach((node) => {
    const turnId = node.dataset.turnId;
    $(".copy-turn", node).addEventListener("click", () => navigator.clipboard.writeText($(".story-output", node).innerText).then(() => toast("Copied")));
    $(".inspect-turn", node).addEventListener("click", () => inspectTurn(turnId));
    $(".save-turn", node).addEventListener("click", () => saveRunFromTurn(turnId));
    $(".accept", node).addEventListener("click", () => openFeedback(turnId, "accepted"));
    $(".edit-accept", node).addEventListener("click", () => openFeedback(turnId, "edited_accept", $(".story-output", node).innerText));
    $(".reject", node).addEventListener("click", () => openFeedback(turnId, "rejected"));
    $(".promote", node).addEventListener("click", () => promoteStorySelection(turnId, $(".story-output", node).innerText));
  });
}

async function inspectTurn(turnId) {
  const turn = await api(`/api/turns/${turnId}`);
  state.activeTurn = turn;
  state.activeRunId = turn.run_id;
  state.contextCache.wcf = turn.wcf || "";
  state.contextCache.aif = turn.aif_core || "";
  state.contextCache.workspace = { text: turn.workspace_context || "", scope: turn.workspace_scope || {}, explicit_references: turn.workspace_refs || [] };
  state.contextCache.projections = turn.projections || [];
  byId("wcfOutput").textContent = state.contextCache.wcf || "No WCF stored.";
  byId("aifOutput").textContent = state.contextCache.aif || "No AIF stored.";
  byId("workspaceContextOutput").textContent = turn.workspace_context || "No workspace context.";
  byId("projectionOutput").textContent = pretty(turn.projections || []);
  byId("postValidation").textContent = pretty(turn.post_validation || {});
  byId("reasoningOutput").textContent = turn.reasoning_text || "No reasoning output.";
  byId("statsOutput").textContent = pretty(turn.stats || {});
  openInspector("context");
}

async function saveRunFromTurn(turnId) {
  const turn = await api(`/api/turns/${turnId}`);
  if (!turn.run_id) return toast("This turn has no run bundle in active cache");
  try {
    const result = await api("/api/save", { method: "POST", body: { run_id: turn.run_id } });
    if (result.download_url) location.href = result.download_url;
    toast(`Saved ${turn.run_id}`);
  } catch (error) { toast(`Save unavailable: ${error.message}`); }
}

async function patchSession(id, patch) {
  await api(`/api/sessions/${id}`, { method: "PATCH", body: patch });
  await loadSessions();
}

function renameSession(session) {
  openForm({ title: "Rename chat", eyebrow: "History", fields: [{ name: "title", label: "Title", value: session.title, full: true }], onSubmit: async (values) => { await patchSession(session.id, { title: values.title }); } });
}

async function forkSession(id) {
  const fork = await api(`/api/sessions/${id}/fork`, { method: "POST", body: {} });
  await loadSessions();
  await openSession(fork.id);
  toast("Chat forked");
}

function moveSession(session) {
  const folders = flattenFolders(state.projectTree?.folders || []);
  openForm({ title: "Move chat", eyebrow: "Folder", fields: [{ name: "folder_id", label: "Folder", type: "select", options: [{ value: "", label: "No folder" }, ...folders.map((f) => ({ value: f.id, label: f.path }))], value: session.folder_id || "", full: true }], onSubmit: async (values) => { await patchSession(session.id, { folder_id: values.folder_id || "" }); } });
}

function editSessionTags(session) {
  openForm({ title: "Chat tags", eyebrow: "Organize", fields: [{ name: "tags", label: "Comma-separated tags", value: (session.tags || []).join(", "), full: true }], onSubmit: async (values) => { await patchSession(session.id, { tags: values.tags.split(",").map((x) => x.trim()).filter(Boolean) }); } });
}

async function deleteSession(id) {
  if (!confirm("Delete this chat and all turns?")) return;
  await api(`/api/sessions/${id}`, { method: "DELETE" });
  if (state.activeSession?.id === id) newChat();
  await loadSessions();
  toast("Chat deleted");
}

function newChat() {
  state.activeSession = null;
  state.activeTurn = null;
  state.activeRunId = null;
  state.selectedReferences = [];
  updateContextChipUI();
  byId("promptInput").value = "";
  byId("conversationFeed").innerHTML = "";
  byId("conversationSection").classList.add("hidden");
  byId("chatLanding").classList.remove("hidden");
  byId("analysisStrip").classList.add("hidden");
  setView("chat");
  renderSessions();
  byId("promptInput").focus();
}

async function analyzePrompt() {
  const payload = promptPayload();
  if (!payload.prompt.trim()) return toast("Write a prompt first");
  loading(true, "Analyzing prompt…", "Building world state, projections, and writer context");
  try {
    const result = await api("/api/analyze", { method: "POST", body: payload });
    state.activeAnalysisId = result.analysis_id;
    loadContextResult(result);
    openInspector("context");
    toast("Analysis ready");
  } catch (error) { toast(`Analysis failed: ${error.message}`, 5000); }
  finally { loading(false); }
}

function loadContextResult(result) {
  state.contextCache.wcf = result.wcf || "";
  state.contextCache.aif = result.aif_core || "";
  state.contextCache.brief = result.narrative_brief || null;
  state.contextCache.workspace = result.workspace_context || null;
  state.contextCache.projections = result.projections || [];
  state.contextCache.traceChoices = result.trace_choices || [];
  state.contextCache.contextBreakdown = result.context_breakdown || null;
  byId("wcfOutput").textContent = result.wcf || "No WCF.";
  byId("aifOutput").textContent = result.aif_core || "No AIF-Core.";
  byId("briefOutput").textContent = result.narrative_brief?.text || pretty(result.narrative_brief || {});
  byId("workspaceContextOutput").textContent = result.workspace_context?.text || "No workspace context.";
  byId("projectionOutput").textContent = pretty(result.projections || []);
  byId("wcfValidation").textContent = pretty(result.wcf_validation || {});
  byId("postValidation").textContent = "Generate to validate prose.";
  renderAnalysisSummary(result.summary || {});
  renderTraceChoices(result.trace_choices || [], result.analysis_id || result.run_id);
  renderContextBreakdown(result.context_breakdown || {});
  updateScopeVisualization();
  updateBudgetUI();
}

function renderAnalysisSummary(summary) {
  byId("analysisStrip").classList.remove("hidden");
  byId("coverageValue").textContent = typeof summary.coverage === "number" ? `${(summary.coverage * 100).toFixed(0)}%` : summary.coverage ?? "—";
  byId("factsValue").textContent = summary.facts ?? summary.entities ?? "—";
  byId("transitionsValue").textContent = summary.transitions ?? summary.events ?? "—";
  byId("projectionsValue").textContent = summary.projections ?? state.contextCache.projections.length;
  byId("wcfTokenValue").textContent = summary.wcf_tokens ?? state.contextCache.contextBreakdown?.wcf_tokens ?? "—";
}

function renderTraceChoices(choices, cacheId) {
  const select = byId("traceSelect");
  select.innerHTML = `<option value="">Select fact…</option>${choices.map((item) => `<option value="${escapeHTML(item.id || item.trace_id)}">${escapeHTML(item.label || item.path || item.id)}</option>`).join("")}`;
  select.dataset.cacheId = cacheId || "";
}

function renderContextBreakdown(breakdown) {
  if (!breakdown || !Object.keys(breakdown).length) {
    byId("contextBreakdown").textContent = "Analyze to inspect context allocation.";
    return;
  }
  const rows = Object.entries(breakdown).filter(([, value]) => typeof value === "number");
  byId("contextBreakdown").innerHTML = rows.map(([key, value]) => `<div><span>${escapeHTML(key.replaceAll("_", " "))}</span><b>${Number(value).toLocaleString()}</b></div>`).join("");
}

function updateScopeVisualization() {
  const ws = state.contextCache.workspace;
  const explicit = state.selectedReferences;
  const auto = ws?.auto_selected || [];
  const pinned = ws?.pinned || [];
  byId("scopeVisualization").innerHTML = `<div class="scope-path"><span>${escapeHTML(state.activeProject?.name || "Project")}</span><b>›</b><span>${escapeHTML(state.activeWorld?.name || "World")}</span><b>›</b><span>${escapeHTML(state.activeBranch?.name || "Branch")}</span></div><div class="scope-list"><b>Explicit</b>: ${explicit.length ? explicit.map((x) => `@${escapeHTML(x.label)}`).join(", ") : "none"}<br><b>Auto-selected</b>: ${auto.length}<br><b>Pinned</b>: ${pinned.length}</div>`;
}

async function generateStory() {
  const payload = promptPayload();
  if (!payload.prompt.trim()) return toast("Write a prompt first");
  if (!payload.model) return toast("Select a model first");
  loading(true, payload.generation_mode === "beats" ? "Writing story beats…" : "Writing story…", payload.generation_mode === "beats" ? `Planning ${payload.beat_count} bounded continuations` : "Compiling context and calling LM Studio");
  try {
    const result = await api("/api/generate", { method: "POST", body: payload });
    state.activeRunId = result.run_id;
    state.activeSession = { id: result.session_id, title: result.session_title, workspace_refs: state.selectedReferences };
    state.activeTurn = { id: result.turn_id };
    loadContextResult(result);
    byId("postValidation").textContent = pretty(result.post_validation || {});
    byId("reasoningOutput").textContent = result.reasoning || "No separate reasoning output.";
    byId("statsOutput").textContent = pretty(result.stats || {});
    await Promise.all([loadSessions(), openSession(result.session_id), loadDatasetStats()]);
    byId("promptInput").value = "";
    updateBudgetUI();
    toast(`Generated ${result.run_id}`);
  } catch (error) { toast(`Generation failed: ${error.message}`, 6000); }
  finally { loading(false); }
}

async function loadTrace() {
  const select = byId("traceSelect");
  if (!select.value || !select.dataset.cacheId) return;
  try {
    const result = await api(`/api/trace/${encodeURIComponent(select.dataset.cacheId)}/${encodeURIComponent(select.value)}`);
    byId("traceOutput").textContent = pretty(result);
  } catch (error) { byId("traceOutput").textContent = error.message; }
}

function addReference(ref) {
  if (!state.selectedReferences.some((item) => item.type === ref.type && item.id === ref.id)) state.selectedReferences.push({ ...ref, mode: ref.mode || "context" });
  updateContextChipUI();
  updateScopeVisualization();
  scheduleContextStackSync();
  toast(`Referenced @${ref.label}`);
}

async function updateAutocomplete() {
  const input = byId("promptInput");
  const before = input.value.slice(0, input.selectionStart);
  const mention = before.match(/@([^@\n]{0,50})$/);
  const slash = before.match(/(?:^|\n)\/([\w-]{0,40})$/);
  if (mention) {
    const q = new URLSearchParams({ ...Object.fromEntries(scopeQuery()), q: mention[1], limit: "15" });
    try {
      const result = await api(`/api/mentions?${q}`);
      state.mentionResults = result.results || [];
      state.mentionIndex = 0;
      renderMentionPopup();
    } catch (_) { hideAutocomplete(); }
  } else if (slash) {
    const query = slash[1].toLowerCase();
    state.slashResults = COMMANDS.filter((item) => item.label.toLowerCase().includes(query) || item.description.toLowerCase().includes(query));
    state.slashIndex = 0;
    renderSlashPopup();
  } else hideAutocomplete();
}

function hideAutocomplete() {
  byId("mentionPopup").classList.add("hidden");
  byId("slashPopup").classList.add("hidden");
}

function renderMentionPopup() {
  const popup = byId("mentionPopup");
  if (!state.mentionResults.length) return popup.classList.add("hidden");
  const groups = {};
  state.mentionResults.forEach((item) => (groups[item.type] ||= []).push(item));
  let index = 0;
  popup.innerHTML = Object.entries(groups).map(([type, items]) => `<div class="autocomplete-group">${escapeHTML(type.replaceAll("_", " "))}</div>${items.map((item) => {
    const current = index++;
    return `<button class="autocomplete-item ${current === state.mentionIndex ? "active" : ""}" data-index="${current}"><span class="auto-icon">${escapeHTML(ENTITY_ICONS[type] || "@")}</span><span><b>${escapeHTML(item.label)}</b><small>${escapeHTML(item.subtitle || item.path || "")}</small></span><em>${item.current_world ? "current" : ""}</em></button>`;
  }).join("")}`).join("");
  popup.classList.remove("hidden");
  $$(".autocomplete-item", popup).forEach((button) => button.addEventListener("click", () => chooseMention(Number(button.dataset.index))));
}

function chooseMention(index) {
  const item = state.mentionResults[index];
  if (!item) return;
  const input = byId("promptInput");
  const cursor = input.selectionStart;
  const before = input.value.slice(0, cursor);
  const match = before.match(/@([^@\n]{0,50})$/);
  if (!match) return;
  const start = cursor - match[0].length;
  input.value = `${input.value.slice(0, start)}@${item.label} ${input.value.slice(cursor)}`;
  const next = start + item.label.length + 2;
  input.setSelectionRange(next, next);
  addReference({ type: item.type, id: item.id, label: item.label });
  hideAutocomplete();
  input.focus();
}

function renderSlashPopup() {
  const popup = byId("slashPopup");
  if (!state.slashResults.length) return popup.classList.add("hidden");
  popup.innerHTML = state.slashResults.map((item, index) => `<button class="autocomplete-item ${index === state.slashIndex ? "active" : ""}" data-index="${index}"><span class="auto-icon">/</span><span><b>${escapeHTML(item.label)}</b><small>${escapeHTML(item.description)}</small></span></button>`).join("");
  popup.classList.remove("hidden");
  $$(".autocomplete-item", popup).forEach((button) => button.addEventListener("click", () => chooseSlash(Number(button.dataset.index))));
}

function chooseSlash(index) {
  const item = state.slashResults[index];
  if (!item) return;
  hideAutocomplete();
  executeCommand(item);
}

async function executeCommand(command) {
  if (command.action === "insert") {
    const input = byId("promptInput");
    input.value = input.value.replace(/(?:^|\n)\/[\w-]*$/, command.text);
    input.focus();
  } else if (command.action === "analyze") analyzePrompt();
  else if (command.action === "new-document") openDocumentForm();
  else if (command.action === "new-character") openEntityForm("character");
  else if (command.action === "new-template") openTemplateForm();
  else if (command.action === "conflicts") { setView("world"); state.activeWorldTab = "canon"; renderWorldGrid(); }
  else if (command.action === "sandbox") createSandbox();
  else if (command.action === "snapshot") createSnapshot();
  else if (command.action === "world-picker") byId("worldSelect").focus();
  else if (command.action === "data") setView("data");
  else if (command.action === "inspector") openInspector();
  byId("commandDialog").close();
}

function handleComposerKey(event) {
  const mentionVisible = !byId("mentionPopup").classList.contains("hidden");
  const slashVisible = !byId("slashPopup").classList.contains("hidden");
  if (mentionVisible || slashVisible) {
    const items = mentionVisible ? state.mentionResults : state.slashResults;
    const key = mentionVisible ? "mentionIndex" : "slashIndex";
    if (event.key === "ArrowDown") { event.preventDefault(); state[key] = (state[key] + 1) % items.length; mentionVisible ? renderMentionPopup() : renderSlashPopup(); }
    else if (event.key === "ArrowUp") { event.preventDefault(); state[key] = (state[key] - 1 + items.length) % items.length; mentionVisible ? renderMentionPopup() : renderSlashPopup(); }
    else if (event.key === "Enter" || event.key === "Tab") { event.preventDefault(); mentionVisible ? chooseMention(state.mentionIndex) : chooseSlash(state.slashIndex); }
    else if (event.key === "Escape") hideAutocomplete();
    return;
  }
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") { event.preventDefault(); generateStory(); }
}

function openCommandPalette(query = "") {
  const dialog = byId("commandDialog");
  dialog.showModal();
  byId("commandSearch").value = query;
  searchCommands(query);
  setTimeout(() => byId("commandSearch").focus(), 0);
}

async function searchCommands(query) {
  const q = query.trim();
  let remote = [];
  if (q && state.activeProject) {
    try { remote = (await api(`/api/commands?project_id=${state.activeProject.id}&q=${encodeURIComponent(q)}`)).results || []; }
    catch (_) {}
  }
  const local = COMMANDS.filter((item) => !q || item.label.toLowerCase().includes(q.toLowerCase()) || item.description.toLowerCase().includes(q.toLowerCase()));
  state.commandResults = [
    ...local.map((item) => ({ ...item, kind: "command" })),
    ...remote.map((item) => ({ ...item, kind: item.type || "resource", action: "resource" })),
    ...state.sessions.filter((item) => !q || item.title.toLowerCase().includes(q.toLowerCase())).slice(0, 8).map((item) => ({ id: item.id, label: item.title, description: item.prompt_preview || "Chat", kind: "session", action: "session" })),
  ];
  state.commandIndex = 0;
  renderCommandResults();
}

function renderCommandResults() {
  byId("commandResults").innerHTML = state.commandResults.map((item, index) => `<button class="command-item ${index === state.commandIndex ? "active" : ""}" data-index="${index}"><span class="command-item-icon">${escapeHTML(ENTITY_ICONS[item.kind] || "⌘")}</span><span><b>${escapeHTML(item.label || item.name)}</b><small>${escapeHTML(item.description || item.subtitle || item.kind)}</small></span>${item.action === "insert" ? "<kbd>insert</kbd>" : ""}</button>`).join("") || `<div class="empty-state small">No results.</div>`;
  $$(".command-item").forEach((button) => button.addEventListener("click", () => chooseCommand(Number(button.dataset.index))));
}

async function chooseCommand(index) {
  const item = state.commandResults[index];
  if (!item) return;
  if (item.action === "session") { byId("commandDialog").close(); return openSession(item.id); }
  if (item.action === "resource") {
    byId("commandDialog").close();
    if (item.type === "entity_family" || item.type === "entity_variant") return openEntitySheet(item.family_id || item.id, item.type === "entity_variant" ? item.id : null);
    if (item.type === "document") return openDocument(item.id);
    if (item.type === "relationship") return openRelationshipSheet(item.id);
    if (item.type === "world") return selectScope(state.activeProject.id, item.id, null);
  }
  await executeCommand(item);
}

function commandKey(event) {
  if (event.key === "ArrowDown") { event.preventDefault(); state.commandIndex = Math.min(state.commandResults.length - 1, state.commandIndex + 1); renderCommandResults(); }
  else if (event.key === "ArrowUp") { event.preventDefault(); state.commandIndex = Math.max(0, state.commandIndex - 1); renderCommandResults(); }
  else if (event.key === "Enter") { event.preventDefault(); chooseCommand(state.commandIndex); }
}

function openForm({ title, eyebrow = "Create", description = "", fields = [], submit = "Save", onSubmit }) {
  byId("formEyebrow").textContent = eyebrow;
  byId("formTitle").textContent = title;
  byId("formDescription").textContent = description;
  byId("formSubmitBtn").textContent = submit;
  const container = byId("formFields");
  container.innerHTML = "";
  for (const field of fields) {
    const label = document.createElement("label");
    if (field.full) label.classList.add("full");
    label.textContent = field.label;
    let control;
    if (field.type === "textarea" || field.type === "json") {
      control = document.createElement("textarea");
      control.rows = field.rows || (field.type === "json" ? 7 : 4);
      control.value = field.type === "json" && typeof field.value !== "string" ? pretty(field.value || {}) : field.value || "";
    } else if (field.type === "select") {
      control = document.createElement("select");
      control.innerHTML = (field.options || []).map((option) => `<option value="${escapeHTML(option.value)}">${escapeHTML(option.label)}</option>`).join("");
      control.value = field.value ?? "";
    } else if (field.type === "checkbox") {
      control = document.createElement("input");
      control.type = "checkbox";
      control.checked = Boolean(field.value);
    } else {
      control = document.createElement("input");
      control.type = field.type || "text";
      control.value = field.value ?? "";
      if (field.placeholder) control.placeholder = field.placeholder;
    }
    control.name = field.name;
    control.dataset.fieldType = field.type || "text";
    if (field.required) control.required = true;
    label.appendChild(control);
    container.appendChild(label);
  }
  state.formHandler = async () => {
    const values = {};
    for (const control of $$('[name]', container)) {
      if (control.type === "checkbox") values[control.name] = control.checked;
      else if (control.dataset.fieldType === "json") values[control.name] = parseJSON(control.value, {});
      else values[control.name] = control.value;
      if (control.required && !String(values[control.name]).trim()) throw new Error(`${control.name} is required`);
    }
    await onSubmit(values);
  };
  byId("formDialog").showModal();
  setTimeout(() => $("input,textarea,select", container)?.focus(), 0);
}

async function submitForm(event) {
  event.preventDefault();
  if (event.submitter?.value === "cancel") {
    byId("formDialog").close();
    return;
  }
  if (!state.formHandler) return;
  try {
    await state.formHandler();
    byId("formDialog").close();
    toast("Saved");
  } catch (error) { toast(error.message, 5000); }
}

function flattenFolders(folders, prefix = "") {
  const result = [];
  for (const folder of folders) {
    const path = prefix ? `${prefix} / ${folder.name}` : folder.name;
    result.push({ ...folder, path });
    result.push(...flattenFolders(folder.children || [], path));
  }
  return result;
}

function projectActions(event) {
  contextMenu(event.clientX, event.clientY, [
    { label: "New project", action: openProjectForm },
    { label: "New world / AU", action: openWorldForm },
    { label: "Fork current world", action: openForkWorldForm },
    { label: "Edit project", action: editProject },
    { label: "Compare worlds", action: openWorldCompare },
    { label: "New entity template", action: openTemplateForm },
    { label: "Delete custom template", danger: true, hidden: !state.templates.some((item) => item.project_id === state.activeProject?.id), action: deleteCustomTemplate },
    { label: `Resolve conflicts (${state.conflicts.length})`, action: () => { setView("world"); state.activeWorldTab = "canon"; renderWorldGrid(); } },
    { label: "Delete current branch", danger: true, hidden: !state.activeBranch || state.activeBranch.kind === "main", action: () => deleteBranch(state.activeBranch) },
    { label: "Delete current world", danger: true, hidden: !state.activeWorld, action: () => deleteWorld(state.activeWorld) },
    { label: "Delete project", danger: true, hidden: !state.activeProject, action: () => deleteProject(state.activeProject) },
  ]);
}

async function deleteProject(project) {
  if (!project) return;
  const ok = confirm(`Permanently delete project “${project.name}”?\n\nThis removes the project workspace: folders, documents, manifest references, project overlays, active-scene metadata, and project-scoped chats. Shared World Bible worlds, sheets, relationships, and canon remain available. This cannot be undone.`);
  if (!ok) return;
  loading(true, "Deleting project…", "Cleaning workspace lineage and chat scope");
  try {
    await api(`/api/projects/${project.id}`, { method: "DELETE" });
    closeSheet();
    state.activeSession = null;
    state.activeDocument = null;
    await loadWorkspaceBootstrap();
    toast(`Deleted project “${project.name}”`);
  } catch (error) { toast(error.message, 5000); }
  finally { loading(false); }
}

async function deleteWorld(world) {
  if (!world) return;
  const ok = confirm(`Delete world “${world.name}”?\n\nWorld-specific variants, relationships, documents, facts, snapshots, branches, and chats are deleted. Shared entity families remain available to other worlds.`);
  if (!ok) return;
  loading(true, "Deleting world…", "Removing world-scoped data");
  try {
    const projectId = state.activeProject.id;
    await api(`/api/worlds/${world.id}`, { method: "DELETE" });
    closeSheet();
    state.activeDocument = null;
    state.activeSession = null;
    await selectScope(projectId);
    toast(`Deleted world “${world.name}”`);
  } catch (error) { toast(error.message, 5000); }
  finally { loading(false); }
}

async function deleteBranch(branch) {
  if (!branch) return;
  if (branch.kind === "main") return toast("The main branch is protected; delete the world instead");
  const ok = confirm(`Delete branch “${branch.name}”?\n\nBranch-only variants, relationships, documents, facts, and chats will be removed. The main world remains unchanged.`);
  if (!ok) return;
  try {
    const projectId = state.activeProject.id;
    const worldId = state.activeWorld.id;
    await api(`/api/branches/${branch.id}`, { method: "DELETE" });
    closeSheet();
    state.activeDocument = null;
    state.activeSession = null;
    await selectScope(projectId, worldId, null);
    toast(`Deleted branch “${branch.name}”`);
  } catch (error) { toast(error.message, 5000); }
}

function openProjectForm() {
  openForm({ title: "New project", eyebrow: "Workspace", description: "A project is a focused story workspace: manuscript, folders, notes, research, assets, and references. World Bible sheets/canon stay shared and are linked through the project context manifest.", fields: [
    { name: "name", label: "Project name", required: true },
    { name: "description", label: "Description", type: "textarea", full: true },
    { name: "language", label: "Default language", type: "select", options: [{ value: "follow_prompt", label: "Follow prompt" }, { value: "id-ID", label: "Bahasa Indonesia" }, { value: "en-US", label: "English" }], value: "follow_prompt" },
  ], onSubmit: async (values) => {
    const project = await api("/api/projects", { method: "POST", body: {
      name: values.name,
      description: values.description,
      settings: {
        preferred_model: byId("modelSelect").value || "",
        reasoning: byId("reasoningSelect").value || "off",
        projection_mode: byId("projectionMode").value || "balanced",
        language: values.language,
        register: "follow_prompt",
        narrator_pronoun: "follow_prompt",
      },
    } });
    await loadWorkspaceBootstrap();
    await selectScope(project.id);
  } });
}

function editProject() {
  const project = state.activeProject;
  const settings = project.settings || {};
  openForm({ title: "Project settings", eyebrow: "Workspace", description: "Project defaults are applied when this workspace opens. World settings may override them without changing other worlds.", fields: [
    { name: "name", label: "Name", value: project.name, required: true },
    { name: "preferred_model", label: "Preferred model", value: settings.preferred_model || byId("modelSelect").value },
    { name: "reasoning", label: "Preferred reasoning", type: "select", options: ["off", "on", "low", "medium", "high"].map((x) => ({ value: x, label: x })), value: settings.reasoning || "off" },
    { name: "projection_mode", label: "Projection", type: "select", options: ["off", "conservative", "balanced", "vivid"].map((x) => ({ value: x, label: x })), value: settings.projection_mode || "balanced" },
    { name: "language", label: "Language", type: "select", options: [{ value: "follow_prompt", label: "Follow prompt" }, { value: "id-ID", label: "Bahasa Indonesia" }, { value: "en-US", label: "English" }], value: settings.language || "follow_prompt" },
    { name: "register", label: "Narrative register", type: "select", options: [
      { value: "follow_prompt", label: "Follow prompt" },
      { value: "natural_informal_neutral", label: "Natural informal-neutral" },
      { value: "natural_neutral", label: "Natural neutral" },
      { value: "literary", label: "Literary" },
      { value: "formal", label: "Formal" },
    ], value: settings.register || "follow_prompt" },
    { name: "narrator_pronoun", label: "Narrator pronoun", type: "select", options: [
      { value: "follow_prompt", label: "Follow prompt" },
      { value: "aku", label: "aku" }, { value: "saya", label: "saya" },
      { value: "gue", label: "gue/gua" }, { value: "third_person", label: "third person" },
    ], value: settings.narrator_pronoun || "follow_prompt" },
    { name: "description", label: "Description", type: "textarea", value: project.description, full: true },
    { name: "description_lens", label: "Description lens defaults (JSON)", type: "json", value: settings.description_lens || {}, full: true },
    { name: "advanced", label: "Model/style profile (JSON)", type: "json", value: settings.advanced || {}, full: true },
  ], onSubmit: async (values) => {
    const nextSettings = {
      preferred_model: values.preferred_model,
      reasoning: values.reasoning,
      projection_mode: values.projection_mode,
      language: values.language,
      register: values.register,
      narrator_pronoun: values.narrator_pronoun,
      description_lens: values.description_lens,
      advanced: values.advanced,
    };
    await api(`/api/projects/${project.id}`, { method: "PATCH", body: { name: values.name, description: values.description, settings: nextSettings } });
    await selectScope(project.id, state.activeWorld.id, state.activeBranch.id);
  } });
}

function openWorldForm() {
  openForm({ title: "Create a world", eyebrow: "World setup", description: "An independent world starts empty. A fork keeps clear lineage and can copy the source world's characters, entities, relationships, and canon.", fields: [
    { name: "creation_mode", label: "How should this world start?", type: "select", options: [{ value: "independent", label: "Independent · start empty" }, { value: "fork", label: "Fork · branch from an existing world" }], value: "independent", full: true },
    { name: "name", label: "World name", required: true },
    { name: "canon_status", label: "Canon status", type: "select", options: (state.bootstrap?.canon_statuses || []).map((x) => ({ value: x, label: x })), value: "draft" },
    { name: "parent_world_id", label: "Source world (fork only)", type: "select", options: (state.activeProject?.worlds || []).map((x) => ({ value: x.id, label: x.name })), value: state.activeWorld?.id || state.activeProject?.worlds?.[0]?.id || "" },
    { name: "clone_parent", label: "Copy source sheets, relationships, and canon", type: "checkbox", value: true },
    { name: "description", label: "World premise / point of divergence", type: "textarea", full: true },
  ], submit: "Create world", onSubmit: async (values) => { const isFork = values.creation_mode === "fork"; if (isFork && !values.parent_world_id) throw new Error("Choose a source world to fork"); const world = await api("/api/worlds", { method: "POST", body: { project_id: state.activeProject.id, name: values.name, description: values.description, parent_world_id: isFork ? values.parent_world_id : null, canon_status: values.canon_status, inheritance_mode: isFork && values.clone_parent ? "snapshot" : "none", clone_parent: isFork && values.clone_parent } }); await selectScope(state.activeProject.id, world.id, null); } });

  const mode = $('[name="creation_mode"]', byId("formFields"));
  const parent = $('[name="parent_world_id"]', byId("formFields"));
  const clone = $('[name="clone_parent"]', byId("formFields"));
  const syncWorldMode = () => { const fork = mode.value === "fork"; parent.disabled = !fork; clone.disabled = !fork; parent.closest("label").classList.toggle("muted-field", !fork); clone.closest("label").classList.toggle("muted-field", !fork); };
  mode.addEventListener("change", syncWorldMode);
  syncWorldMode();
}

function openForkWorldForm() {
  openForm({ title: "Fork current world", eyebrow: "Alternate world", description: "The new world gets its own variants, relationships, and canon facts while preserving lineage.", fields: [{ name: "name", label: "Fork name", value: `${state.activeWorld.name} AU`, required: true }, { name: "canon_status", label: "Status", type: "select", options: [{ value: "what_if", label: "what_if" }, { value: "draft", label: "draft" }, { value: "canon", label: "canon" }], value: "what_if" }, { name: "description", label: "Divergence", type: "textarea", full: true }], onSubmit: async (values) => { const world = await api(`/api/worlds/${state.activeWorld.id}/fork`, { method: "POST", body: { project_id: state.activeProject.id, name: values.name, description: values.description, parent_world_id: state.activeWorld.id, canon_status: values.canon_status, inheritance_mode: "snapshot", clone_parent: true } }); await selectScope(state.activeProject.id, world.id, null); } });
}

async function createSandbox() {
  const name = prompt("Sandbox branch name", "What-if");
  if (!name) return;
  const branch = await api(`/api/worlds/${state.activeWorld.id}/sandbox?name=${encodeURIComponent(name)}`, { method: "POST" });
  await selectScope(state.activeProject.id, state.activeWorld.id, branch.id);
  toast("Sandbox created; changes remain non-canonical until promoted");
}

function openFolderForm(parentId = null) {
  openForm({ title: "New folder", eyebrow: "Project files", description: "Folders can organize chats, documents, and character/entity families together or separately.", fields: [{ name: "name", label: "Folder name", required: true }, { name: "kind", label: "Content kind", type: "select", options: ["mixed", "entity", "chat", "draft", "lore"].map((x) => ({ value: x, label: x === "entity" ? "character / entity" : x })), value: "mixed" }], onSubmit: async (values) => { await api("/api/folders", { method: "POST", body: { project_id: state.activeProject.id, world_id: state.activeWorld?.id, branch_id: state.activeBranch?.id, parent_id: parentId, ...values } }); await loadProjectData(); } });
}

function renameFolder(folder) {
  openForm({ title: "Rename folder", eyebrow: "Project files", fields: [{ name: "name", label: "Name", value: folder.name, required: true }], onSubmit: async (values) => { await api(`/api/folders/${folder.id}`, { method: "PATCH", body: values }); await loadProjectData(); } });
}

async function deleteFolder(folder) {
  if (!folder || !confirm(`Move folder “${folder.name}” to Trash?\n\nIts contents stay recoverable until you permanently delete the folder.`)) return;
  await trashResource("folder", folder.id, folder.name);
}

function openDocumentForm(folderId = null, type = "scene") {
  openForm({ title: "New document", eyebrow: "Draft", fields: [
    { name: "title", label: "Title", required: true },
    { name: "document_type", label: "Type", type: "select", options: (state.bootstrap?.document_types || ["draft", "scene", "lore", "note", "outline"]).map((x) => ({ value: x, label: x })), value: type },
    { name: "status", label: "Status", type: "select", options: [{ value: "draft", label: "draft" }, { value: "provisional", label: "provisional" }, { value: "canon", label: "canon" }], value: "draft" },
    { name: "content", label: "Initial content", type: "textarea", full: true },
  ], onSubmit: async (values) => { const doc = await api("/api/documents", { method: "POST", body: { project_id: state.activeProject.id, world_id: state.activeWorld?.id, branch_id: state.activeBranch?.id, folder_id: folderId, ...values } }); await loadProjectData(); await openDocument(doc.id); } });
}

function draftRecoveryKey(id) { return `arline:draft-recovery:${id}`; }
function storeDraftRecovery() {
  if (!state.activeDocument) return;
  try { localStorage.setItem(draftRecoveryKey(state.activeDocument.id), JSON.stringify({ title:byId("draftTitle")?.value||"", content:byId("draftEditor")?.value||"", status:byId("draftStatus")?.value||"writing", saved_at:Date.now() })); } catch (_) {}
}
function clearDraftRecovery(id) { try { localStorage.removeItem(draftRecoveryKey(id)); } catch (_) {} }
function getDraftRecovery(id) { try { return JSON.parse(localStorage.getItem(draftRecoveryKey(id)) || "null"); } catch (_) { return null; } }

function renderManuscriptSuggestions(doc) {
  const host=byId("suggestionCards"); if(!host)return;
  const active=state.activeScene?.document_id===doc?.id;
  const staged=(state.stagedChanges||[]).slice(0,5);
  const parts=[];
  if(active) parts.push(`<article class="manuscript-proposal active"><b>◎ Active narrative cursor</b><small>${escapeHTML(state.activeScene?.narrative_time||"Scene-aware context enabled")}</small></article>`);
  for(const change of staged) parts.push(`<article class="manuscript-proposal"><b>∆ ${escapeHTML(change.path||"Proposed canon change")}</b><small>${escapeHTML(change.owner_type||"state")} · confidence ${Math.round((change.confidence||0)*100)}%</small><div><button class="tiny-btn manuscript-stage-accept" data-id="${change.id}">Accept</button><button class="tiny-danger-btn manuscript-stage-reject" data-id="${change.id}">Reject</button></div></article>`);
  host.innerHTML=parts.join("")||`<div class="empty-note">No pending proposals. Arline will surface state changes here without writing them into canon automatically.</div>`;
  $$('.manuscript-stage-accept',host).forEach((b)=>b.addEventListener("click",async()=>{await resolveStagedChange(b.dataset.id,true);renderManuscriptSuggestions(state.activeDocument);}));
  $$('.manuscript-stage-reject',host).forEach((b)=>b.addEventListener("click",async()=>{await resolveStagedChange(b.dataset.id,false);renderManuscriptSuggestions(state.activeDocument);}));
}

async function openDocument(id) {
  const [doc, dependencies] = await Promise.all([
    api(`/api/documents/${id}`),
    api(`/api/scenes/${id}/dependencies`).catch(() => ({valid:true,dependencies:[]})),
  ]);
  state.activeDocument = doc;
  state.sceneDependencies = dependencies.dependencies || [];
  const recovery = getDraftRecovery(doc.id);
  const serverTime = Date.parse(doc.updated_at || 0) || 0;
  const hasRecovery = recovery && Number(recovery.saved_at || 0) > serverTime && (recovery.content !== (doc.content || "") || recovery.title !== doc.title);
  const useRecovery = hasRecovery && confirm("Arline found newer local recovery text from an interrupted edit. Restore it?");
  byId("draftTitle").value = useRecovery ? recovery.title : doc.title;
  byId("draftEditor").value = useRecovery ? recovery.content : (doc.content || "");
  const normalizedStatus = ({draft:"writing",provisional:"revising",canon:"final"}[doc.status] || doc.status || "writing");
  byId("draftStatus").value = useRecovery ? (recovery.status || normalizedStatus) : normalizedStatus;
  byId("draftSaveStatus").textContent = useRecovery ? "Recovered locally · not saved yet" : `Saved ${formatRelative(doc.updated_at)} ago`;
  byId("draftStats").textContent = `${wordCount(doc.content)} words`;
  renderDocuments();
  renderRevisions(doc.revisions || []);
  renderSceneDependencies(dependencies);
  renderManuscriptSuggestions(doc);
  setView("draft");
  recordNavigation();
}

function renderDocuments(filter = null) {
  const activeFilter = filter || $(".document-filters button.active")?.dataset.docFilter || "all";
  const docs = state.documents.filter((doc) => activeFilter === "all" || doc.document_type === activeFilter);
  byId("documentList").innerHTML = docs.map((doc) => `<button class="document-item ${state.activeDocument?.id === doc.id ? "active" : ""}" data-doc-id="${doc.id}"><b>${escapeHTML(doc.title)}</b><span>${escapeHTML(doc.document_type)} · ${formatRelative(doc.updated_at)}</span></button>`).join("");
  byId("documentEmpty").classList.toggle("hidden", docs.length > 0);
  $$(".document-item").forEach((button) => button.addEventListener("click", () => openDocument(button.dataset.docId)));
}

function filterDocumentsByFolder(folderId) {
  const docs = state.documents.filter((doc) => doc.folder_id === folderId);
  byId("documentList").innerHTML = docs.map((doc) => `<button class="document-item" data-doc-id="${doc.id}"><b>${escapeHTML(doc.title)}</b><span>${escapeHTML(doc.document_type)}</span></button>`).join("");
  $$(".document-item").forEach((button) => button.addEventListener("click", () => openDocument(button.dataset.docId)));
}

async function saveDraft(note = "manual save") {
  if (!state.activeDocument) return toast("Select or create a document first");
  const payload = { title: byId("draftTitle").value || "Untitled", content: byId("draftEditor").value, status: byId("draftStatus").value, note };
  const doc = await api(`/api/documents/${state.activeDocument.id}`, { method: "PATCH", body: payload });
  state.activeDocument = { ...state.activeDocument, ...doc };
  byId("draftSaveStatus").textContent = "Saved now";
  await loadProjectData();
}

function scheduleDraftAutosave() {
  byId("draftStats").textContent = `${wordCount(byId("draftEditor").value)} words`;
  byId("draftSaveStatus").textContent = "Unsaved changes";
  if (!state.config?.workspace?.autosave_drafts || !state.activeDocument) return;
  clearTimeout(state.draftTimer);
  state.draftTimer = setTimeout(() => saveDraft("autosave").catch((error) => toast(error.message)), 1200);
}

function renderRevisions(revisions) {
  byId("revisionList").innerHTML = revisions.map((rev) => `<div class="revision-item"><div><b>v${rev.version} · ${escapeHTML(rev.note || "revision")}</b><small>${formatDate(rev.created_at)}</small></div><button class="tiny-btn restore-revision" data-revision-id="${rev.id}">Restore</button></div>`).join("") || `<div class="empty-note">No revisions yet.</div>`;
  $$(".restore-revision", byId("revisionList")).forEach((button) => button.addEventListener("click", () => restoreResourceRevision(button.dataset.revisionId, state.activeDocument?.id)));
}

async function restoreResourceRevision(revisionId, reopenId = null, reopenType = "document") {
  if (!confirm("Restore this revision as a new current revision? Existing history will remain available.")) return;
  await api(`/api/revisions/${revisionId}/restore`, { method: "POST", body: { note: "restored in Studio" } });
  await loadProjectData();
  if (reopenType === "document" && reopenId) await openDocument(reopenId);
  if (reopenType === "relationship" && reopenId) await openRelationshipSheet(reopenId);
  if (reopenType === "entity_variant" && reopenId) { const variant = await api(`/api/entities/variants/${reopenId}`); await openEntitySheet(variant.family_id, reopenId); }
  toast("Revision restored non-destructively");
}

async function deleteDocument(doc) {
  if (!confirm(`Delete “${doc.title}”?`)) return;
  await api(`/api/documents/${doc.id}`, { method: "DELETE" });
  if (state.activeDocument?.id === doc.id) state.activeDocument = null;
  await loadProjectData();
}

async function deleteEntityFamily(family) {
  if (!family) return;
  const variantCount = family.variants?.length ?? state.variants.filter((item) => item.family_id === family.id).length;
  const ok = confirm(`Delete entity family “${family.name}”?\n\nThis removes ${variantCount} variant(s), connected relationships, owned canon facts, revisions, pins, and tags. This cannot be undone.`);
  if (!ok) return;
  await api(`/api/entities/families/${family.id}`, { method: "DELETE" });
  closeSheet();
  state.selectedReferences = state.selectedReferences.filter((ref) => ref.id !== family.id);
  updateContextChipUI();
  await loadProjectData();
  toast(`Deleted “${family.name}”`);
}

async function deleteVariant(variant, family) {
  if (!variant) return;
  const ok = confirm(`Delete variant “${variant.display_name}” from ${worldName(variant.world_id)}?\n\nRelationships and facts owned by this variant are also removed. Other variants in the family stay intact.`);
  if (!ok) return;
  await api(`/api/entities/variants/${variant.id}`, { method: "DELETE" });
  closeSheet();
  state.selectedReferences = state.selectedReferences.filter((ref) => ref.id !== variant.id);
  updateContextChipUI();
  await loadProjectData();
  if (family) await openEntitySheet(family.id);
  toast(`Deleted variant “${variant.display_name}”`);
}

async function deleteRelationship(rel) {
  if (!rel) return;
  if (!confirm(`Delete relationship “${rel.subject_name} ↔ ${rel.object_name}” (${rel.relation_type})?`)) return;
  await api(`/api/relationships/${rel.id}`, { method: "DELETE" });
  closeSheet();
  state.selectedReferences = state.selectedReferences.filter((ref) => ref.id !== rel.id);
  updateContextChipUI();
  await loadProjectData();
  toast("Relationship deleted");
}

async function deleteFact(fact) {
  if (!fact) return;
  if (!confirm(`Delete canon fact “${fact.path}”?\n\nThis removes the fact itself and dependency references to it. Use retcon instead if you want to preserve semantic history.`)) return;
  await api(`/api/facts/${fact.id}`, { method: "DELETE" });
  closeSheet();
  await loadProjectData();
  toast("Fact deleted");
}

async function deleteTag(tag) {
  if (!tag) return;
  if (!confirm(`Delete tag #${tag.name}? Resource content is kept; only the tag and its links are removed.`)) return;
  await api(`/api/tags/${tag.id}`, { method: "DELETE" });
  await loadProjectData();
  toast(`Deleted #${tag.name}`);
}

async function deleteSnapshot(snapshotId) {
  const snapshot = state.snapshots.find((item) => item.id === snapshotId);
  if (!confirm(`Delete snapshot “${snapshot?.name || snapshotId}”? This only removes the checkpoint; current world data is unchanged.`)) return;
  await api(`/api/snapshots/${snapshotId}`, { method: "DELETE" });
  await loadProjectData();
  if (state.activeWorld) openWorldSheet(await api(`/api/worlds/${state.activeWorld.id}`));
  toast("Snapshot deleted");
}

function moveDocument(doc) {
  const folders = flattenFolders(state.projectTree?.folders || []);
  openForm({ title: "Move document", eyebrow: "Folder", fields: [{ name: "folder_id", label: "Folder", type: "select", options: [{ value: "", label: "No folder" }, ...folders.map((f) => ({ value: f.id, label: f.path }))], value: doc.folder_id || "", full: true }], onSubmit: async (values) => { await api(`/api/documents/${doc.id}`, { method: "PATCH", body: { folder_id: values.folder_id || "", note: "moved" } }); await loadProjectData(); } });
}

function openEntityForm(defaultType = "character", folderId = null) {
  const typeOptions = (state.bootstrap?.entity_types || ["character", "location", "item", "organization", "world_rule", "lore"]).map((x) => ({ value: x, label: x.replaceAll("_", " ") }));
  const familyOptions = () => state.families
    .filter((item) => item.entity_type === ($('[name="entity_type"]', byId("formFields"))?.value || defaultType))
    .map((item) => ({ value: item.id, label: `${item.name} · ${item.entity_type}` }));

  openForm({ title: "New entity / variant", eyebrow: "World Bible", description: "Create an independent identity family or attach a new world/branch variant to an existing conceptual identity. Names never act as IDs.", fields: [
    { name: "identity_mode", label: "Identity", type: "select", options: [{ value: "independent", label: "New independent entity family" }, { value: "variant_existing", label: "Variant of existing family" }], value: "independent" },
    { name: "existing_family_id", label: "Existing family (variant mode)", type: "select", options: [{ value: "", label: "Select family…" }, ...familyOptions()], value: "" },
    { name: "name", label: "Name / display name", required: true },
    { name: "folder_id", label: "Folder", type: "select", options: [{ value: "", label: "No folder" }, ...flattenFolders(state.projectTree?.folders || []).map((folder) => ({ value: folder.id, label: folder.path }))], value: folderId || "" },
    { name: "entity_type", label: "Type", type: "select", options: typeOptions, value: defaultType },
    { name: "template_id", label: "Template", type: "select", options: [{ value: "", label: "Blank" }, ...state.templates.filter((t) => t.entity_type === defaultType).map((t) => ({ value: t.id, label: t.name }))], value: state.templates.find((t) => t.entity_type === defaultType)?.id || "" },
    { name: "canon_status", label: "Variant status", type: "select", options: (state.bootstrap?.canon_statuses || []).map((x) => ({ value: x, label: x })), value: state.activeBranch?.kind === "main" ? "draft" : "what_if" },
    { name: "description", label: "Family description (new family only)", type: "textarea", full: true },
    { name: "shared_core", label: "Shared core across worlds (new family only, JSON)", type: "json", value: {}, full: true },
    { name: "summary", label: "Current-world/branch summary", type: "textarea", full: true },
    { name: "inherit_attributes", label: "Inherit source attributes for variant", type: "checkbox", value: false },
    { name: "inherit_voice", label: "Inherit source voice for variant", type: "checkbox", value: true },
    { name: "attributes", label: "World-specific attributes (JSON)", type: "json", value: {}, full: true },
    { name: "voice", label: "Voice sheet (JSON)", type: "json", value: {}, full: true },
  ], onSubmit: async (values) => {
    const template = state.templates.find((t) => t.id === values.template_id)?.template || {};
    const attributes = Object.keys(values.attributes || {}).length ? values.attributes : (template.attributes || {});
    const voice = Object.keys(values.voice || {}).length ? values.voice : (template.voice || {});

    if (values.identity_mode === "variant_existing") {
      if (!values.existing_family_id) throw new Error("Choose an existing family for variant mode");
      const family = await api(`/api/entities/families/${values.existing_family_id}`);
      if (family.entity_type !== values.entity_type) throw new Error("Entity type must match the selected family");
      const branchId = state.activeBranch?.kind === "main" ? null : state.activeBranch?.id;
      const already = (family.variants || []).find((item) => item.world_id === state.activeWorld.id && (item.branch_id || null) === branchId);
      if (already) throw new Error("This family already has a variant in the active world/branch. Open it and edit the existing variant instead.");
      const source = (family.variants || []).find((item) => item.world_id === state.activeWorld.id && item.branch_id == null) || family.variants?.[0] || null;
      const inheritSections = [];
      if (values.inherit_attributes) inheritSections.push("attributes");
      if (values.inherit_voice) inheritSections.push("voice");
      const variant = await api("/api/entities/variants", { method: "POST", body: {
        family_id: family.id,
        world_id: state.activeWorld.id,
        branch_id: branchId,
        display_name: values.name,
        summary: values.summary,
        canon_status: values.canon_status,
        inherit_from_variant_id: source?.id || null,
        inherit_sections: inheritSections,
        attributes,
        voice,
        knowledge: template.knowledge || {},
        beliefs: template.beliefs || {},
        current_state: template.current_state || {},
      } });
      await loadProjectData();
      await openEntitySheet(family.id, variant.id);
      return;
    }

    const sharedCore = Object.keys(values.shared_core || {}).length ? values.shared_core : (template.shared_core || {});
    const family = await api("/api/entities/families", { method: "POST", body: {
      project_id: state.activeProject.id,
      folder_id: values.folder_id || null,
      name: values.name,
      entity_type: values.entity_type,
      description: values.description,
      shared_core: sharedCore,
      create_variant_in_world: state.activeWorld.id,
      branch_id: state.activeBranch?.kind === "main" ? null : state.activeBranch?.id,
    } });
    const current = family.variants?.find((variant) => variant.world_id === state.activeWorld.id) || family.variants?.[0];
    if (current) await api(`/api/entities/variants/${current.id}`, { method: "PATCH", body: {
      summary: values.summary,
      canon_status: values.canon_status,
      attributes,
      voice,
      knowledge: template.knowledge || {},
      beliefs: template.beliefs || {},
      current_state: template.current_state || {},
      note: "created from Studio template",
    } });
    await loadProjectData();
    await openEntitySheet(family.id, current?.id);
  } });

  const typeControl = $('[name="entity_type"]', byId("formFields"));
  const templateControl = $('[name="template_id"]', byId("formFields"));
  const familyControl = $('[name="existing_family_id"]', byId("formFields"));
  const refreshDependentOptions = () => {
    const type = typeControl.value;
    const matchingTemplates = state.templates.filter((item) => item.entity_type === type);
    templateControl.innerHTML = `<option value="">Blank</option>${matchingTemplates.map((item) => `<option value="${escapeHTML(item.id)}">${escapeHTML(item.name)}</option>`).join("")}`;
    templateControl.value = matchingTemplates[0]?.id || "";
    const matchingFamilies = state.families.filter((item) => item.entity_type === type);
    familyControl.innerHTML = `<option value="">Select family…</option>${matchingFamilies.map((item) => `<option value="${escapeHTML(item.id)}">${escapeHTML(item.name)} · ${escapeHTML(item.entity_type)}</option>`).join("")}`;
  };
  typeControl?.addEventListener("change", refreshDependentOptions);
}

async function openEntitySheet(familyId, variantId = null) {
  const family = await api(`/api/entities/families/${familyId}`);
  let variant = variantId ? await api(`/api/entities/variants/${variantId}`) : null;
  if (!variant) {
    const resolved = (family.variants || []).find((item) => item.world_id === state.activeWorld?.id && (item.branch_id === state.activeBranch?.id || item.branch_id == null));
    variant = resolved ? await api(`/api/entities/variants/${resolved.id}`) : null;
  }
  byId("sheetEyebrow").textContent = `${family.entity_type} family`;
  byId("sheetTitle").textContent = variant?.display_name || family.name;
  byId("sheetSubtitle").textContent = `${state.activeWorld?.name || "No world"} · ${variant?.canon_status || "no variant"}`;
  const variants = family.variants || [];
  byId("sheetBody").innerHTML = `
    <section class="sheet-section"><div class="sheet-section-head"><h3>Variants</h3><span class="revision-badge">${variants.length} worlds/branches</span></div><div class="variant-switcher">${variants.map((item) => `<button class="${item.id === variant?.id ? "active" : ""}" data-variant-id="${item.id}">${escapeHTML(item.display_name)} · ${escapeHTML(worldName(item.world_id))}${item.branch_id ? " / branch" : ""}</button>`).join("") || "No variants"}</div></section>
    <section class="sheet-section"><div class="sheet-section-head"><h3>Family shared core</h3><button id="editFamilyBtn" class="tiny-btn">Edit</button></div><p>${escapeHTML(family.description || "No family description")}</p><pre class="json-block">${escapeHTML(pretty(family.shared_core || {}))}</pre></section>
    ${variant ? entityVariantSections(variant) : `<div class="empty-state small">No variant exists in this scope.</div>`}
  `;
  const inManifest = state.manifestRefs.some((ref) => ref.resource_type === "entity_family" && ref.resource_id === family.id);
  byId("sheetFooter").innerHTML = `<button id="deleteFamilyBtn" class="danger-text-btn">Delete family</button>${variant ? `<button id="deleteVariantBtn" class="danger-text-btn">Delete variant</button>` : ""}<button id="whereUsedEntityBtn" class="secondary-btn">Where used</button>${variant ? `<button id="timelineStateEntityBtn" class="secondary-btn">Timeline state</button>` : ""}<button id="manifestEntityBtn" class="secondary-btn" ${inManifest ? "disabled" : ""}>${inManifest ? "In project working set" : "＋ Add to project"}</button><button id="pinEntityBtn" class="secondary-btn">Pin context</button><button id="tagEntityBtn" class="secondary-btn">Tags</button><button id="compareVariantBtn" class="secondary-btn">Compare variants</button><button id="newVariantBtn" class="secondary-btn">＋ Variant</button>${variant ? `<button id="editVariantBtn" class="primary-btn">Edit current variant</button>` : ""}`;
  $$("[data-variant-id]", byId("sheetBody")).forEach((button) => button.addEventListener("click", () => openEntitySheet(familyId, button.dataset.variantId)));
  byId("editFamilyBtn").addEventListener("click", () => editFamily(family));
  byId("deleteFamilyBtn").addEventListener("click", () => deleteEntityFamily(family));
  byId("newVariantBtn").addEventListener("click", () => openVariantForm(family, variant));
  byId("compareVariantBtn").addEventListener("click", () => openVariantCompare(family, variant));
  byId("pinEntityBtn").addEventListener("click", () => pinContext({ type: variant ? "entity_variant" : "entity_family", id: variant?.id || family.id, label: variant?.display_name || family.name }));
  byId("tagEntityBtn").addEventListener("click", () => editResourceTags(variant ? "entity_variant" : "entity_family", variant?.id || family.id, variant?.tags || family.tags || []));
  byId("whereUsedEntityBtn")?.addEventListener("click", () => openBacklinks(variant ? "entity_variant" : "entity_family", variant?.id || family.id, variant?.display_name || family.name));
  byId("manifestEntityBtn")?.addEventListener("click", async () => { if (!state.activeProject || inManifest) return; await api(`/api/projects/${state.activeProject.id}/manifest/refs`, { method: "POST", body: { resource_type: "entity_family", resource_id: family.id, label: family.name, priority: 1 } }); await loadProjectData(); await openEntitySheet(family.id, variant?.id); toast("Added to project working set"); });
  if (variant) {
    byId("deleteVariantBtn").addEventListener("click", () => deleteVariant(variant, family));
    byId("editVariantBtn").addEventListener("click", () => editVariant(variant, family));
    byId("timelineStateEntityBtn")?.addEventListener("click", () => openEntityTimelineState(variant, family));
    byId("addFactBtn")?.addEventListener("click", () => addCanonFact("entity_variant", variant.id));
    byId("addRelationshipFromSheetBtn")?.addEventListener("click", () => openRelationshipForm(variant.id));
    $$(".relationship-mini[data-rel-id]", byId("sheetBody")).forEach((button) => button.addEventListener("click", () => openRelationshipSheet(button.dataset.relId)));
    $$(".variant-revision-restore", byId("sheetBody")).forEach((button) => button.addEventListener("click", () => restoreResourceRevision(button.dataset.revisionId, variant.id, "entity_variant")));
  }
  openSheet();
}

function entityVariantSections(variant) {
  const relationships = variant.relationships || [];
  const facts = variant.facts || [];
  return `<section class="sheet-section"><div class="sheet-section-head"><h3>Overview</h3><span class="canon-badge ${escapeHTML(variant.canon_status)}">${escapeHTML(variant.canon_status)}</span></div><p>${escapeHTML(variant.summary || "No summary")}</p><div class="sheet-grid"><div class="sheet-field"><span>World</span><b>${escapeHTML(worldName(variant.world_id))}</b></div><div class="sheet-field"><span>Branch</span><b>${escapeHTML(branchName(variant.branch_id) || "world-level")}</b></div><div class="sheet-field"><span>Inheritance</span><code>${escapeHTML(variant.inherit_from_variant_id || "local")}</code></div><div class="sheet-field"><span>Updated</span><b>${escapeHTML(formatDate(variant.updated_at))}</b></div></div></section>
  ${jsonSheetSection("Attributes", variant.attributes)}${jsonSheetSection("Voice", variant.voice)}${jsonSheetSection("Knowledge", variant.knowledge)}${jsonSheetSection("Beliefs / misconceptions", variant.beliefs)}${jsonSheetSection("Current state", variant.current_state)}
  <section class="sheet-section"><div class="sheet-section-head"><h3>Canon facts</h3><button id="addFactBtn" class="tiny-btn">＋ Fact</button></div>${facts.map((fact) => `<div class="fact-row"><div><code>${escapeHTML(fact.path)} = ${escapeHTML(JSON.stringify(fact.value))}</code><small>${escapeHTML(fact.status)} · ${escapeHTML(fact.authority)}</small></div><span class="canon-badge ${escapeHTML(fact.status)}">${escapeHTML(fact.status)}</span></div>`).join("") || `<div class="empty-note">No extra facts.</div>`}</section>
  <section class="sheet-section"><div class="sheet-section-head"><h3>Relationships</h3><button id="addRelationshipFromSheetBtn" class="tiny-btn">＋ Relation</button></div>${relationships.map((rel) => `<button class="relationship-mini" data-rel-id="${rel.id}">${escapeHTML(rel.subject_name)} —${escapeHTML(rel.relation_type)}→ ${escapeHTML(rel.object_name)}</button>`).join("") || `<div class="empty-note">No relationships in this world.</div>`}</section>
  <section class="sheet-section"><div class="sheet-section-head"><h3>Revision history</h3></div>${(variant.revisions || []).map((rev) => `<div class="revision-item"><div><b>v${rev.version} · ${escapeHTML(rev.note || "revision")}</b><small>${formatDate(rev.created_at)}</small></div><button class="tiny-btn variant-revision-restore" data-revision-id="${rev.id}">Restore</button></div>`).join("") || `<div class="empty-note">No revisions.</div>`}</section>`;
}

function jsonSheetSection(title, value) {
  return `<section class="sheet-section"><div class="sheet-section-head"><h3>${escapeHTML(title)}</h3></div><pre class="json-block">${escapeHTML(pretty(value || {}))}</pre></section>`;
}

function worldName(id) { return state.activeProject?.worlds?.find((item) => item.id === id)?.name || id || ""; }
function branchName(id) { return state.activeWorld?.branches?.find((item) => item.id === id)?.name || id || ""; }

function editFamily(family) {
  openForm({ title: `Edit ${family.name} family`, eyebrow: "Shared identity", fields: [{ name: "name", label: "Family name", value: family.name, required: true }, { name: "folder_id", label: "Folder", type: "select", options: [{ value: "", label: "No folder" }, ...flattenFolders(state.projectTree?.folders || []).map((folder) => ({ value: folder.id, label: folder.path }))], value: family.folder_id || "" }, { name: "description", label: "Description", type: "textarea", value: family.description, full: true }, { name: "shared_core", label: "Shared core (JSON)", type: "json", value: family.shared_core, full: true }], onSubmit: async (values) => { await api(`/api/entities/families/${family.id}`, { method: "PATCH", body: values }); await loadProjectData(); await openEntitySheet(family.id); } });
}

function moveEntityFamily(family) {
  const folders = flattenFolders(state.projectTree?.folders || []);
  openForm({ title: `Move ${family.name}`, eyebrow: "Character / entity folder", fields: [{ name: "folder_id", label: "Folder", type: "select", options: [{ value: "", label: "No folder" }, ...folders.map((folder) => ({ value: folder.id, label: folder.path }))], value: family.folder_id || "", full: true }], onSubmit: async (values) => { await api(`/api/entities/families/${family.id}`, { method: "PATCH", body: { folder_id: values.folder_id || "" } }); await loadProjectData(); } });
}

function editVariant(variant, family) {
  openForm({ title: `Edit ${variant.display_name}`, eyebrow: `${worldName(variant.world_id)} variant`, fields: [
    { name: "display_name", label: "Display name", value: variant.display_name, required: true },
    { name: "canon_status", label: "Canon status", type: "select", options: (state.bootstrap?.canon_statuses || []).map((x) => ({ value: x, label: x })), value: variant.canon_status },
    { name: "summary", label: "Summary", type: "textarea", value: variant.summary, full: true },
    { name: "attributes", label: "Attributes (JSON)", type: "json", value: variant.attributes, full: true },
    { name: "voice", label: "Voice sheet (JSON)", type: "json", value: variant.voice, full: true },
    { name: "knowledge", label: "Knowledge (JSON)", type: "json", value: variant.knowledge, full: true },
    { name: "beliefs", label: "Beliefs / misconceptions (JSON)", type: "json", value: variant.beliefs, full: true },
    { name: "current_state", label: "Current state (JSON)", type: "json", value: variant.current_state, full: true },
  ], onSubmit: async (values) => { await api(`/api/entities/variants/${variant.id}`, { method: "PATCH", body: { ...values, note: "edited in Studio" } }); await loadProjectData(); await openEntitySheet(family.id, variant.id); } });
}

function openVariantForm(family, sourceVariant = null) {
  openForm({ title: `New ${family.name} variant`, eyebrow: "World identity", description: "Only explicitly selected sections are inherited. Knowledge, memories, relationships, and current state remain variant-specific by default.", fields: [
    { name: "world_id", label: "Target world", type: "select", options: (state.activeProject?.worlds || []).map((x) => ({ value: x.id, label: x.name })), value: state.activeWorld.id },
    { name: "display_name", label: "Display name", value: family.name, required: true },
    { name: "canon_status", label: "Status", type: "select", options: (state.bootstrap?.canon_statuses || []).map((x) => ({ value: x, label: x })), value: "draft" },
    { name: "inherit_attributes", label: "Inherit attributes", type: "checkbox", value: true },
    { name: "inherit_voice", label: "Inherit voice", type: "checkbox", value: true },
    { name: "summary", label: "Variant summary", type: "textarea", full: true },
  ], onSubmit: async (values) => { const sections = []; if (values.inherit_attributes) sections.push("attributes"); if (values.inherit_voice) sections.push("voice"); const variant = await api("/api/entities/variants", { method: "POST", body: { family_id: family.id, world_id: values.world_id, branch_id: null, display_name: values.display_name, summary: values.summary, canon_status: values.canon_status, inherit_from_variant_id: sourceVariant?.id || null, inherit_sections: sections, attributes: {}, voice: {}, knowledge: {}, beliefs: {}, current_state: {} } }); await selectScope(state.activeProject.id, values.world_id, null); await openEntitySheet(family.id, variant.id); } });
}

function openVariantCompare(family, current) {
  const variants = (family.variants || []).filter((item) => item.id !== current?.id);
  if (!current || !variants.length) return toast("Create at least two variants first");
  openForm({ title: "Compare variants", eyebrow: family.name, fields: [{ name: "other", label: "Compare with", type: "select", options: variants.map((x) => ({ value: x.id, label: `${x.display_name} · ${worldName(x.world_id)}` })), full: true }], submit: "Compare", onSubmit: async (values) => { const diff = await api(`/api/entities/variants/compare/${current.id}/${values.other}`); showCompare(`${family.name} variants`, diff); } });
}

function showCompare(title, diff) {
  byId("compareTitle").textContent = title;
  const difference = diff.difference || {};
  if (diff.entities) {
    byId("compareBody").innerHTML = `<table class="diff-table"><thead><tr><th>Entity</th><th>${escapeHTML(diff.left.name)}</th><th>${escapeHTML(diff.right.name)}</th><th>Difference</th></tr></thead><tbody>${diff.entities.map((row) => `<tr class="${row.difference.kind === "changed" ? "diff-changed" : ""}"><td>${escapeHTML(row.name)}<br><small>${escapeHTML(row.entity_type)}</small></td><td><pre>${escapeHTML(pretty(row.left || null))}</pre></td><td><pre>${escapeHTML(pretty(row.right || null))}</pre></td><td>${escapeHTML(row.difference.kind)}</td></tr>`).join("")}</tbody></table>`;
  } else {
    byId("compareBody").innerHTML = `<div class="sheet-grid"><div><h3>${escapeHTML(diff.left?.display_name || "Left")}</h3><pre class="json-block">${escapeHTML(pretty(diff.left))}</pre></div><div><h3>${escapeHTML(diff.right?.display_name || "Right")}</h3><pre class="json-block">${escapeHTML(pretty(diff.right))}</pre></div></div><h3>Difference</h3><pre class="json-block">${escapeHTML(pretty(difference))}</pre>`;
  }
  byId("compareDialog").showModal();
}

function openRelationshipForm(subjectVariantId = null) {
  if (state.variants.length < 2) return toast("Create at least two entity variants first");
  const options = state.variants.map((v) => ({ value: v.id, label: v.display_name }));
  openForm({ title: "New relationship", eyebrow: state.activeWorld.name, fields: [
    { name: "subject_variant_id", label: "Subject", type: "select", options, value: subjectVariantId || options[0].value },
    { name: "object_variant_id", label: "Object", type: "select", options, value: options.find((x) => x.value !== subjectVariantId)?.value || options[1].value },
    { name: "relation_type", label: "Relationship", placeholder: "dating / sibling / enemy", required: true },
    { name: "status", label: "Temporal status", type: "select", options: ["current", "historical", "future", "conditional"].map((x) => ({ value: x, label: x })), value: "current" },
    { name: "canon_status", label: "Canon status", type: "select", options: (state.bootstrap?.canon_statuses || []).map((x) => ({ value: x, label: x })), value: state.activeBranch?.kind === "main" ? "draft" : "what_if" },
    { name: "attributes", label: "Relationship details (JSON)", type: "json", value: {}, full: true },
  ], onSubmit: async (values) => { const rel = await api("/api/relationships", { method: "POST", body: { world_id: state.activeWorld.id, branch_id: state.activeBranch?.kind === "main" ? null : state.activeBranch?.id, ...values } }); await loadProjectData(); await openRelationshipSheet(rel.id); } });
}

async function openRelationshipSheet(id) {
  const rel = await api(`/api/relationships/${id}`);
  byId("sheetEyebrow").textContent = "Relationship sheet";
  byId("sheetTitle").textContent = `${rel.subject_name} ↔ ${rel.object_name}`;
  byId("sheetSubtitle").textContent = `${rel.relation_type} · ${rel.status} · ${rel.canon_status}`;
  byId("sheetBody").innerHTML = `<section class="sheet-section"><div class="sheet-grid"><div class="sheet-field"><span>Subject</span><b>${escapeHTML(rel.subject_name)}</b></div><div class="sheet-field"><span>Object</span><b>${escapeHTML(rel.object_name)}</b></div><div class="sheet-field"><span>Type</span><b>${escapeHTML(rel.relation_type)}</b></div><div class="sheet-field"><span>Status</span><b>${escapeHTML(rel.status)}</b></div></div></section>${jsonSheetSection("Relationship details", rel.attributes)}<section class="sheet-section"><div class="sheet-section-head"><h3>Canon facts</h3><button id="addRelationshipFactBtn" class="tiny-btn">＋ Fact</button></div>${(rel.facts || []).map((fact) => `<div class="fact-row"><code>${escapeHTML(fact.path)} = ${escapeHTML(JSON.stringify(fact.value))}</code><small>${escapeHTML(fact.status)}</small></div>`).join("") || `<div class="empty-note">No relationship facts.</div>`}</section><section class="sheet-section"><div class="sheet-section-head"><h3>Revision history</h3></div>${(rel.revisions || []).map((rev) => `<div class="revision-item"><div><b>v${rev.version} · ${escapeHTML(rev.note)}</b><small>${formatDate(rev.created_at)}</small></div><button class="tiny-btn relationship-revision-restore" data-revision-id="${rev.id}">Restore</button></div>`).join("")}</section>`;
  byId("sheetFooter").innerHTML = `<button id="deleteRelationshipBtn" class="danger-text-btn">Delete relationship</button><button id="pinRelationshipBtn" class="secondary-btn">Pin context</button><button id="editRelationshipTagsBtn" class="secondary-btn">Tags</button><button id="editRelationshipBtn" class="primary-btn">Edit relationship</button>`;
  byId("deleteRelationshipBtn").addEventListener("click", () => deleteRelationship(rel));
  byId("pinRelationshipBtn").addEventListener("click", () => pinContext({ type: "relationship", id: rel.id, label: `${rel.subject_name} ↔ ${rel.object_name}` }));
  byId("editRelationshipTagsBtn").addEventListener("click", () => editResourceTags("relationship", rel.id, rel.tags || []));
  byId("editRelationshipBtn").addEventListener("click", () => editRelationship(rel));
  byId("addRelationshipFactBtn").addEventListener("click", () => addCanonFact("relationship", rel.id));
  $$(".relationship-revision-restore", byId("sheetBody")).forEach((button) => button.addEventListener("click", () => restoreResourceRevision(button.dataset.revisionId, rel.id, "relationship")));
  openSheet();
}

function editRelationship(rel) {
  openForm({ title: "Edit relationship", eyebrow: `${rel.subject_name} ↔ ${rel.object_name}`, fields: [{ name: "relation_type", label: "Type", value: rel.relation_type, required: true }, { name: "status", label: "Status", type: "select", options: ["current", "historical", "future", "conditional"].map((x) => ({ value: x, label: x })), value: rel.status }, { name: "canon_status", label: "Canon", type: "select", options: (state.bootstrap?.canon_statuses || []).map((x) => ({ value: x, label: x })), value: rel.canon_status }, { name: "attributes", label: "Details (JSON)", type: "json", value: rel.attributes, full: true }], onSubmit: async (values) => { await api(`/api/relationships/${rel.id}`, { method: "PATCH", body: { ...values, note: "edited in Studio" } }); await loadProjectData(); await openRelationshipSheet(rel.id); } });
}

function addCanonFact(ownerType, ownerId, selectedText = "") {
  openForm({ title: "Add canon fact", eyebrow: state.activeBranch?.kind === "main" ? "Canon workflow" : "Sandbox fact", description: state.activeBranch?.kind === "main" ? "Facts remain draft until explicitly marked canon." : "This fact belongs to a non-canonical branch until promoted.", fields: [
    { name: "path", label: "Semantic path", placeholder: "habits.knocks_twice", required: true },
    { name: "status", label: "Canon status", type: "select", options: (state.bootstrap?.canon_statuses || []).map((x) => ({ value: x, label: x })), value: state.activeBranch?.kind === "main" ? "draft" : "what_if" },
    { name: "value", label: "Value (JSON or text)", type: "textarea", value: selectedText || "", full: true },
  ], onSubmit: async (values) => { let value; try { value = JSON.parse(values.value); } catch (_) { value = values.value; } await api("/api/facts", { method: "POST", body: { project_id: state.activeProject.id, world_id: state.activeWorld.id, branch_id: state.activeBranch?.kind === "main" ? null : state.activeBranch?.id, owner_type: ownerType, owner_id: ownerId, path: values.path, value, status: values.status, authority: "user_explicit", source_type: selectedText ? "accepted_generated_prose" : "manual", source_id: state.activeTurn?.id || null } }); await loadProjectData(); toast("Fact saved"); } });
}

function promoteStorySelection(turnId, story) {
  const selected = window.getSelection()?.toString().trim() || "";
  const text = selected || story.slice(0, 240);
  openForm({ title: "Promote to canon", eyebrow: "Generated discovery", description: "Generated prose never becomes canon automatically. Choose a stable semantic owner and path.", fields: [
    { name: "owner_type", label: "Owner type", type: "select", options: [{ value: "world", label: "World" }, { value: "entity_variant", label: "Character/entity" }, { value: "relationship", label: "Relationship" }], value: "world" },
    { name: "owner_id", label: "Owner ID", value: state.activeWorld.id, required: true },
    { name: "path", label: "Semantic path", placeholder: "lore.generated_discovery", required: true },
    { name: "value", label: "Proposed canon content", type: "textarea", value: text, full: true },
    { name: "status", label: "Status", type: "select", options: [{ value: "draft", label: "draft" }, { value: "provisional", label: "provisional" }, { value: "canon", label: "canon" }], value: "draft" },
  ], onSubmit: async (values) => { await api("/api/canon/promote", { method: "POST", body: { project_id: state.activeProject.id, world_id: state.activeWorld.id, branch_id: state.activeBranch?.kind === "main" ? null : state.activeBranch?.id, owner_type: values.owner_type, owner_id: values.owner_id, path: values.path, value: values.value, status: values.status, authority: "user_explicit", source_type: "accepted_generated_prose", source_id: turnId } }); await loadProjectData(); } });
}

async function pinContext(ref) {
  await api("/api/context/pins", { method: "POST", body: { project_id: state.activeProject.id, world_id: state.activeWorld.id, branch_id: state.activeBranch?.kind === "main" ? null : state.activeBranch?.id, resource_type: ref.type, resource_id: ref.id, scope: state.activeBranch?.kind === "main" ? "world" : "branch", priority: 1 } });
  addReference(ref);
  toast("Pinned to workspace context");
}

function editResourceTags(resourceType, resourceId, existing) {
  const currentIds = new Set((existing || []).map((tag) => tag.id));
  openForm({ title: "Resource tags", eyebrow: "Organization", fields: [{ name: "tag_ids", label: "Tag IDs, comma-separated", value: [...currentIds].join(", "), full: true }], onSubmit: async (values) => { const desired = new Set(values.tag_ids.split(",").map((x) => x.trim()).filter(Boolean)); for (const tag of state.tags) { const has = currentIds.has(tag.id), wants = desired.has(tag.id); if (!has && wants) await api(`/api/tags/${tag.id}/link`, { method: "POST", body: { resource_type: resourceType, resource_id: resourceId } }); if (has && !wants) await api(`/api/tags/${tag.id}/link?resource_type=${encodeURIComponent(resourceType)}&resource_id=${encodeURIComponent(resourceId)}`, { method: "DELETE" }); } await loadProjectData(); } });
}

function openTagForm() {
  openForm({ title: "New tag", eyebrow: "Organization", fields: [{ name: "name", label: "Tag name", required: true }, { name: "color", label: "Color", type: "color", value: "#6b7280" }, { name: "kind", label: "Kind", type: "select", options: [{ value: "organizational", label: "organizational" }, { value: "semantic", label: "semantic" }], value: "organizational" }], onSubmit: async (values) => { await api("/api/tags", { method: "POST", body: { project_id: state.activeProject.id, ...values } }); await loadProjectData(); } });
}

function createSnapshot() {
  openForm({ title: "Save world snapshot", eyebrow: "Checkpoint", description: "Snapshots capture world/branch entities, relationships, facts, and documents. Restores create a new sandbox branch rather than overwriting history.", fields: [{ name: "name", label: "Snapshot name", value: `Before ${new Date().toLocaleDateString()}`, required: true }, { name: "description", label: "Description", type: "textarea", full: true }], onSubmit: async (values) => { await api("/api/snapshots", { method: "POST", body: { project_id: state.activeProject.id, world_id: state.activeWorld.id, branch_id: state.activeBranch?.id, ...values } }); await loadProjectData(); } });
}

function openWorldCompare() {
  const worlds = state.activeProject?.worlds || [];
  if (worlds.length < 2) return toast("Create another world first");
  openForm({ title: "Compare worlds", eyebrow: "Canon diff", fields: [{ name: "other", label: "Compare current world with", type: "select", options: worlds.filter((x) => x.id !== state.activeWorld.id).map((x) => ({ value: x.id, label: x.name })), full: true }], submit: "Compare", onSubmit: async (values) => { const diff = await api(`/api/worlds/compare/${state.activeWorld.id}/${values.other}`); showCompare("World canon diff", diff); } });
}

function openWorldSheet(world) {
  byId("sheetEyebrow").textContent = "World";
  byId("sheetTitle").textContent = world.name;
  byId("sheetSubtitle").textContent = `${world.canon_status} · ${world.inheritance_mode}`;
  const lineage = world.lineage || [];
  byId("sheetBody").innerHTML = `<section class="sheet-section"><p>${escapeHTML(world.description || "No description")}</p><div class="sheet-grid"><div class="sheet-field"><span>Canon status</span><b>${escapeHTML(world.canon_status)}</b></div><div class="sheet-field"><span>Inheritance</span><b>${escapeHTML(world.inheritance_mode)}</b></div></div></section><section class="sheet-section"><div class="sheet-section-head"><h3>World lineage</h3></div><div class="variant-switcher">${lineage.map((x) => `<button data-world-id="${x.id}">${escapeHTML(x.name)}</button>`).join(" → ")}</div></section><section class="sheet-section"><div class="sheet-section-head"><h3>Branches</h3></div>${(world.branches || []).map((branch) => `<div class="resource-inline-row"><button class="relationship-mini" data-branch-id="${branch.id}">${escapeHTML(branch.name)} · ${escapeHTML(branch.kind)} · ${escapeHTML(branch.canon_status)}</button>${branch.kind !== "main" ? `<button class="tiny-danger-btn delete-branch" data-delete-branch-id="${branch.id}">Delete</button>` : `<span class="protected-note">protected</span>`}</div>`).join("")}</section><section class="sheet-section"><div class="sheet-section-head"><h3>Snapshots</h3></div>${state.snapshots.map((snap) => `<div class="revision-item resource-inline-row"><div><b>${escapeHTML(snap.name)}</b><small>${formatDate(snap.created_at)}</small></div><div class="inline-actions"><button class="tiny-btn restore-snapshot" data-snapshot-id="${snap.id}">Restore</button><button class="tiny-danger-btn delete-snapshot" data-snapshot-id="${snap.id}">Delete</button></div></div>`).join("") || `<div class="empty-note">No snapshots.</div>`}</section>`;
  byId("sheetFooter").innerHTML = `<button id="deleteWorldBtn" class="danger-text-btn">Delete world</button><button id="editWorldBtn" class="primary-btn">Edit world</button>`;
  byId("deleteWorldBtn").addEventListener("click", () => deleteWorld(world));
  byId("editWorldBtn").addEventListener("click", () => editWorld(world));
  $$('[data-world-id]', byId("sheetBody")).forEach((button) => button.addEventListener("click", () => selectScope(state.activeProject.id, button.dataset.worldId, null)));
  $$('[data-branch-id]', byId("sheetBody")).forEach((button) => button.addEventListener("click", () => selectScope(state.activeProject.id, world.id, button.dataset.branchId)));
  $$(".delete-branch", byId("sheetBody")).forEach((button) => button.addEventListener("click", (event) => {
    event.stopPropagation();
    const branch = (world.branches || []).find((item) => item.id === button.dataset.deleteBranchId);
    if (branch) deleteBranch(branch);
  }));
  $$(".restore-snapshot", byId("sheetBody")).forEach((button) => button.addEventListener("click", () => restoreSnapshot(button.dataset.snapshotId)));
  $$(".delete-snapshot", byId("sheetBody")).forEach((button) => button.addEventListener("click", () => deleteSnapshot(button.dataset.snapshotId)));
  openSheet();
}

function editWorld(world) {
  openForm({ title: "Edit world", eyebrow: "World settings", fields: [{ name: "name", label: "Name", value: world.name, required: true }, { name: "canon_status", label: "Status", type: "select", options: (state.bootstrap?.canon_statuses || []).map((x) => ({ value: x, label: x })), value: world.canon_status }, { name: "description", label: "Description", type: "textarea", value: world.description, full: true }, { name: "settings", label: "World model/style defaults (JSON)", type: "json", value: world.settings || {}, full: true }], onSubmit: async (values) => { await api(`/api/worlds/${world.id}`, { method: "PATCH", body: values }); await selectScope(state.activeProject.id, world.id, state.activeBranch?.id); } });
}

async function restoreSnapshot(id) {
  const name = prompt("Name for restored sandbox branch", "Restored snapshot");
  if (!name) return;
  const result = await api(`/api/snapshots/${id}/restore`, { method: "POST", body: { branch_name: name } });
  await selectScope(state.activeProject.id, state.activeWorld.id, result.branch_id);
}

function renderWorldGrid() {
  if (state.activeView !== "world") return;
  const tab = state.activeWorldTab;
  let cards = [];
  if (["character", "location", "item", "organization", "lore"].includes(tab)) {
    const types = tab === "lore" ? ["lore", "world_rule"] : [tab];
    cards = state.families.filter((family) => types.includes(family.entity_type)).map((family) => {
      const variant = state.variants.find((v) => v.family_id === family.id && (v.branch_id === state.activeBranch?.id || v.branch_id == null));
      return { type: "entity", family, variant, label: variant?.display_name || family.name, summary: variant?.summary || family.description, status: variant?.canon_status || "no variant" };
    });
  } else if (tab === "relationship") cards = state.relationships.map((rel) => ({ type: "relationship", id: rel.id, label: `${rel.subject_name} ↔ ${rel.object_name}`, summary: rel.relation_type, status: rel.canon_status }));
  else if (tab === "canon") cards = [
    ...state.conflicts.map((conflict) => ({type:"conflict",id:conflict.id,label:`Conflict: ${conflict.path}`,summary:`${JSON.stringify(conflict.left)} ↔ ${JSON.stringify(conflict.right)}`,status:"open",conflict})),
    ...state.facts.map((fact) => ({ type: "fact", id: fact.id, label: fact.path, summary: JSON.stringify(fact.value), status: fact.status, fact })),
  ];
  else if (tab === "timeline") cards = state.documents.filter((doc) => ["scene", "outline"].includes(doc.document_type)).map((doc) => ({ type: "document", id: doc.id, label: doc.title, summary: doc.content.slice(0, 130), status: doc.status }));
  else if (tab === "worlds") cards = (state.activeProject?.worlds || []).map((world) => ({ type: "world", id: world.id, label: world.name, summary: world.description, status: world.canon_status, world }));
  const search = byId("worldSearch").value.trim().toLowerCase();
  if (search) cards = cards.filter((card) => `${card.label} ${card.summary}`.toLowerCase().includes(search));
  byId("worldGrid").innerHTML = cards.map(worldCardHTML).join("");
  byId("worldEmpty").classList.toggle("hidden", cards.length > 0);
  $$(".world-card").forEach((card) => card.addEventListener("click", async () => {
    const index = Number(card.dataset.index);
    const item = cards[index];
    if (item.type === "entity") openEntitySheet(item.family.id, item.variant?.id);
    else if (item.type === "relationship") openRelationshipSheet(item.id);
    else if (item.type === "document") openDocument(item.id);
    else if (item.type === "world") openWorldSheet(await api(`/api/worlds/${item.id}`));
    else if (item.type === "fact") openFactSheet(item.fact);
    else if (item.type === "conflict") openConflictSheet(item.conflict);
  }));
}

function worldCardHTML(item, index) {
  const iconType = item.type === "entity" ? item.family.entity_type : item.type;
  return `<article class="world-card" data-index="${index}"><div class="world-card-head"><span class="world-card-icon">${escapeHTML(ENTITY_ICONS[iconType] || "◇")}</span><span class="canon-badge ${escapeHTML(item.status)}">${escapeHTML(item.status)}</span></div><h3>${escapeHTML(item.label)}</h3><p>${escapeHTML(item.summary || "No description")}</p><div class="world-card-meta"><span>${escapeHTML(iconType.replaceAll("_", " "))}</span>${item.variant ? `<span>${escapeHTML(worldName(item.variant.world_id))}</span>` : ""}</div></article>`;
}

function openFactSheet(fact) {
  byId("sheetEyebrow").textContent = "Canon fact";
  byId("sheetTitle").textContent = fact.path;
  byId("sheetSubtitle").textContent = `${fact.status} · ${fact.authority}`;
  byId("sheetBody").innerHTML = `<section class="sheet-section"><pre class="json-block">${escapeHTML(pretty(fact.value))}</pre></section><section class="sheet-section"><div class="sheet-grid"><div class="sheet-field"><span>Owner</span><code>${escapeHTML(fact.owner_type)} / ${escapeHTML(fact.owner_id)}</code></div><div class="sheet-field"><span>Source</span><code>${escapeHTML(fact.source_type)} / ${escapeHTML(fact.source_id || "-")}</code></div><div class="sheet-field"><span>World</span><b>${escapeHTML(worldName(fact.world_id))}</b></div><div class="sheet-field"><span>Updated</span><b>${escapeHTML(formatDate(fact.updated_at))}</b></div></div></section>`;
  byId("sheetFooter").innerHTML = `<button id="deleteFactBtn" class="danger-text-btn">Delete fact</button><button id="retconFactBtn" class="secondary-btn">Preview retcon</button>`;
  byId("deleteFactBtn").addEventListener("click", () => deleteFact(fact));
  byId("retconFactBtn").addEventListener("click", () => retconFact(fact));
  openSheet();
}

function retconFact(fact) {
  openForm({ title: "Retcon fact", eyebrow: "Impact preview", description: "Arline previews affected facts, relationships, documents, chats, and feedback lineage before applying a retcon.", fields: [{ name: "new_value", label: "New value (JSON or text)", type: "textarea", value: pretty(fact.value), full: true }, { name: "note", label: "Reason", type: "textarea", full: true }], submit: "Preview impact", onSubmit: async (values) => { let value; try { value = JSON.parse(values.new_value); } catch (_) { value = values.new_value; } const payload = { project_id: state.activeProject.id, world_id: state.activeWorld.id, branch_id: state.activeBranch?.kind === "main" ? null : state.activeBranch?.id, owner_type: fact.owner_type, owner_id: fact.owner_id, path: fact.path, new_value: value, note: values.note }; const preview = await api("/api/retcon/preview", { method: "POST", body: payload }); showRetconPreview(payload, preview); } });
}

function showRetconPreview(payload, preview) {
  byId("compareTitle").textContent = "Retcon impact";
  byId("compareBody").innerHTML = `<div class="metric-grid"><div class="metric-card"><span>Facts</span><strong>${preview.affected_facts?.length || 0}</strong></div><div class="metric-card"><span>Relationships</span><strong>${preview.affected_relationships?.length || 0}</strong></div><div class="metric-card"><span>Documents</span><strong>${preview.affected_documents?.length || 0}</strong></div><div class="metric-card"><span>Sessions/data</span><strong>${preview.affected_sessions?.length || 0}</strong></div></div><pre class="json-block">${escapeHTML(pretty(preview))}</pre><div class="dialog-actions"><button id="applyRetconBtn" class="primary-btn">Apply retcon</button></div>`;
  byId("compareDialog").showModal();
  byId("applyRetconBtn").addEventListener("click", async () => { await api("/api/retcon/apply", { method: "POST", body: payload }); byId("compareDialog").close(); closeSheet(); await loadProjectData(); toast("Retcon applied with lineage preserved"); });
}

function deleteCustomTemplate() {
  const customTemplates = state.templates.filter((item) => item.project_id === state.activeProject?.id);
  if (!customTemplates.length) return toast("No custom templates in this project");
  openForm({
    title: "Delete custom template",
    eyebrow: "Reusable sheet",
    description: "Built-in templates are protected. Deleting a custom template does not delete entities that were already created from it.",
    fields: [{ name: "template_id", label: "Custom template", type: "select", options: customTemplates.map((item) => ({ value: item.id, label: `${item.name} · ${item.entity_type.replaceAll("_", " ")}` })), full: true }],
    submit: "Delete template",
    onSubmit: async (values) => {
      const template = customTemplates.find((item) => item.id === values.template_id);
      if (!template || !confirm(`Delete custom template “${template.name}”? Existing entities are kept.`)) return;
      await api(`/api/templates/${template.id}`, { method: "DELETE" });
      await loadProjectData();
      toast(`Deleted template “${template.name}”`);
    },
  });
}

function openTemplateForm() {
  openForm({ title: "New entity template", eyebrow: "Reusable sheet", description: "Templates define structure and defaults only. Applying one never promotes its values to canon automatically.", fields: [
    { name: "name", label: "Template name", required: true },
    { name: "entity_type", label: "Entity type", type: "select", options: (state.bootstrap?.entity_types || []).map(x=>({value:x,label:x.replaceAll("_"," ")})), value: "character" },
    { name: "description", label: "Description", type: "textarea", full: true },
    { name: "template", label: "Template payload (JSON)", type: "json", value: {shared_core:{},attributes:{},voice:{},knowledge:{},beliefs:{},current_state:{}}, full: true },
  ], onSubmit: async (values) => { await api("/api/templates", {method:"POST",body:{project_id:state.activeProject.id,...values}}); await loadProjectData(); } });
}

function renderSceneDependencies(result = {valid:true,dependencies:[]}) {
  const dependencies = result.dependencies || [];
  byId("dependencyStatus").textContent = `${dependencies.filter(x=>x.satisfied).length}/${dependencies.length}`;
  byId("dependencyStatus").style.color = result.valid ? "#83cdb6" : "#d9b46f";
  byId("dependencyList").innerHTML = dependencies.map(dep => `<div class="dependency-item ${dep.satisfied ? "ok" : "blocked"}" data-dependency-id="${dep.id}"><span>${dep.satisfied ? "✓" : "!"}</span><div><b>${escapeHTML(dep.requirement_type.replaceAll("_"," "))}</b><small>${escapeHTML(dep.target_type)} · ${escapeHTML(dep.detail || dep.target_id)}</small></div><button class="mini-icon-btn">×</button></div>`).join("") || `<div class="empty-note">No prerequisites. This scene can be entered from any state.</div>`;
  $$(".dependency-item button", byId("dependencyList")).forEach(button => button.addEventListener("click", async ()=>{ const id=button.closest(".dependency-item").dataset.dependencyId; await api(`/api/scenes/dependencies/${id}`,{method:"DELETE"}); if(state.activeDocument) openDocument(state.activeDocument.id); }));
}

function openSceneDependencyForm() {
  if (!state.activeDocument) return toast("Select a scene document first");
  const targets = [
    ...state.documents.filter(d=>d.id!==state.activeDocument.id).map(d=>({value:`document:${d.id}`,label:`Document · ${d.title}`})),
    ...state.variants.map(v=>({value:`entity_variant:${v.id}`,label:`Entity · ${v.display_name}`})),
    ...state.relationships.map(r=>({value:`relationship:${r.id}`,label:`Relationship · ${r.subject_name} ${r.relation_type} ${r.object_name}`})),
    ...state.facts.map(f=>({value:`fact:${f.id}`,label:`Fact · ${f.path}`})),
  ];
  if (!targets.length) return toast("Create a document, entity, relationship, or fact to reference first");
  openForm({ title:"Scene dependency",eyebrow:"Continuity graph",description:"Dependencies are checked before generation. They can require another scene, entity, relationship, fact, or knowledge state.",fields:[
    {name:"requirement_type",label:"Requirement",type:"select",options:["exists","completed","known","active","before_scene"].map(x=>({value:x,label:x.replaceAll("_"," ")})),value:"exists"},
    {name:"target",label:"Target",type:"select",options:targets,full:true},
    {name:"condition",label:"Additional condition (JSON)",type:"json",value:{},full:true},
  ],onSubmit:async values=>{ const [target_type,target_id]=values.target.split(":",2); await api("/api/scenes/dependencies",{method:"POST",body:{project_id:state.activeProject.id,world_id:state.activeWorld.id,branch_id:state.activeBranch?.kind==="main"?null:state.activeBranch?.id,scene_document_id:state.activeDocument.id,requirement_type:values.requirement_type,target_type,target_id,condition:values.condition}}); await openDocument(state.activeDocument.id); }});
}

function openConflictSheet(conflict) {
  byId("sheetEyebrow").textContent="Continuity conflict";
  byId("sheetTitle").textContent=conflict.path;
  byId("sheetSubtitle").textContent=`${conflict.conflict_class} · ${conflict.status}`;
  byId("sheetBody").innerHTML=`<section class="sheet-section"><div class="sheet-grid"><div><h3>Left / earlier</h3><pre class="json-block">${escapeHTML(pretty(conflict.left))}</pre></div><div><h3>Right / newer</h3><pre class="json-block">${escapeHTML(pretty(conflict.right))}</pre></div></div></section><section class="sheet-section"><h3>Resolution classes</h3><p>Choose whether this is a temporal transition, a world variant, a retcon, a bad source, or intentionally unresolved. Arline does not silently pick a side.</p></section>`;
  byId("sheetFooter").innerHTML=`<button id="keepConflictBtn" class="secondary-btn">Keep unresolved</button><button id="resolveConflictBtn" class="primary-btn">Resolve…</button>`;
  byId("keepConflictBtn").addEventListener("click",()=>resolveConflict(conflict,"keep_unresolved"));
  byId("resolveConflictBtn").addEventListener("click",()=>openConflictResolutionForm(conflict));
  openSheet();
}

function openConflictResolutionForm(conflict) {
  openForm({title:"Resolve conflict",eyebrow:"Continuity",description:"Resolution is recorded; neither source is destroyed.",fields:[
    {name:"resolution_type",label:"Interpretation",type:"select",options:[
      {value:"temporal_transition",label:"Historical → current transition"},{value:"world_variant",label:"Different world variant"},{value:"retcon_left",label:"Retcon left / keep right"},{value:"retcon_right",label:"Retcon right / keep left"},{value:"mark_source_wrong",label:"Mark a source wrong"},{value:"keep_unresolved",label:"Keep unresolved"},
    ],value:"temporal_transition"},
    {name:"chosen_value",label:"Chosen/normalized value (JSON, optional)",type:"json",value:{},full:true},
    {name:"note",label:"Resolution note",type:"textarea",full:true},
  ],onSubmit:async values=>{ await resolveConflict(conflict,values.resolution_type,values.chosen_value,values.note); }});
}

async function resolveConflict(conflict,resolutionType,chosenValue=null,note="") {
  await api(`/api/conflicts/${conflict.id}/resolve`,{method:"POST",body:{resolution_type:resolutionType,chosen_value:chosenValue,note}});
  closeSheet(); await loadProjectData(); toast("Conflict resolution recorded");
}

async function loadDatasetStats() {
  try {
    const stats = await api("/api/dataset/stats");
    const reviewed = (stats.accepted || 0) + (stats.edited_accept || 0) + (stats.rejected || 0);
    byId("datasetMiniCount").textContent = `${reviewed} reviewed`;
    byId("datasetCards").innerHTML = [
      ["All runs", stats.total || 0], ["Unreviewed", stats.unreviewed || 0], ["SFT ready", stats.sft_ready || 0], ["Preferences", stats.preference_ready || 0],
    ].map(([label, value]) => `<div class="metric-card"><span>${label}</span><strong>${value}</strong></div>`).join("");
  } catch (_) {}
}

async function exportDataset(kind) {
  loading(true, "Compiling dataset…", kind);
  try {
    const result = await api(`/api/dataset/export/${kind}`, { method: "POST" });
    toast(`${result.rows} ${kind} rows exported`);
    location.href = result.download_url;
  } catch (error) { toast(error.message); }
  finally { loading(false); }
}

function openFeedback(turnId, mode, story = "") {
  state.feedbackTurnId = turnId;
  state.feedbackMode = mode;
  byId("feedbackTitle").textContent = mode === "accepted" ? "Accept candidate" : mode === "edited_accept" ? "Edit & accept" : "Reject candidate";
  byId("editedStoryLabel").classList.toggle("hidden", mode !== "edited_accept");
  byId("editedStory").value = story;
  byId("feedbackNote").value = "";
  byId("issueGrid").innerHTML = ISSUE_LABELS.map((issue) => `<label><input type="checkbox" value="${issue}">${escapeHTML(issue.replaceAll("_", " "))}</label>`).join("");
  byId("feedbackDialog").showModal();
}

async function submitFeedback(event) {
  event.preventDefault();
  const issues = $$('#issueGrid input:checked').map((node) => node.value);
  const payload = { status: state.feedbackMode, issues, note: byId("feedbackNote").value, edited_story: state.feedbackMode === "edited_accept" ? byId("editedStory").value : "" };
  try {
    await api(`/api/turns/${state.feedbackTurnId}/feedback`, { method: "POST", body: payload });
    byId("feedbackDialog").close();
    if (state.activeSession) await openSession(state.activeSession.id);
    await loadDatasetStats();
    toast("Feedback saved to feedback lineage");
  } catch (error) { toast(error.message); }
}

function openWorldActionsForTab() {
  if (state.activeWorldTab === "relationship") return openRelationshipForm();
  if (["character", "location", "item", "organization", "lore"].includes(state.activeWorldTab)) return openEntityForm(state.activeWorldTab === "lore" ? "lore" : state.activeWorldTab);
  if (state.activeWorldTab === "worlds") return openWorldForm();
  if (state.activeWorldTab === "timeline") return openDocumentForm(null, "scene");
  return addCanonFact("world", state.activeWorld.id);
}

async function openContract() {
  try { byId("contractEditor").value = (await api("/api/contract")).content || ""; }
  catch (error) { byId("contractEditor").value = error.message; }
}

async function saveContract() {
  await api("/api/contract", { method: "POST", body: { content: byId("contractEditor").value } });
  toast("Writer contract saved");
}

async function runAblation() {
  const prompt = byId("promptInput").value;
  if (!prompt.trim()) return toast("Write a prompt first");
  const conditions = ["raw:off", "wcf:off", "smart_hybrid:off"];
  loading(true, "Running ablation…", conditions.join(" · "));
  try {
    const result = await api("/api/ablation", { method: "POST", body: { ...promptPayload(), conditions } });
    byId("statsOutput").textContent = pretty(result);
    openInspector("debug");
  } catch (error) { toast(error.message); }
  finally { loading(false); }
}

function renderReasoningMetrics(stats) {
  const total = Number(stats.total_output_tokens || 0);
  const reasoning = Number(stats.reasoning_output_tokens || 0);
  const story = Math.max(0, total - reasoning);
  return { total, reasoning, story, share: total ? reasoning / total : 0, ratio: story ? reasoning / story : 0 };
}

/* -------------------------------------------------------------------------
 * Arline Studio v1.1 Foundation / UX overrides
 * Structured underneath, natural on the surface.
 * ---------------------------------------------------------------------- */

function formatTokenCount(value) {
  const n = Number(value || 0);
  if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(n % (1024 * 1024) ? 1 : 0)}M`;
  if (n >= 1024) {
    const k = n / 1024;
    return `${Number.isInteger(k) ? k : k.toFixed(1)}K`;
  }
  return String(Math.round(n));
}

function dynamicVisibleMaximum() {
  const model = state.modelMap.get(byId("modelSelect")?.value);
  const modelLimit = Number(model?.max_context_length || byId("contextLength")?.value || 32768);
  const estimatedInput = Number(state.contextCache.contextBreakdown?.estimated_total_tokens || Math.max(1, Math.ceil((byId("promptInput")?.value || "").length / 4)));
  const reasoning = byId("reasoningSelect")?.value === "off" ? 0 : Number(byId("reasoningReserve")?.value || 0);
  const safety = Number(byId("safetyReserve")?.value || 2048);
  return Math.max(256, Math.floor((modelLimit - estimatedInput - reasoning - safety) / 256) * 256);
}

function buildLengthSteps() {
  const safeMax = dynamicVisibleMaximum();
  const fixed = [1024, 2048, 4096].filter((n) => n <= safeMax);
  const steps = fixed.length ? [...fixed] : [safeMax];
  let next = 8192;
  while (next <= safeMax) {
    steps.push(next);
    next *= 2;
  }
  const last = steps[steps.length - 1] || 0;
  if (safeMax > last) steps.push(safeMax);
  state.lengthSteps = [...new Set(steps)].sort((a, b) => a - b);
  return state.lengthSteps;
}

function syncDynamicLength({ preserveValue = true } = {}) {
  const current = Number(byId("visibleTokens")?.value || 4096);
  const steps = buildLengthSteps();
  const slider = byId("lengthSlider");
  if (!slider) return;
  slider.max = String(Math.max(0, steps.length - 1));
  let index = steps.indexOf(current);
  if (index < 0) {
    index = steps.reduce((best, value, i) => Math.abs(value - current) < Math.abs(steps[best] - current) ? i : best, 0);
  }
  if (!preserveValue && steps.includes(4096)) index = steps.indexOf(4096);
  slider.value = String(index);
  const selected = steps[index] || steps[0] || 256;
  byId("visibleTokens").max = String(dynamicVisibleMaximum());
  byId("visibleTokens").value = String(selected);

  const labels = ["Short", "Medium", "Long"];
  const isExactMax = index === steps.length - 1 && selected === dynamicVisibleMaximum() && ![1024, 2048, 4096].includes(selected);
  const title = labels[index] || (isExactMax ? "Maximum" : formatTokenCount(selected));
  byId("lengthLabel").textContent = `${title} · ${formatTokenCount(selected)}`;
  byId("lengthMaxLabel").textContent = `safe max ${formatTokenCount(dynamicVisibleMaximum())}`;
  byId("lengthTicks").innerHTML = steps.map((value, i) => `<span class="${i === index ? "active" : ""}" style="--tick:${steps.length <= 1 ? 0 : (i / (steps.length - 1)) * 100}%">${i < 3 ? labels[i] : i === steps.length - 1 && value === dynamicVisibleMaximum() ? "MAX" : formatTokenCount(value)}</span>`).join("");
}

function syncLengthSlider() {
  const steps = state.lengthSteps.length ? state.lengthSteps : buildLengthSteps();
  const index = Math.max(0, Math.min(steps.length - 1, Number(byId("lengthSlider")?.value || 0)));
  byId("visibleTokens").value = String(steps[index] || 4096);
  syncDynamicLength();
  updateBudgetUI();
}

function collectPromptReferences() {
  const merged = new Map();
  for (const ref of [...state.selectedReferences, ...state.detectedReferences.filter((r) => r.resolved)]) {
    if (!ref?.id) continue;
    const key = `${ref.type}:${ref.id}`;
    const previous = merged.get(key);
    const mode = ref.mode || previous?.mode || "context";
    merged.set(key, { type: ref.type, id: ref.id, label: ref.label || ref.name || ref.id, mode });
  }
  return [...merged.values()];
}

function promptPayload() {
  return {
    ...runtimePayload(),
    prompt: byId("promptInput").value,
    timezone: timezoneName(),
    session_id: state.activeSession?.id || null,
    project_id: state.activeProject?.id || null,
    world_id: state.activeWorld?.id || null,
    branch_id: state.activeBranch?.id || null,
    folder_id: null,
    references: collectPromptReferences(),
    context_recipe_id: byId("contextRecipeSelect")?.value || null,
    scratch_mode: Boolean(state.scratchMode),
  };
}

function updateBudgetUI() {
  syncDynamicLength();
  const runtime = runtimePayload();
  const reasoning = runtime.reasoning === "off" ? 0 : runtime.reasoning_reserve_tokens;
  const totalOutput = runtime.visible_output_tokens + reasoning;
  const estimatedInput = Number(state.contextCache.contextBreakdown?.estimated_total_tokens || Math.max(1, Math.ceil((byId("promptInput")?.value || "").length / 4)));
  const model = state.modelMap.get(runtime.model);
  const contextMax = Number(model?.max_context_length || runtime.context_length || 32768);
  const free = Math.max(0, contextMax - estimatedInput - totalOutput);
  const pct = Math.min(100, ((estimatedInput + totalOutput) / Math.max(contextMax, 1)) * 100);
  byId("totalBudget").textContent = totalOutput.toLocaleString();
  byId("modeNote").textContent = state.scratchMode ? "Scratch mode · generated discoveries stay outside canon staging." : (MODE_NOTES[runtime.input_mode] || "");
  byId("beatControls").classList.toggle("hidden", runtime.generation_mode !== "beats");
  const inspectorBar = $("i", byId("contextBudgetBar"));
  if (inspectorBar) inspectorBar.style.width = `${pct}%`;
  const composerFill = byId("composerBudgetFill");
  if (composerFill) composerFill.style.width = `${pct}%`;
  byId("tokenEstimate").textContent = `${formatTokenCount(estimatedInput)} input · ${formatTokenCount(totalOutput)} output ceiling`;
  byId("composerBudgetText").textContent = `${formatTokenCount(estimatedInput)} context · ${formatTokenCount(runtime.visible_output_tokens)} response · ${formatTokenCount(free)} free`;
}

function updateModelInfo() {
  const model = state.modelMap.get(byId("modelSelect").value);
  const reasoning = byId("reasoningSelect");
  const previous = reasoning.value;
  reasoning.innerHTML = "";
  const allowed = model?.reasoning_options?.length ? model.reasoning_options : ["off", "on"];
  for (const mode of allowed) {
    const option = document.createElement("option");
    option.value = mode;
    option.textContent = mode === "off" ? "Thinking Off" : `Thinking ${mode[0].toUpperCase()}${mode.slice(1)}`;
    reasoning.appendChild(option);
  }
  reasoning.value = allowed.includes(previous) ? previous : allowed.includes(state.config?.reasoning) ? state.config.reasoning : allowed[0];
  if (!model) {
    byId("modelInfo").textContent = "Select a model to inspect its capabilities.";
  } else {
    if (model.max_context_length) {
      byId("contextLength").value = model.max_context_length;
      byId("contextLength").max = model.max_context_length;
    }
    byId("modelInfo").innerHTML = `<b>${escapeHTML(model.display_name)}</b><br>Loaded: ${model.loaded ? "yes" : "no"}<br>Max context: ${(model.max_context_length || 0).toLocaleString()}<br>Reasoning: ${escapeHTML(allowed.join(", "))}`;
  }
  updateReasoningWarning();
  syncDynamicLength();
  updateBudgetUI();
}

async function loadWorkspaceBootstrap() {
  const bootstrap = await api("/api/workspace/bootstrap");
  state.bootstrap = bootstrap;
  state.projects = bootstrap.projects || [];
  state.worlds = bootstrap.worlds || [];
  const active = bootstrap.active || {};
  const nextProjectId = active.project?.id || state.projects[0]?.id;
  if (nextProjectId) {
    await selectScope(nextProjectId, active.world?.id || bootstrap.world_bible?.default_world_id, active.branch?.id || bootstrap.world_bible?.default_branch_id);
    return;
  }
  state.activeProject = null;
  state.activeWorld = state.worlds[0] || null;
  state.activeBranch = state.activeWorld?.branches?.find((b) => b.kind === "main") || null;
  state.projectTree = { folders: [] };
  state.families = []; state.variants = []; state.relationships = []; state.documents = [];
  state.tags = []; state.facts = []; state.snapshots = []; state.templates = []; state.conflicts = [];
  state.sessions = []; state.selectedReferences = [];
  renderScopeSelectors(); updateBreadcrumbs(); updateContextChipUI(); renderProjectTree();
  renderLibraryCounts(); renderTags(); renderDocuments(); renderSessions(); renderWorldGrid(); updateScopeVisualization();
}

async function selectScope(projectId, worldId = null, branchId = null) {
  if (!projectId) return;
  loading(true, "Opening workspace…", "Resolving project workspace and shared World Bible");
  try {
    const [project, projectList, bootstrap] = await Promise.all([
      api(`/api/projects/${encodeURIComponent(projectId)}`),
      api("/api/projects"),
      api("/api/workspace/bootstrap"),
    ]);
    state.activeProject = project;
    state.projects = projectList.projects || state.projects;
    state.worlds = bootstrap.worlds || state.worlds;
    state.bootstrap = { ...state.bootstrap, ...bootstrap };
    applyProjectDefaults(project);
    const linked = project.worlds || [];
    const preferredId = worldId || project.default_world_id || linked[0]?.id || bootstrap.world_bible?.default_world_id;
    let worldMeta = state.worlds.find((item) => item.id === preferredId) || linked.find((item) => item.id === preferredId) || state.worlds[0];
    state.activeWorld = worldMeta ? await api(`/api/worlds/${encodeURIComponent(worldMeta.id)}`) : null;
    if (state.activeWorld && !state.worlds.some((item) => item.id === state.activeWorld.id)) state.worlds.push(state.activeWorld);
    const branches = state.activeWorld?.branches || [];
    state.activeBranch = branches.find((item) => item.id === branchId) || branches.find((item) => item.kind === "main") || branches[0] || null;
    state.selectedReferences = [];
    updateContextChipUI();
    renderScopeSelectors();
    updateBreadcrumbs();
    await Promise.all([loadProjectData(), loadSessions()]);
  } catch (error) { toast(`Workspace error: ${error.message}`, 6000); }
  finally { loading(false); }
}

function renderScopeSelectors() {
  const projectSelect = byId("projectSelect");
  projectSelect.innerHTML = state.projects.map((item) => `<option value="${escapeHTML(item.id)}">${escapeHTML(item.name)}</option>`).join("");
  if (state.activeProject) projectSelect.value = state.activeProject.id;
  const worldSelect = byId("worldSelect");
  worldSelect.innerHTML = state.worlds.map((item) => `<option value="${escapeHTML(item.id)}">${escapeHTML(item.name)} · ${escapeHTML(item.canon_status || "draft")}</option>`).join("");
  if (state.activeWorld) worldSelect.value = state.activeWorld.id;
  const branchSelect = byId("branchSelect");
  branchSelect.innerHTML = (state.activeWorld?.branches || []).map((item) => `<option value="${escapeHTML(item.id)}">${escapeHTML(item.name)} · ${escapeHTML(item.kind)}</option>`).join("");
  if (state.activeBranch) branchSelect.value = state.activeBranch.id;
}

function populateContextRecipes() {
  const select = byId("contextRecipeSelect");
  const previous = select.value;
  select.innerHTML = (state.contextRecipes || []).map((recipe) => `<option value="${escapeHTML(recipe.id)}">${escapeHTML(recipe.name)}</option>`).join("");
  const preferred = previous && state.contextRecipes.some((r) => r.id === previous) ? previous : (state.contextRecipes.find((r) => r.id === "RECIPE-STORY")?.id || state.contextRecipes[0]?.id || "");
  select.value = preferred;
}

async function loadProjectData() {
  if (!state.activeProject) return;
  const worldId = state.activeWorld?.id || "";
  const branchId = state.activeBranch?.id || "";
  const branchForFacts = state.activeBranch?.kind === "main" ? "" : branchId;
  const qTree = new URLSearchParams({ ...(worldId ? { world_id: worldId } : {}), ...(branchId ? { branch_id: branchId } : {}) });
  const qBible = new URLSearchParams({ ...(worldId ? { world_id: worldId } : {}), ...(branchId ? { branch_id: branchId } : {}), project_id: state.activeProject.id });
  const factQ = new URLSearchParams({ ...(worldId ? { world_id: worldId } : {}), ...(branchForFacts ? { branch_id: branchForFacts } : {}) });
  const stagedQ = new URLSearchParams({ ...(worldId ? { world_id: worldId } : {}), ...(branchForFacts ? { branch_id: branchForFacts } : {}) });
  const [tree, bible, documents, tags, facts, snapshots, staged, continuity] = await Promise.all([
    api(`/api/projects/${state.activeProject.id}/tree?${qTree}`),
    api(`/api/world-bible?${qBible}`),
    api(`/api/documents?${new URLSearchParams({ project_id: state.activeProject.id })}`),
    api(`/api/tags?project_id=${state.activeProject.id}`),
    worldId ? api(`/api/facts?${factQ}`) : { facts: [] },
    worldId ? api(`/api/snapshots?world_id=${encodeURIComponent(worldId)}`) : { snapshots: [] },
    api(`/api/projects/${state.activeProject.id}/staged-changes?${stagedQ}`),
    api(`/api/projects/${state.activeProject.id}/continuity?${qTree}`),
  ]);
  state.projectTree = tree;
  state.worlds = bible.worlds || state.worlds;
  state.families = bible.families || [];
  state.variants = bible.variants || [];
  state.relationships = bible.relationships || [];
  state.timelineEvents = bible.timeline || [];
  state.contextRecipes = bible.recipes || [];
  state.documents = documents.documents || tree.documents || [];
  state.tags = tags.tags || [];
  state.facts = facts.facts || [];
  state.snapshots = snapshots.snapshots || [];
  state.templates = tree.templates || [];
  state.conflicts = tree.conflicts || [];
  state.manifestRefs = tree.manifest_refs || [];
  state.activeScene = tree.active_scene || null;
  state.sceneCards = tree.scene_cards || [];
  state.overlays = tree.overlays || [];
  state.stagedChanges = staged.changes || [];
  state.continuity = continuity || null;
  populateContextRecipes();
  renderScopeSelectors(); renderProjectTree(); renderLibraryCounts(); renderTags(); renderDocuments(); renderWorldGrid(); updateScopeVisualization(); updateActiveSceneUI();
  refreshPromptHighlight();
}

function renderProjectTree() {
  const root = byId("projectTree");
  root.innerHTML = "";
  const documentsByFolder = new Map();
  for (const doc of state.documents) {
    const key = doc.folder_id || "root";
    if (!documentsByFolder.has(key)) documentsByFolder.set(key, []);
    documentsByFolder.get(key).push(doc);
  }
  const appendDocuments = (container, folderId, depth) => {
    for (const doc of documentsByFolder.get(folderId || "root") || []) container.appendChild(documentTreeNode(doc, depth));
  };
  const appendFolder = (container, folder, depth = 0) => {
    const wrapper = document.createElement("div");
    wrapper.className = "tree-folder-group";
    const row = document.createElement("div"); row.className = "tree-node"; row.style.paddingLeft = `${depth * 13}px`;
    row.innerHTML = `<button class="tree-toggle">⌄</button><span class="tree-icon">▱</span><button class="tree-main">${escapeHTML(folder.name)}</button><button class="row-menu">•••</button>`;
    const children = document.createElement("div"); children.className = "tree-children";
    wrapper.append(row, children); container.appendChild(wrapper);
    $(".tree-toggle", row).addEventListener("click", () => { children.classList.toggle("hidden"); $(".tree-toggle", row).textContent = children.classList.contains("hidden") ? "›" : "⌄"; });
    $(".tree-main", row).addEventListener("click", () => { setView("draft"); filterDocumentsByFolder(folder.id); });
    $(".row-menu", row).addEventListener("click", (event) => contextMenu(event.clientX, event.clientY, [
      { label: "New document here", action: () => openDocumentForm(folder.id) },
      { label: "New subfolder", action: () => openFolderForm(folder.id) },
      { label: "Rename", action: () => renameFolder(folder) },
      { label: "Delete", danger: true, action: () => deleteFolder(folder) },
    ]));
    appendDocuments(children, folder.id, depth + 1);
    for (const child of folder.children || []) appendFolder(children, child, depth + 1);
  };
  appendDocuments(root, null, 0);
  for (const folder of state.projectTree?.folders || []) appendFolder(root, folder, 0);
  byId("projectTreeEmpty").classList.toggle("hidden", root.children.length > 0);
}

async function loadSessions(tag = "") {
  if (!state.activeProject) return;
  const q = new URLSearchParams({ limit: "150", project_id: state.activeProject.id, ...(state.activeWorld?.id ? { world_id: state.activeWorld.id } : {}), ...(state.activeBranch?.id ? { branch_id: state.activeBranch.id } : {}), ...(tag ? { tag } : {}) });
  state.sessions = (await api(`/api/sessions?${q}`)).sessions || [];
  renderSessions();
}

function bindSessionRows() {
  $$(".session-row").forEach((row) => {
    const id = row.dataset.sessionId;
    $(".session-main", row).addEventListener("click", () => openSession(id));
    $(".row-menu", row).addEventListener("click", (event) => {
      const session = state.sessions.find((item) => item.id === id);
      contextMenu(event.clientX, event.clientY, [
        { label: "Rename", action: () => renameSession(session) },
        { label: session.pinned ? "Unpin" : "Pin", action: () => patchSession(id, { pinned: !session.pinned }) },
        { label: "Fork chat", action: () => forkSession(id) },
        { label: session.scratch_mode ? "Disable scratch" : "Scratch mode", action: () => patchSession(id, { scratch_mode: !session.scratch_mode }) },
        { label: "Edit tags", action: () => editSessionTags(session) },
        { label: "Delete", danger: true, action: () => deleteSession(id) },
      ]);
    });
  });
}

async function openSession(id) {
  loading(true, "Opening chat…", "Loading turn history and branch lineage");
  try {
    const [session, forks] = await Promise.all([api(`/api/sessions/${id}`), api(`/api/sessions/${id}/forks`)]);
    state.activeSession = session; state.forkGraph = forks;
    state.scratchMode = Boolean(session.scratch_mode);
    byId("activeChatTitle").textContent = session.title || "Current chat";
    state.selectedReferences = session.workspace_refs || [];
    updateContextChipUI(); updateScratchUI(); renderForkTrail();
    byId("chatLanding").classList.add("hidden"); byId("conversationSection").classList.remove("hidden");
    renderConversation(session.turns || []); setView("chat"); renderSessions();
    scheduleContextStackSync(); recordNavigation();
  } catch (error) { toast(error.message); }
  finally { loading(false); }
}

function renderForkTrail() {
  const el = byId("chatForkTrail");
  const graph = state.forkGraph;
  if (!graph) { el.innerHTML = ""; return; }
  const nodes = graph.sessions || graph.nodes || [];
  const currentId = state.activeSession?.id;
  const rootId = graph.root_id || graph.root?.id || nodes.find((n) => !n.parent_session_id)?.id;
  const current = nodes.find((n) => n.id === currentId) || state.activeSession;
  const siblings = nodes.filter((n) => n.parent_session_id && n.parent_session_id === current?.parent_session_id);
  const chips = [];
  if (rootId && rootId !== currentId) chips.push(`<button data-fork-session="${escapeHTML(rootId)}">Root</button><span>›</span>`);
  if (current?.parent_session_id && current.parent_session_id !== rootId) chips.push(`<button data-fork-session="${escapeHTML(current.parent_session_id)}">Parent</button><span>›</span>`);
  chips.push(`<b>${escapeHTML(current?.title || "Current branch")}</b>`);
  if (siblings.length > 1) chips.push(`<em>${siblings.length} sibling forks</em>`);
  if (current?.world_fork_id) chips.push(`<span class="fork-world-badge">◇ World branch</span>`);
  else if (current?.parent_session_id) chips.push(`<button class="promote-fork-inline" data-promote-world-fork>Promote to world branch</button>`);
  el.innerHTML = chips.join("");
  $$('[data-fork-session]', el).forEach((btn) => btn.addEventListener("click", () => openSession(btn.dataset.forkSession)));
  $('[data-promote-world-fork]', el)?.addEventListener("click", promoteChatForkToWorldBranch);
}

async function forkSession(id, throughTurnId = null) {
  const fork = await api(`/api/sessions/${id}/fork`, { method: "POST", body: { through_turn_id: throughTurnId || null } });
  await loadSessions(); await openSession(fork.id); toast(throughTurnId ? "Forked chat from this turn" : "Chat forked");
}

function updateScratchUI() {
  const button = byId("scratchToggleBtn");
  button.classList.toggle("active", state.scratchMode);
  button.textContent = state.scratchMode ? "◆ Scratch on" : "◇ Scratch";
  document.body.classList.toggle("scratch-mode", state.scratchMode);
  updateBudgetUI();
}

async function toggleScratchMode() {
  state.scratchMode = !state.scratchMode;
  if (state.activeSession?.id) {
    await api(`/api/sessions/${state.activeSession.id}`, { method: "PATCH", body: { scratch_mode: state.scratchMode } });
    state.activeSession.scratch_mode = state.scratchMode;
  }
  updateScratchUI();
  scheduleContextStackSync();
  toast(state.scratchMode ? "Scratch mode enabled — nothing is staged into canon" : "Scratch mode disabled");
}

function turnHTML(turn) {
  const story = turn.feedback_status === "edited_accept" && turn.edited_story ? turn.edited_story : turn.story;
  const stats = turn.stats || {}; const total = stats.total_output_tokens || 0; const reason = stats.reasoning_output_tokens || 0; const visible = Math.max(0, total - reason);
  return `<article class="turn" data-turn-id="${turn.id}">
    <div class="turn-user"><div class="user-bubble">${escapeHTML(turn.user_prompt)}</div></div>
    <div class="turn-assistant"><div class="assistant-head"><div class="assistant-meta"><span class="run-chip">${escapeHTML(turn.run_id)}</span><span>${escapeHTML(turn.model || "model")}</span><span>${escapeHTML(turn.mode)} · ${escapeHTML(turn.reasoning)}</span>${turn.feedback_status && turn.feedback_status !== "unreviewed" ? `<span class="feedback-badge ${turn.feedback_status}">${escapeHTML(turn.feedback_status)}</span>` : ""}</div><div class="assistant-actions"><button class="tiny-btn fork-turn">↗ Fork here</button><button class="tiny-btn state-turn">∆ State</button><button class="tiny-btn copy-turn">Copy</button><button class="tiny-btn inspect-turn">Inspect</button><button class="tiny-btn save-turn">Save run</button></div></div>
    ${turn.feedback_status === "edited_accept" ? `<div class="edited-marker">Human-edited accepted version</div>` : ""}<div class="story-output">${storyHTML(story)}</div>
    <div class="usage-strip">${stats.input_tokens ? `<span class="usage-pill">${stats.input_tokens} in</span>` : ""}${visible ? `<span class="usage-pill">${visible} story</span>` : ""}${reason ? `<span class="usage-pill warning">${reason} reasoning</span>` : ""}${stats.tokens_per_second ? `<span class="usage-pill">${Number(stats.tokens_per_second).toFixed(1)} tok/s</span>` : ""}</div>
    <div class="feedback-row"><button class="accept">✓ Accept</button><button class="edit-accept">✎ Edit & Accept</button><button class="reject">✕ Reject</button><button class="quick-from-turn">＋ Create from prose</button><button class="promote">＋ Stage canon change</button></div></div>
  </article>`;
}

function bindTurnActions() {
  $$(".turn").forEach((node) => {
    const turnId = node.dataset.turnId; const storyNode = $(".story-output", node);
    $(".copy-turn", node).addEventListener("click", () => navigator.clipboard.writeText(storyNode.innerText).then(() => toast("Copied")));
    $(".inspect-turn", node).addEventListener("click", () => inspectTurn(turnId));
    $(".save-turn", node).addEventListener("click", () => saveRunFromTurn(turnId));
    $(".fork-turn", node).addEventListener("click", () => state.activeSession && forkSession(state.activeSession.id, turnId));
    $(".state-turn", node).addEventListener("click", () => reviewStateProposals(turnId, storyNode.innerText));
    $(".quick-from-turn", node).addEventListener("click", () => openQuickCreate(window.getSelection()?.toString().trim() || storyNode.innerText.slice(0, 600)));
    $(".accept", node).addEventListener("click", () => openFeedback(turnId, "accepted"));
    $(".edit-accept", node).addEventListener("click", () => openFeedback(turnId, "edited_accept", storyNode.innerText));
    $(".reject", node).addEventListener("click", () => openFeedback(turnId, "rejected"));
    $(".promote", node).addEventListener("click", () => openStagedChangeForm(turnId, window.getSelection()?.toString().trim() || storyNode.innerText.slice(0, 300)));
  });
}

function referenceRegistry() {
  const registry = [];
  for (const family of state.families) registry.push({ type: "entity_family", id: family.id, label: family.name, subtitle: family.entity_type, family });
  for (const variant of state.variants) registry.push({ type: "entity_variant", id: variant.id, label: variant.display_name, subtitle: `${variant.entity_type || "entity"} · ${worldName(variant.world_id)}`, variant });
  for (const world of state.worlds) registry.push({ type: "world", id: world.id, label: world.name, subtitle: "world", world });
  for (const doc of state.documents) registry.push({ type: "document", id: doc.id, label: doc.title, subtitle: doc.document_type, document: doc });
  return registry.filter((r) => r.label);
}

function refreshPromptHighlight() {
  const input = byId("promptInput"); const overlay = byId("promptHighlight"); const preview = byId("referencePreviewBar");
  if (!input || !overlay) return;
  const text = input.value || ""; const registry = referenceRegistry().sort((a, b) => b.label.length - a.label.length);
  const found = []; const tokenRegex = /(@[^\s@,;:()\[\]{}]+(?:\s+[^\s@,;:()\[\]{}]+){0,4}|\/[\w-]+)/g;
  let cursor = 0, html = "", match;
  while ((match = tokenRegex.exec(text))) {
    html += escapeHTML(text.slice(cursor, match.index));
    const token = match[0];
    if (token.startsWith("/")) {
      const known = COMMANDS.some((c) => c.label === token || c.label.startsWith(token));
      html += `<span class="command-token ${known ? "" : "unresolved"}">${escapeHTML(token)}</span>`;
    } else {
      const raw = token.slice(1).trim();
      let resolved = registry.find((r) => raw === r.label) || registry.find((r) => raw.startsWith(`${r.label} `));
      if (!resolved) resolved = registry.find((r) => r.label.toLowerCase() === raw.toLowerCase());
      if (resolved) {
        found.push({ ...resolved, resolved: true });
        html += `<span class="ref-known">${escapeHTML(token)}</span>`;
      } else {
        found.push({ type: "unresolved", id: `unresolved:${raw}`, label: raw, resolved: false });
        html += `<span class="ref-unresolved">${escapeHTML(token)}</span>`;
      }
    }
    cursor = match.index + token.length;
  }
  html += escapeHTML(text.slice(cursor));
  overlay.innerHTML = html + (text.endsWith("\n") ? "\n " : "");
  overlay.scrollTop = input.scrollTop; overlay.scrollLeft = input.scrollLeft;
  input.closest(".composer-editor-shell")?.classList.toggle("has-highlight", Boolean(text));
  const unique = new Map(); found.forEach((r) => unique.set(`${r.type}:${r.id}`, r)); state.detectedReferences = [...unique.values()];
  preview.innerHTML = state.detectedReferences.map((ref) => `<button class="reference-preview-chip ${ref.resolved ? "resolved" : "unresolved"}" data-preview-key="${escapeHTML(`${ref.type}:${ref.id}`)}">${ref.resolved ? escapeHTML(ENTITY_ICONS[ref.type] || "@") : "?"} @${escapeHTML(ref.label)}</button>`).join("");
  preview.classList.toggle("hidden", !state.detectedReferences.length);
  $$(".reference-preview-chip", preview).forEach((button) => {
    const ref = state.detectedReferences.find((r) => `${r.type}:${r.id}` === button.dataset.previewKey);
    button.addEventListener("mouseenter", () => showReferencePeek(ref, button));
    button.addEventListener("mouseleave", scheduleHideReferencePeek);
    button.addEventListener("click", () => ref?.resolved && addReference(ref));
  });
  updateContextChipUI();
}

let referencePeekHideTimer = null;
function scheduleHideReferencePeek() { clearTimeout(referencePeekHideTimer); referencePeekHideTimer = setTimeout(() => byId("referencePeek")?.classList.add("hidden"), 180); }
function showReferencePeek(ref, anchor) {
  if (!ref) return;
  clearTimeout(referencePeekHideTimer);
  const peek = byId("referencePeek");
  let body = "";
  if (!ref.resolved) body = `<b>@${escapeHTML(ref.label)}</b><small>Unresolved reference</small><p>Create it or choose a known World Bible object.</p>`;
  else if (ref.family) body = `<b>${escapeHTML(ref.family.name)}</b><small>${escapeHTML(ref.family.entity_type)} · World Bible</small><p>${escapeHTML(ref.family.description || "No description")}</p>`;
  else if (ref.variant) body = `<b>${escapeHTML(ref.variant.display_name)}</b><small>${escapeHTML(worldName(ref.variant.world_id))} · ${escapeHTML(ref.variant.canon_status || "draft")}</small><p>${escapeHTML(ref.variant.summary || "No summary")}</p>`;
  else if (ref.world) body = `<b>${escapeHTML(ref.world.name)}</b><small>World · ${escapeHTML(ref.world.canon_status || "draft")}</small><p>${escapeHTML(ref.world.description || "No description")}</p>`;
  else if (ref.document) body = `<b>${escapeHTML(ref.document.title)}</b><small>Project ${escapeHTML(ref.document.document_type)}</small><p>${escapeHTML((ref.document.content || "").slice(0, 180))}</p>`;
  else body = `<b>${escapeHTML(ref.label)}</b><small>${escapeHTML(ref.type)}</small>`;
  peek.innerHTML = body;
  const rect = anchor.getBoundingClientRect(); peek.style.left = `${Math.min(innerWidth - 340, Math.max(12, rect.left))}px`; peek.style.top = `${Math.min(innerHeight - 220, rect.bottom + 8)}px`;
  peek.classList.remove("hidden"); peek.onmouseenter = () => clearTimeout(referencePeekHideTimer); peek.onmouseleave = scheduleHideReferencePeek;
}

function updateContextChipUI() {
  const container = byId("contextChips");
  const modeLabel = (mode) => ({mention:"M",context:"C",deep:"D"}[mode] || "C");
  container.innerHTML = state.selectedReferences.map((ref) => `<span class="context-chip" data-ref-key="${escapeHTML(`${ref.type}:${ref.id}`)}"><button class="context-peek" title="Peek">${escapeHTML(ENTITY_ICONS[ref.type] || "@")} <b>@${escapeHTML(ref.label)}</b></button><button class="context-mode" title="Reference depth: ${escapeHTML(ref.mode || "context")} · click to cycle">${modeLabel(ref.mode)}</button><button class="context-pin" title="Pin context">⌖</button><button class="context-remove" title="Remove context">×</button></span>`).join("");
  container.classList.toggle("hidden", state.selectedReferences.length === 0);
  $$(".context-chip", container).forEach((chip) => {
    const [type, ...idParts] = chip.dataset.refKey.split(":"); const id = idParts.join(":");
    const ref = state.selectedReferences.find((r) => r.type === type && r.id === id);
    $(".context-remove", chip).addEventListener("click", () => { state.selectedReferences = state.selectedReferences.filter((r) => !(r.type === type && r.id === id)); updateContextChipUI(); updateScopeVisualization(); scheduleContextStackSync(); });
    $(".context-mode", chip).addEventListener("click", () => { const order=["mention","context","deep"]; const current=ref.mode||"context"; ref.mode=order[(order.indexOf(current)+1)%order.length]; updateContextChipUI(); updateScopeVisualization(); scheduleContextStackSync(); toast(`@${ref.label}: ${ref.mode} context`); });
    $(".context-pin", chip).addEventListener("click", () => pinContext(ref));
    $(".context-peek", chip).addEventListener("mouseenter", (event) => showReferencePeek(referenceRegistry().find((r) => r.type === type && r.id === id) || { ...ref, resolved: true }, event.currentTarget));
    $(".context-peek", chip).addEventListener("mouseleave", scheduleHideReferencePeek);
  });
  const automatic = state.detectedReferences.filter((r) => r.resolved).length;
  byId("contextScopeLabel").textContent = `${state.selectedReferences.length + automatic} refs`;
}

function chooseMention(index) {
  const item = state.mentionResults[index]; if (!item) return;
  const input = byId("promptInput"); const cursor = input.selectionStart; const before = input.value.slice(0, cursor); const match = before.match(/@([^@\n]{0,50})$/); if (!match) return;
  const start = cursor - match[0].length; input.value = `${input.value.slice(0, start)}@${item.label} ${input.value.slice(cursor)}`;
  const next = start + item.label.length + 2; input.setSelectionRange(next, next); addReference({ type: item.type, id: item.id, label: item.label }); hideAutocomplete(); refreshPromptHighlight(); input.focus();
}

function renderContextWhy() {
  const ws = state.contextCache.workspace || {};
  const auto = ws.auto_selected || []; const pins = ws.pinned || []; const explicit = ws.explicit_references || collectPromptReferences();
  const reasons = [
    ...explicit.map((x) => ({ label: `@${x.label || x.id}`, why: "explicit reference in this request", kind: "explicit" })),
    ...auto.map((x) => ({ label: x.label || x.name || x.resource_id || x.id || "context item", why: x.reason || x.selection_reason || "selected by context strategy", kind: "auto" })),
    ...pins.map((x) => ({ label: x.label || x.resource_id || x.id || "pinned item", why: "pinned to workspace context", kind: "pin" })),
  ];
  byId("contextWhy").innerHTML = reasons.length ? reasons.map((r) => `<div class="context-why-row"><span class="why-kind ${r.kind}">${escapeHTML(r.kind)}</span><div><b>${escapeHTML(r.label)}</b><small>${escapeHTML(r.why)}</small></div></div>`).join("") : `<div class="empty-note">Analyze to see why each context item was included.</div>`;
}

function updateScopeVisualization() {
  const ws = state.contextCache.workspace;
  const explicit = collectPromptReferences(); const auto = ws?.auto_selected || []; const pinned = ws?.pinned || [];
  const recipe = state.contextRecipes.find((r) => r.id === byId("contextRecipeSelect")?.value);
  const scene = state.activeScene;
  byId("scopeVisualization").innerHTML = `<div class="scope-path"><span>${escapeHTML(state.activeProject?.name || "No project")}</span><b>›</b><span>${escapeHTML(state.activeWorld?.name || "World Bible")}</span><b>›</b><span>${escapeHTML(state.activeBranch?.name || "Main")}</span></div><div class="scope-list"><b>Recipe</b>: ${escapeHTML(recipe?.name || "default")}<br><b>Explicit</b>: ${explicit.length ? explicit.map((x) => `@${escapeHTML(x.label)}`).join(", ") : "none"}<br><b>Auto-selected</b>: ${auto.length}<br><b>Pinned</b>: ${pinned.length}<br><b>Project overlays</b>: ${state.overlays.length}<br><b>Pending canon changes</b>: ${state.stagedChanges.length}${scene ? `<br><b>Active scene</b>: ${escapeHTML(scene.document_title || scene.document_id || scene.notes || "set")}` : ""}</div>`;
  renderContextWhy();
}

function loadContextResult(result) {
  state.activeAnalysisId = result.analysis_id || state.activeAnalysisId;
  state.contextCache.wcf = result.wcf || ""; state.contextCache.aif = result.aif_core || ""; state.contextCache.brief = result.narrative_brief || null; state.contextCache.workspace = result.workspace_context || null; state.contextCache.projections = result.projections || []; state.contextCache.traceChoices = result.trace_choices || []; state.contextCache.contextBreakdown = result.context_breakdown || null;
  byId("wcfOutput").textContent = state.contextCache.wcf || "No WCF available."; byId("aifOutput").textContent = state.contextCache.aif || "No AIF-Core available."; byId("briefOutput").textContent = pretty(state.contextCache.brief); byId("workspaceContextOutput").textContent = state.contextCache.workspace?.text || "No workspace context."; byId("projectionOutput").textContent = pretty(state.contextCache.projections); byId("wcfValidation").textContent = pretty(result.wcf_validation || {});
  const summary = result.summary || {}; byId("coverageValue").textContent = summary.coverage ?? "—"; byId("factsValue").textContent = summary.facts ?? "—"; byId("transitionsValue").textContent = summary.transitions ?? "—"; byId("projectionsValue").textContent = summary.projections ?? "—"; byId("wcfTokenValue").textContent = result.context_breakdown?.estimated_total_tokens?.toLocaleString?.() || "—"; byId("analysisStrip").classList.remove("hidden");
  byId("contextBreakdown").innerHTML = Object.entries(result.context_breakdown || {}).map(([key, value]) => `<div><span>${escapeHTML(key.replaceAll("_", " "))}</span><b>${typeof value === "number" ? value.toLocaleString() : escapeHTML(String(value))}</b></div>`).join("");
  const trace = byId("traceSelect"); trace.dataset.cacheId = result.run_id || result.analysis_id || ""; trace.innerHTML = `<option value="">Choose a fact…</option>` + (result.trace_choices || []).map((x) => `<option value="${escapeHTML(x.trace_id)}">${escapeHTML(x.label || x.trace_id)}</option>`).join("");
  updateScopeVisualization(); updateBudgetUI();
}

function openQuickCreate(prefill = "", forcedKind = "") {
  const dialog = byId("quickCreateDialog");
  byId("quickCreateInput").value = prefill || ""; byId("quickCreateKind").value = forcedKind || ""; state.quickCreatePreview = null;
  dialog.showModal(); scheduleQuickCreatePreview(); setTimeout(() => byId("quickCreateInput").focus(), 0);
}

function scheduleQuickCreatePreview() {
  clearTimeout(state.quickCreateTimer);
  state.quickCreateTimer = setTimeout(previewQuickCreate, 180);
}

async function previewQuickCreate() {
  const text = byId("quickCreateInput").value.trim(); const forced = byId("quickCreateKind").value || null;
  if (!text) { byId("quickCreatePreview").innerHTML = `<span class="preview-icon">◇</span><div><b>Start typing…</b><small>Arline will infer the schema underneath.</small></div>`; return; }
  try {
    const preview = await api("/api/quick-create/preview", { method: "POST", body: { text, forced_kind: forced, project_id: state.activeProject?.id || null, world_id: state.activeWorld?.id || null, branch_id: state.activeBranch?.id || null, folder_id: state.activeWorldFolderId || null } }); state.quickCreatePreview = preview;
    const detail = preview.kind === "entity" ? `${preview.entity_type || "entity"}${preview.attributes && Object.keys(preview.attributes).length ? ` · ${Object.entries(preview.attributes).filter(([k])=>k!=="hierarchy").map(([k,v]) => `${k}: ${Array.isArray(v)?v.join(" › "):v}`).join(" · ")}` : ""}` : (preview.document_type || preview.description || preview.kind);
    const matches = (preview.possible_matches || []).map((item)=>`<button type="button" class="qc-existing-match" data-id="${escapeHTML(item.id)}"><span>↪</span><div><b>Use existing ${escapeHTML(item.label)}</b><small>${escapeHTML(item.entity_type || "sheet")}${item.alias?` · alias: ${escapeHTML(item.alias)}`:""} · ${Math.round((item.score||0)*100)}% match</small></div></button>`).join("");
    byId("quickCreatePreview").innerHTML = `<span class="preview-icon">${escapeHTML(ENTITY_ICONS[preview.entity_type || preview.kind] || "◇")}</span><div><b>${escapeHTML(preview.name || text)}</b><small>Detected ${escapeHTML(preview.kind)} · ${escapeHTML(detail || "ready")}</small>${preview.attributes?.hierarchy ? `<code>${escapeHTML(preview.attributes.hierarchy.join(" › "))}</code>` : ""}${matches ? `<div class="quick-create-matches"><em>Possible existing sheets</em>${matches}</div>` : ""}</div>`;
    $$('.qc-existing-match',byId("quickCreatePreview")).forEach((button)=>button.addEventListener("click",async()=>{byId("quickCreateDialog").close();await openEntitySheet(button.dataset.id);toast("Linked to the existing World Bible sheet instead of duplicating it");}));
  } catch (error) { byId("quickCreatePreview").innerHTML = `<span class="preview-icon">!</span><div><b>Could not infer structure</b><small>${escapeHTML(error.message)}</small></div>`; }
}

async function submitQuickCreate(event) {
  event.preventDefault(); if (event.submitter?.value === "cancel") return byId("quickCreateDialog").close();
  const text = byId("quickCreateInput").value.trim(); if (!text) return toast("Describe what you want to create");
  try {
    const result = await api("/api/quick-create", { method: "POST", body: { text, forced_kind: byId("quickCreateKind").value || null, project_id: state.activeProject?.id || null, world_id: state.activeWorld?.id || null, branch_id: state.activeBranch?.id || null } });
    byId("quickCreateDialog").close();
    if (result.kind === "project") await loadWorkspaceBootstrap();
    else if (result.kind === "world") { await loadWorkspaceBootstrap(); if (state.activeProject) await selectScope(state.activeProject.id, result.resource.id); }
    else { await loadProjectData(); if (result.kind === "entity" && result.resource?.id) await openEntitySheet(result.resource.id, result.variant?.id); }
    toast(`Created ${result.kind}: ${result.resource?.name || result.resource?.title || state.quickCreatePreview?.name || "resource"}`);
  } catch (error) { toast(error.message, 5000); }
}

function quickCreateAdvanced() {
  const preview = state.quickCreatePreview || {}; const kind = byId("quickCreateKind").value || preview.kind;
  byId("quickCreateDialog").close();
  if (kind === "world") openWorldForm(); else if (kind === "project") openProjectForm(); else if (kind === "folder") openFolderForm(); else if (kind === "document") openDocumentForm(); else openEntityForm(preview.entity_type || "character");
}

function openEntityForm(defaultType = "character") {
  const typeOptions = (state.bootstrap?.entity_types || ["character","location","item","organization","world_rule","lore"]).map((x) => ({ value:x,label:x.replaceAll("_"," ") }));
  openForm({ title: "Advanced entity / variant", eyebrow: "World Bible · schema inspector", description: "Use Quick Create for normal creation. This screen exposes the underlying family/variant schema when you explicitly need it.", fields: [
    { name:"name",label:"Name / display name",required:true,full:true },
    { name:"entity_type",label:"Type",type:"select",options:typeOptions,value:defaultType },
    { name:"description",label:"Family description",type:"textarea",full:true },
    { name:"shared_core",label:"Shared core across worlds (JSON)",type:"json",value:{},full:true },
    { name:"summary",label:"Current world / branch summary",type:"textarea",full:true },
    { name:"attributes",label:"World-specific attributes (JSON)",type:"json",value:{},full:true },
    { name:"canon_status",label:"Variant status",type:"select",options:(state.bootstrap?.canon_statuses || []).map((x)=>({value:x,label:x})),value:"draft" },
  ], onSubmit: async (values) => {
    const family = await api("/api/entities/families", { method:"POST", body:{ project_id:null,name:values.name,entity_type:values.entity_type,description:values.description,shared_core:values.shared_core,create_variant_in_world:null } });
    let variant = null; if (state.activeWorld) variant = await api("/api/entities/variants", { method:"POST", body:{ family_id:family.id,world_id:state.activeWorld.id,branch_id:state.activeBranch?.kind === "main" ? null : state.activeBranch?.id,display_name:values.name,summary:values.summary,canon_status:values.canon_status,attributes:values.attributes,voice:{},knowledge:{},beliefs:{},current_state:{} } });
    if (state.activeProject) await api(`/api/projects/${state.activeProject.id}/manifest/refs`, { method:"POST", body:{ resource_type:"entity_family",resource_id:family.id,label:family.name,priority:1 } });
    await loadProjectData(); await openEntitySheet(family.id, variant?.id);
  }});
}

function openFolderForm(parentId = null) {
  openForm({ title:"New project folder", eyebrow:"Project filesystem", description:"Folders organize project files only. World Bible sheets and chats remain independent.", fields:[
    {name:"name",label:"Folder name",required:true,full:true},
    {name:"kind",label:"Purpose",type:"select",options:["mixed","manuscript","notes","research","assets","references"].map((x)=>({value:x,label:x[0].toUpperCase()+x.slice(1)})),value:"mixed"},
  ], onSubmit: async (values)=>{ await api("/api/folders",{method:"POST",body:{project_id:state.activeProject.id,name:values.name,parent_id:parentId,kind:values.kind,world_id:null,branch_id:null}}); await loadProjectData(); }});
}

function worldName(id) { return state.worlds.find((item) => item.id === id)?.name || state.activeWorld?.id === id && state.activeWorld?.name || id || ""; }

function openVariantForm(family, sourceVariant = null) {
  openForm({ title:`New ${family.name} variant`, eyebrow:"World Bible variant", description:"Variants belong to worlds/branches, never to project folders.", fields:[
    {name:"world_id",label:"Target world",type:"select",options:state.worlds.map((x)=>({value:x.id,label:x.name})),value:state.activeWorld?.id},
    {name:"display_name",label:"Display name",value:family.name,required:true},
    {name:"canon_status",label:"Status",type:"select",options:(state.bootstrap?.canon_statuses||[]).map((x)=>({value:x,label:x})),value:"draft"},
    {name:"inherit_attributes",label:"Inherit attributes",type:"checkbox",value:true}, {name:"inherit_voice",label:"Inherit voice",type:"checkbox",value:true},
    {name:"summary",label:"Variant summary",type:"textarea",full:true},
  ], onSubmit: async (values)=>{ const sections=[]; if(values.inherit_attributes)sections.push("attributes"); if(values.inherit_voice)sections.push("voice"); const variant=await api("/api/entities/variants",{method:"POST",body:{family_id:family.id,world_id:values.world_id,branch_id:null,display_name:values.display_name,summary:values.summary,canon_status:values.canon_status,inherit_from_variant_id:sourceVariant?.id||null,inherit_sections:sections,attributes:{},voice:{},knowledge:{},beliefs:{},current_state:{}}}); await selectScope(state.activeProject.id,values.world_id,null); await openEntitySheet(family.id,variant.id); }});
}

function editFamily(family) {
  const folderOptions=[{value:"",label:"No folder"},...(state.worldBibleFolders||[]).map((folder)=>({value:folder.id,label:folder.name}))];
  openForm({ title:`Edit ${family.name}`, eyebrow:"World Bible · shared identity", description:"Folder changes organization only. The sheet remains shared World Bible knowledge.", fields:[
    {name:"name",label:"Family name",value:family.name,required:true},
    {name:"folder_id",label:"World Bible folder",type:"select",options:folderOptions,value:family.folder_id||""},
    {name:"description",label:"Description",type:"textarea",value:family.description,full:true},
    {name:"shared_core",label:"Shared core (JSON)",type:"json",value:family.shared_core,full:true}
  ], onSubmit:async(values)=>{await api(`/api/entities/families/${family.id}`,{method:"PATCH",body:{...values,note:"edited in Studio"}});await loadProjectData();await openEntitySheet(family.id);}});
}

function openForm({ title, eyebrow = "Create", description = "", fields = [], submit = "Save", onSubmit }) {
  byId("formEyebrow").textContent=eyebrow; byId("formTitle").textContent=title; byId("formDescription").textContent=description; byId("formSubmitBtn").textContent=submit; const container=byId("formFields"); container.innerHTML="";
  for(const field of fields){ const label=document.createElement("label"); if(field.full)label.classList.add("full"); label.append(document.createTextNode(field.label)); let control;
    if(field.type==="textarea"||field.type==="json"){control=document.createElement("textarea");control.rows=field.rows||(field.type==="json"?7:4);control.value=field.type==="json"&&typeof field.value!=="string"?pretty(field.value||{}):(field.value??"");}
    else if(field.type==="select"||field.type==="multiselect"){control=document.createElement("select");if(field.type==="multiselect")control.multiple=true;control.innerHTML=(field.options||[]).map((o)=>`<option value="${escapeHTML(o.value)}">${escapeHTML(o.label)}</option>`).join(""); if(field.type==="multiselect"){const selected=new Set(field.value||[]);[...control.options].forEach((o)=>o.selected=selected.has(o.value));}else control.value=field.value??"";}
    else if(field.type==="checkbox"){control=document.createElement("input");control.type="checkbox";control.checked=Boolean(field.value);} else {control=document.createElement("input");control.type=field.type||"text";control.value=field.value??"";if(field.placeholder)control.placeholder=field.placeholder;if(field.min!=null)control.min=field.min;if(field.max!=null)control.max=field.max;if(field.step!=null)control.step=field.step;}
    control.name=field.name;control.dataset.fieldType=field.type||"text";if(field.required)control.required=true;label.appendChild(control);container.appendChild(label);
  }
  state.formHandler=async()=>{const values={};for(const control of $$('[name]',container)){if(control.type==="checkbox")values[control.name]=control.checked;else if(control.dataset.fieldType==="json")values[control.name]=parseJSON(control.value,{});else if(control.dataset.fieldType==="multiselect")values[control.name]=[...control.selectedOptions].map((o)=>o.value);else values[control.name]=control.value;if(control.required && (Array.isArray(values[control.name])?!values[control.name].length:!String(values[control.name]).trim()))throw new Error(`${control.name} is required`);}await onSubmit(values);};
  byId("formDialog").showModal();setTimeout(()=>$('input,textarea,select',container)?.focus(),0);
}

function updateActiveSceneUI() {
  const scene = state.activeScene; const doc = scene?.document_id ? state.documents.find((d)=>d.id===scene.document_id) : null;
  byId("activeSceneNote").textContent = scene ? `Scene · ${doc?.title || scene.narrative_time || scene.notes || "active"}` : "No active scene";
}

function openActiveSceneForm(prefillDocumentId = null) {
  if (!state.activeProject) return toast("Open a project first");
  const current=state.activeScene||{};
  const documentId=prefillDocumentId||current.document_id||"";
  const card=state.sceneCards.find((item)=>item.document_id===documentId)||null;
  const seed=(prefillDocumentId && card) ? card : current;
  const variantOptions=state.variants.map((v)=>({value:v.id,label:`${v.display_name} · ${worldName(v.world_id)}`}));
  openForm({title:"Active scene / narrative cursor",eyebrow:"Project context",description:"Anchors where the story currently is. When linked to a document, this also updates its outline scene card.",fields:[
    {name:"document_id",label:"Scene document",type:"select",options:[{value:"",label:"No linked document"},...state.documents.filter((d)=>["scene","draft","chapter"].includes(d.document_type)).map((d)=>({value:d.id,label:`${d.title} · ${d.document_type}`}))],value:documentId,full:true},
    {name:"pov_variant_id",label:"POV",type:"select",options:[{value:"",label:"Unspecified"},...variantOptions],value:seed.pov_variant_id||""},
    {name:"location_variant_id",label:"Location",type:"select",options:[{value:"",label:"Unspecified"},...state.variants.filter((v)=>v.entity_type==="location").map((v)=>({value:v.id,label:v.display_name}))],value:seed.location_variant_id||""},
    {name:"participants",label:"Present entities",type:"multiselect",options:variantOptions,value:seed.participants||[],full:true},
    {name:"narrative_time",label:"Narrative time",value:seed.narrative_time||"",placeholder:"17 Aug 2026 · 21:32"},
    {name:"target_outcome",label:"Scene target / intended outcome",type:"textarea",value:card?.target_outcome||"",full:true},
    {name:"scene_status",label:"Outline status",type:"select",options:["planned","drafting","complete","skipped"].map((x)=>({value:x,label:x})),value:card?.status||"drafting"},
    {name:"notes",label:"Scene notes",type:"textarea",value:seed.notes||card?.notes||"",full:true},
  ],onSubmit:async(values)=>{
    const branchId=state.activeBranch?.kind==="main"?null:state.activeBranch?.id||null;
    if(values.document_id){
      const existing=state.sceneCards.find((item)=>item.document_id===values.document_id);
      await api(`/api/projects/${state.activeProject.id}/scene-cards/${values.document_id}`,{method:"PUT",body:{world_id:state.activeWorld?.id||null,branch_id:branchId,pov_variant_id:values.pov_variant_id||null,location_variant_id:values.location_variant_id||null,participants:values.participants||[],narrative_time:values.narrative_time,target_outcome:values.target_outcome,notes:values.notes,status:values.scene_status,sort_order:Number(existing?.sort_order||0)}});
    }
    state.activeScene=await api(`/api/projects/${state.activeProject.id}/active-scene`,{method:"PUT",body:{document_id:values.document_id||null,world_id:state.activeWorld?.id||null,branch_id:branchId,pov_variant_id:values.pov_variant_id||null,location_variant_id:values.location_variant_id||null,participants:values.participants||[],narrative_time:values.narrative_time,notes:values.notes}});
    await loadProjectData();toast("Narrative cursor updated");
  }});
}

function openSceneCardForm(doc) {
  if(!state.activeProject||!doc)return;
  const card=state.sceneCards.find((item)=>item.document_id===doc.id)||{};
  const variantOptions=state.variants.map((v)=>({value:v.id,label:`${v.display_name} · ${v.entity_type||"entity"}`}));
  openForm({title:`Scene card · ${doc.title}`,eyebrow:"Project story outline",description:"Plan this scene while keeping its character/location references in the shared World Bible.",fields:[
    {name:"status",label:"Status",type:"select",options:["planned","drafting","complete","skipped"].map((x)=>({value:x,label:x})),value:card.status||"planned"},
    {name:"sort_order",label:"Outline order",type:"number",step:0.1,value:card.sort_order??doc.sort_order??state.sceneCards.length},
    {name:"pov_variant_id",label:"POV",type:"select",options:[{value:"",label:"Unspecified"},...variantOptions],value:card.pov_variant_id||""},
    {name:"location_variant_id",label:"Location",type:"select",options:[{value:"",label:"Unspecified"},...state.variants.filter((v)=>v.entity_type==="location").map((v)=>({value:v.id,label:v.display_name}))],value:card.location_variant_id||""},
    {name:"participants",label:"Present entities",type:"multiselect",options:variantOptions,value:card.participants||[],full:true},
    {name:"narrative_time",label:"Narrative time",value:card.narrative_time||""},
    {name:"target_outcome",label:"Target outcome",type:"textarea",value:card.target_outcome||"",full:true},
    {name:"notes",label:"Planning notes",type:"textarea",value:card.notes||"",full:true},
  ],onSubmit:async(values)=>{await api(`/api/projects/${state.activeProject.id}/scene-cards/${doc.id}`,{method:"PUT",body:{world_id:state.activeWorld?.id||doc.world_id||null,branch_id:state.activeBranch?.kind==="main"?null:state.activeBranch?.id||doc.branch_id||null,pov_variant_id:values.pov_variant_id||null,location_variant_id:values.location_variant_id||null,participants:values.participants||[],narrative_time:values.narrative_time,target_outcome:values.target_outcome,notes:values.notes,status:values.status,sort_order:Number(values.sort_order||0)}});await loadProjectData();await openStoryOutline();}});
}

function openStoryOutline() {
  if(!state.activeProject)return;
  const docs=state.documents.filter((d)=>["chapter","scene","draft","outline"].includes(d.document_type));
  const rows=docs.map((doc)=>({doc,card:state.sceneCards.find((c)=>c.document_id===doc.id)||null})).sort((a,b)=>Number(a.card?.sort_order??a.doc.sort_order??0)-Number(b.card?.sort_order??b.doc.sort_order??0));
  const variantName=(id)=>state.variants.find((v)=>v.id===id)?.display_name||"—";
  byId("sheetEyebrow").textContent="Project story outline";byId("sheetTitle").textContent=state.activeProject.name;byId("sheetSubtitle").textContent="Narrative plan linked to World Bible state, without moving sheets into the project";
  byId("sheetBody").innerHTML=`<section class="sheet-section"><div class="sheet-section-head"><h3>Story sequence</h3><span>${rows.length} documents</span></div><div class="story-outline-list">${rows.map(({doc,card},i)=>`<article class="story-outline-row ${state.activeScene?.document_id===doc.id?"active":""}" data-doc-id="${escapeHTML(doc.id)}"><div class="story-outline-order">${escapeHTML(String(card?.sort_order??doc.sort_order??i+1))}</div><div class="story-outline-main"><div><b>${escapeHTML(doc.title)}</b><span class="canon-badge ${escapeHTML(card?.status||doc.status||"planned")}">${escapeHTML(card?.status||doc.status||"planned")}</span></div><small>${escapeHTML(doc.document_type)}${card?.narrative_time?` · ${escapeHTML(card.narrative_time)}`:""}${card?.pov_variant_id?` · POV ${escapeHTML(variantName(card.pov_variant_id))}`:""}${card?.location_variant_id?` · @${escapeHTML(variantName(card.location_variant_id))}`:""}</small>${card?.target_outcome?`<p>${escapeHTML(card.target_outcome)}</p>`:""}</div><div class="story-outline-actions"><button class="tiny-btn outline-open">Open</button><button class="tiny-btn outline-edit">Plan</button><button class="tiny-btn outline-active">${state.activeScene?.document_id===doc.id?"Active":"Set active"}</button></div></article>`).join("")||`<div class="empty-note">No chapter/scene/draft documents yet.</div>`}</div></section>`;
  byId("sheetFooter").innerHTML=`<button id="outlineNewDocBtn" class="secondary-btn">＋ Story document</button><button id="outlineSceneBtn" class="primary-btn">Set narrative cursor</button>`;
  $$('.story-outline-row',byId("sheetBody")).forEach((row)=>{const doc=state.documents.find((d)=>d.id===row.dataset.docId);$('.outline-open',row).addEventListener('click',()=>openDocument(doc.id));$('.outline-edit',row).addEventListener('click',()=>openSceneCardForm(doc));$('.outline-active',row).addEventListener('click',()=>openActiveSceneForm(doc.id));});
  byId("outlineNewDocBtn").addEventListener("click",()=>openDocumentForm());byId("outlineSceneBtn").addEventListener("click",()=>openActiveSceneForm());openSheet();
}

function openOverlayForm() {
  if(!state.activeProject)return; const targets=[...state.variants.map((v)=>({value:`entity_variant:${v.id}`,label:`${v.display_name} · entity variant`})),...(state.activeWorld?[{value:`world:${state.activeWorld.id}`,label:`${state.activeWorld.name} · world`}]:[])];
  openForm({title:"Project overlay",eyebrow:"Project-specific canon view",description:"Overrides the project view of base canon without mutating the shared World Bible.",fields:[{name:"target",label:"Target",type:"select",options:targets,full:true},{name:"path",label:"Semantic path",placeholder:"attributes.bedrooms",required:true},{name:"value",label:"Override value (JSON or text)",type:"textarea",full:true}],onSubmit:async(values)=>{const [owner_type,owner_id]=values.target.split(":");let value;try{value=JSON.parse(values.value);}catch(_){value=values.value;}await api(`/api/projects/${state.activeProject.id}/overlays`,{method:"POST",body:{owner_type,owner_id,path:values.path,value,world_id:state.activeWorld?.id||null,branch_id:state.activeBranch?.kind==="main"?null:state.activeBranch?.id}});await loadProjectData();}});
}

function openStagedChangeForm(turnId = null, sourceText = "", proposal = null) {
  if(state.scratchMode)return toast("Scratch mode is active — canon staging is intentionally disabled");
  if(!state.activeProject||!state.activeWorld)return toast("Open a project and world first");
  const targets=[{value:`world:${state.activeWorld.id}`,label:`${state.activeWorld.name} · world`},...state.variants.map((v)=>({value:`entity_variant:${v.id}`,label:`${v.display_name} · entity`})),...state.relationships.map((r)=>({value:`relationship:${r.id}`,label:`${r.subject_name} → ${r.object_name} · ${r.relation_type}`}))];
  openForm({title:"Stage canon change",eyebrow:"Review before canon",description:"AI discoveries stay proposed until explicitly accepted.",fields:[{name:"target",label:"Owner",type:"select",options:targets,full:true},{name:"path",label:"Semantic path",value:proposal?.path||"",placeholder:"current_state.location",required:true},{name:"proposed_value",label:"Proposed value (JSON or text)",type:"textarea",value:proposal?.value!=null?pretty(proposal.value):sourceText,full:true},{name:"confidence",label:"Confidence",type:"number",min:0,max:1,step:0.01,value:proposal?.confidence??0.75}],onSubmit:async(values)=>{const [owner_type,owner_id]=values.target.split(":");let value;try{value=JSON.parse(values.proposed_value);}catch(_){value=values.proposed_value;}await api(`/api/projects/${state.activeProject.id}/staged-changes`,{method:"POST",body:{owner_type,owner_id,path:values.path,proposed_value:value,confidence:Number(values.confidence||0.5),world_id:state.activeWorld.id,branch_id:state.activeBranch?.kind==="main"?null:state.activeBranch?.id,session_id:state.activeSession?.id||null,turn_id:turnId,source_text:sourceText}});await loadProjectData();toast("Change staged for review");}});
}

async function reviewStateProposals(turnId, text) {
  loading(true,"Extracting state proposals…","Running Arline analytical pipeline without changing canon");
  try{const result=await api("/api/state-proposals",{method:"POST",body:{text,project_id:state.activeProject?.id||null,world_id:state.activeWorld?.id||null,branch_id:state.activeBranch?.id||null,session_id:state.activeSession?.id||null,turn_id:turnId}});byId("compareTitle").textContent="Proposed state diff";
    const patches=result.patches||[];const entities=result.entities||[];const relations=result.relations||[];
    byId("compareBody").innerHTML=`<div class="metric-grid"><div class="metric-card"><span>Patches</span><strong>${patches.length}</strong></div><div class="metric-card"><span>Entities</span><strong>${entities.length}</strong></div><div class="metric-card"><span>Relations</span><strong>${relations.length}</strong></div><div class="metric-card"><span>Conflicts</span><strong>${(result.conflicts||[]).length}</strong></div></div>${patches.length?`<div class="proposal-list">${patches.map((p,i)=>`<article><div><b>${escapeHTML(p.path||p.field||p.operation||`Patch ${i+1}`)}</b><small>${escapeHTML(p.entity||p.subject||p.event_id||"")}</small></div><pre>${escapeHTML(pretty(p))}</pre><button class="tiny-btn stage-proposal" data-index="${i}">Stage manually…</button></article>`).join("")}</div>`:`<div class="empty-note">No deterministic state patch was extracted. You can still stage a manual change.</div>`}<details><summary>Extracted entities & relations</summary><pre class="json-block">${escapeHTML(pretty({entities,relations,claims:result.claims,uncertainties:result.uncertainties}))}</pre></details>`;
    byId("compareDialog").showModal();$$('.stage-proposal',byId("compareBody")).forEach((b)=>b.addEventListener("click",()=>{const p=patches[Number(b.dataset.index)];byId("compareDialog").close();openStagedChangeForm(turnId,text,{path:p.path||p.field||"state.extracted",value:p.value??p.after??p,confidence:p.confidence??0.7});}));
  }catch(error){toast(error.message,6000);}finally{loading(false);}
}

async function resolveStagedChange(id, accept) { await api(`/api/staged-changes/${id}/resolve`,{method:"POST",body:{accept}}); await loadProjectData(); toast(accept?"Change accepted into canon":"Change rejected"); }

async function openProjectContextSheet() {
  if(!state.activeProject)return;
  const scene=state.activeScene;const doc=scene?.document_id?state.documents.find((d)=>d.id===scene.document_id):null;
  byId("sheetEyebrow").textContent="Project context manifest";byId("sheetTitle").textContent=state.activeProject.name;byId("sheetSubtitle").textContent="What this project is making · shared canon stays in World Bible";
  byId("sheetBody").innerHTML=`<section class="sheet-section"><div class="sheet-section-head"><h3>Working set</h3><button id="manifestAddBtn" class="tiny-btn">＋ Reference</button></div>${state.manifestRefs.map((r)=>`<div class="resource-inline-row"><div><b>${escapeHTML(r.label||r.resource_id)}</b><small>${escapeHTML(r.resource_type)} · priority ${r.priority}</small></div><button class="tiny-danger-btn manifest-remove" data-type="${escapeHTML(r.resource_type)}" data-id="${escapeHTML(r.resource_id)}">×</button></div>`).join("")||`<div class="empty-note">No explicit working-set references yet. @ references still work normally.</div>`}</section>
  <section class="sheet-section"><div class="sheet-section-head"><h3>Active scene</h3><button id="sceneEditBtn" class="tiny-btn">Edit</button></div><p>${scene?escapeHTML(doc?.title||scene.narrative_time||scene.notes||"Active scene configured"):"No narrative cursor set."}</p>${scene?`<pre class="json-block">${escapeHTML(pretty(scene))}</pre>`:""}</section>
  <section class="sheet-section"><div class="sheet-section-head"><h3>Project overlays</h3><button id="overlayAddBtn" class="tiny-btn">＋ Overlay</button></div>${state.overlays.map((o)=>`<div class="fact-row"><div><code>${escapeHTML(o.owner_type)}:${escapeHTML(o.owner_id)} · ${escapeHTML(o.path)}</code><small>${escapeHTML(JSON.stringify(o.value))}</small></div><button class="tiny-danger-btn overlay-remove" data-id="${escapeHTML(o.id)}">×</button></div>`).join("")||`<div class="empty-note">No project-specific overrides.</div>`}</section>
  <section class="sheet-section"><div class="sheet-section-head"><h3>Canon staging</h3><span>${state.stagedChanges.length} pending</span></div>${state.stagedChanges.map((c)=>`<div class="staged-change"><div><b>${escapeHTML(c.path)}</b><small>${escapeHTML(c.owner_type)} · confidence ${Number(c.confidence||0).toFixed(2)}</small><code>${escapeHTML(JSON.stringify(c.proposed_value))}</code></div><div><button class="tiny-btn staged-accept" data-id="${c.id}">Accept</button><button class="tiny-danger-btn staged-reject" data-id="${c.id}">Reject</button></div></div>`).join("")||`<div class="empty-note">Nothing waiting for canon approval.</div>`}</section>`;
  byId("sheetFooter").innerHTML=`<button id="projectOutlineSheetBtn" class="secondary-btn">Story outline</button><button id="projectContinuitySheetBtn" class="secondary-btn">Continuity · ${state.continuity?.warning_count||0}</button><button id="projectSceneSheetBtn" class="primary-btn">Set active scene</button>`;
  byId("manifestAddBtn").addEventListener("click",openManifestRefForm);byId("sceneEditBtn").addEventListener("click",()=>openActiveSceneForm());byId("overlayAddBtn").addEventListener("click",openOverlayForm);byId("projectOutlineSheetBtn").addEventListener("click",openStoryOutline);byId("projectContinuitySheetBtn").addEventListener("click",openContinuityReport);byId("projectSceneSheetBtn").addEventListener("click",()=>openActiveSceneForm());
  $$('.manifest-remove',byId("sheetBody")).forEach((b)=>b.addEventListener("click",async()=>{const q=new URLSearchParams({resource_type:b.dataset.type,resource_id:b.dataset.id});await api(`/api/projects/${state.activeProject.id}/manifest/refs?${q}`,{method:"DELETE"});await loadProjectData();await openProjectContextSheet();}));
  $$('.overlay-remove',byId("sheetBody")).forEach((b)=>b.addEventListener("click",async()=>{if(!confirm("Remove this project overlay? Shared World Bible canon will be unchanged."))return;await api(`/api/overlays/${b.dataset.id}`,{method:"DELETE"});await loadProjectData();await openProjectContextSheet();}));
  $$('.staged-accept',byId("sheetBody")).forEach((b)=>b.addEventListener("click",()=>resolveStagedChange(b.dataset.id,true)));$$('.staged-reject',byId("sheetBody")).forEach((b)=>b.addEventListener("click",()=>resolveStagedChange(b.dataset.id,false)));openSheet();
}

function openManifestRefForm() {
  const resources=[...state.families.map((f)=>({value:`entity_family:${f.id}`,label:`${f.name} · ${f.entity_type}`})),...state.worlds.map((w)=>({value:`world:${w.id}`,label:`${w.name} · world`})),...state.documents.map((d)=>({value:`document:${d.id}`,label:`${d.title} · project document`}))];
  openForm({title:"Add to project working set",eyebrow:"Reference, don't copy",fields:[{name:"resource",label:"World Bible / project resource",type:"select",options:resources,full:true},{name:"priority",label:"Context priority",type:"number",min:0,max:10,step:1,value:1}],onSubmit:async(values)=>{const [resource_type,resource_id]=values.resource.split(":");const item=referenceRegistry().find((r)=>r.type===resource_type&&r.id===resource_id);await api(`/api/projects/${state.activeProject.id}/manifest/refs`,{method:"POST",body:{resource_type,resource_id,label:item?.label||resource_id,priority:Number(values.priority||1)}});await loadProjectData();await openProjectContextSheet();}});
}

async function openContinuityReport() {
  if(!state.activeProject)return;const q=new URLSearchParams({...(state.activeWorld?.id?{world_id:state.activeWorld.id}:{}),...(state.activeBranch?.kind!=="main"&&state.activeBranch?.id?{branch_id:state.activeBranch.id}:{})});const report=await api(`/api/projects/${state.activeProject.id}/continuity?${q}`);state.continuity=report;byId("compareTitle").textContent="Continuity lint";byId("compareBody").innerHTML=`<div class="continuity-summary"><strong>${report.warning_count||0}</strong><span>continuity warning${report.warning_count===1?"":"s"}</span></div>${(report.warnings||[]).map((w)=>`<article class="continuity-warning ${escapeHTML(w.severity||"warning")}"><b>${escapeHTML(w.kind?.replaceAll("_"," ")||"warning")}</b><p>${escapeHTML(w.message)}</p></article>`).join("")||`<div class="empty-state small">No deterministic continuity warnings in this scope.</div>`}<h3>Pending canon changes</h3>${(report.pending_changes||[]).map((c)=>`<div class="fact-row"><code>${escapeHTML(c.path)} → ${escapeHTML(JSON.stringify(c.proposed_value))}</code></div>`).join("")||`<div class="empty-note">None.</div>`}`;byId("compareDialog").showModal();
}

async function openBacklinks(resourceType,id,title="Backlinks") {const result=await api(`/api/backlinks/${encodeURIComponent(resourceType)}/${encodeURIComponent(id)}`);byId("compareTitle").textContent=`Where ${title} is used`;byId("compareBody").innerHTML=`<div class="metric-card"><span>References</span><strong>${result.count||0}</strong></div>${(result.links||[]).map((link)=>`<article class="backlink-row"><b>${escapeHTML(link.kind?.replaceAll("_"," ")||"reference")}</b><small>${escapeHTML(link.path||link.summary||link.project_id||link.scene_document_id||link.id||"")}</small></article>`).join("")||`<div class="empty-note">No backlinks yet.</div>`}`;byId("compareDialog").showModal();}

async function openEntityTimelineState(variant, family) {
  if (!state.activeWorld || !variant) return;
  const branchId = state.activeBranch?.kind === "main" ? null : state.activeBranch?.id;
  const params = new URLSearchParams({world_id:state.activeWorld.id,owner_type:"entity_variant",owner_id:variant.id,...(branchId?{branch_id:branchId}:{})});
  const timeline = await api(`/api/timeline?${params}`);
  const events = timeline.events || [];
  const options = [{value:"",label:"Latest state"},...events.map((event)=>({value:String(event.order_key),label:`${event.time_label || `#${event.order_key}`} · ${event.summary}`}))];
  openForm({title:`Timeline state · ${family?.name || variant.display_name}`,eyebrow:"World Bible · temporal state",description:"Inspect the accumulated state patches for this entity at a specific point in its timeline. This never changes current canon.",submit:"Inspect",fields:[{name:"at_order",label:"Timeline point",type:"select",options,value:"",full:true}],onSubmit:async(values)=>{
    const q = new URLSearchParams({world_id:state.activeWorld.id,owner_type:"entity_variant",owner_id:variant.id,...(branchId?{branch_id:branchId}:{})});
    if(values.at_order!=="")q.set("at_order",values.at_order);
    const snapshot=await api(`/api/timeline/state?${q}`);
    const applied=new Set(snapshot.applied_events||[]);
    const visibleEvents=events.filter((event)=>applied.has(event.id));
    byId("compareTitle").textContent=`Timeline state · ${family?.name || variant.display_name}`;
    byId("compareBody").innerHTML=`<div class="metric-grid"><div class="metric-card"><span>Applied events</span><strong>${visibleEvents.length}</strong></div><div class="metric-card"><span>Point</span><strong>${values.at_order===""?"Latest":escapeHTML(values.at_order)}</strong></div></div><h3>Accumulated temporal state</h3><pre class="json-block">${escapeHTML(pretty(snapshot.state||{}))}</pre><h3>Applied timeline</h3>${visibleEvents.map((event)=>`<article class="backlink-row"><b>${escapeHTML(event.time_label||String(event.order_key))}</b><small>${escapeHTML(event.summary)}</small><code>${escapeHTML(pretty(event.state_patch||{}))}</code></article>`).join("")||`<div class="empty-note">No entity-specific state events yet.</div>`}`;
    byId("compareDialog").showModal();
  }});
}

function openTimelineEventForm() {if(!state.activeWorld)return;openForm({title:"New timeline event",eyebrow:"World Bible timeline",fields:[{name:"time_label",label:"Time label",placeholder:"17 Aug 2026 · 21:32"},{name:"order_key",label:"Sort order",type:"number",step:0.01,value:state.timelineEvents.length+1},{name:"summary",label:"Event",type:"textarea",required:true,full:true},{name:"event_type",label:"Type",value:"event"},{name:"state_patch",label:"Optional state patch (JSON)",type:"json",value:{},full:true}],onSubmit:async(values)=>{await api("/api/timeline",{method:"POST",body:{world_id:state.activeWorld.id,branch_id:state.activeBranch?.kind==="main"?null:state.activeBranch?.id,time_label:values.time_label,order_key:Number(values.order_key||0),summary:values.summary,event_type:values.event_type,state_patch:values.state_patch,status:state.activeBranch?.kind==="main"?"canon":"what_if"}});await loadProjectData();}});}

function renderWorldGrid() {
  if(state.activeView!=="world")return;const tab=state.activeWorldTab;let cards=[];
  if(["character","location","item","organization","lore"].includes(tab)){const types=tab==="lore"?["lore","world_rule"]:[tab];cards=state.families.filter((f)=>types.includes(f.entity_type)).map((family)=>{const variant=state.variants.find((v)=>v.family_id===family.id&&(v.branch_id===state.activeBranch?.id||v.branch_id==null));return{type:"entity",family,variant,label:variant?.display_name||family.name,summary:variant?.summary||family.description,status:variant?.canon_status||"no variant"};});}
  else if(tab==="relationship")cards=state.relationships.map((rel)=>({type:"relationship",id:rel.id,label:`${rel.subject_name} ↔ ${rel.object_name}`,summary:rel.relation_type,status:rel.canon_status}));
  else if(tab==="canon")cards=[...state.conflicts.map((conflict)=>({type:"conflict",id:conflict.id,label:`Conflict: ${conflict.path}`,summary:`${JSON.stringify(conflict.left)} ↔ ${JSON.stringify(conflict.right)}`,status:"open",conflict})),...state.facts.map((fact)=>({type:"fact",id:fact.id,label:fact.path,summary:JSON.stringify(fact.value),status:fact.status,fact}))];
  else if(tab==="timeline")cards=state.timelineEvents.map((event)=>({type:"timeline",id:event.id,label:event.time_label||event.event_type||"Event",summary:event.summary,status:event.status,event}));
  else if(tab==="worlds")cards=state.worlds.map((world)=>({type:"world",id:world.id,label:world.name,summary:world.description,status:world.canon_status,world}));
  const search=byId("worldSearch").value.trim().toLowerCase();if(search)cards=cards.filter((c)=>`${c.label} ${c.summary}`.toLowerCase().includes(search));byId("worldGrid").innerHTML=cards.map(worldCardHTML).join("");byId("worldEmpty").classList.toggle("hidden",cards.length>0);
  $$(".world-card").forEach((card)=>card.addEventListener("click",async()=>{const item=cards[Number(card.dataset.index)];if(item.type==="entity")openEntitySheet(item.family.id,item.variant?.id);else if(item.type==="relationship")openRelationshipSheet(item.id);else if(item.type==="world")openWorldSheet(await api(`/api/worlds/${item.id}`));else if(item.type==="fact")openFactSheet(item.fact);else if(item.type==="conflict")openConflictSheet(item.conflict);else if(item.type==="timeline")showCompare(item.label,item.event);}));
}

function openWorldActionsForTab() {if(state.activeWorldTab==="relationship")return openRelationshipForm();if(["character","location","item","organization","lore"].includes(state.activeWorldTab))return openQuickCreate("", "entity");if(state.activeWorldTab==="worlds")return openQuickCreate("","world");if(state.activeWorldTab==="timeline")return openTimelineEventForm();return addCanonFact("world",state.activeWorld.id);}

function openWorldCompare() {const worlds=state.worlds;if(worlds.length<2)return toast("Create another world first");openForm({title:"Compare worlds",eyebrow:"World Bible diff",fields:[{name:"other",label:"Compare current world with",type:"select",options:worlds.filter((x)=>x.id!==state.activeWorld.id).map((x)=>({value:x.id,label:x.name})),full:true}],submit:"Compare",onSubmit:async(values)=>showCompare("World canon diff",await api(`/api/worlds/compare/${state.activeWorld.id}/${values.other}`))});}

async function openBranchCompare() {const branches=state.activeWorld?.branches||[];if(branches.length<2)return toast("Create a sandbox/what-if branch first");openForm({title:"Compare branches",eyebrow:"Semantic state diff",description:"Compare semantic state, then selectively merge only the changes you want.",fields:[{name:"target",label:"Compare current branch with",type:"select",options:branches.filter((b)=>b.id!==state.activeBranch.id).map((b)=>({value:b.id,label:`${b.name} · ${b.kind}`})),full:true}],submit:"Compare",onSubmit:async(values)=>showBranchCompare(await api(`/api/branches/compare/${state.activeBranch.id}/${values.target}`),state.activeBranch.id,values.target)});}

function showBranchCompare(diff,sourceId,targetId){byId("compareTitle").textContent=`${diff.left.name} → ${diff.right.name}`;const entityRows=(diff.entities||[]).map((row,i)=>`<label class="branch-change"><input type="checkbox" data-merge-kind="entity" data-index="${i}" checked><div><b>${escapeHTML(row.name)}</b><small>${escapeHTML(row.difference.kind)} · ${escapeHTML(Object.keys(row.difference.fields||{}).join(", ")||"variant presence")}</small></div></label>`).join("");const relRows=(diff.relationships||[]).map((row,i)=>`<label class="branch-change"><input type="checkbox" data-merge-kind="relationship" data-index="${i}" checked><div><b>${escapeHTML(row.left?.subject_name||row.right?.subject_name||"Relation")} —${escapeHTML(row.relation_type)}→ ${escapeHTML(row.left?.object_name||row.right?.object_name||"")}</b><small>${escapeHTML(row.difference.kind)}</small></div></label>`).join("");const factRows=(diff.facts?.left||[]).map((row,i)=>`<label class="branch-change"><input type="checkbox" data-merge-kind="fact" data-index="${i}"><div><b>${escapeHTML(row.path)}</b><small>${escapeHTML(JSON.stringify(row.value))}</small></div></label>`).join("");byId("compareBody").innerHTML=`<p class="compare-note">Source is the current branch. Merge copies semantic state; transcript text is never merged automatically.</p>${entityRows||relRows||factRows?`<div class="branch-change-list">${entityRows}${relRows}${factRows}</div>`:`<div class="empty-note">Branches have no semantic differences.</div>`}<div class="dialog-actions"><button id="mergeBranchBtn" class="primary-btn">Merge selected into ${escapeHTML(diff.right.name)}</button></div>`;byId("compareDialog").showModal();byId("mergeBranchBtn")?.addEventListener("click",async()=>{const changes=[];$$('[data-merge-kind]:checked',byId("compareBody")).forEach((input)=>{const kind=input.dataset.mergeKind;const i=Number(input.dataset.index);if(kind==="entity"){const row=diff.entities[i];changes.push({kind:"entity",family_id:row.family_id,fields:Object.keys(row.difference.fields||{})});}else if(kind==="relationship"){const row=diff.relationships[i];changes.push({kind:"relationship",relationship_id:row.left?.id||null,subject_family_id:row.subject_family_id,object_family_id:row.object_family_id,relation_type:row.relation_type});}else{const row=diff.facts.left[i];changes.push({kind:"fact",fact_id:row.id});}});const result=await api(`/api/branches/${sourceId}/merge`,{method:"POST",body:{target_branch_id:targetId,changes,note:"merged from Studio branch compare"}});byId("compareDialog").close();await loadProjectData();toast(`Merged ${result.merged?.length||0} semantic change(s)`);});}

async function promoteChatForkToWorldBranch() {if(!state.activeSession?.parent_session_id)return toast("Fork the chat first");if(state.activeSession.world_fork_id)return toast("This chat fork already has a world branch");openForm({title:"Promote chat fork to world branch",eyebrow:"Separate conversation and canon branches",description:"The chat fork can stay exploratory, or receive its own semantic world branch now.",fields:[{name:"name",label:"Branch name",value:`What-if · ${state.activeSession.title}`,required:true,full:true}],onSubmit:async(values)=>{const branch=await api("/api/branches",{method:"POST",body:{world_id:state.activeWorld.id,name:values.name,parent_branch_id:state.activeBranch?.id||null,kind:"what_if",canon_status:"what_if",description:`Promoted from chat ${state.activeSession.id}`}});await api(`/api/sessions/${state.activeSession.id}`,{method:"PATCH",body:{branch_id:branch.id,world_fork_id:branch.id}});await selectScope(state.activeProject.id,state.activeWorld.id,branch.id);await openSession(state.activeSession.id);toast("Chat fork promoted to a world branch");}});}

function projectActions(event) {contextMenu(event.clientX,event.clientY,[{label:"Project context manifest",action:openProjectContextSheet},{label:"Story outline / scene cards",action:openStoryOutline},{label:"New project",action:openProjectForm},{label:"Link / switch world",action:()=>byId("worldSelect").focus()},{label:"New world / AU",action:()=>openQuickCreate("","world")},{label:"Edit project",action:editProject},{label:"Compare worlds",action:openWorldCompare},{label:`Continuity (${state.continuity?.warning_count||0})`,action:openContinuityReport},{label:"New context recipe",action:openContextRecipeForm},{label:"Delete project",danger:true,hidden:!state.activeProject,action:()=>deleteProject(state.activeProject)}]);}

function openContextRecipeForm(){openForm({title:"Custom context recipe",eyebrow:"Explainable context strategy",description:"Choose what Arline prioritizes for a specific writing workflow.",fields:[{name:"name",label:"Recipe name",required:true},{name:"description",label:"Description",type:"textarea",full:true},{name:"recipe",label:"Recipe policy (JSON)",type:"json",value:{active_scene:true,explicit_refs:true,pins:true,project_manifest:true,project_documents:true,project_overlays:true,relationships:true,recent_turns:5,world_canon:"relevant",timeline:false,conflicts:false},full:true}],onSubmit:async(values)=>{await api(`/api/projects/${state.activeProject.id}/context-recipes`,{method:"POST",body:values});await loadProjectData();}});}

function executeCommand(command){const input=byId("promptInput");if(command.action==="insert"){input.value=input.value.replace(/(?:^|\n)\/[\w-]*$/,command.text);input.focus();refreshPromptHighlight();}else if(command.action==="analyze")analyzePrompt();else if(command.action==="new-document")openDocumentForm();else if(command.action==="new-character")openQuickCreate("","entity");else if(command.action==="new-template")openTemplateForm();else if(command.action==="conflicts"){setView("world");state.activeWorldTab="canon";renderWorldGrid();}else if(command.action==="sandbox")createSandbox();else if(command.action==="snapshot")createSnapshot();else if(command.action==="world-picker")byId("worldSelect").focus();else if(command.action==="data")setView("data");else if(command.action==="inspector")openInspector();else if(command.action==="quick-create"){const raw=input.value.match(/\/new\s+(.+)$/m)?.[1]||"";openQuickCreate(raw); }else if(command.action==="scratch")toggleScratchMode();else if(command.action==="fork-chat"&&state.activeSession)forkSession(state.activeSession.id);else if(command.action==="context")openInspector("context");else if(command.action==="continuity")openContinuityReport();else if(command.action==="active-scene")openActiveSceneForm();else if(command.action==="import-manuscript")openManuscriptImport();else if(command.action==="activity")openActivityCenter();byId("commandDialog").close();}

async function searchCommands(query){const q=query.trim();let remote=[];if(q){try{const params=new URLSearchParams({q,...(state.activeProject?.id?{project_id:state.activeProject.id}:{})});remote=(await api(`/api/commands?${params}`)).results||[];}catch(_){}}const local=COMMANDS.filter((item)=>!q||item.label.toLowerCase().includes(q.toLowerCase())||item.description.toLowerCase().includes(q.toLowerCase()));state.commandResults=[...local.map((item)=>({...item,kind:"command"})),...remote.map((item)=>({...item,kind:item.type||"resource",action:"resource"})),...state.sessions.filter((item)=>!q||item.title.toLowerCase().includes(q.toLowerCase())).slice(0,8).map((item)=>({id:item.id,label:item.title,description:item.prompt_preview||"Chat",kind:"session",action:"session"}))];state.commandIndex=0;renderCommandResults();}

function addCanonFact(ownerType,ownerId,selectedText=""){openStagedChangeForm(state.activeTurn?.id||null,selectedText,{path:"",value:selectedText||"",confidence:1});}
function promoteStorySelection(turnId,story){openStagedChangeForm(turnId,window.getSelection()?.toString().trim()||story.slice(0,300));}

function retconFact(fact){openForm({title:"Retcon fact",eyebrow:"Impact preview",description:"Retcon preserves semantic history and previews downstream effects.",fields:[{name:"new_value",label:"New value (JSON or text)",type:"textarea",value:pretty(fact.value),full:true},{name:"note",label:"Reason",type:"textarea",full:true}],submit:"Preview impact",onSubmit:async(values)=>{let value;try{value=JSON.parse(values.new_value);}catch(_){value=values.new_value;}const payload={project_id:fact.project_id||state.bootstrap?.world_bible?.backing_project_id,world_id:fact.world_id||state.activeWorld.id,branch_id:fact.branch_id||null,owner_type:fact.owner_type,owner_id:fact.owner_id,path:fact.path,new_value:value,note:values.note};showRetconPreview(payload,await api("/api/retcon/preview",{method:"POST",body:payload}));}});}

async function deleteWorld(world){if(!world)return;if(world.id===state.bootstrap?.world_bible?.default_world_id)return toast("The shared World Bible Main world is protected");if(!confirm(`Delete world “${world.name}”?\n\nWorld-specific variants, relationships, facts, timeline and branches are removed. Project files and shared entity families remain.`))return;loading(true,"Deleting world…","Removing world-scoped state");try{await api(`/api/worlds/${world.id}`,{method:"DELETE"});closeSheet();state.activeSession=null;state.activeDocument=null;await loadWorkspaceBootstrap();if(state.activeProject)await selectScope(state.activeProject.id);toast(`Deleted world “${world.name}”`);}catch(error){toast(error.message,5000);}finally{loading(false);}}

function updateBreadcrumbs(){const project=state.activeProject?.name||"No project";const world=state.activeWorld?.name||"World Bible";const branch=state.activeBranch?.name||"Main";const buttons=$$("#breadcrumbs button");if(buttons[0])buttons[0].textContent=project;if(buttons[1])buttons[1].textContent=world;if(buttons[2])buttons[2].textContent=branch;const sandbox=["sandbox","what_if"].includes(state.activeBranch?.kind);byId("sandboxBadge").classList.toggle("hidden",!sandbox&&!state.scratchMode);byId("sandboxBadge").textContent=state.scratchMode?"Scratch":sandbox?"What-if":"Sandbox";byId("scopeStatus").innerHTML=`<span class="status-dot"></span><span>${escapeHTML(world)} · ${escapeHTML(branch)}</span>`;byId("worldTitle").textContent=world;byId("worldDescription").textContent=state.activeWorld?.description||"Shared World Bible: canonical entities, variants, relationships, timeline, and lore.";}

function setDocumentActiveScene(){if(!state.activeDocument)return toast("Open a project document first");openActiveSceneForm(state.activeDocument.id);}

async function generateStory(){const payload=promptPayload();if(!payload.prompt.trim())return toast("Write a prompt first");if(!payload.model)return toast("Select a model first");loading(true,payload.generation_mode==="beats"?"Writing story beats…":"Writing story…",state.scratchMode?"Scratch mode · canon staging disabled":"Compiling explainable context and calling LM Studio");try{const result=await api("/api/generate",{method:"POST",body:payload});state.activeRunId=result.run_id;state.activeSession={id:result.session_id,title:result.session_title,workspace_refs:payload.references,scratch_mode:result.scratch_mode};state.activeTurn={id:result.turn_id};state.scratchMode=Boolean(result.scratch_mode);loadContextResult(result);byId("postValidation").textContent=pretty(result.post_validation||{});byId("reasoningOutput").textContent=result.reasoning||"No separate reasoning output.";byId("statsOutput").textContent=pretty(result.stats||{});await Promise.all([loadSessions(),openSession(result.session_id),loadDatasetStats()]);byId("promptInput").value="";refreshPromptHighlight();updateBudgetUI();toast(`Generated ${result.run_id}${state.scratchMode?" · scratch":""}`);}catch(error){toast(`Generation failed: ${error.message}`,6000);}finally{loading(false);}}

function openWorldSheet(world) {
  byId("sheetEyebrow").textContent="World Bible · World";byId("sheetTitle").textContent=world.name;byId("sheetSubtitle").textContent=`${world.canon_status} · ${world.inheritance_mode}`;const lineage=world.lineage||[];
  byId("sheetBody").innerHTML=`<section class="sheet-section"><p>${escapeHTML(world.description||"No description")}</p><div class="sheet-grid"><div class="sheet-field"><span>Canon status</span><b>${escapeHTML(world.canon_status)}</b></div><div class="sheet-field"><span>Inheritance</span><b>${escapeHTML(world.inheritance_mode)}</b></div></div></section><section class="sheet-section"><div class="sheet-section-head"><h3>World lineage</h3></div><div class="variant-switcher">${lineage.map((x)=>`<button data-world-id="${x.id}">${escapeHTML(x.name)}</button>`).join(" → ")}</div></section><section class="sheet-section"><div class="sheet-section-head"><h3>Branches</h3></div>${(world.branches||[]).map((branch)=>`<div class="resource-inline-row"><button class="relationship-mini" data-branch-id="${branch.id}">${escapeHTML(branch.name)} · ${escapeHTML(branch.kind)} · ${escapeHTML(branch.canon_status)}</button>${branch.kind!=="main"?`<button class="tiny-danger-btn delete-branch" data-delete-branch-id="${branch.id}">Delete</button>`:`<span class="protected-note">protected</span>`}</div>`).join("")}</section><section class="sheet-section"><div class="sheet-section-head"><h3>Snapshots</h3></div>${state.snapshots.map((snap)=>`<div class="revision-item resource-inline-row"><div><b>${escapeHTML(snap.name)}</b><small>${formatDate(snap.created_at)}</small></div><div class="inline-actions"><button class="tiny-btn restore-snapshot" data-snapshot-id="${snap.id}">Restore</button><button class="tiny-danger-btn delete-snapshot" data-snapshot-id="${snap.id}">Delete</button></div></div>`).join("")||`<div class="empty-note">No snapshots.</div>`}</section>`;
  const protectedWorld=world.id===state.bootstrap?.world_bible?.default_world_id;byId("sheetFooter").innerHTML=`${protectedWorld?`<span class="protected-note">Shared Main world protected</span>`:`<button id="deleteWorldBtn" class="danger-text-btn">Delete world</button>`}<button id="worldBacklinksBtn" class="secondary-btn">Where used</button><button id="editWorldBtn" class="primary-btn">Edit world</button>`;
  byId("deleteWorldBtn")?.addEventListener("click",()=>deleteWorld(world));byId("worldBacklinksBtn").addEventListener("click",()=>openBacklinks("world",world.id,world.name));byId("editWorldBtn").addEventListener("click",()=>editWorld(world));$$('[data-world-id]',byId("sheetBody")).forEach((b)=>b.addEventListener("click",()=>selectScope(state.activeProject.id,b.dataset.worldId,null)));$$('[data-branch-id]',byId("sheetBody")).forEach((b)=>b.addEventListener("click",()=>selectScope(state.activeProject.id,world.id,b.dataset.branchId)));$$('.delete-branch',byId("sheetBody")).forEach((b)=>b.addEventListener("click",(e)=>{e.stopPropagation();const branch=(world.branches||[]).find((x)=>x.id===b.dataset.deleteBranchId);if(branch)deleteBranch(branch);}));$$('.restore-snapshot',byId("sheetBody")).forEach((b)=>b.addEventListener("click",()=>restoreSnapshot(b.dataset.snapshotId)));$$('.delete-snapshot',byId("sheetBody")).forEach((b)=>b.addEventListener("click",()=>deleteSnapshot(b.dataset.snapshotId)));openSheet();
}



// ---------------------------------------------------------------------------
// v1.1 foundation hardening: the UI below intentionally overrides a handful
// of earlier v1.1 functions.  Domain data stays structured underneath while
// navigation, context and creation remain simple on the surface.
// ---------------------------------------------------------------------------

function localPrefs() {
  try { return JSON.parse(localStorage.getItem("arline.ui.v1.1") || "{}"); }
  catch (_) { return {}; }
}

function saveLocalPrefs(patch = {}) {
  const next = { ...localPrefs(), ...patch };
  localStorage.setItem("arline.ui.v1.1", JSON.stringify(next));
  state.layoutPrefs = next;
  return next;
}

function restoreLayoutPrefs() {
  const prefs = localPrefs();
  state.layoutPrefs = prefs;
  document.body.classList.toggle("sidebar-collapsed", Boolean(prefs.sidebarCollapsed));
  document.body.dataset.density = prefs.density || "comfortable";
}

function navigationSnapshot() {
  return {
    view: state.activeView,
    project_id: state.activeProject?.id || null,
    world_id: state.activeWorld?.id || null,
    branch_id: state.activeBranch?.id || null,
    document_id: state.activeDocument?.id || null,
    session_id: state.activeSession?.id || null,
    world_tab: state.activeWorldTab,
    world_folder_id: state.activeWorldFolderId,
  };
}

function recordNavigation(snapshot = navigationSnapshot()) {
  if (state.suppressNavigationRecord) return;
  const last = state.navigationHistory[state.navigationIndex];
  if (last && JSON.stringify(last) === JSON.stringify(snapshot)) return;
  state.navigationHistory = state.navigationHistory.slice(0, state.navigationIndex + 1);
  state.navigationHistory.push(snapshot);
  if (state.navigationHistory.length > 80) state.navigationHistory.shift();
  state.navigationIndex = state.navigationHistory.length - 1;
  updateNavigationButtons();
}

function updateNavigationButtons() {
  const back = byId("navBackBtn"), forward = byId("navForwardBtn");
  if (back) back.disabled = state.navigationIndex <= 0;
  if (forward) forward.disabled = state.navigationIndex < 0 || state.navigationIndex >= state.navigationHistory.length - 1;
}

async function navigateHistory(delta) {
  const nextIndex = state.navigationIndex + delta;
  const target = state.navigationHistory[nextIndex];
  if (!target) return;
  state.suppressNavigationRecord = true;
  try {
    if (target.project_id && (state.activeProject?.id !== target.project_id || state.activeWorld?.id !== target.world_id || state.activeBranch?.id !== target.branch_id)) {
      await selectScope(target.project_id, target.world_id, target.branch_id, { record: false });
    }
    if (target.world_tab) state.activeWorldTab = target.world_tab;
    state.activeWorldFolderId = target.world_folder_id || null;
    setView(target.view || "home", { record: false });
    if (target.document_id) await openDocument(target.document_id);
    else if (target.session_id) await openSession(target.session_id);
    state.navigationIndex = nextIndex;
  } finally {
    state.suppressNavigationRecord = false;
    updateNavigationButtons();
  }
}

function setView(view, options = {}) {
  state.activeView = view;
  $$('[data-view]').forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  $$('[data-view-panel]').forEach((panel) => panel.classList.toggle("active", panel.dataset.viewPanel === view));
  if (view === "home") loadHome();
  if (view === "world") { renderWorldLibraryNavigation(); renderWorldGrid(); }
  if (view === "draft") renderDocuments();
  if (view === "data") loadFeedbackLab();
  if (options.record !== false) recordNavigation();
  saveLocalPrefs({ lastView: view });
}

let contextStackTimer = null;
function scheduleContextStackSync() {
  clearTimeout(contextStackTimer);
  contextStackTimer = setTimeout(syncContextStack, 120);
}

async function syncContextStack() {
  if (!state.activeProject) return;
  const payload = {
    project_id: state.activeProject?.id || null,
    world_id: state.activeWorld?.id || null,
    branch_id: state.activeBranch?.id || null,
    scene_document_id: state.activeScene?.document_id || null,
    session_id: state.activeSession?.id || null,
    recipe_id: byId("contextRecipeSelect")?.value || null,
    run_profile_id: state.activeRunProfileId || null,
    references: state.selectedReferences || [],
    overrides: { scratch_mode: Boolean(state.scratchMode) },
  };
  try { state.contextStack = await api("/api/context-stack", { method: "PUT", body: payload }); }
  catch (_) { state.contextStack = payload; }
  updateContextStackUI();
}

function updateContextStackUI() {
  const project = state.activeProject?.name || "No project";
  const world = state.activeWorld?.name || "World Bible";
  const branch = state.activeBranch?.name || "Main";
  const doc = state.activeScene?.document_id ? state.documents.find((item) => item.id === state.activeScene.document_id) : null;
  if (byId("contextStackProject")) byId("contextStackProject").textContent = project;
  if (byId("contextStackWorld")) byId("contextStackWorld").textContent = `${world} · ${branch}`;
  if (byId("contextStackScene")) byId("contextStackScene").textContent = doc ? `Scene · ${doc.title}` : (state.activeScene?.narrative_time || "No active scene");
  if (byId("contextScopeLabel")) byId("contextScopeLabel").textContent = `${state.selectedReferences.length} refs`;
  const count = (state.issues || []).filter((item) => item.status === "open").length + (state.stagedChanges || []).length;
  if (byId("activityCount")) byId("activityCount").textContent = String(count);
  updateComposerProfileSummary();
}

function openContextStackEditor() {
  if (!state.activeProject) return;
  const projectOptions = state.projects.map((p) => ({ value: p.id, label: p.name }));
  const worldOptions = state.worlds.map((w) => ({ value: w.id, label: `${w.name} · ${w.canon_status || "draft"}` }));
  const branchOptions = (state.activeWorld?.branches || []).map((b) => ({ value: b.id, label: `${b.name} · ${b.kind}` }));
  const recipeOptions = (state.contextRecipes || []).map((r) => ({ value: r.id, label: r.name }));
  const profileOptions = (state.runProfiles || []).map((r) => ({ value: r.id, label: r.name }));
  openForm({
    title: "AI Context Stack",
    eyebrow: "What Arline is using",
    description: "Navigation and AI context are separate. Opening a sheet does not automatically inject it into the model.",
    fields: [
      { name: "project_id", label: "Project workspace", type: "select", options: projectOptions, value: state.activeProject.id, full: true },
      { name: "world_id", label: "World", type: "select", options: worldOptions, value: state.activeWorld?.id || "" },
      { name: "branch_id", label: "Timeline / branch", type: "select", options: branchOptions, value: state.activeBranch?.id || "" },
      { name: "recipe_id", label: "Context recipe", type: "select", options: recipeOptions, value: byId("contextRecipeSelect")?.value || "" },
      { name: "run_profile_id", label: "Run profile", type: "select", options: profileOptions, value: state.activeRunProfileId || "" },
    ],
    submit: "Apply context",
    onSubmit: async (values) => {
      await selectScope(values.project_id, values.world_id || null, values.branch_id || null);
      if (values.recipe_id && byId("contextRecipeSelect")) byId("contextRecipeSelect").value = values.recipe_id;
      if (values.run_profile_id) applyRunProfile(values.run_profile_id);
      await syncContextStack();
    },
  });
}

function populateRunProfiles() {
  const select = byId("runProfileSelect");
  if (!select) return;
  const profiles = state.runProfiles || [];
  select.innerHTML = profiles.map((p) => `<option value="${escapeHTML(p.id)}">${escapeHTML(p.name)}</option>`).join("");
  const preferred = profiles.some((p) => p.id === state.activeRunProfileId) ? state.activeRunProfileId : (profiles[0]?.id || "");
  select.value = preferred;
  state.activeRunProfileId = preferred;
  updateComposerProfileSummary();
}

function applyRunProfile(profileId, { quiet = false } = {}) {
  const profile = (state.runProfiles || []).find((item) => item.id === profileId);
  if (!profile) return;
  state.activeRunProfileId = profileId;
  const data = profile.profile || {};
  if (data.context_recipe_id && byId("contextRecipeSelect")) byId("contextRecipeSelect").value = data.context_recipe_id;
  if (data.input_mode && byId("modeSelect")) byId("modeSelect").value = data.input_mode;
  if (data.reasoning && byId("reasoningSelect") && [...byId("reasoningSelect").options].some((o) => o.value === data.reasoning)) byId("reasoningSelect").value = data.reasoning;
  if (data.visible_output_tokens && byId("visibleTokens")) byId("visibleTokens").value = data.visible_output_tokens;
  if (data.temperature != null && byId("temperature")) byId("temperature").value = data.temperature;
  if (data.generation_mode && byId("generationMode")) byId("generationMode").value = data.generation_mode;
  syncDynamicLength({ preserveValue: true });
  syncRangeOutputs();
  updateBudgetUI();
  updateReasoningWarning();
  updateComposerProfileSummary();
  scheduleContextStackSync();
  if (!quiet) toast(`Run profile: ${profile.name}`);
}

function updateComposerProfileSummary() {
  const profile = (state.runProfiles || []).find((p) => p.id === state.activeRunProfileId);
  const model = state.modelMap.get(byId("modelSelect")?.value || "");
  const modelName = model?.display_name || byId("modelSelect")?.selectedOptions?.[0]?.textContent || "Choose model";
  const mode = byId("modeSelect")?.selectedOptions?.[0]?.textContent || "Smart Hybrid";
  const tokens = Number(byId("visibleTokens")?.value || 4096);
  const target = `${profile?.name || "Custom"} · ${formatTokenCount(tokens)}`;
  if (byId("composerProfileSummary")) byId("composerProfileSummary").textContent = `${modelName} · ${mode} · ${formatTokenCount(tokens)}`;
  if (byId("runProfileSelect") && profile) byId("runProfileSelect").value = profile.id;
  if (byId("lengthLabel")) byId("lengthLabel").textContent = target;
}

function openRunProfileForm() {
  const current = {
    context_recipe_id: byId("contextRecipeSelect")?.value || null,
    input_mode: byId("modeSelect")?.value || "smart_hybrid",
    reasoning: byId("reasoningSelect")?.value || "off",
    visible_output_tokens: Number(byId("visibleTokens")?.value || 4096),
    temperature: Number(byId("temperature")?.value || 0.8),
    generation_mode: byId("generationMode")?.value || "single",
    model: byId("modelSelect")?.value || "",
  };
  openForm({ title: "Save run profile", eyebrow: "Composer", description: "A profile packages model-facing controls so the composer can stay prompt-first.", fields: [
    { name: "name", label: "Profile name", required: true },
    { name: "description", label: "Description", type: "textarea", full: true },
  ], onSubmit: async (values) => {
    const saved = await api("/api/run-profiles", { method: "POST", body: { project_id: state.activeProject?.id || null, name: values.name, description: values.description || "", profile: current } });
    await loadRunProfiles(saved.id);
    toast(`Saved profile ${saved.name}`);
  }});
}

async function loadRunProfiles(selectId = null) {
  const result = await api(`/api/run-profiles?${new URLSearchParams(state.activeProject?.id ? { project_id: state.activeProject.id } : {})}`);
  state.runProfiles = result.profiles || [];
  if (selectId) state.activeRunProfileId = selectId;
  populateRunProfiles();
}

function updateBreadcrumbs() {
  const project = state.activeProject?.name || "No project";
  const world = state.activeWorld?.name || "World Bible";
  const branch = state.activeBranch?.name || "Main";
  const buttons = $$("#breadcrumbs button");
  if (buttons[0]) buttons[0].textContent = project;
  if (buttons[1]) buttons[1].textContent = world;
  if (buttons[2]) buttons[2].textContent = branch;
  const sandbox = ["sandbox", "what_if"].includes(state.activeBranch?.kind);
  byId("sandboxBadge")?.classList.toggle("hidden", !sandbox && !state.scratchMode);
  if (byId("sandboxBadge")) byId("sandboxBadge").textContent = state.scratchMode ? "Scratch" : sandbox ? "What-if" : "Sandbox";
  if (byId("scopeStatus")) byId("scopeStatus").innerHTML = `<span class="status-dot"></span><span>${escapeHTML(world)} · ${escapeHTML(branch)}</span>`;
  if (byId("worldTitle")) byId("worldTitle").textContent = world;
  if (byId("worldDescription")) byId("worldDescription").textContent = state.activeWorld?.description || "Shared World Bible: canonical entities, variants, relationships, timeline, and lore.";
  updateContextStackUI();
}

async function loadWorkspaceBootstrap() {
  const bootstrap = await api("/api/workspace/bootstrap");
  state.bootstrap = bootstrap;
  state.projects = bootstrap.projects || [];
  state.worlds = bootstrap.worlds || [];
  state.contextStack = bootstrap.context_stack || null;
  state.runProfiles = bootstrap.run_profiles || [];
  state.favorites = bootstrap.favorites || [];
  const saved = localPrefs();
  const active = bootstrap.active || {};
  const stackProject = state.projects.some((p)=>p.id===state.contextStack?.project_id) ? state.contextStack?.project_id : null;
  const stackWorld = state.worlds.some((w)=>w.id===state.contextStack?.world_id) ? state.contextStack?.world_id : null;
  const preferredProject = stackProject || active.project?.id || state.projects[0]?.id;
  if (preferredProject) {
    await selectScope(preferredProject, stackWorld || active.world?.id || bootstrap.world_bible?.default_world_id, state.contextStack?.branch_id || active.branch?.id || bootstrap.world_bible?.default_branch_id, { record: false });
    if (state.contextStack?.run_profile_id) state.activeRunProfileId = state.contextStack.run_profile_id;
    if (state.contextStack?.references?.length) state.selectedReferences = state.contextStack.references;
    populateRunProfiles();
    updateContextChipUI();
    setView(saved.lastView || "home", { record: false });
    recordNavigation();
    return;
  }
  state.activeProject = null;
  state.activeWorld = state.worlds[0] || null;
  state.activeBranch = state.activeWorld?.branches?.find((b) => b.kind === "main") || null;
  state.projectTree = { folders: [] };
  renderScopeSelectors(); updateBreadcrumbs(); renderProjectTree(); renderLibraryCounts(); renderTags(); renderDocuments(); renderSessions(); renderWorldGrid();
}

async function selectScope(projectId, worldId = null, branchId = null, options = {}) {
  if (!projectId) return;
  loading(true, "Opening workspace…", "Resolving project workspace and shared World Bible");
  try {
    const [project, projectList, bootstrap] = await Promise.all([
      api(`/api/projects/${encodeURIComponent(projectId)}`), api("/api/projects"), api("/api/workspace/bootstrap"),
    ]);
    state.activeProject = project;
    state.projects = projectList.projects || state.projects;
    state.worlds = bootstrap.worlds || state.worlds;
    state.bootstrap = { ...state.bootstrap, ...bootstrap };
    applyProjectDefaults(project);
    const linked = project.worlds || [];
    const preferredId = worldId || project.default_world_id || linked[0]?.id || bootstrap.world_bible?.default_world_id;
    const worldMeta = state.worlds.find((item) => item.id === preferredId) || linked.find((item) => item.id === preferredId) || state.worlds[0];
    state.activeWorld = worldMeta ? await api(`/api/worlds/${encodeURIComponent(worldMeta.id)}`) : null;
    if (state.activeWorld && !state.worlds.some((item) => item.id === state.activeWorld.id)) state.worlds.push(state.activeWorld);
    const branches = state.activeWorld?.branches || [];
    state.activeBranch = branches.find((item) => item.id === branchId) || branches.find((item) => item.kind === "main") || branches[0] || null;
    if (options.preserveReferences !== true) state.selectedReferences = [];
    renderScopeSelectors(); updateBreadcrumbs(); updateContextChipUI();
    await Promise.all([loadProjectData(), loadSessions(), loadRunProfiles()]);
    scheduleContextStackSync();
    if (options.record !== false) recordNavigation();
  } catch (error) { toast(`Workspace error: ${error.message}`, 6000); }
  finally { loading(false); }
}

async function loadProjectData() {
  if (!state.activeProject) return;
  const worldId = state.activeWorld?.id || "";
  const branchId = state.activeBranch?.id || "";
  const branchForFacts = state.activeBranch?.kind === "main" ? "" : branchId;
  const qTree = new URLSearchParams({ ...(worldId ? { world_id: worldId } : {}), ...(branchId ? { branch_id: branchId } : {}) });
  const qBible = new URLSearchParams({ ...(worldId ? { world_id: worldId } : {}), ...(branchId ? { branch_id: branchId } : {}), project_id: state.activeProject.id });
  const factQ = new URLSearchParams({ ...(worldId ? { world_id: worldId } : {}), ...(branchForFacts ? { branch_id: branchForFacts } : {}) });
  const stagedQ = new URLSearchParams({ ...(worldId ? { world_id: worldId } : {}), ...(branchForFacts ? { branch_id: branchForFacts } : {}) });
  const [tree, bible, facts, snapshots, staged, continuity] = await Promise.all([
    api(`/api/projects/${state.activeProject.id}/tree?${qTree}`),
    api(`/api/world-bible?${qBible}`),
    worldId ? api(`/api/facts?${factQ}`) : { facts: [] },
    worldId ? api(`/api/snapshots?world_id=${encodeURIComponent(worldId)}`) : { snapshots: [] },
    api(`/api/projects/${state.activeProject.id}/staged-changes?${stagedQ}`),
    api(`/api/projects/${state.activeProject.id}/continuity?${qTree}`),
  ]);
  state.projectTree = { ...tree, folders: tree.folder_tree || tree.folders || [] };
  state.worlds = bible.worlds || state.worlds;
  state.families = bible.families || [];
  state.variants = bible.variants || [];
  state.relationships = bible.relationships || [];
  state.timelineEvents = bible.timeline || [];
  state.contextRecipes = bible.recipes || [];
  state.worldBibleFolders = bible.folders || [];
  state.worldBibleFolderTree = bible.folder_tree || [];
  state.worldCollections = bible.collections || [];
  state.worldSavedViews = bible.saved_views || [];
  state.documents = tree.documents || [];
  state.tags = tree.tags || [];
  state.facts = facts.facts || [];
  state.snapshots = snapshots.snapshots || [];
  state.templates = tree.templates || [];
  state.conflicts = tree.conflicts || [];
  state.manifestRefs = tree.manifest_refs || [];
  state.activeScene = tree.active_scene || null;
  state.sceneCards = tree.scene_cards || [];
  state.overlays = tree.overlays || [];
  state.stagedChanges = staged.changes || [];
  state.continuity = continuity || null;
  state.activity = tree.activity || [];
  state.issues = tree.issues || [];
  state.favorites = tree.favorites || state.favorites;
  state.runProfiles = tree.run_profiles || state.runProfiles;
  populateContextRecipes(); populateRunProfiles();
  renderScopeSelectors(); renderProjectTree(); renderLibraryCounts(); renderTags(); renderDocuments(); renderWorldLibraryNavigation(); renderWorldGrid(); updateScopeVisualization(); updateActiveSceneUI(); updateContextStackUI(); refreshPromptHighlight();
}

function renderProjectTree() {
  const root = byId("projectTree");
  if (!root) return;
  root.innerHTML = "";
  const documentsByFolder = new Map();
  for (const doc of state.documents) {
    const key = doc.folder_id || "root";
    if (!documentsByFolder.has(key)) documentsByFolder.set(key, []);
    documentsByFolder.get(key).push(doc);
  }
  const appendDocuments = (container, folderId, depth) => {
    for (const doc of documentsByFolder.get(folderId || "root") || []) container.appendChild(documentTreeNode(doc, depth));
  };
  const appendFolder = (container, folder, depth = 0) => {
    const wrapper = document.createElement("div"); wrapper.className = "tree-folder-group";
    const row = document.createElement("div"); row.className = "tree-node"; row.style.paddingLeft = `${depth * 13}px`;
    row.innerHTML = `<button class="tree-toggle">⌄</button><span class="tree-icon">▱</span><button class="tree-main">${escapeHTML(folder.name)}</button><button class="row-menu">•••</button>`;
    const children = document.createElement("div"); children.className = "tree-children";
    wrapper.append(row, children); container.appendChild(wrapper);
    $(".tree-toggle", row).addEventListener("click", () => { children.classList.toggle("hidden"); $(".tree-toggle", row).textContent = children.classList.contains("hidden") ? "›" : "⌄"; });
    $(".tree-main", row).addEventListener("click", () => { setView("draft"); filterDocumentsByFolder(folder.id); });
    $(".row-menu", row).addEventListener("click", (event) => contextMenu(event.clientX, event.clientY, [
      { label: "New document here", action: () => openDocumentForm(folder.id) }, { label: "New subfolder", action: () => openFolderForm(folder.id) },
      { label: "Rename", action: () => renameFolder(folder) }, { label: "Move to Trash", danger: true, action: () => trashResource("folder", folder.id, folder.name) },
    ]));
    appendDocuments(children, folder.id, depth + 1);
    for (const child of folder.children || []) appendFolder(children, child, depth + 1);
  };
  appendDocuments(root, null, 0);
  for (const folder of state.projectTree?.folders || []) appendFolder(root, folder, 0);
  byId("projectTreeEmpty")?.classList.toggle("hidden", root.children.length > 0);
}

function renderWorldLibraryNavigation() {
  const tree = byId("worldFolderTree");
  const collections = byId("worldCollections");
  const views = byId("worldSavedViews");
  if (!tree || !collections || !views) return;
  const folderHTML = (items, depth = 0) => items.map((folder) => `<div class="world-library-tree-group"><button class="world-library-nav ${state.activeWorldFolderId === folder.id ? "active" : ""}" data-world-folder="${escapeHTML(folder.id)}" style="--depth:${depth}"><span>▱</span><b>${escapeHTML(folder.name)}</b></button>${folder.children?.length ? folderHTML(folder.children, depth + 1) : ""}</div>`).join("");
  tree.innerHTML = folderHTML(state.worldBibleFolderTree || []);
  collections.innerHTML = (state.worldCollections || []).map((item) => `<button class="world-library-nav ${state.activeCollectionId === item.id ? "active" : ""}" data-collection="${escapeHTML(item.id)}"><span>${escapeHTML(item.icon || "◇")}</span><b>${escapeHTML(item.name)}</b><em>${item.links?.length || 0}</em></button>`).join("") || `<div class="empty-note">Collections can group sheets without moving them.</div>`;
  views.innerHTML = (state.worldSavedViews || []).map((item) => `<button class="world-library-nav ${state.activeSavedViewId === item.id ? "active" : ""}" data-saved-view="${escapeHTML(item.id)}"><span>⌁</span><b>${escapeHTML(item.name)}</b></button>`).join("");
  byId("worldAllFolderBtn")?.classList.toggle("active", !state.activeWorldFolderId && !state.activeCollectionId && !state.activeSavedViewId);
  $$('[data-world-folder]', tree).forEach((button) => button.addEventListener("click", () => { state.activeWorldFolderId = button.dataset.worldFolder; state.activeCollectionId = null; state.activeSavedViewId = null; renderWorldLibraryNavigation(); renderWorldGrid(); recordNavigation(); }));
  $$('[data-collection]', collections).forEach((button) => button.addEventListener("click", () => { state.activeCollectionId = button.dataset.collection; state.activeWorldFolderId = null; state.activeSavedViewId = null; renderWorldLibraryNavigation(); renderWorldGrid(); }));
  $$('[data-saved-view]', views).forEach((button) => button.addEventListener("click", () => applySavedWorldView(button.dataset.savedView)));
}

function descendantWorldFolderIds(folderId) {
  if (!folderId) return new Set();
  const result = new Set([folderId]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const folder of state.worldBibleFolders || []) if (folder.parent_id && result.has(folder.parent_id) && !result.has(folder.id)) { result.add(folder.id); changed = true; }
  }
  return result;
}

function filteredWorldFamilies() {
  let families = [...(state.families || [])];
  if (state.activeWorldFolderId) {
    const ids = descendantWorldFolderIds(state.activeWorldFolderId);
    families = families.filter((f) => ids.has(f.folder_id));
  }
  if (state.activeCollectionId) {
    const coll = state.worldCollections.find((item) => item.id === state.activeCollectionId);
    const allowed = new Set((coll?.links || []).filter((l) => l.resource_type === "entity_family").map((l) => l.resource_id));
    families = families.filter((f) => allowed.has(f.id));
  }
  const view = state.worldSavedViews.find((item) => item.id === state.activeSavedViewId);
  if (view) {
    if (view.resource_type && view.resource_type !== "all") {
      const types = view.resource_type === "lore" ? ["lore", "world_rule"] : [view.resource_type];
      families = families.filter((f) => types.includes(f.entity_type));
    }
    if (view.query?.description_empty) families = families.filter((f) => !(f.description || "").trim());
    if (view.query?.sort === "updated_at") families.sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")));
  }
  return families;
}

function applySavedWorldView(viewId) {
  const view = state.worldSavedViews.find((item) => item.id === viewId);
  if (!view) return;
  state.activeSavedViewId = viewId; state.activeWorldFolderId = null; state.activeCollectionId = null;
  const type = view.resource_type;
  if (["character", "location", "item", "organization", "lore"].includes(type)) state.activeWorldTab = type;
  $$('[data-world-tab]').forEach((tab) => tab.classList.toggle("active", tab.dataset.worldTab === state.activeWorldTab));
  renderWorldLibraryNavigation(); renderWorldGrid();
}

function openWorldFolderForm(parentId = null) {
  openForm({ title: "New World Bible folder", eyebrow: "Organization only", description: "Folders organize sheets but never make them project-owned.", fields: [{ name: "name", label: "Folder name", required: true }], onSubmit: async (values) => {
    await api("/api/folders", { method: "POST", body: { project_id: state.bootstrap.world_bible.backing_project_id, parent_id: parentId, name: values.name, kind: "world_bible" } });
    await loadProjectData();
  }});
}

function openCollectionForm() {
  openForm({ title: "New collection", eyebrow: "World Bible", description: "A collection groups references without moving their folders.", fields: [
    { name: "name", label: "Name", required: true }, { name: "icon", label: "Icon", value: "◇" }, { name: "description", label: "Description", type: "textarea", full: true },
  ], onSubmit: async (values) => { await api("/api/collections", { method: "POST", body: { ...values, scope_type: "world_bible" } }); await loadProjectData(); }});
}

function openSavedViewForm() {
  const resourceType = ["character", "location", "item", "organization", "lore"].includes(state.activeWorldTab) ? state.activeWorldTab : "all";
  openForm({ title: "Save World Bible view", eyebrow: "Reusable filter", fields: [
    { name: "name", label: "View name", required: true },
    { name: "resource_type", label: "Entity type", type: "select", value: resourceType, options: ["all","character","location","item","organization","lore"].map((x) => ({ value:x,label:x })) },
  ], onSubmit: async (values) => { await api("/api/saved-views", { method:"POST", body:{ ...values, scope_type:"world_bible", query:{} } }); await loadProjectData(); }});
}

function renderWorldGrid() {
  if (state.activeView !== "world") return;
  const tab = state.activeWorldTab;
  let cards = [];
  if (["character", "location", "item", "organization", "lore"].includes(tab)) {
    const types = tab === "lore" ? ["lore", "world_rule"] : [tab];
    cards = filteredWorldFamilies().filter((family) => types.includes(family.entity_type)).map((family) => {
      const variant = state.variants.find((v) => v.family_id === family.id && (v.branch_id === state.activeBranch?.id || v.branch_id == null));
      return { type: "entity", family, variant, label: variant?.display_name || family.name, summary: variant?.summary || family.description, status: variant?.canon_status || "no variant" };
    });
  } else if (tab === "relationship") cards = state.relationships.map((rel) => ({ type: "relationship", id: rel.id, label: `${rel.subject_name} ↔ ${rel.object_name}`, summary: rel.relation_type, status: rel.canon_status }));
  else if (tab === "canon") cards = [
    ...state.conflicts.map((conflict) => ({ type:"conflict", id:conflict.id, label:`Conflict: ${conflict.path}`, summary:`${JSON.stringify(conflict.left)} ↔ ${JSON.stringify(conflict.right)}`, status:"open", conflict })),
    ...state.facts.map((fact) => ({ type:"fact", id:fact.id, label:fact.path, summary:JSON.stringify(fact.value), status:fact.status, fact })),
  ];
  else if (tab === "timeline") cards = (state.timelineEvents || []).map((event) => ({ type:"timeline", id:event.id, label:event.time_label || event.summary, summary:event.summary, status:event.status || "canon", event }));
  else if (tab === "worlds") cards = state.worlds.map((world) => ({ type:"world", id:world.id, label:world.name, summary:world.description, status:world.canon_status, world }));
  const search = byId("worldSearch")?.value.trim().toLowerCase();
  if (search) cards = cards.filter((card) => `${card.label} ${card.summary}`.toLowerCase().includes(search));
  byId("worldGrid").innerHTML = cards.map(worldCardHTML).join("");
  byId("worldEmpty")?.classList.toggle("hidden", cards.length > 0);
  $$(".world-card").forEach((card) => {
    const index = Number(card.dataset.index), item = cards[index];
    card.addEventListener("click", async () => {
      if (item.type === "entity") openEntitySheet(item.family.id, item.variant?.id);
      else if (item.type === "relationship") openRelationshipSheet(item.id);
      else if (item.type === "world") openWorldSheet(await api(`/api/worlds/${item.id}`));
      else if (item.type === "fact") openFactSheet(item.fact);
      else if (item.type === "conflict") openConflictSheet(item.conflict);
      else if (item.type === "timeline") showCompare(item.label, item.event);
    });
    card.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      const resourceType = item.type === "entity" ? "entity_family" : item.type;
      const resourceId = item.type === "entity" ? item.family.id : item.id;
      contextMenu(event.clientX, event.clientY, [
        { label:"Open universal inspector", action:()=>openResourceInspector(resourceType, resourceId) },
        { label:"Pin / favorite", action:()=>favoriteResource(resourceType, resourceId, item.label) },
        { label:"Add to collection…", hidden:item.type!=="entity", action:()=>addResourceToCollection(resourceType, resourceId) },
        { label:"Move to Trash", danger:true, hidden:["world","timeline","conflict"].includes(item.type), action:()=>trashResource(resourceType, resourceId, item.label) },
      ]);
    });
  });
}

async function addResourceToCollection(resourceType, resourceId) {
  if (!state.worldCollections.length) return openCollectionForm();
  openForm({ title:"Add to collection", eyebrow:"World Bible", fields:[{ name:"collection_id", label:"Collection", type:"select", options:state.worldCollections.map((c)=>({value:c.id,label:c.name})), full:true }], onSubmit:async(values)=>{ await api(`/api/collections/${values.collection_id}/links`,{method:"POST",body:{resource_type:resourceType,resource_id:resourceId}}); await loadProjectData(); }});
}

async function favoriteResource(resourceType, resourceId, label = "") {
  await api("/api/favorites", { method:"POST", body:{ project_id:state.activeProject?.id||null,resource_type:resourceType,resource_id:resourceId,label } });
  const result = await api(`/api/favorites?${new URLSearchParams(state.activeProject?.id?{project_id:state.activeProject.id}:{})}`);
  state.favorites = result.favorites || [];
  renderHome();
  toast("Pinned to workspace");
}

let lastUndo = null;
async function trashResource(resourceType, resourceId, label = "resource") {
  if (!confirm(`Move “${label}” to Trash? You can restore it later.`)) return;
  try {
    await api("/api/lifecycle/trash", { method:"POST", body:{resource_type:resourceType,resource_id:resourceId} });
    lastUndo = { type:"restore", resourceType, resourceId, label };
    state.selectedReferences = (state.selectedReferences || []).filter((ref) => !(ref.type === resourceType && ref.id === resourceId));
    updateContextChipUI(); scheduleContextStackSync();
    await loadProjectData();
    closeSheet();
    toast(`Moved “${label}” to Trash · Ctrl+Z to undo`, 5000);
  } catch (error) { toast(error.message, 5000); }
}

async function undoLastAction() {
  if (!lastUndo) return;
  const action = lastUndo; lastUndo = null;
  if (action.type === "restore") {
    await api("/api/lifecycle/restore", { method:"POST", body:{resource_type:action.resourceType,resource_id:action.resourceId} });
    if (action.resourceType === "project" || action.resourceType === "world" || action.resourceType === "branch") await loadWorkspaceBootstrap();
    else if (action.resourceType === "session") await loadSessions();
    else await loadProjectData();
    toast(`Restored “${action.label}”`);
  }
}

async function deleteDocument(doc) { return trashResource("document", doc.id, doc.title); }
async function deleteEntityFamily(family) { return trashResource("entity_family", family.id, family.name); }
async function deleteVariant(variant, family) { return trashResource("entity_variant", variant.id, `${family?.name || variant.display_name} variant`); }
async function deleteRelationship(rel) { return trashResource("relationship", rel.id, `${rel.subject_name || "Relationship"} ↔ ${rel.object_name || ""}`); }
async function deleteFact(fact) { return trashResource("fact", fact.id, fact.path); }

async function openResourceInspector(resourceType, resourceId) {
  try {
    const result = await api(`/api/resources/${encodeURIComponent(resourceType)}/${encodeURIComponent(resourceId)}`);
    const resource = result.resource || {};
    const title = resource.name || resource.display_name || resource.title || resource.id || resourceId;
    byId("sheetEyebrow").textContent = `${resourceType.replaceAll("_", " ")} · Inspector`;
    byId("sheetTitle").textContent = title;
    byId("sheetSubtitle").textContent = "Overview · Properties · References · History · Advanced";
    const lifecycle = result.lifecycle || {};
    const backlinkLinks = result.backlinks?.links || [];
    byId("sheetBody").innerHTML = `
      <section class="sheet-section"><div class="sheet-section-head"><h3>Overview</h3><span>${lifecycle.archived_at?"Archived":"Active"}</span></div><pre class="json-block universal-overview">${escapeHTML(pretty(resource))}</pre></section>
      <section class="sheet-section"><div class="sheet-section-head"><h3>Identity</h3><button id="addAliasBtn" class="tiny-btn">＋ Alias</button></div>${(result.aliases||[]).map((a)=>`<div class="resource-inline-row"><b>${escapeHTML(a.alias)}</b><button class="tiny-danger-btn inspector-alias-delete" data-id="${a.id}">×</button></div>`).join("")||`<div class="empty-note">No aliases. Add nicknames or alternate names for @ reference resolution.</div>`}</section>
      <section class="sheet-section"><div class="sheet-section-head"><h3>References</h3><span>${backlinkLinks.length}</span></div>${backlinkLinks.slice(0,30).map((link)=>`<div class="backlink-row"><b>${escapeHTML(link.kind||"reference")}</b><small>${escapeHTML(link.path||link.summary||link.resource_id||"")}</small></div>`).join("")||`<div class="empty-note">No backlinks yet.</div>`}</section>
      <section class="sheet-section"><div class="sheet-section-head"><h3>Organization</h3></div><p>${(result.collections||[]).map((c)=>`<span class="tag-chip">${escapeHTML(c.name)}</span>`).join(" ")||"No collections"}</p></section>`;
    byId("sheetFooter").innerHTML = `<button id="inspectorFavoriteBtn" class="secondary-btn">Pin</button><button id="inspectorArchiveBtn" class="secondary-btn">${lifecycle.archived_at?"Unarchive":"Archive"}</button><button id="inspectorTrashBtn" class="danger-text-btn">Trash</button>`;
    byId("addAliasBtn").addEventListener("click",()=>openForm({title:`Alias · ${title}`,eyebrow:"Identity resolver",fields:[{name:"alias",label:"Alias",required:true,full:true}],onSubmit:async(values)=>{await api("/api/aliases",{method:"POST",body:{resource_type:resourceType,resource_id:resourceId,alias:values.alias}});await openResourceInspector(resourceType,resourceId);}}));
    $$('.inspector-alias-delete',byId("sheetBody")).forEach((b)=>b.addEventListener("click",async()=>{await api(`/api/aliases/${b.dataset.id}`,{method:"DELETE"});await openResourceInspector(resourceType,resourceId);}));
    byId("inspectorFavoriteBtn").addEventListener("click",()=>favoriteResource(resourceType,resourceId,title));
    byId("inspectorArchiveBtn").addEventListener("click",async()=>{await api(`/api/lifecycle/archive?archived=${lifecycle.archived_at?"false":"true"}`,{method:"POST",body:{resource_type:resourceType,resource_id:resourceId}});await loadProjectData();closeSheet();});
    byId("inspectorTrashBtn").addEventListener("click",()=>trashResource(resourceType,resourceId,title));
    openSheet();
  } catch (error) { toast(error.message, 5000); }
}

async function openActivityCenter() {
  const params = new URLSearchParams(state.activeProject?.id ? { project_id: state.activeProject.id } : {});
  const [activity, issues, trash] = await Promise.all([api(`/api/activity?${params}`), api(`/api/issues?${params}`), api("/api/trash")]);
  state.activity = activity.activity || []; state.issues = issues.issues || [];
  byId("sheetEyebrow").textContent = "Workspace"; byId("sheetTitle").textContent = "Activity Center"; byId("sheetSubtitle").textContent = "Issues, recent changes, and recoverable trash";
  byId("sheetBody").innerHTML = `<section class="sheet-section"><div class="sheet-section-head"><h3>Needs attention</h3><span>${state.issues.length}</span></div>${state.issues.map((i)=>`<article class="continuity-warning ${escapeHTML(i.severity)}"><b>${escapeHTML(i.title)}</b><p>${escapeHTML(i.description||i.issue_type)}</p><button class="tiny-btn issue-resolve" data-id="${i.id}">Resolve</button></article>`).join("")||`<div class="empty-note">Nothing unresolved.</div>`}</section>
  <section class="sheet-section"><div class="sheet-section-head"><h3>Trash</h3><span>${trash.items?.length||0}</span></div>${(trash.items||[]).map((x)=>`<div class="resource-inline-row"><div><b>${escapeHTML(x.resource?.name||x.resource?.title||x.resource?.display_name||x.resource_id)}</b><small>${escapeHTML(x.resource_type)} · ${formatDate(x.trashed_at)}</small></div><div class="inline-actions"><button class="tiny-btn trash-restore" data-type="${x.resource_type}" data-id="${x.resource_id}">Restore</button><button class="tiny-danger-btn trash-permanent" data-type="${x.resource_type}" data-id="${x.resource_id}">Delete forever</button></div></div>`).join("")||`<div class="empty-note">Trash is empty.</div>`}</section>
  <section class="sheet-section"><div class="sheet-section-head"><h3>Recent activity</h3></div>${state.activity.map((a)=>`<div class="backlink-row"><b>${escapeHTML(a.event_type.replaceAll("_"," "))}</b><small>${escapeHTML(a.label||a.resource_type||"")} · ${formatRelative(a.created_at)}</small></div>`).join("")||`<div class="empty-note">No activity recorded yet.</div>`}</section>`;
  byId("sheetFooter").innerHTML = `<button id="densityToggleBtn" class="secondary-btn">Density: ${escapeHTML(state.layoutPrefs.density||"comfortable")}</button>`;
  $$('.issue-resolve',byId("sheetBody")).forEach((b)=>b.addEventListener("click",async()=>{await api(`/api/issues/${b.dataset.id}/resolve`,{method:"POST"});await openActivityCenter();}));
  $$('.trash-restore',byId("sheetBody")).forEach((b)=>b.addEventListener("click",async()=>{await api("/api/lifecycle/restore",{method:"POST",body:{resource_type:b.dataset.type,resource_id:b.dataset.id}});await loadProjectData();await openActivityCenter();}));
  $$('.trash-permanent',byId("sheetBody")).forEach((b)=>b.addEventListener("click",async()=>{if(!confirm("Permanently delete this resource? This cannot be undone."))return;await api(`/api/trash/${b.dataset.type}/${b.dataset.id}`,{method:"DELETE"});await loadProjectData();await openActivityCenter();}));
  byId("densityToggleBtn").addEventListener("click",()=>{const density=document.body.dataset.density==="compact"?"comfortable":"compact";document.body.dataset.density=density;saveLocalPrefs({density});byId("densityToggleBtn").textContent=`Density: ${density}`;});
  updateContextStackUI(); openSheet();
}

function openDocumentForm(folderId = null, type = "scene") {
  const docTypes = ["scene","chapter","note","research","outline"];
  openForm({ title:"New manuscript item", eyebrow:"Project workspace", description:"Project files belong to what you are making; World Bible sheets stay shared.", fields:[
    {name:"title",label:"Title",required:true,full:true},
    {name:"document_type",label:"Type",type:"select",options:docTypes.map((x)=>({value:x,label:x[0].toUpperCase()+x.slice(1)})),value:docTypes.includes(type)?type:"scene"},
    {name:"status",label:"Writing status",type:"select",options:["planned","writing","revising","final"].map((x)=>({value:x,label:x[0].toUpperCase()+x.slice(1)})),value:"planned"},
    {name:"content",label:"Initial content",type:"textarea",full:true},
  ], onSubmit:async(values)=>{const doc=await api("/api/documents",{method:"POST",body:{project_id:state.activeProject.id,folder_id:folderId,...values}});await loadProjectData();await openDocument(doc.id);}});
}

async function saveDraft(note = "checkpoint") {
  if (!state.activeDocument) return toast("Select or create a manuscript item first");
  const payload = { title:byId("draftTitle").value||"Untitled", content:byId("draftEditor").value, status:byId("draftStatus").value, note };
  const doc = await api(`/api/documents/${state.activeDocument.id}`, { method:"PATCH", body:payload });
  state.activeDocument = { ...state.activeDocument, ...doc };
  clearDraftRecovery(state.activeDocument.id);
  byId("draftSaveStatus").textContent = note.startsWith("autosave") ? "Saved automatically" : "Checkpoint created";
  await loadProjectData();
}

function scheduleDraftAutosave() {
  if (!state.activeDocument) return;
  storeDraftRecovery();
  byId("draftStats").textContent = `${wordCount(byId("draftEditor").value)} words`;
  byId("draftSaveStatus").textContent = "Saving…";
  clearTimeout(state.draftTimer);
  state.draftTimer = setTimeout(async()=>{try{await saveDraft("autosave recovery");}catch(error){byId("draftSaveStatus").textContent=`Save failed · ${error.message}`;}},650);
}

function renderDocuments(filter = null) {
  const activeFilter = filter || $(".document-filters button.active")?.dataset.docFilter || "all";
  const list = byId("documentList"); if (!list) return;
  list.innerHTML = "";
  const bindDoc = (button, doc) => {
    button.addEventListener("click",()=>openDocument(doc.id));
    button.addEventListener("contextmenu",(event)=>{event.preventDefault();contextMenu(event.clientX,event.clientY,[
      {label:"Open inspector",action:()=>openResourceInspector("document",doc.id)},
      {label:"Pin",action:()=>favoriteResource("document",doc.id,doc.title)},
      {label:"Move to Trash",danger:true,action:()=>trashResource("document",doc.id,doc.title)},
    ]);});
  };
  const appendDoc = (host, doc, depth = 0) => {
    const button=document.createElement("button"); button.className=`document-item ${state.activeDocument?.id===doc.id?"active":""}`; button.dataset.docId=doc.id; button.style.setProperty("--binder-depth",depth);
    button.innerHTML=`<b>${escapeHTML(doc.title)}</b><span>${escapeHTML(doc.document_type)} · ${escapeHTML(({draft:"writing",provisional:"revising",canon:"final"}[doc.status]||doc.status||"planned"))} · ${formatRelative(doc.updated_at)}</span>`;
    host.appendChild(button); bindDoc(button,doc);
  };
  if (activeFilter === "all") {
    const docsByFolder=new Map();
    for(const doc of state.documents){const key=doc.folder_id||"root";if(!docsByFolder.has(key))docsByFolder.set(key,[]);docsByFolder.get(key).push(doc);}
    for(const doc of docsByFolder.get("root")||[]) appendDoc(list,doc,0);
    const appendFolder=(host,folder,depth=0)=>{
      const group=document.createElement("div");group.className="binder-folder-group";
      const head=document.createElement("button");head.className="binder-folder";head.style.setProperty("--binder-depth",depth);head.innerHTML=`<span>⌄</span><b>${escapeHTML(folder.name)}</b><em>${(docsByFolder.get(folder.id)||[]).length}</em>`;
      const body=document.createElement("div");body.className="binder-folder-body";group.append(head,body);host.appendChild(group);
      for(const doc of docsByFolder.get(folder.id)||[])appendDoc(body,doc,depth+1);
      for(const child of folder.children||[])appendFolder(body,child,depth+1);
      head.addEventListener("click",()=>{body.classList.toggle("hidden");head.querySelector("span").textContent=body.classList.contains("hidden")?"›":"⌄";});
      head.addEventListener("contextmenu",(event)=>{event.preventDefault();contextMenu(event.clientX,event.clientY,[{label:"New document here",action:()=>openDocumentForm(folder.id)},{label:"New subfolder",action:()=>openFolderForm(folder.id)},{label:"Rename",action:()=>renameFolder(folder)},{label:"Move folder to Trash",danger:true,action:()=>trashResource("folder",folder.id,folder.name)}]);});
    };
    for(const folder of state.projectTree?.folders||[])appendFolder(list,folder,0);
  } else {
    for(const doc of state.documents.filter((doc)=>doc.document_type===activeFilter))appendDoc(list,doc,0);
  }
  const visibleDocs=activeFilter==="all"?state.documents:state.documents.filter((doc)=>doc.document_type===activeFilter);
  byId("documentEmpty")?.classList.toggle("hidden", visibleDocs.length > 0 || (activeFilter==="all" && (state.projectTree?.folders||[]).length>0));
}

async function loadHome() {
  if (!state.activeProject) return;
  try {
    state.homeData = await api(`/api/home?${new URLSearchParams({project_id:state.activeProject.id,...(state.activeWorld?.id?{world_id:state.activeWorld.id}:{}),...(state.activeBranch?.id?{branch_id:state.activeBranch.id}:{})})}`);
    renderHome();
  } catch (error) { toast(error.message,4000); }
}

function renderHome() {
  if (!byId("homeContinue")) return;
  const data = state.homeData || {};
  byId("homeProjectTitle").textContent = state.activeProject?.name || "Arline Studio";
  const scene = data.active_scene || state.activeScene;
  const sceneDoc = scene?.document_id ? state.documents.find((d)=>d.id===scene.document_id) : null;
  byId("homeContinue").innerHTML = scene ? `<button class="home-action-row" data-home-doc="${escapeHTML(scene.document_id||"")}"><span>◎</span><div><b>${escapeHTML(sceneDoc?.title||"Active scene")}</b><small>${escapeHTML(scene.narrative_time||"Narrative cursor")}</small></div><em>Continue →</em></button>` : `<div class="empty-note">No active scene. Set one from Manuscript when you want scene-aware context.</div>`;
  const feedback = data.feedback || {};
  byId("homeAttention").innerHTML = `<button class="home-action-row" data-home-view="data"><span>◫</span><div><b>${feedback.unreviewed||0} responses to review</b><small>Feedback Lab</small></div><em>Open →</em></button><button class="home-action-row" data-home-activity="1"><span>◌</span><div><b>${(data.issues||[]).length} unresolved issues</b><small>${state.stagedChanges.length} canon changes staged</small></div><em>Inspect →</em></button>`;
  const recentDocs = data.recent_documents || [], recentChats = data.recent_chats || [];
  byId("homeRecent").innerHTML = [...recentDocs.slice(0,4).map((d)=>`<button class="home-action-row" data-home-doc="${d.id}"><span>▤</span><div><b>${escapeHTML(d.title)}</b><small>${escapeHTML(d.document_type)} · ${formatRelative(d.updated_at)}</small></div></button>`),...recentChats.slice(0,4).map((c)=>`<button class="home-action-row" data-home-chat="${c.id}"><span>◉</span><div><b>${escapeHTML(c.title)}</b><small>${formatRelative(c.updated_at)}</small></div></button>`)].join("")||`<div class="empty-note">Start a chat or create your first scene.</div>`;
  const favorites = data.favorites || state.favorites || [];
  byId("homeFavorites").innerHTML = favorites.map((f)=>`<button class="home-action-row" data-home-resource="${escapeHTML(f.resource_type)}:${escapeHTML(f.resource_id)}"><span>★</span><div><b>${escapeHTML(f.label||f.resource_id)}</b><small>${escapeHTML(f.resource_type.replaceAll("_"," "))}</small></div></button>`).join("")||`<div class="empty-note">Pin frequently used sheets, scenes, or worlds here.</div>`;
  $$('[data-home-view]',byId("homeView")).forEach((b)=>b.addEventListener("click",()=>setView(b.dataset.homeView)));
  $$('[data-home-doc]',byId("homeView")).forEach((b)=>b.addEventListener("click",()=>b.dataset.homeDoc&&openDocument(b.dataset.homeDoc)));
  $$('[data-home-chat]',byId("homeView")).forEach((b)=>b.addEventListener("click",()=>openSession(b.dataset.homeChat)));
  $$('[data-home-activity]',byId("homeView")).forEach((b)=>b.addEventListener("click",openActivityCenter));
  $$('[data-home-resource]',byId("homeView")).forEach((b)=>b.addEventListener("click",()=>{const [type,...rest]=b.dataset.homeResource.split(":");openResourceInspector(type,rest.join(":"));}));
}

async function loadDatasetStats() {
  try {
    const stats = await api("/api/dataset/stats");
    const metrics = [
      ["To review", stats.unreviewed || 0], ["Accepted", (stats.accepted||0)+(stats.edited_accept||0)], ["SFT ready", stats.sft_ready||0], ["Comparisons", state.feedbackComparisons.length||0],
    ];
    if (byId("datasetCards")) byId("datasetCards").innerHTML = metrics.map(([label,value])=>`<div class="metric-card"><span>${escapeHTML(label)}</span><strong>${Number(value).toLocaleString()}</strong></div>`).join("");
    if (byId("datasetMiniCount")) byId("datasetMiniCount").textContent = `${stats.unreviewed||0} to review`;
    return stats;
  } catch (_) { return {}; }
}

async function loadFeedbackLab() {
  if (!state.activeProject) return;
  const projectId = state.activeProject.id;
  try {
    const [stats, comparisons] = await Promise.all([loadDatasetStats(), api(`/api/feedback/comparisons?${new URLSearchParams({project_id:projectId,limit:"100"})}`)]);
    state.feedbackComparisons = comparisons.items || [];
    await loadDatasetStats();
    if (state.feedbackTab === "queue") state.feedbackQueue = (await api(`/api/feedback/queue?${new URLSearchParams({project_id:projectId,status:"unreviewed",limit:"100"})}`)).items || [];
    else if (state.feedbackTab === "reviewed") {
      const groups = await Promise.all(["accepted","edited_accept","rejected"].map((status)=>api(`/api/feedback/queue?${new URLSearchParams({project_id:projectId,status,limit:"60"})}`)));
      state.feedbackQueue = groups.flatMap((x)=>x.items||[]).sort((a,b)=>String(b.updated_at).localeCompare(String(a.updated_at)));
    }
    renderFeedbackLab();
  } catch (error) { toast(error.message,5000); }
}

function renderFeedbackLab() {
  const host = byId("feedbackQueue"); if (!host) return;
  $$('[data-feedback-tab]').forEach((b)=>b.classList.toggle("active",b.dataset.feedbackTab===state.feedbackTab));
  if (state.feedbackTab === "comparisons") {
    host.innerHTML = state.feedbackComparisons.map((opp,idx)=>`<article class="feedback-card"><div class="feedback-card-head"><div><span class="eyebrow">Fork comparison</span><b>${escapeHTML((opp.prompt||"").slice(0,120)||"Continuation")}</b></div><span>${opp.candidates.length} candidates</span></div><div class="comparison-grid">${opp.candidates.slice(0,3).map((c,i)=>`<section><small>${escapeHTML(c.label)}</small><p>${escapeHTML((c.story||"").slice(0,1000))}</p><button class="tiny-btn choose-preference" data-opp="${idx}" data-candidate="${i}">Prefer this</button></section>`).join("")}</div></article>`).join("");
  } else {
    host.innerHTML = state.feedbackQueue.map((turn)=>`<article class="feedback-card"><div class="feedback-card-head"><div><span class="eyebrow">${escapeHTML(turn.session_title||"Chat")}</span><b>${escapeHTML((turn.user_prompt||"").slice(0,160))}</b></div><span>${escapeHTML(turn.feedback_status)}</span></div><div class="feedback-prose">${storyHTML((turn.story||"").slice(0,2200))}</div><div class="feedback-actions"><button class="tiny-btn feedback-accept" data-id="${turn.id}">Accept</button><button class="tiny-btn feedback-edit" data-id="${turn.id}">Edit & accept</button><button class="tiny-danger-btn feedback-reject" data-id="${turn.id}">Reject</button><button class="tiny-btn feedback-open-chat" data-session="${turn.session_id}">Open chat</button></div></article>`).join("");
  }
  byId("feedbackQueueEmpty")?.classList.toggle("hidden", host.children.length > 0);
  $$('.feedback-accept',host).forEach((b)=>b.addEventListener("click",()=>openFeedback(b.dataset.id,"accepted")));
  $$('.feedback-edit',host).forEach((b)=>{const t=state.feedbackQueue.find((x)=>x.id===b.dataset.id);b.addEventListener("click",()=>openFeedback(b.dataset.id,"edited_accept",t?.story||""));});
  $$('.feedback-reject',host).forEach((b)=>b.addEventListener("click",()=>openFeedback(b.dataset.id,"rejected")));
  $$('.feedback-open-chat',host).forEach((b)=>b.addEventListener("click",()=>openSession(b.dataset.session)));
  $$('.choose-preference',host).forEach((b)=>b.addEventListener("click",()=>choosePreference(Number(b.dataset.opp),Number(b.dataset.candidate))));
}

async function choosePreference(opportunityIndex, candidateIndex) {
  const opp = state.feedbackComparisons[opportunityIndex]; if (!opp) return;
  const chosen = opp.candidates[candidateIndex];
  await Promise.all(opp.candidates.map((candidate,i)=>api(`/api/turns/${candidate.turn_id}/feedback`,{method:"POST",body:{status:i===candidateIndex?"accepted":"rejected",issues:[],note:`Preference comparison · chosen ${chosen.label}`,edited_story:""}})));
  toast(`Preference recorded: ${chosen.label}`); await loadFeedbackLab();
}

async function submitFeedback(event) {
  event.preventDefault();
  if (event.submitter?.value === "cancel") return byId("feedbackDialog").close();
  const issues = $$("#issueGrid input:checked").map((input)=>input.value);
  const payload = { status: state.feedbackMode, issues, note: byId("feedbackNote").value, edited_story: state.feedbackMode === "edited_accept" ? byId("editedStory").value : "" };
  try { await api(`/api/turns/${state.feedbackTurnId}/feedback`,{method:"POST",body:payload});byId("feedbackDialog").close();await Promise.all([loadDatasetStats(),loadSessions(),loadFeedbackLab()]);if(state.activeSession)await openSession(state.activeSession.id);toast("Feedback saved"); }
  catch(error){toast(error.message,5000);}
}

async function searchCommands(query) {
  const q = query.trim(); let remote = [];
  if (q) {
    try { const params=new URLSearchParams({q,...(state.activeProject?.id?{project_id:state.activeProject.id}:{}),...(state.activeWorld?.id?{world_id:state.activeWorld.id}:{}),...(state.activeBranch?.id?{branch_id:state.activeBranch.id}:{})});remote=(await api(`/api/search?${params}`)).results||[]; } catch (_) {}
  }
  const local = COMMANDS.filter((item)=>!q||item.label.toLowerCase().includes(q.toLowerCase())||item.description.toLowerCase().includes(q.toLowerCase()));
  state.commandResults = [...local.map((item)=>({...item,kind:"command"})),...remote.map((item)=>({...item,kind:item.type||"resource",action:item.type==="session"?"session":"resource"}))];
  state.commandIndex=0;renderCommandResults();
}

async function chooseCommand(index) {
  const item=state.commandResults[index];if(!item)return;
  if(item.action==="session"){byId("commandDialog").close();return openSession(item.id);}
  if(item.action==="resource"){
    byId("commandDialog").close();
    if(item.type==="entity_family"||item.type==="entity_variant")return openEntitySheet(item.family_id||item.id,item.type==="entity_variant"?item.id:null);
    if(item.type==="document")return openDocument(item.id);
    if(item.type==="relationship")return openRelationshipSheet(item.id);
    if(item.type==="world")return selectScope(state.activeProject.id,item.id,null);
    if(item.type==="fact")return openResourceInspector("fact",item.id);
    if(item.type==="folder"){setView("draft");return filterDocumentsByFolder(item.id);}
    return openResourceInspector(item.type,item.id);
  }
  await executeCommand(item);
}

async function submitQuickCreate(event) {
  event.preventDefault(); if(event.submitter?.value==="cancel")return byId("quickCreateDialog").close();
  const text=byId("quickCreateInput").value.trim();if(!text)return toast("Describe what you want to create");
  const preview=state.quickCreatePreview||{};
  if((preview.kind||byId("quickCreateKind").value)==="entity"){
    const duplicate=state.families.find((f)=>f.name.trim().toLowerCase()===(preview.name||text).trim().toLowerCase());
    if(duplicate && confirm(`“${duplicate.name}” already exists. Open and reference the existing sheet instead of duplicating it?`)){byId("quickCreateDialog").close();await openEntitySheet(duplicate.id);return;}
  }
  try{
    const result=await api("/api/quick-create",{method:"POST",body:{text,forced_kind:byId("quickCreateKind").value||null,project_id:state.activeProject?.id||null,world_id:state.activeWorld?.id||null,branch_id:state.activeBranch?.id||null,folder_id:preview.kind==="entity"?state.activeWorldFolderId:null}});
    byId("quickCreateDialog").close();
    if(result.kind==="project")await loadWorkspaceBootstrap();else if(result.kind==="world"){await loadWorkspaceBootstrap();if(state.activeProject)await selectScope(state.activeProject.id,result.resource.id);}else{await loadProjectData();if(result.kind==="entity"&&result.resource?.id)await openEntitySheet(result.resource.id,result.variant?.id);}
    toast(`Created ${result.kind}: ${result.resource?.name||result.resource?.title||preview.name||"resource"}`);
  }catch(error){toast(error.message,5000);}
}

function downloadJSONFile(data, filename) {
  const blob=new Blob([JSON.stringify(data,null,2)],{type:"application/json"});
  const url=URL.createObjectURL(blob);const a=document.createElement("a");a.href=url;a.download=filename;document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),500);
}

async function exportProjectBundle() {
  if(!state.activeProject)return;
  try{const data=await api(`/api/export/project/${encodeURIComponent(state.activeProject.id)}`);downloadJSONFile(data,`${(state.activeProject.slug||state.activeProject.name||"project").replace(/[^a-z0-9_-]+/gi,"-")}.arline-project.json`);toast("Project bundle exported");}catch(error){toast(error.message,5000);}
}
async function exportWorldBibleBundle() {
  try{const q=new URLSearchParams({...(state.activeWorld?.id?{world_id:state.activeWorld.id}:{}),...(state.activeBranch?.kind!=="main"&&state.activeBranch?.id?{branch_id:state.activeBranch.id}:{})});const data=await api(`/api/export/world-bible?${q}`);downloadJSONFile(data,`${(state.activeWorld?.name||"world-bible").replace(/[^a-z0-9_-]+/gi,"-")}.arline-world.json`);toast("World Bible bundle exported");}catch(error){toast(error.message,5000);}
}

function openManuscriptImport() {
  if(!state.activeProject)return toast("Open a project first");
  const folders=flattenFolders(state.projectTree?.folders||[]);
  openForm({title:"Import manuscript text",eyebrow:"Project · Import Center",description:"Markdown # headings become chapters and ##/### headings become scenes. Import never creates World Bible canon automatically.",fields:[
    {name:"title",label:"Fallback title",value:"Imported manuscript",required:true},
    {name:"folder_id",label:"Project folder",type:"select",options:[{value:"",label:"No folder"},...folders.map((f)=>({value:f.id,label:f.path}))],value:""},
    {name:"split_headings",label:"Split Markdown headings",type:"checkbox",value:true},
    {name:"text",label:"Text / Markdown",type:"textarea",rows:14,required:true,full:true},
  ],submit:"Preview & import",onSubmit:async(values)=>{
    const payload={project_id:state.activeProject.id,title:values.title,text:values.text,folder_id:values.folder_id||null,split_headings:Boolean(values.split_headings),default_type:"scene"};
    const preview=await api("/api/import/manuscript/preview",{method:"POST",body:payload});
    const sample=(preview.sections||[]).slice(0,8).map((x)=>`• ${x.title} · ${x.document_type} · ${x.words} words`).join("\n");
    if(!confirm(`Import ${preview.count} manuscript item${preview.count===1?"":"s"}?\n\n${sample}${preview.count>8?"\n…":""}`))return;
    const result=await api("/api/import/manuscript",{method:"POST",body:payload});
    await loadProjectData();if(result.documents?.[0])await openDocument(result.documents[0].id);toast(`Imported ${result.documents?.length||0} manuscript items`);
  }});
}

function projectActions(event) {
  contextMenu(event.clientX,event.clientY,[
    {label:"AI Context Stack",action:openContextStackEditor},{label:"Project context manifest",action:openProjectContextSheet},{label:"Story outline / scene cards",action:openStoryOutline},
    {label:"Import manuscript…",action:openManuscriptImport},{label:"Export project bundle",action:exportProjectBundle},{label:"Export current World Bible",action:exportWorldBibleBundle},
    {label:"New project",action:openProjectForm},{label:"New world / AU",action:()=>openQuickCreate("","world")},{label:"Edit project",action:editProject},
    {label:"Continuity & issues",action:openActivityCenter},{label:"New context recipe",action:openContextRecipeForm},{label:"Save run profile",action:openRunProfileForm},
    {label:"Delete project",danger:true,hidden:!state.activeProject,action:()=>deleteProject(state.activeProject)},
  ]);
}


// Lifecycle-aware destructive actions. Normal UI delete means recoverable Trash;
// permanent deletion lives exclusively in Activity Center → Trash.
async function deleteSession(id) {
  const session = state.sessions.find((item) => item.id === id) || state.activeSession;
  if (!id || !confirm(`Move chat “${session?.title || "Untitled chat"}” to Trash?`)) return;
  try {
    await api("/api/lifecycle/trash", { method:"POST", body:{resource_type:"session",resource_id:id} });
    lastUndo = { type:"restore", resourceType:"session", resourceId:id, label:session?.title || "chat" };
    if (state.activeSession?.id === id) {
      state.activeSession = null; state.activeTurn = null; state.forkGraph = null;
      byId("conversationSection")?.classList.add("hidden"); byId("chatLanding")?.classList.remove("hidden");
    }
    await loadSessions(); scheduleContextStackSync(); toast("Chat moved to Trash · Ctrl+Z to undo",5000);
  } catch (error) { toast(error.message,5000); }
}

async function deleteProject(project) {
  if (!project || !confirm(`Move project “${project.name}” to Trash?\n\nWorld Bible sheets are shared and will not be deleted.`)) return;
  try {
    await api("/api/lifecycle/trash", { method:"POST", body:{resource_type:"project",resource_id:project.id} });
    lastUndo = { type:"restore", resourceType:"project", resourceId:project.id, label:project.name };
    state.activeDocument = null; state.activeSession = null;
    await loadWorkspaceBootstrap(); setView("home",{record:false}); recordNavigation();
    toast(`Project “${project.name}” moved to Trash`,5000);
  } catch (error) { toast(error.message,5000); }
}

async function deleteWorld(world) {
  if (!world) return;
  if (world.id === state.bootstrap?.world_bible?.default_world_id) return toast("The shared World Bible Main world is protected");
  if (!confirm(`Move world “${world.name}” to Trash?\n\nProject manuscript files and shared entity families remain.`)) return;
  try {
    await api("/api/lifecycle/trash", { method:"POST", body:{resource_type:"world",resource_id:world.id} });
    lastUndo = { type:"restore", resourceType:"world", resourceId:world.id, label:world.name };
    closeSheet(); state.activeSession = null;
    await loadWorkspaceBootstrap();
    if (state.activeProject) await selectScope(state.activeProject.id,null,null,{record:false});
    toast(`World “${world.name}” moved to Trash`,5000);
  } catch (error) { toast(error.message,5000); }
}

async function deleteBranch(branch) {
  if (!branch) return;
  if (branch.kind === "main" || branch.id === state.bootstrap?.world_bible?.default_branch_id) return toast("Main timeline is protected. Trash the world instead.");
  if (!confirm(`Move branch “${branch.name}” to Trash?`)) return;
  try {
    await api("/api/lifecycle/trash", { method:"POST", body:{resource_type:"branch",resource_id:branch.id} });
    lastUndo = { type:"restore", resourceType:"branch", resourceId:branch.id, label:branch.name };
    closeSheet();
    if (state.activeWorld) await selectScope(state.activeProject.id,state.activeWorld.id,null,{record:false});
    toast(`Branch “${branch.name}” moved to Trash`,5000);
  } catch (error) { toast(error.message,5000); }
}


function attachEvents() {
  const on = (id, event, handler, options) => byId(id)?.addEventListener(event, handler, options);
  document.addEventListener("pointerdown", (event) => {
    if (!event.target.closest(".context-menu")) closeContextMenu();
    if (!event.target.closest(".reference-peek") && !event.target.closest(".reference-preview-chip") && !event.target.closest(".context-peek")) scheduleHideReferencePeek();
  });

  on("collapseSidebarBtn", "click", () => {
    document.body.classList.toggle("sidebar-collapsed");
    saveLocalPrefs({ sidebarCollapsed: document.body.classList.contains("sidebar-collapsed") });
  });
  on("mobileSidebarBtn", "click", () => { byId("workspaceSidebar")?.classList.add("mobile-open"); byId("sidebarScrim")?.classList.remove("hidden"); });
  on("sidebarScrim", "click", () => { byId("workspaceSidebar")?.classList.remove("mobile-open"); byId("sidebarScrim")?.classList.add("hidden"); });
  on("navBackBtn", "click", () => navigateHistory(-1));
  on("navForwardBtn", "click", () => navigateHistory(1));
  on("activityBtn", "click", openActivityCenter);
  on("contextStackEditBtn", "click", openContextStackEditor);
  on("contextStackSummary", "click", openContextStackEditor);

  on("newChatBtn", "click", newChat);
  on("deleteActiveChatBtn", "click", () => state.activeSession && deleteSession(state.activeSession.id));
  on("scratchToggleBtn", "click", toggleScratchMode);
  on("forkCurrentChatBtn", "click", () => state.activeSession ? forkSession(state.activeSession.id) : toast("Open a chat first"));
  on("forkCurrentChatBtn", "contextmenu", (event) => {
    event.preventDefault();
    contextMenu(event.clientX, event.clientY, [
      { label: "Fork latest turn", action: () => state.activeSession && forkSession(state.activeSession.id) },
      { label: "Promote current chat fork to world branch", hidden: !state.activeSession?.parent_session_id || Boolean(state.activeSession?.world_fork_id), action: promoteChatForkToWorldBranch },
    ]);
  });
  on("commandBtn", "click", () => openCommandPalette());
  on("projectMenuBtn", "click", projectActions);
  $$('[data-view]').forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
  $$('[data-library]').forEach((button) => button.addEventListener("click", () => {
    const type = button.dataset.library;
    setView("world");
    state.activeWorldTab = type === "relationship" ? "relationship" : type === "timeline" ? "timeline" : type;
    $$('[data-world-tab]').forEach((tab) => tab.classList.toggle("active", tab.dataset.worldTab === state.activeWorldTab));
    renderWorldGrid();
  }));

  // Legacy selectors remain hidden for compatibility, but Context Stack is the user-facing scope controller.
  on("projectSelect", "change", () => selectScope(byId("projectSelect").value));
  on("worldSelect", "change", () => state.activeProject && selectScope(state.activeProject.id, byId("worldSelect").value));
  on("branchSelect", "change", () => state.activeProject && state.activeWorld && selectScope(state.activeProject.id, state.activeWorld.id, byId("branchSelect").value));

  on("homeQuickCreateBtn", "click", () => openQuickCreate());
  on("manuscriptEmptyCreateBtn", "click", () => openDocumentForm());
  on("worldEmptyCreateBtn", "click", () => openQuickCreate("", "entity"));
  on("newLibraryBtn", "click", () => openQuickCreate("", ["character","location","item","organization","lore"].includes(state.activeWorldTab) ? "entity" : state.activeWorldTab === "worlds" ? "world" : ""));
  on("newFolderBtn", "click", () => openFolderForm());
  on("newWorldFolderBtn", "click", () => openWorldFolderForm());
  on("newCollectionBtn", "click", openCollectionForm);
  on("newSavedViewBtn", "click", openSavedViewForm);
  on("worldAllFolderBtn", "click", () => {
    state.activeWorldFolderId = null; state.activeCollectionId = null; state.activeSavedViewId = null;
    renderWorldLibraryNavigation(); renderWorldGrid(); recordNavigation();
  });
  on("newTagBtn", "click", openTagForm);
  on("datasetFooterBtn", "click", () => setView("data"));
  on("openDataBtn", "click", () => setView("data"));

  on("settingsBtn", "click", () => openInspector("runtime"));
  on("openInspectorBtn", "click", () => openInspector());
  on("closeInspectorBtn", "click", closeInspector);
  on("inspectorScrim", "click", closeInspector);
  on("closeSheetBtn", "click", closeSheet);
  on("sheetScrim", "click", closeSheet);
  $$('[data-inspector-tab]').forEach((button) => button.addEventListener("click", () => activateInspectorTab(button.dataset.inspectorTab)));
  $$('[data-subtab]').forEach((button) => button.addEventListener("click", () => {
    const group = button.closest(".inspector-panel");
    $$('[data-subtab]', group).forEach((x) => x.classList.toggle("active", x === button));
    $$('[data-subpanel]', group).forEach((x) => x.classList.toggle("active", x.dataset.subpanel === button.dataset.subtab));
  }));

  on("modelSelect", "change", () => { updateModelInfo(); updateComposerProfileSummary(); scheduleContextStackSync(); });
  on("contextRecipeSelect", "change", () => { updateScopeVisualization(); updateBudgetUI(); updateComposerProfileSummary(); scheduleContextStackSync(); });
  on("modeSelect", "change", () => { updateReasoningWarning(); updateBudgetUI(); updateComposerProfileSummary(); });
  on("reasoningSelect", "change", () => { updateReasoningWarning(); updateBudgetUI(); updateComposerProfileSummary(); });
  on("runProfileSelect", "change", (event) => applyRunProfile(event.target.value));
  on("composerProfileBtn", "click", () => byId("composerAdvanced")?.classList.toggle("hidden"));
  on("saveRunProfileBtn", "click", openRunProfileForm);
  on("composerAddContextBtn", "click", () => {
    const input = byId("promptInput"); if (!input) return;
    const start = input.selectionStart ?? input.value.length;
    input.setRangeText("@", start, input.selectionEnd ?? start, "end");
    input.focus(); updateAutocomplete(); refreshPromptHighlight();
  });
  on("composerAttachBtn", "click", () => openQuickCreate());

  on("lengthSlider", "input", () => { syncLengthSlider(); updateComposerProfileSummary(); });
  on("generationMode", "change", () => { updateBudgetUI(); updateComposerProfileSummary(); });
  ["gpuRatio","temperature","topP","minP","repeatPenalty"].forEach((id) => on(id, "input", () => { syncRangeOutputs(); updateBudgetUI(); }));
  ["visibleTokens","reasoningReserve","contextLength","beatCount","beatTokens","totalStoryTokens"].forEach((id) => on(id, "input", () => { if (id === "visibleTokens") syncDynamicLength(); updateBudgetUI(); updateComposerProfileSummary(); }));
  on("refreshModelsBtn", "click", refreshModels); on("saveSettingsBtn", "click", saveSettings); on("reloadModelBtn", "click", reloadModel);
  on("analyzeBtn", "click", analyzePrompt); on("generateBtn", "click", generateStory);
  on("promptInput", "input", () => { updateAutocomplete(); refreshPromptHighlight(); updateBudgetUI(); });
  on("promptInput", "scroll", () => { if (byId("promptHighlight")) { byId("promptHighlight").scrollTop = byId("promptInput").scrollTop; byId("promptHighlight").scrollLeft = byId("promptInput").scrollLeft; } });
  on("promptInput", "keydown", handleComposerKey);
  on("traceSelect", "change", loadTrace);
  on("contextScopeBtn", "click", openContextStackEditor);
  on("composerBudgetButton", "click", () => openInspector("context"));

  on("newDocumentBtn", "click", () => openDocumentForm());
  on("saveDraftBtn", "click", () => saveDraft("checkpoint"));
  on("deleteDraftBtn", "click", () => state.activeDocument && deleteDocument(state.activeDocument));
  on("setActiveSceneBtn", "click", setDocumentActiveScene);
  on("newDependencyBtn", "click", openSceneDependencyForm);
  on("draftEditor", "input", scheduleDraftAutosave);
  on("draftTitle", "input", scheduleDraftAutosave);
  on("draftReferenceBtn", "click", () => { if (state.activeDocument) addReference({ type: "document", id: state.activeDocument.id, label: state.activeDocument.title }); });
  $$(".document-filters button").forEach((button) => button.addEventListener("click", () => { $$(".document-filters button").forEach((x) => x.classList.toggle("active", x === button)); renderDocuments(button.dataset.docFilter); }));

  $$('[data-world-tab]').forEach((button) => button.addEventListener("click", () => {
    state.activeWorldTab = button.dataset.worldTab;
    $$('[data-world-tab]').forEach((x) => x.classList.toggle("active", x === button));
    state.activeSavedViewId = null; renderWorldLibraryNavigation(); renderWorldGrid(); recordNavigation();
  }));
  on("worldSearch", "input", renderWorldGrid);
  on("newEntityBtn", "click", openWorldActionsForTab);
  on("compareWorldBtn", "click", openWorldCompare);
  on("compareBranchBtn", "click", openBranchCompare);
  on("continuityBtn", "click", openContinuityReport);
  on("snapshotBtn", "click", createSnapshot);
  on("sandboxBtn", "click", createSandbox);

  $$('[data-feedback-tab]').forEach((button) => button.addEventListener("click", () => {
    state.feedbackTab = button.dataset.feedbackTab;
    loadFeedbackLab();
  }));
  on("feedbackAdvancedToggle", "click", () => byId("feedbackAdvanced")?.classList.toggle("hidden"));
  $$('[data-export]').forEach((button) => button.addEventListener("click", () => exportDataset(button.dataset.export)));

  on("formDialog", "submit", submitForm);
  $$('#formDialog button[value="cancel"]').forEach((button) => button.addEventListener("click", (event) => { event.preventDefault(); byId("formDialog").close(); }));
  on("quickCreateForm", "submit", submitQuickCreate);
  on("quickCreateInput", "input", scheduleQuickCreatePreview);
  on("quickCreateKind", "change", scheduleQuickCreatePreview);
  on("quickCreateAdvancedBtn", "click", quickCreateAdvanced);
  on("feedbackDialog", "submit", submitFeedback);
  on("closeCompareBtn", "click", () => byId("compareDialog").close());
  on("commandSearch", "input", (event) => searchCommands(event.target.value));
  on("commandSearch", "keydown", commandKey);
  on("saveContractBtn", "click", saveContract);

  document.addEventListener("keydown", (event) => {
    const key = event.key.toLowerCase();
    const mod = event.metaKey || event.ctrlKey;
    const target = event.target;
    const editing = target && (target.matches?.("input,textarea,select") || target.isContentEditable);
    if (mod && key === "k") { event.preventDefault(); openCommandPalette(); return; }
    if (mod && event.shiftKey && key === "p") { event.preventDefault(); openCommandPalette(">"); return; }
    if (mod && key === "n") { event.preventDefault(); if (event.shiftKey) newChat(); else openQuickCreate(); return; }
    if (mod && event.shiftKey && key === "i") { event.preventDefault(); openInspector(); return; }
    if (mod && key === "s" && state.activeView === "draft") { event.preventDefault(); if (state.activeDocument) saveDraft("checkpoint"); else toast("Open a manuscript document first"); return; }
    if (mod && key === "z" && !editing && lastUndo) { event.preventDefault(); undoLastAction(); return; }
    if (event.altKey && event.key === "ArrowLeft") { event.preventDefault(); navigateHistory(-1); return; }
    if (event.altKey && event.key === "ArrowRight") { event.preventDefault(); navigateHistory(1); return; }
    if (event.key === "Escape") { hideAutocomplete(); closeContextMenu(); scheduleHideReferencePeek(); }
  });

  refreshPromptHighlight(); updateScratchUI(); updateNavigationButtons();
}

async function init() {
  restoreLayoutPrefs();
  attachEvents();
  loading(true, "Starting Arline Studio…", "Loading configuration, workspace, and UI foundation");
  try {
    const [config, contract] = await Promise.all([api("/api/config"), api("/api/contract")]);
    applyConfig(config);
    if (byId("contractEditor")) byId("contractEditor").value = contract.content || "";
    await Promise.all([refreshModels(), loadWorkspaceBootstrap(), loadDatasetStats()]);
    const preferred = localPrefs().lastView || "home";
    setView(preferred, { record: false });
    if (preferred === "home") await loadHome();
    updateNavigationButtons(); updateContextStackUI();
  } catch (error) { toast(`Startup failed: ${error.message}`, 7000); }
  finally { loading(false); }
}

init();
