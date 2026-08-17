from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "src/interface/web/static/arline.js"
CSS = ROOT / "src/interface/web/static/arline.css"
HTML = ROOT / "src/interface/web/static/index.html"
APP = ROOT / "src/interface/web/app.py"
WORKSPACE = ROOT / "src/workspace/store.py"
HISTORY = ROOT / "src/history/store.py"
FOUNDATION = ROOT / "src/workspace/foundation.py"
PYPROJECT = ROOT / "pyproject.toml"
README = ROOT / "README.md"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one occurrence, got {count}")
    return text.replace(old, new, 1)


def replace_re(text: str, pattern: str, repl: str, label: str, flags: int = 0) -> str:
    out, count = re.subn(pattern, repl, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"{label}: expected one regex match, got {count}")
    return out


def skip_string(text: str, i: int, quote: str) -> int:
    i += 1
    n = len(text)
    while i < n:
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == quote:
            return i + 1
        i += 1
    return n


def skip_comment(text: str, i: int) -> int:
    if text.startswith("//", i):
        end = text.find("\n", i + 2)
        return len(text) if end < 0 else end + 1
    if text.startswith("/*", i):
        end = text.find("*/", i + 2)
        return len(text) if end < 0 else end + 2
    return i


def find_open_brace(text: str, i: int) -> int:
    n = len(text)
    while i < n:
        if text.startswith("//", i) or text.startswith("/*", i):
            i = skip_comment(text, i)
            continue
        if text[i] in "'\"`":
            i = skip_string(text, i, text[i])
            continue
        if text[i] == "{":
            return i
        i += 1
    raise RuntimeError("Function body brace not found")


def find_matching_brace(text: str, start: int) -> int:
    depth = 0
    i = start
    n = len(text)
    while i < n:
        if text.startswith("//", i) or text.startswith("/*", i):
            i = skip_comment(text, i)
            continue
        ch = text[i]
        if ch in "'\"`":
            i = skip_string(text, i, ch)
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise RuntimeError("Unbalanced function braces")


FUNC_HEAD = re.compile(r"(?:(?:async)\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(")


def top_level_functions(text: str):
    functions = []
    i = 0
    n = len(text)
    depth = 0
    while i < n:
        if text.startswith("//", i) or text.startswith("/*", i):
            i = skip_comment(text, i)
            continue
        ch = text[i]
        if ch in "'\"`":
            i = skip_string(text, i, ch)
            continue
        if depth == 0:
            match = FUNC_HEAD.match(text, i)
            if match:
                body = find_open_brace(text, match.end())
                end = find_matching_brace(text, body)
                functions.append((match.group(1), i, end))
                i = end
                continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        i += 1
    return functions


def dedupe_top_level_functions(text: str) -> tuple[str, dict[str, int]]:
    found = top_level_functions(text)
    groups: dict[str, list[tuple[int, int]]] = {}
    for name, start, end in found:
        groups.setdefault(name, []).append((start, end))
    removals = []
    dupes = {}
    for name, spans in groups.items():
        if len(spans) > 1:
            dupes[name] = len(spans)
            removals.extend(spans[:-1])
    for start, end in sorted(removals, reverse=True):
        # absorb surrounding blank lines to avoid leaving giant dead gaps
        while end < len(text) and text[end] in " \t":
            end += 1
        if end < len(text) and text[end] == "\n":
            end += 1
        text = text[:start] + text[end:]
    remaining = top_level_functions(text)
    names = [name for name, _, _ in remaining]
    if len(names) != len(set(names)):
        raise RuntimeError("Top-level JS function dedupe failed")
    return text, dupes


def replace_js_function(text: str, name: str, source: str) -> str:
    matches = [(n, s, e) for n, s, e in top_level_functions(text) if n == name]
    if len(matches) != 1:
        raise RuntimeError(f"{name}: expected one final function, got {len(matches)}")
    _, start, end = matches[0]
    return text[:start] + source.strip() + text[end:]


# ---------------------------------------------------------------------------
# Frontend: remove override stack, repair contracts, composer, profiles.
# ---------------------------------------------------------------------------
js = JS.read_text(encoding="utf-8")
js, duplicates = dedupe_top_level_functions(js)
print("Removed duplicate top-level JS functions:", duplicates)

# Move command metadata into a small dedicated module.
commands_match = re.search(r"const COMMANDS = \[(?:.|\n)*?\n\];", js)
if not commands_match:
    raise RuntimeError("COMMANDS block not found")
commands_block = commands_match.group(0)
array_body = commands_block[len("const COMMANDS = "):]
commands_js = (
    '"use strict";\n\n'
    "// Central command metadata. Execution lives in the single command dispatcher in arline.js.\n"
    f"window.ARLINE_COMMANDS = {array_body}\n"
)
commands_path = ROOT / "src/interface/web/static/js/commands.js"
commands_path.parent.mkdir(parents=True, exist_ok=True)
commands_path.write_text(commands_js, encoding="utf-8")
js = js[:commands_match.start()] + "const COMMANDS = window.ARLINE_COMMANDS || [];" + js[commands_match.end():]

# Client-scoped context stack; avoids two browser tabs mutating one global row.
anchor = "let contextStackTimer = null;"
context_id_helper = r'''function contextStackId() {
  const key = "arline.contextStackId";
  let value = sessionStorage.getItem(key);
  if (!value) {
    const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    value = `browser-${suffix}`;
    sessionStorage.setItem(key, value);
  }
  return value;
}

'''
if anchor not in js:
    raise RuntimeError("contextStackTimer anchor missing")
js = js.replace(anchor, context_id_helper + anchor, 1)

# Secure runtime payload: blank API key means "preserve configured secret" server-side.
js = replace_js_function(js, "runtimePayload", r'''function runtimePayload() {
  const visible = Number(byId("visibleTokens").value || 4096);
  const apiKey = byId("apiKey").value.trim();
  return {
    server_url: byId("serverUrl").value.trim(),
    api_key: apiKey || null,
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
}''')

# Accurate preflight estimate: reuse exact backend breakdown only while prompt still matches;
# otherwise keep stable workspace/system/session base + current prompt estimate.
estimator = r'''function estimatedComposerInputTokens() {
  const text = byId("promptInput")?.value || "";
  const promptEstimate = Math.max(1, Math.ceil(text.length / 4));
  const breakdown = state.contextCache.contextBreakdown;
  if (!breakdown) return promptEstimate;
  if (state.contextCache.promptText === text && Number.isFinite(Number(breakdown.estimated_input_tokens))) {
    return Math.max(promptEstimate, Number(breakdown.estimated_input_tokens));
  }
  const items = breakdown.items || {};
  const stableBase = Number(items.system_contract || 0) + Number(items.workspace || 0) + Number(items.session_continuity || 0);
  return Math.max(promptEstimate, stableBase + promptEstimate);
}

'''
format_end = js.find("function formatTokenCount")
if format_end < 0:
    raise RuntimeError("formatTokenCount not found")
# Insert immediately before dynamic maximum, after format helper function block by replacing target later anchor.
dyn_pos = js.find("function dynamicVisibleMaximum")
js = js[:dyn_pos] + estimator + js[dyn_pos:]

js = replace_js_function(js, "dynamicVisibleMaximum", r'''function dynamicVisibleMaximum() {
  const model = state.modelMap.get(byId("modelSelect")?.value);
  const modelLimit = Number(model?.max_context_length || byId("contextLength")?.value || 32768);
  const estimatedInput = estimatedComposerInputTokens();
  const reasoning = byId("reasoningSelect")?.value === "off" ? 0 : Number(byId("reasoningReserve")?.value || 0);
  const breakdownSafety = Number(state.contextCache.contextBreakdown?.items?.safety_margin || 0);
  const configuredSafety = Number(byId("safetyReserve")?.value || 0);
  const safety = Math.max(1536, breakdownSafety, configuredSafety);
  const available = Math.max(256, modelLimit - estimatedInput - reasoning - safety);
  return Math.max(256, Math.floor(available / 256) * 256);
}''')

js = replace_js_function(js, "updateBudgetUI", r'''function updateBudgetUI() {
  syncDynamicLength();
  const runtime = runtimePayload();
  const reasoning = runtime.reasoning === "off" ? 0 : runtime.reasoning_reserve_tokens;
  const totalOutput = runtime.visible_output_tokens + reasoning;
  const estimatedInput = estimatedComposerInputTokens();
  const model = state.modelMap.get(runtime.model);
  const contextMax = Number(model?.max_context_length || runtime.context_length || 32768);
  const safety = Math.max(0, Number(state.contextCache.contextBreakdown?.items?.safety_margin || 0));
  const used = estimatedInput + totalOutput + safety;
  const free = Math.max(0, contextMax - used);
  const pct = Math.min(100, (used / Math.max(contextMax, 1)) * 100);
  if (byId("totalBudget")) byId("totalBudget").textContent = totalOutput.toLocaleString();
  if (byId("modeNote")) byId("modeNote").textContent = state.scratchMode ? "Scratch mode · generated discoveries stay outside canon staging." : (MODE_NOTES[runtime.input_mode] || "");
  byId("beatControls")?.classList.toggle("hidden", runtime.generation_mode !== "beats");
  const inspectorBar = byId("contextBudgetBar") ? $("i", byId("contextBudgetBar")) : null;
  if (inspectorBar) {
    inspectorBar.style.width = `${pct}%`;
    inspectorBar.style.background = pct > 90 ? "var(--danger)" : pct > 75 ? "var(--warning)" : "var(--accent)";
  }
  const composerFill = byId("composerBudgetFill");
  if (composerFill) {
    composerFill.style.width = `${pct}%`;
    composerFill.style.background = pct > 90 ? "var(--danger)" : pct > 75 ? "var(--warning)" : "var(--accent)";
  }
  if (byId("tokenEstimate")) byId("tokenEstimate").textContent = `${formatTokenCount(estimatedInput)} input · ${formatTokenCount(totalOutput)} output ceiling`;
  if (byId("composerBudgetText")) byId("composerBudgetText").textContent = `${formatTokenCount(estimatedInput)} context · ${formatTokenCount(runtime.visible_output_tokens)} response · ${formatTokenCount(free)} free`;
}''')

# API response normalization fixes coverage, trace IDs, nested context breakdown.
js = replace_js_function(js, "loadContextResult", r'''function loadContextResult(result) {
  state.activeAnalysisId = result.analysis_id || state.activeAnalysisId;
  state.contextCache.wcf = result.wcf || "";
  state.contextCache.aif = result.aif_core || "";
  state.contextCache.brief = result.narrative_brief || null;
  state.contextCache.workspace = result.workspace_context || null;
  state.contextCache.projections = result.projections || [];
  state.contextCache.traceChoices = result.trace_choices || [];
  state.contextCache.contextBreakdown = result.context_breakdown || null;
  state.contextCache.promptText = byId("promptInput")?.value || "";

  if (byId("wcfOutput")) byId("wcfOutput").textContent = state.contextCache.wcf || "No WCF available.";
  if (byId("aifOutput")) byId("aifOutput").textContent = state.contextCache.aif || "No AIF-Core available.";
  if (byId("briefOutput")) byId("briefOutput").textContent = pretty(state.contextCache.brief);
  if (byId("workspaceContextOutput")) byId("workspaceContextOutput").textContent = state.contextCache.workspace?.text || "No workspace context.";
  if (byId("projectionOutput")) byId("projectionOutput").textContent = pretty(state.contextCache.projections);
  if (byId("wcfValidation")) byId("wcfValidation").textContent = pretty(result.wcf_validation || {});

  const summary = result.summary || {};
  if (byId("coverageValue")) byId("coverageValue").textContent = summary.semantic_coverage ?? summary.coverage ?? "—";
  if (byId("factsValue")) byId("factsValue").textContent = summary.facts ?? "—";
  if (byId("transitionsValue")) byId("transitionsValue").textContent = summary.transitions ?? "—";
  if (byId("projectionsValue")) byId("projectionsValue").textContent = summary.projections ?? "—";
  const breakdown = result.context_breakdown || {};
  const contextTokens = breakdown.estimated_input_tokens ?? summary.wcf_tokens ?? breakdown.items?.wcf;
  if (byId("wcfTokenValue")) byId("wcfTokenValue").textContent = Number.isFinite(Number(contextTokens)) ? Number(contextTokens).toLocaleString() : "—";
  byId("analysisStrip")?.classList.remove("hidden");

  if (byId("contextBreakdown")) {
    const rows = [];
    for (const [key, value] of Object.entries(breakdown.items || {})) rows.push([key, value]);
    for (const key of ["estimated_input_tokens", "estimated_total_reserved", "remaining_tokens", "model_context_length"]) {
      if (breakdown[key] != null) rows.push([key, breakdown[key]]);
    }
    byId("contextBreakdown").innerHTML = rows.map(([key, value]) => `<div><span>${escapeHTML(key.replaceAll("_", " "))}</span><b>${typeof value === "number" ? value.toLocaleString() : escapeHTML(String(value))}</b></div>`).join("");
  }
  const trace = byId("traceSelect");
  if (trace) {
    trace.dataset.cacheId = result.run_id || result.analysis_id || "";
    trace.innerHTML = `<option value="">Choose a fact…</option>` + (result.trace_choices || []).map((x) => `<option value="${escapeHTML(x.id || x.trace_id || "")}">${escapeHTML(x.label || x.id || x.trace_id || "trace")}</option>`).join("");
  }
  updateScopeVisualization();
  updateBudgetUI();
}''')

# Longest-known-label parser; plain prose no longer activates the transparent overlay.
js = replace_js_function(js, "refreshPromptHighlight", r'''function refreshPromptHighlight() {
  const input = byId("promptInput");
  const overlay = byId("promptHighlight");
  const preview = byId("referencePreviewBar");
  if (!input || !overlay || !preview) return;
  const text = input.value || "";
  const registry = referenceRegistry().sort((a, b) => b.label.length - a.label.length);
  const lower = text.toLocaleLowerCase();
  const found = [];
  let html = "";
  let cursor = 0;
  let i = 0;
  let decorated = false;
  const boundary = (ch) => !ch || /[\s.,;:!?()[\]{}<>"'`/\\|+=*~—–-]/.test(ch);

  while (i < text.length) {
    if (text[i] === "@") {
      const after = i + 1;
      let resolved = null;
      for (const ref of registry) {
        const label = String(ref.label || "");
        if (!label) continue;
        const end = after + label.length;
        if (lower.slice(after, end) === label.toLocaleLowerCase() && boundary(text[end])) {
          resolved = ref;
          break;
        }
      }
      let end;
      let rendered;
      if (resolved) {
        end = after + resolved.label.length;
        found.push({ ...resolved, resolved: true });
        rendered = `<span class="ref-known">${escapeHTML(text.slice(i, end))}</span>`;
      } else {
        const match = text.slice(after).match(/^[^\s@,;:()\[\]{}]+/);
        if (!match) { i += 1; continue; }
        end = after + match[0].length;
        found.push({ type: "unresolved", id: `unresolved:${match[0]}`, label: match[0], resolved: false });
        rendered = `<span class="ref-unresolved">${escapeHTML(text.slice(i, end))}</span>`;
      }
      html += escapeHTML(text.slice(cursor, i)) + rendered;
      cursor = end; i = end; decorated = true; continue;
    }
    if (text[i] === "/" && (i === 0 || boundary(text[i - 1]))) {
      const match = text.slice(i).match(/^\/[\w-]+/);
      if (match) {
        const end = i + match[0].length;
        const known = COMMANDS.some((c) => c.label === match[0] || c.label.startsWith(match[0]));
        html += escapeHTML(text.slice(cursor, i)) + `<span class="command-token ${known ? "" : "unresolved"}">${escapeHTML(match[0])}</span>`;
        cursor = end; i = end; decorated = true; continue;
      }
    }
    i += 1;
  }
  html += escapeHTML(text.slice(cursor));
  overlay.innerHTML = decorated ? html + (text.endsWith("\n") ? "\n " : "") : "";
  overlay.scrollTop = input.scrollTop;
  overlay.scrollLeft = input.scrollLeft;
  const shell = input.closest(".composer-editor-shell");
  shell?.classList.toggle("has-highlight", decorated);
  input.spellcheck = !decorated;

  const unique = new Map();
  found.forEach((ref) => unique.set(`${ref.type}:${ref.id}`, ref));
  state.detectedReferences = [...unique.values()];
  preview.innerHTML = state.detectedReferences.map((ref) => `<button class="reference-preview-chip ${ref.resolved ? "resolved" : "unresolved"}" data-preview-key="${escapeHTML(`${ref.type}:${ref.id}`)}">${ref.resolved ? escapeHTML(ENTITY_ICONS[ref.type] || "@") : "?"} @${escapeHTML(ref.label)}</button>`).join("");
  preview.classList.toggle("hidden", !state.detectedReferences.length);
  $$(".reference-preview-chip", preview).forEach((button) => {
    const ref = state.detectedReferences.find((r) => `${r.type}:${r.id}` === button.dataset.previewKey);
    button.addEventListener("mouseenter", () => showReferencePeek(ref, button));
    button.addEventListener("mouseleave", scheduleHideReferencePeek);
    button.addEventListener("click", () => ref?.resolved && addReference(ref));
  });
  updateContextChipUI();
}''')

# Complete run profile semantics.
js = replace_js_function(js, "applyRunProfile", r'''function applyRunProfile(profileId, { quiet = false } = {}) {
  const profile = (state.runProfiles || []).find((item) => item.id === profileId);
  if (!profile) return;
  state.activeRunProfileId = profileId;
  const data = profile.profile || {};
  const set = (id, value) => { if (value != null && byId(id)) byId(id).value = value; };
  if (data.model && byId("modelSelect") && [...byId("modelSelect").options].some((o) => o.value === data.model)) set("modelSelect", data.model);
  set("contextRecipeSelect", data.context_recipe_id);
  set("modeSelect", data.input_mode);
  if (data.reasoning && byId("reasoningSelect") && [...byId("reasoningSelect").options].some((o) => o.value === data.reasoning)) set("reasoningSelect", data.reasoning);
  set("projectionMode", data.projection_mode);
  set("visibleTokens", data.visible_output_tokens);
  set("reasoningReserve", data.reasoning_reserve_tokens);
  set("temperature", data.temperature);
  set("topP", data.top_p);
  set("topK", data.top_k);
  set("minP", data.min_p);
  set("repeatPenalty", data.repeat_penalty);
  set("contextLength", data.context_length);
  set("generationMode", data.generation_mode);
  set("beatCount", data.beat_count);
  set("beatTokens", data.beat_tokens);
  set("totalStoryTokens", data.total_story_target_tokens);
  updateModelInfo();
  syncDynamicLength({ preserveValue: true });
  syncRangeOutputs();
  updateBudgetUI();
  updateReasoningWarning();
  updateComposerProfileSummary();
  scheduleContextStackSync();
  if (!quiet) toast(`Run profile: ${profile.name}`);
}''')

js = replace_js_function(js, "openRunProfileForm", r'''function openRunProfileForm() {
  const current = {
    model: byId("modelSelect")?.value || "",
    context_recipe_id: byId("contextRecipeSelect")?.value || null,
    input_mode: byId("modeSelect")?.value || "smart_hybrid",
    reasoning: byId("reasoningSelect")?.value || "off",
    projection_mode: byId("projectionMode")?.value || "balanced",
    visible_output_tokens: Number(byId("visibleTokens")?.value || 4096),
    reasoning_reserve_tokens: Number(byId("reasoningReserve")?.value || 0),
    temperature: Number(byId("temperature")?.value || 0.8),
    top_p: Number(byId("topP")?.value || 0.95),
    top_k: Number(byId("topK")?.value || 40),
    min_p: Number(byId("minP")?.value || 0),
    repeat_penalty: Number(byId("repeatPenalty")?.value || 1.05),
    context_length: Number(byId("contextLength")?.value || 32768),
    generation_mode: byId("generationMode")?.value || "single",
    beat_count: Number(byId("beatCount")?.value || 4),
    beat_tokens: Number(byId("beatTokens")?.value || 2048),
    total_story_target_tokens: Number(byId("totalStoryTokens")?.value || 8192),
  };
  openForm({ title: "Save run profile", eyebrow: "Composer", description: "A profile packages the complete model-facing run configuration so switching profiles is reproducible.", fields: [
    { name: "name", label: "Profile name", required: true },
    { name: "description", label: "Description", type: "textarea", full: true },
  ], onSubmit: async (values) => {
    const saved = await api("/api/run-profiles", { method: "POST", body: { project_id: state.activeProject?.id || null, name: values.name, description: values.description || "", profile: current } });
    await loadRunProfiles(saved.id);
    toast(`Saved profile ${saved.name}`);
  }});
}''')

# Secure model discovery endpoint.
js = replace_js_function(js, "refreshModels", r'''async function refreshModels() {
  try {
    const apiKey = byId("apiKey").value.trim();
    const payload = await api("/api/models/query", { method: "POST", body: { server_url: byId("serverUrl").value.trim() || null, api_key: apiKey || null } });
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
    if (byId("modelInfo")) byId("modelInfo").textContent = error.message;
  }
}''')

js = replace_js_function(js, "applyConfig", r'''function applyConfig(config) {
  state.config = config;
  byId("serverUrl").value = config.server_url || "http://127.0.0.1:1234";
  byId("apiKey").value = "";
  byId("apiKey").placeholder = config.api_key_configured ? "Configured — leave blank to keep" : "Optional API key";
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
}''')

# Context stack stores one row per browser tab. Bootstrap reads the same stack.
js = replace_js_function(js, "syncContextStack", r'''async function syncContextStack() {
  if (!state.activeProject) return;
  const payload = {
    stack_id: contextStackId(),
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
}''')

# Every bootstrap request must use the current browser-tab stack.
js = js.replace('api("/api/workspace/bootstrap")', 'api(`/api/workspace/bootstrap?stack_id=${encodeURIComponent(contextStackId())}`)')

# Real command dispatcher instead of a growing if/else chain.
command_handlers = r'''const COMMAND_HANDLERS = {
  analyze: () => analyzePrompt(),
  "new-document": () => openDocumentForm(),
  "new-character": () => openQuickCreate("", "entity"),
  "new-template": () => openTemplateForm(),
  conflicts: () => { setView("world"); state.activeWorldTab = "canon"; renderWorldGrid(); },
  sandbox: () => createSandbox(),
  snapshot: () => createSnapshot(),
  "world-picker": () => openContextStackEditor(),
  data: () => setView("data"),
  inspector: () => openInspector(),
  scratch: () => toggleScratchMode(),
  "fork-chat": () => state.activeSession ? forkSession(state.activeSession.id) : toast("Open a chat first"),
  context: () => openInspector("context"),
  continuity: () => openContinuityReport(),
  "active-scene": () => openActiveSceneForm(),
  "import-manuscript": () => openManuscriptImport(),
  activity: () => openActivityCenter(),
};

'''
execute_pos = js.find("function executeCommand")
if execute_pos < 0:
    raise RuntimeError("executeCommand missing")
js = js[:execute_pos] + command_handlers + js[execute_pos:]
js = replace_js_function(js, "executeCommand", r'''async function executeCommand(command) {
  const input = byId("promptInput");
  if (command.action === "insert") {
    input.value = input.value.replace(/(?:^|\n)\/[\w-]*$/, command.text);
    input.focus(); refreshPromptHighlight();
  } else if (command.action === "quick-create") {
    const raw = input.value.match(/\/new\s+(.+)$/m)?.[1] || "";
    openQuickCreate(raw);
  } else {
    const handler = COMMAND_HANDLERS[command.action];
    if (!handler) return toast(`Unknown command action: ${command.action}`);
    await handler(command);
  }
  byId("commandDialog")?.close();
}''')

# Remove remaining user-facing v1.0 Draft vocabulary in outline.
js = js.replace('["chapter","scene","draft","outline"]', '["chapter","scene","outline"]')
js = js.replace('No chapter/scene/draft documents yet.', 'No chapter or scene documents yet.')

# Persist exact prompt association for budget cache and keep UI state fresh.
js = js.replace('on("promptInput", "input", () => { updateAutocomplete(); refreshPromptHighlight(); updateBudgetUI(); });',
                'on("promptInput", "input", () => { updateAutocomplete(); refreshPromptHighlight(); updateBudgetUI(); });')

# Verify dedupe after all replacements.
final_functions = top_level_functions(js)
fn_names = [name for name, _, _ in final_functions]
if len(fn_names) != len(set(fn_names)):
    raise RuntimeError("Patch reintroduced duplicate top-level JS functions")
JS.write_text(js, encoding="utf-8")

# CSS: textarea and overlay must be pixel-identical. Overlay is absent for normal prose.
css = CSS.read_text(encoding="utf-8")
css += r'''

/* v1.1 hardening: composer overlay must share the native editor's text metrics. */
.composer-editor-shell textarea,.composer-editor-shell .prompt-highlight{
  padding:7px 5px;font-family:inherit;font-size:13px;font-weight:400;line-height:1.58;
  letter-spacing:normal;white-space:pre-wrap;overflow-wrap:anywhere;tab-size:4
}
.composer-editor-shell:not(.has-highlight) .prompt-highlight{display:none}
.composer-editor-shell.has-highlight .prompt-highlight{display:block}
.composer-editor-shell:focus-within{filter:drop-shadow(0 0 0 rgba(0,0,0,0))}
.composer-card:has(#promptInput:focus){border-color:rgba(47,155,129,.28);box-shadow:var(--shadow),0 0 0 3px rgba(47,155,129,.045),inset 0 1px rgba(255,255,255,.025)}
.generate-btn:disabled,.primary-btn:disabled{opacity:.46;cursor:not-allowed;box-shadow:none}
'''
CSS.write_text(css, encoding="utf-8")

# Load command module before app script.
html = HTML.read_text(encoding="utf-8")
if '/static/js/commands.js' not in html:
    html = html.replace('<script src="/static/arline.js"></script>', '<script src="/static/js/commands.js"></script>\n  <script src="/static/arline.js"></script>')
HTML.write_text(html, encoding="utf-8")

# ---------------------------------------------------------------------------
# Backend: version, secure secrets, centralized backup/deletion, tab context.
# ---------------------------------------------------------------------------
app = APP.read_text(encoding="utf-8")
app = app.replace("from dataclasses import dataclass\n", "from dataclasses import dataclass\nfrom importlib.metadata import PackageNotFoundError, version as package_version\n")
app = app.replace("from src.history import HistoryStore, VALID_FEEDBACK\n", "from src.history import HistoryStore, VALID_FEEDBACK\nfrom src.history.store import SCHEMA_VERSION as HISTORY_SCHEMA_VERSION\n")
app = app.replace("from src.service import ArlineService, ArtifactStore, make_run_id\n", "from src.service import ArlineService, ArtifactStore, make_run_id\nfrom src.storage_backup import backup_sqlite_before_migrations\n")
app = replace_once(app, 'STUDIO_VERSION = "1.1.0"', 'try:\n    STUDIO_VERSION = package_version("arline-studio")\nexcept PackageNotFoundError:\n    STUDIO_VERSION = "1.1.0"', "studio version")
app = replace_once(app, '    api_key: str = ""\n', '    api_key: str | None = None\n', "runtime API key optional")
app = replace_once(app, '    cfg.lmstudio.api_key = payload.api_key or ""\n', '    if payload.api_key is not None:\n        cfg.lmstudio.api_key = payload.api_key\n', "preserve configured API key")
app = replace_once(app, '        "api_key": cfg.lmstudio.api_key,\n', '        "api_key_configured": bool(cfg.lmstudio.api_key),\n', "hide API key")

# Context payload identifies browser/tab stack without schema changes.
app = replace_once(app, 'class ContextStackPayload(BaseModel):\n    project_id: str | None = None\n', 'class ContextStackPayload(BaseModel):\n    stack_id: str = "default"\n    project_id: str | None = None\n', "context stack payload")

# Add secure model payload.
models_payload = '''\n\nclass ModelsPayload(BaseModel):\n    server_url: str | None = None\n    api_key: str | None = None\n'''
app = app.replace('\n\nclass SavePayload(BaseModel):', models_payload + '\n\nclass SavePayload(BaseModel):', 1)

# Central backup happens before HistoryStore can ALTER anything. Group paths so a shared SQLite file is copied once.
old_init = '''    initial_cfg = RuntimeConfig.load(config_path)\n    history = HistoryStore(initial_cfg.history.database_path)\n    workspace = WorkspaceStore(initial_cfg.workspace.database_path)\n    foundation = FoundationStore(initial_cfg.workspace.database_path)\n    if workspace.last_migration_backup is not None:\n        foundation.log_activity(\n            None, "schema_backup", "database", None,\n            label=f"Backup before schema v{WORKSPACE_SCHEMA_VERSION}",\n            detail={"path": str(workspace.last_migration_backup), "schema_version": WORKSPACE_SCHEMA_VERSION},\n        )\n'''
new_init = '''    initial_cfg = RuntimeConfig.load(config_path)\n    migration_targets: dict[Path, dict[str, int]] = {}\n    history_path = Path(initial_cfg.history.database_path).resolve()\n    workspace_path = Path(initial_cfg.workspace.database_path).resolve()\n    migration_targets.setdefault(history_path, {})["meta"] = HISTORY_SCHEMA_VERSION\n    migration_targets.setdefault(workspace_path, {})["workspace_meta"] = max(WORKSPACE_SCHEMA_VERSION, FoundationStore.SCHEMA_VERSION)\n    migration_backups = []\n    for database_path, targets in migration_targets.items():\n        backup = backup_sqlite_before_migrations(database_path, targets)\n        if backup is not None:\n            migration_backups.append(backup)\n\n    history = HistoryStore(initial_cfg.history.database_path, backup_before_migration=False)\n    workspace = WorkspaceStore(initial_cfg.workspace.database_path, backup_before_migration=False)\n    foundation = FoundationStore(initial_cfg.workspace.database_path)\n    for backup in migration_backups:\n        foundation.log_activity(\n            None, "schema_backup", "database", None,\n            label="Backup before database migration",\n            detail={"path": str(backup), "workspace_schema_version": WORKSPACE_SCHEMA_VERSION, "history_schema_version": HISTORY_SCHEMA_VERSION},\n        )\n'''
app = replace_once(app, old_init, new_init, "bootstrap migration backup")

# Bootstrap/get Context Stack are now tab scoped.
app = replace_once(app, '    def workspace_bootstrap(create_default: bool = Query(True)):\n', '    def workspace_bootstrap(create_default: bool = Query(True), stack_id: str = Query("default")):\n', "bootstrap stack id")
app = replace_once(app, '        stack = foundation.get_context_stack()\n', '        stack = foundation.get_context_stack(stack_id)\n', "bootstrap stack get")
app = replace_once(app, '    @app.get("/api/context-stack")\n    def get_context_stack():\n        return foundation.get_context_stack()\n', '    @app.get("/api/context-stack")\n    def get_context_stack(stack_id: str = Query("default")):\n        return foundation.get_context_stack(stack_id)\n', "context stack GET")

# Add POST model query while retaining GET as legacy compatibility.
models_route_anchor = '''    @app.post("/api/settings")\n    def save_settings(payload: RuntimePayload):\n'''
models_post = '''    @app.post("/api/models/query")\n    def query_models(payload: ModelsPayload):\n        cfg = RuntimeConfig.load(config_path)\n        if payload.server_url:\n            cfg.lmstudio.base_url = RuntimeConfig.normalize_server_url(payload.server_url)\n        if payload.api_key is not None:\n            cfg.lmstudio.api_key = payload.api_key\n        service = ArlineService(cfg)\n        try:\n            models = service.list_models()\n        except Exception as exc:\n            raise HTTPException(503, str(exc)) from exc\n        return {\n            "models": [\n                {\n                    "key": item.get("key"),\n                    "display_name": item.get("display_name") or item.get("key"),\n                    "loaded": bool(item.get("loaded_instances")),\n                    "max_context_length": item.get("max_context_length"),\n                    "reasoning": (item.get("capabilities") or {}).get("reasoning") or item.get("reasoning") or {},\n                    "format": item.get("format"),\n                }\n                for item in models\n            ]\n        }\n\n'''
if models_route_anchor not in app:
    raise RuntimeError("models route insertion anchor missing")
app = app.replace(models_route_anchor, models_post + models_route_anchor, 1)

# Permanent deletion is a single cross-store transaction boundary at the application layer.
old_perm = '''    def _permanent_delete(resource_type: str, resource_id: str) -> None:\n        deleters = {\n            "project": workspace.delete_project,\n            "world": workspace.delete_world,\n            "branch": workspace.delete_branch,\n            "folder": workspace.delete_folder,\n            "document": workspace.delete_document,\n            "entity_family": workspace.delete_entity_family,\n            "entity_variant": workspace.delete_variant,\n            "relationship": workspace.delete_relationship,\n            "fact": workspace.delete_fact,\n            "tag": workspace.delete_tag,\n            "snapshot": workspace.delete_snapshot,\n        }\n        if resource_type == "session":\n            history.delete_session(resource_id)\n            foundation.forget_resource(resource_type, resource_id)\n            return\n        delete = deleters.get(resource_type)\n        if not delete:\n            raise ValueError(f"Permanent delete is not supported for {resource_type}")\n        delete(resource_id)\n        foundation.forget_resource(resource_type, resource_id)\n'''
new_perm = '''    def _permanent_delete(resource_type: str, resource_id: str) -> None:\n        if resource_type == "session":\n            history.delete_session(resource_id)\n            foundation.forget_resource(resource_type, resource_id)\n            return\n        if resource_type == "project":\n            history.delete_sessions_by_scope(project_id=resource_id)\n            workspace.delete_project(resource_id)\n        elif resource_type == "world":\n            history.delete_sessions_by_scope(world_id=resource_id)\n            workspace.delete_world(resource_id)\n        elif resource_type == "branch":\n            history.delete_sessions_by_scope(branch_id=resource_id)\n            workspace.delete_branch(resource_id)\n        else:\n            deleters = {\n                "folder": workspace.delete_folder,\n                "document": workspace.delete_document,\n                "entity_family": workspace.delete_entity_family,\n                "entity_variant": workspace.delete_variant,\n                "relationship": workspace.delete_relationship,\n                "fact": workspace.delete_fact,\n                "tag": workspace.delete_tag,\n                "snapshot": workspace.delete_snapshot,\n            }\n            delete = deleters.get(resource_type)\n            if not delete:\n                raise ValueError(f"Permanent delete is not supported for {resource_type}")\n            delete(resource_id)\n        foundation.forget_resource(resource_type, resource_id)\n'''
app = replace_once(app, old_perm, new_perm, "central permanent delete")

# Direct destructive endpoints route through the same cleanup path.
app = replace_re(app, r'''    @app\.delete\("/api/projects/\{project_id\}"\)\n    def delete_project\(project_id: str\):\n        try:\n            workspace\.delete_project\(project_id\)\n            history\.delete_sessions_by_scope\(project_id=project_id\)\n        except KeyError as exc:\n            raise HTTPException\(404, "Project not found"\) from exc\n        return \{"ok": True\}\n''', '''    @app.delete("/api/projects/{project_id}")\n    def delete_project(project_id: str):\n        try:\n            _permanent_delete("project", project_id)\n        except KeyError as exc:\n            raise HTTPException(404, "Project not found") from exc\n        return {"ok": True}\n''', "project direct delete")
# World/branch endpoint bodies differ between versions; replace their core calls if present.
app = app.replace('            workspace.delete_world(world_id)\n            history.delete_sessions_by_scope(world_id=world_id)\n', '            _permanent_delete("world", world_id)\n')
app = app.replace('            workspace.delete_branch(branch_id)\n            history.delete_sessions_by_scope(branch_id=branch_id)\n', '            _permanent_delete("branch", branch_id)\n')
APP.write_text(app, encoding="utf-8")

# Shared migration backup utility.
backup_code = '''from __future__ import annotations\n\nfrom datetime import datetime, timezone\nfrom pathlib import Path\nimport sqlite3\nfrom typing import Mapping\n\n\ndef _read_version(con: sqlite3.Connection, table: str) -> int | None:\n    exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()\n    if not exists:\n        return None\n    try:\n        row = con.execute(f"SELECT value FROM {table} WHERE key='schema_version'").fetchone()\n    except sqlite3.DatabaseError:\n        return None\n    try:\n        return int(row[0]) if row else None\n    except (TypeError, ValueError):\n        return None\n\n\ndef backup_sqlite_before_migrations(database_path: Path | str, targets: Mapping[str, int]) -> Path | None:\n    \"\"\"Create one consistent backup before any store mutates an existing SQLite DB.\n\n    ``targets`` maps metadata table names to their expected schema versions. A\n    pre-versioned/legacy database is backed up whenever it already contains user\n    tables even if the metadata table does not exist yet.\n    \"\"\"\n    path = Path(database_path)\n    if not path.exists() or path.stat().st_size == 0:\n        return None\n    source = sqlite3.connect(path, timeout=30)\n    try:\n        tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()}\n        if not tables:\n            return None\n        reasons = []\n        for meta_table, target in targets.items():\n            current = _read_version(source, meta_table)\n            if current is None:\n                reasons.append(f"{meta_table}:legacy->{target}")\n            elif current < target:\n                reasons.append(f"{meta_table}:{current}->{target}")\n        if not reasons:\n            return None\n        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")\n        backup_dir = path.parent / "backups"\n        backup_dir.mkdir(parents=True, exist_ok=True)\n        suffix = path.suffix or ".db"\n        backup = backup_dir / f"{path.stem}.pre-migration-{stamp}{suffix}"\n        target = sqlite3.connect(backup, timeout=30)\n        try:\n            source.backup(target)\n        finally:\n            target.close()\n        return backup\n    finally:\n        source.close()\n'''
(ROOT / "src/storage_backup.py").write_text(backup_code, encoding="utf-8")

# Stores can be safely used outside create_app too; central bootstrap disables the second copy.
history = HISTORY.read_text(encoding="utf-8")
history = history.replace("from typing import Any, Iterable\n", "from typing import Any, Iterable\n\nfrom src.storage_backup import backup_sqlite_before_migrations\n")
history = replace_once(history, '    def __init__(self, database_path: Path | str):\n        self.path = Path(database_path)\n        self.path.parent.mkdir(parents=True, exist_ok=True)\n        self._lock = RLock()\n        self._init_db()\n', '    def __init__(self, database_path: Path | str, *, backup_before_migration: bool = True):\n        self.path = Path(database_path)\n        self.path.parent.mkdir(parents=True, exist_ok=True)\n        self._lock = RLock()\n        self.last_migration_backup = backup_sqlite_before_migrations(self.path, {"meta": SCHEMA_VERSION}) if backup_before_migration else None\n        self._init_db()\n', "HistoryStore backup hook")
HISTORY.write_text(history, encoding="utf-8")

workspace = WORKSPACE.read_text(encoding="utf-8")
workspace = replace_once(workspace, 'DOCUMENT_TYPES = {"draft", "chapter", "scene", "lore", "note", "outline", "research"}', 'DOCUMENT_TYPES = {"chapter", "scene", "lore", "note", "outline", "research"}', "canonical document types")
workspace = replace_once(workspace, '    def __init__(self, database_path: Path | str):\n        self.path = Path(database_path)\n        self.path.parent.mkdir(parents=True, exist_ok=True)\n        self._lock = RLock()\n        self.last_migration_backup: Path | None = self._backup_before_schema_upgrade()\n        self._init_db()\n', '    def __init__(self, database_path: Path | str, *, backup_before_migration: bool = True):\n        self.path = Path(database_path)\n        self.path.parent.mkdir(parents=True, exist_ok=True)\n        self._lock = RLock()\n        self.last_migration_backup: Path | None = self._backup_before_schema_upgrade() if backup_before_migration else None\n        self._init_db()\n', "WorkspaceStore backup hook")
# Treat an existing unversioned DB as schema v0 instead of silently skipping backup.
workspace = workspace.replace('                if not has_meta:\n                    return None\n', '                if not has_meta:\n                    has_tables = con.execute("SELECT 1 FROM sqlite_master WHERE type=\'table\' AND name NOT LIKE \'sqlite_%\' LIMIT 1").fetchone()\n                    return 0 if has_tables else None\n', 1)
# Fresh schema defaults use v1.1 vocabulary; compatibility adapter still accepts incoming draft values.
workspace = workspace.replace("document_type TEXT NOT NULL DEFAULT 'draft'", "document_type TEXT NOT NULL DEFAULT 'scene'")
# Only change document status default inside workspace_documents CREATE block.
doc_table = re.search(r"CREATE TABLE IF NOT EXISTS workspace_documents \((.*?)\n                \);", workspace, re.S)
if doc_table:
    block = doc_table.group(0)
    patched = block.replace("status TEXT NOT NULL DEFAULT 'draft'", "status TEXT NOT NULL DEFAULT 'planned'")
    workspace = workspace[:doc_table.start()] + patched + workspace[doc_table.end():]
WORKSPACE.write_text(workspace, encoding="utf-8")

# Built-in profiles become complete/reproducible. Model intentionally stays unspecified for portable defaults.
foundation = FOUNDATION.read_text(encoding="utf-8")
seed_anchor = '        for profile_id, name, description, data in profiles:\n            con.execute(\n'
seed_repl = '''        profile_defaults = {\n            "projection_mode": "balanced", "reasoning_reserve_tokens": 4096,\n            "top_p": 0.95, "top_k": 40, "min_p": 0.0, "repeat_penalty": 1.05,\n            "generation_mode": "single", "beat_count": 4, "beat_tokens": 2048,\n            "total_story_target_tokens": 8192,\n        }\n        for profile_id, name, description, data in profiles:\n            data = {**profile_defaults, **data}\n            con.execute(\n'''
foundation = replace_once(foundation, seed_anchor, seed_repl, "run profile defaults")
FOUNDATION.write_text(foundation, encoding="utf-8")

# Version source of truth.
pyproject = PYPROJECT.read_text(encoding="utf-8")
pyproject = replace_re(pyproject, r'(?m)^version = "[^"]+"$', 'version = "1.1.0"', "package version")
PYPROJECT.write_text(pyproject, encoding="utf-8")

# README hardening note.
readme = README.read_text(encoding="utf-8")
if "## v1.1 hardening guarantees" not in readme:
    readme += '''\n\n## v1.1 hardening guarantees\n\n- Composer reference highlighting only overlays actual `@references` and `/commands`; plain prose remains a native textarea with native spellcheck.\n- Context-budget UI consumes the same token-breakdown contract returned by the backend, so response MAX is computed from real assembled context rather than prompt length alone.\n- Run Profiles capture and restore the complete generation configuration.\n- Normal deletion is recoverable Trash; permanent project/world/branch deletion uses one cross-store cleanup path so chat history cannot become orphaned.\n- Existing SQLite data is backed up before **any** History/Workspace migration starts, including pre-versioned legacy databases.\n- Context Stack state is browser-tab scoped, preventing two open Studio tabs from overwriting each other.\n- API keys are no longer returned by `/api/config` or sent in model-discovery query strings.\n- CI rejects duplicate top-level frontend functions and frontend/backend context-contract regressions.\n'''
README.write_text(readme, encoding="utf-8")

# Permanent CI + regression tests.
ci = '''name: CI\n\non:\n  push:\n    branches: [main, "fix/**", "feat/**"]\n  pull_request:\n\npermissions:\n  contents: read\n\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-python@v5\n        with:\n          python-version: "3.11"\n          cache: pip\n      - uses: actions/setup-node@v4\n        with:\n          node-version: "22"\n      - run: python -m pip install -e .\n      - run: python -m unittest discover -s tests -v\n      - run: python -m compileall -q src tests\n      - run: node --check src/interface/web/static/js/commands.js\n      - run: node --check src/interface/web/static/arline.js\n'''
ci_path = ROOT / ".github/workflows/ci.yml"
ci_path.parent.mkdir(parents=True, exist_ok=True)
ci_path.write_text(ci, encoding="utf-8")

tests = ROOT / "tests"
tests.mkdir(exist_ok=True)
(tests / "__init__.py").write_text('"""Arline Studio regression tests."""\n', encoding="utf-8")
(tests / "test_v11_hardening.py").write_text(r'''from __future__ import annotations

from pathlib import Path
import re
import sqlite3
import tempfile
import unittest

from src.history import HistoryStore
from src.storage_backup import backup_sqlite_before_migrations
from src.workspace import DOCUMENT_TYPES, FoundationStore, WorkspaceStore


ROOT = Path(__file__).resolve().parents[1]


class HardeningTests(unittest.TestCase):
    def test_frontend_has_one_top_level_definition_per_name(self):
        js = (ROOT / "src/interface/web/static/arline.js").read_text(encoding="utf-8")
        names = re.findall(r"(?m)^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(", js)
        duplicates = sorted({name for name in names if names.count(name) > 1})
        self.assertEqual(duplicates, [])

    def test_frontend_uses_backend_context_contract(self):
        js = (ROOT / "src/interface/web/static/arline.js").read_text(encoding="utf-8")
        self.assertIn("estimated_input_tokens", js)
        self.assertIn("semantic_coverage", js)
        self.assertNotIn("contextBreakdown?.estimated_total_tokens", js)
        self.assertIn("x.id || x.trace_id", js)

    def test_composer_overlay_does_not_activate_for_every_plain_text(self):
        js = (ROOT / "src/interface/web/static/arline.js").read_text(encoding="utf-8")
        css = (ROOT / "src/interface/web/static/arline.css").read_text(encoding="utf-8")
        self.assertNotIn('classList.toggle("has-highlight", Boolean(text))', js)
        self.assertIn('shell?.classList.toggle("has-highlight", decorated)', js)
        self.assertIn('padding:7px 5px', css)
        self.assertIn('.composer-editor-shell:not(.has-highlight) .prompt-highlight{display:none}', css)

    def test_draft_is_compatibility_input_not_canonical_type(self):
        self.assertNotIn("draft", DOCUMENT_TYPES)
        with tempfile.TemporaryDirectory() as td:
            store = WorkspaceStore(Path(td) / "workspace.db")
            project = store.create_project("Test")
            doc = store.create_document(project["id"], "Legacy", document_type="draft", status="draft")
            self.assertEqual(doc["document_type"], "scene")
            self.assertEqual(doc["status"], "writing")

    def test_preversioned_database_is_backed_up(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "legacy.db"
            con = sqlite3.connect(db)
            con.execute("CREATE TABLE sessions(id TEXT PRIMARY KEY)")
            con.commit(); con.close()
            backup = backup_sqlite_before_migrations(db, {"meta": 4, "workspace_meta": 6})
            self.assertIsNotNone(backup)
            self.assertTrue(backup.exists())

    def test_context_stacks_are_isolated(self):
        with tempfile.TemporaryDirectory() as td:
            store = FoundationStore(Path(td) / "foundation.db")
            store.set_context_stack(stack_id="tab-a", project_id="P-A")
            store.set_context_stack(stack_id="tab-b", project_id="P-B")
            self.assertEqual(store.get_context_stack("tab-a")["project_id"], "P-A")
            self.assertEqual(store.get_context_stack("tab-b")["project_id"], "P-B")

    def test_history_store_standalone_backup_hook(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "history.db"
            con = sqlite3.connect(db)
            con.execute("CREATE TABLE sessions(id TEXT PRIMARY KEY)")
            con.commit(); con.close()
            store = HistoryStore(db)
            self.assertIsNotNone(store.last_migration_backup)


if __name__ == "__main__":
    unittest.main()
''', encoding="utf-8")

# Remove this one-shot migration mechanism from the resulting branch.
Path(__file__).unlink(missing_ok=True)
apply_workflow = ROOT / ".github/workflows/apply-hardening.yml"
apply_workflow.unlink(missing_ok=True)
print("v1.1 hardening patch applied successfully")
