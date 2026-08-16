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
  world: "◎", command: "/", session: "◉",
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
  { id: "dataset", label: "Open dataset", description: "Review feedback and exports", action: "data" },
  { id: "inspector", label: "Open developer inspector", description: "Inspect WCF, trace, validator, and runtime", action: "inspector" },
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
  await selectScope(active.project?.id || state.projects[0]?.id, active.world?.id, active.branch?.id);
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
    { label: "Move to folder", action: () => moveDocument(doc) },
    { label: "Delete", danger: true, action: () => deleteDocument(doc) },
  ]));
  return row;
}

function renderTags() {
  const section = byId("tagSection");
  section.classList.toggle("hidden", state.tags.length === 0);
  byId("tagList").innerHTML = state.tags.map((tag) => `<button class="tag-chip" style="--tag-color:${escapeHTML(tag.color)}" data-tag="${escapeHTML(tag.name)}">#${escapeHTML(tag.name)}</button>`).join("");
  $$("#tagList .tag-chip").forEach((button) => button.addEventListener("click", () => loadSessions(button.dataset.tag)));
  byId("worldTagFilters").innerHTML = state.tags.map((tag) => `<button class="tag-chip" style="--tag-color:${escapeHTML(tag.color)}" data-tag-id="${tag.id}">#${escapeHTML(tag.name)}</button>`).join("");
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
        { label: "Move to folder", action: () => moveSession(session) },
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
  if (!state.selectedReferences.some((item) => item.type === ref.type && item.id === ref.id)) state.selectedReferences.push(ref);
  updateContextChipUI();
  updateScopeVisualization();
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
    { label: `Resolve conflicts (${state.conflicts.length})`, action: () => { setView("world"); state.activeWorldTab = "canon"; renderWorldGrid(); } },
  ]);
}

function openProjectForm() {
  openForm({ title: "New project", eyebrow: "Workspace", description: "A project contains worlds, branches, identity families, chats, drafts, canon, and dataset lineage.", fields: [
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
  if (!confirm(`Delete folder “${folder.name}”? Nested folders are deleted; documents become unfiled if allowed by database rules.`)) return;
  await api(`/api/folders/${folder.id}`, { method: "DELETE" });
  await loadProjectData();
}

function openDocumentForm(folderId = null, type = "scene") {
  openForm({ title: "New document", eyebrow: "Draft", fields: [
    { name: "title", label: "Title", required: true },
    { name: "document_type", label: "Type", type: "select", options: (state.bootstrap?.document_types || ["draft", "scene", "lore", "note", "outline"]).map((x) => ({ value: x, label: x })), value: type },
    { name: "status", label: "Status", type: "select", options: [{ value: "draft", label: "draft" }, { value: "provisional", label: "provisional" }, { value: "canon", label: "canon" }], value: "draft" },
    { name: "content", label: "Initial content", type: "textarea", full: true },
  ], onSubmit: async (values) => { const doc = await api("/api/documents", { method: "POST", body: { project_id: state.activeProject.id, world_id: state.activeWorld?.id, branch_id: state.activeBranch?.id, folder_id: folderId, ...values } }); await loadProjectData(); await openDocument(doc.id); } });
}

async function openDocument(id) {
  const [doc, dependencies] = await Promise.all([
    api(`/api/documents/${id}`),
    api(`/api/scenes/${id}/dependencies`).catch(() => ({valid:true,dependencies:[]})),
  ]);
  state.activeDocument = doc;
  state.sceneDependencies = dependencies.dependencies || [];
  byId("draftTitle").value = doc.title;
  byId("draftEditor").value = doc.content || "";
  byId("draftStatus").value = doc.status || "draft";
  byId("draftSaveStatus").textContent = `Saved ${formatRelative(doc.updated_at)} ago`;
  byId("draftStats").textContent = `${wordCount(doc.content)} words`;
  renderDocuments();
  renderRevisions(doc.revisions || []);
  renderSceneDependencies(dependencies);
  setView("draft");
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
  byId("sheetFooter").innerHTML = `<button id="pinEntityBtn" class="secondary-btn">Pin context</button><button id="tagEntityBtn" class="secondary-btn">Tags</button><button id="compareVariantBtn" class="secondary-btn">Compare variants</button><button id="newVariantBtn" class="secondary-btn">＋ Variant</button>${variant ? `<button id="editVariantBtn" class="primary-btn">Edit current variant</button>` : ""}`;
  $$("[data-variant-id]", byId("sheetBody")).forEach((button) => button.addEventListener("click", () => openEntitySheet(familyId, button.dataset.variantId)));
  byId("editFamilyBtn").addEventListener("click", () => editFamily(family));
  byId("newVariantBtn").addEventListener("click", () => openVariantForm(family, variant));
  byId("compareVariantBtn").addEventListener("click", () => openVariantCompare(family, variant));
  byId("pinEntityBtn").addEventListener("click", () => pinContext({ type: variant ? "entity_variant" : "entity_family", id: variant?.id || family.id, label: variant?.display_name || family.name }));
  byId("tagEntityBtn").addEventListener("click", () => editResourceTags(variant ? "entity_variant" : "entity_family", variant?.id || family.id, variant?.tags || family.tags || []));
  if (variant) {
    byId("editVariantBtn").addEventListener("click", () => editVariant(variant, family));
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
  byId("sheetFooter").innerHTML = `<button id="pinRelationshipBtn" class="secondary-btn">Pin context</button><button id="editRelationshipTagsBtn" class="secondary-btn">Tags</button><button id="editRelationshipBtn" class="primary-btn">Edit relationship</button>`;
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
  byId("sheetBody").innerHTML = `<section class="sheet-section"><p>${escapeHTML(world.description || "No description")}</p><div class="sheet-grid"><div class="sheet-field"><span>Canon status</span><b>${escapeHTML(world.canon_status)}</b></div><div class="sheet-field"><span>Inheritance</span><b>${escapeHTML(world.inheritance_mode)}</b></div></div></section><section class="sheet-section"><div class="sheet-section-head"><h3>World lineage</h3></div><div class="variant-switcher">${lineage.map((x) => `<button data-world-id="${x.id}">${escapeHTML(x.name)}</button>`).join(" → ")}</div></section><section class="sheet-section"><div class="sheet-section-head"><h3>Branches</h3></div>${(world.branches || []).map((branch) => `<button class="relationship-mini" data-branch-id="${branch.id}">${escapeHTML(branch.name)} · ${escapeHTML(branch.kind)} · ${escapeHTML(branch.canon_status)}</button>`).join("")}</section><section class="sheet-section"><div class="sheet-section-head"><h3>Snapshots</h3></div>${state.snapshots.map((snap) => `<div class="revision-item"><b>${escapeHTML(snap.name)}</b><small>${formatDate(snap.created_at)}</small><button class="tiny-btn restore-snapshot" data-snapshot-id="${snap.id}">Restore as sandbox</button></div>`).join("") || `<div class="empty-note">No snapshots.</div>`}</section>`;
  byId("sheetFooter").innerHTML = `<button id="editWorldBtn" class="primary-btn">Edit world</button>`;
  byId("editWorldBtn").addEventListener("click", () => editWorld(world));
  $$('[data-world-id]', byId("sheetBody")).forEach((button) => button.addEventListener("click", () => selectScope(state.activeProject.id, button.dataset.worldId, null)));
  $$('[data-branch-id]', byId("sheetBody")).forEach((button) => button.addEventListener("click", () => selectScope(state.activeProject.id, world.id, button.dataset.branchId)));
  $$(".restore-snapshot", byId("sheetBody")).forEach((button) => button.addEventListener("click", () => restoreSnapshot(button.dataset.snapshotId)));
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
  byId("sheetFooter").innerHTML = `<button id="retconFactBtn" class="secondary-btn">Preview retcon</button>`;
  byId("retconFactBtn").addEventListener("click", () => retconFact(fact));
  openSheet();
}

function retconFact(fact) {
  openForm({ title: "Retcon fact", eyebrow: "Impact preview", description: "Arline previews affected facts, relationships, documents, chats, and dataset lineage before applying a retcon.", fields: [{ name: "new_value", label: "New value (JSON or text)", type: "textarea", value: pretty(fact.value), full: true }, { name: "note", label: "Reason", type: "textarea", full: true }], submit: "Preview impact", onSubmit: async (values) => { let value; try { value = JSON.parse(values.new_value); } catch (_) { value = values.new_value; } const payload = { project_id: state.activeProject.id, world_id: state.activeWorld.id, branch_id: state.activeBranch?.kind === "main" ? null : state.activeBranch?.id, owner_type: fact.owner_type, owner_id: fact.owner_id, path: fact.path, new_value: value, note: values.note }; const preview = await api("/api/retcon/preview", { method: "POST", body: payload }); showRetconPreview(payload, preview); } });
}

function showRetconPreview(payload, preview) {
  byId("compareTitle").textContent = "Retcon impact";
  byId("compareBody").innerHTML = `<div class="metric-grid"><div class="metric-card"><span>Facts</span><strong>${preview.affected_facts?.length || 0}</strong></div><div class="metric-card"><span>Relationships</span><strong>${preview.affected_relationships?.length || 0}</strong></div><div class="metric-card"><span>Documents</span><strong>${preview.affected_documents?.length || 0}</strong></div><div class="metric-card"><span>Sessions/data</span><strong>${preview.affected_sessions?.length || 0}</strong></div></div><pre class="json-block">${escapeHTML(pretty(preview))}</pre><div class="dialog-actions"><button id="applyRetconBtn" class="primary-btn">Apply retcon</button></div>`;
  byId("compareDialog").showModal();
  byId("applyRetconBtn").addEventListener("click", async () => { await api("/api/retcon/apply", { method: "POST", body: payload }); byId("compareDialog").close(); closeSheet(); await loadProjectData(); toast("Retcon applied with lineage preserved"); });
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
    toast("Feedback saved to dataset lineage");
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

function attachEvents() {
  document.addEventListener("pointerdown", (event) => { if (!event.target.closest(".context-menu")) closeContextMenu(); });
  byId("collapseSidebarBtn").addEventListener("click", () => document.body.classList.toggle("sidebar-collapsed"));
  byId("mobileSidebarBtn").addEventListener("click", () => { byId("workspaceSidebar").classList.add("mobile-open"); byId("sidebarScrim").classList.remove("hidden"); });
  byId("sidebarScrim").addEventListener("click", () => { byId("workspaceSidebar").classList.remove("mobile-open"); byId("sidebarScrim").classList.add("hidden"); });
  byId("newChatBtn").addEventListener("click", newChat);
  byId("deleteActiveChatBtn").addEventListener("click", () => state.activeSession && deleteSession(state.activeSession.id));
  byId("commandBtn").addEventListener("click", () => openCommandPalette());
  byId("projectMenuBtn").addEventListener("click", projectActions);
  $$("[data-view]").forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
  $$("[data-library]").forEach((button) => button.addEventListener("click", () => { const type = button.dataset.library; setView("world"); state.activeWorldTab = type === "relationship" ? "relationship" : type === "timeline" ? "timeline" : type; $$("[data-world-tab]").forEach((tab) => tab.classList.toggle("active", tab.dataset.worldTab === state.activeWorldTab)); renderWorldGrid(); }));
  byId("projectSelect").addEventListener("change", () => selectScope(byId("projectSelect").value));
  byId("worldSelect").addEventListener("change", () => selectScope(state.activeProject.id, byId("worldSelect").value));
  byId("branchSelect").addEventListener("change", () => selectScope(state.activeProject.id, state.activeWorld.id, byId("branchSelect").value));
  byId("newLibraryBtn").addEventListener("click", openWorldActionsForTab);
  byId("newFolderBtn").addEventListener("click", () => openFolderForm());
  byId("newTagBtn").addEventListener("click", openTagForm);
  byId("datasetFooterBtn").addEventListener("click", () => setView("data"));
  byId("settingsBtn").addEventListener("click", () => openInspector("runtime"));
  byId("openInspectorBtn").addEventListener("click", () => openInspector());
  byId("closeInspectorBtn").addEventListener("click", closeInspector);
  byId("inspectorScrim").addEventListener("click", closeInspector);
  byId("closeSheetBtn").addEventListener("click", closeSheet);
  byId("sheetScrim").addEventListener("click", closeSheet);
  $$("[data-inspector-tab]").forEach((button) => button.addEventListener("click", () => activateInspectorTab(button.dataset.inspectorTab)));
  $$("[data-subtab]").forEach((button) => button.addEventListener("click", () => { const group = button.closest(".inspector-panel"); $$("[data-subtab]", group).forEach((x) => x.classList.toggle("active", x === button)); $$("[data-subpanel]", group).forEach((x) => x.classList.toggle("active", x.dataset.subpanel === button.dataset.subtab)); }));
  byId("modelSelect").addEventListener("change", updateModelInfo);
  byId("modeSelect").addEventListener("change", () => { updateReasoningWarning(); updateBudgetUI(); });
  byId("reasoningSelect").addEventListener("change", () => { updateReasoningWarning(); updateBudgetUI(); });
  byId("lengthPreset").addEventListener("change", () => { const value = byId("lengthPreset").value; if (value === "maximum") byId("visibleTokens").value = dynamicVisibleMaximum(); else if (value !== "custom") byId("visibleTokens").value = value; updateBudgetUI(); });
  byId("generationMode").addEventListener("change", updateBudgetUI);
  ["gpuRatio", "temperature", "topP", "minP", "repeatPenalty"].forEach((id) => byId(id).addEventListener("input", () => { syncRangeOutputs(); updateBudgetUI(); }));
  ["visibleTokens", "reasoningReserve", "contextLength", "beatCount", "beatTokens", "totalStoryTokens"].forEach((id) => byId(id).addEventListener("input", updateBudgetUI));
  byId("refreshModelsBtn").addEventListener("click", refreshModels);
  byId("saveSettingsBtn").addEventListener("click", saveSettings);
  byId("reloadModelBtn").addEventListener("click", reloadModel);
  byId("analyzeBtn").addEventListener("click", analyzePrompt);
  byId("generateBtn").addEventListener("click", generateStory);
  byId("promptInput").addEventListener("input", () => { updateAutocomplete(); updateBudgetUI(); });
  byId("promptInput").addEventListener("keydown", handleComposerKey);
  byId("traceSelect").addEventListener("change", loadTrace);
  byId("contextScopeBtn").addEventListener("click", () => openInspector("context"));
  byId("newDocumentBtn").addEventListener("click", () => openDocumentForm());
  byId("saveDraftBtn").addEventListener("click", () => saveDraft());
  byId("newDependencyBtn").addEventListener("click", openSceneDependencyForm);
  byId("draftEditor").addEventListener("input", scheduleDraftAutosave);
  byId("draftTitle").addEventListener("input", scheduleDraftAutosave);
  byId("draftReferenceBtn").addEventListener("click", () => { if (state.activeDocument) addReference({ type: "document", id: state.activeDocument.id, label: state.activeDocument.title }); });
  $$(".document-filters button").forEach((button) => button.addEventListener("click", () => { $$(".document-filters button").forEach((x) => x.classList.toggle("active", x === button)); renderDocuments(button.dataset.docFilter); }));
  $$("[data-world-tab]").forEach((button) => button.addEventListener("click", () => { state.activeWorldTab = button.dataset.worldTab; $$("[data-world-tab]").forEach((x) => x.classList.toggle("active", x === button)); renderWorldGrid(); }));
  byId("worldSearch").addEventListener("input", renderWorldGrid);
  byId("newEntityBtn").addEventListener("click", openWorldActionsForTab);
  byId("compareWorldBtn").addEventListener("click", openWorldCompare);
  byId("snapshotBtn").addEventListener("click", createSnapshot);
  byId("sandboxBtn").addEventListener("click", createSandbox);
  $$('[data-export]').forEach((button) => button.addEventListener("click", () => exportDataset(button.dataset.export)));
  byId("formDialog").addEventListener("submit", submitForm);
  $$('#formDialog button[value="cancel"]').forEach((button) => button.addEventListener("click", (event) => { event.preventDefault(); byId("formDialog").close(); }));
  byId("feedbackDialog").addEventListener("submit", submitFeedback);
  byId("closeCompareBtn").addEventListener("click", () => byId("compareDialog").close());
  byId("commandSearch").addEventListener("input", (event) => searchCommands(event.target.value));
  byId("commandSearch").addEventListener("keydown", commandKey);
  byId("saveContractBtn").addEventListener("click", saveContract);
  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); openCommandPalette(); }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "n") { event.preventDefault(); newChat(); }
    if ((event.metaKey || event.ctrlKey) && event.shiftKey && event.key.toLowerCase() === "i") { event.preventDefault(); openInspector(); }
    if (event.key === "Escape") { hideAutocomplete(); closeContextMenu(); }
  });
  byId("openDataBtn")?.addEventListener("click", () => setView("data"));
}

async function init() {
  attachEvents();
  loading(true, "Starting Arline Studio…", "Loading configuration and workspace");
  try {
    const [config, contract] = await Promise.all([api("/api/config"), api("/api/contract")]);
    applyConfig(config);
    byId("contractEditor").value = contract.content || "";
    await Promise.all([refreshModels(), loadWorkspaceBootstrap(), loadDatasetStats()]);
    setView("chat");
  } catch (error) { toast(`Startup failed: ${error.message}`, 7000); }
  finally { loading(false); }
}

init();
