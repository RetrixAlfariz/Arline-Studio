"use strict";

(() => {
  const STORAGE_KEY = "arline.command-center.v1.2.5";
  const MAX_DEPTH = 4;
  const MAX_STEPS = 32;
  const runtime = () => window.ArlineRuntime?.getState?.() || {};
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const esc = (value) => String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
  const pretty = (value) => JSON.stringify(value ?? {}, null, 2);

  const ui = {
    catalog: [],
    selectors: [],
    dynamicRefs: [],
    tab: "overview",
    selectedBuiltIn: null,
    selectedCustom: null,
    editing: null,
  };

  function loadStore() {
    try {
      const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
      return { recipes: [], history: [], ...parsed };
    } catch (_) {
      return { recipes: [], history: [] };
    }
  }

  function saveStore(store) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
  }

  function scope() {
    const current = window.ArlineRuntime?.getScope?.() || {};
    return { projectId: current.projectId || null, worldId: current.worldId || null };
  }

  function recipeVisible(recipe) {
    const s = scope();
    if (recipe.scope === "global" || !recipe.scope) return true;
    if (recipe.scope === "project") return !recipe.project_id || recipe.project_id === s.projectId;
    if (recipe.scope === "world") return (!recipe.project_id || recipe.project_id === s.projectId) && (!recipe.world_id || recipe.world_id === s.worldId);
    return true;
  }

  function normalizeCommandName(value) {
    const text = String(value || "").trim().replace(/^\/+/, "").replace(/[^\w-]+/g, "-").replace(/^-+|-+$/g, "").toLowerCase();
    return text || "custom-command";
  }

  function customCommandRows() {
    return loadStore().recipes.filter(recipeVisible).map((recipe) => ({
      id: `custom:${recipe.id}`,
      label: `/${recipe.command}`,
      category: "Custom",
      description: recipe.description || recipe.name || "Custom command recipe",
      action: "insert",
      text: `/${recipe.command} `,
      aliases: recipe.aliases || [],
      custom: true,
      recipe_id: recipe.id,
      help: {
        title: recipe.name || recipe.command,
        about: recipe.description || "Reusable custom command recipe.",
        syntax: `/${recipe.command} [@refs] [key=value] [\"goal\"]`,
        examples: [{ label: "Use recipe", text: `/${recipe.command} @scene \"goal\"` }],
        parameters: (recipe.parameters || []).map((p) => [p.name, `${p.kind || "text"}${p.default ? ` · default ${p.default}` : ""}`]),
        behavior: (recipe.steps || []).map((step) => `${step.type}: ${step.value}`),
        memory: ["Generation orchestration only", "Does not grant Canon authority", `Recipe v${recipe.version || 1}`],
      },
    }));
  }

  function syncCustomCommands() {
    const list = window.ARLINE_COMMANDS || [];
    for (let i = list.length - 1; i >= 0; i -= 1) if (list[i]?.custom) list.splice(i, 1);
    list.push(...customCommandRows());
  }

  async function loadCatalog() {
    try {
      const response = await fetch("/api/commands");
      const payload = await response.json();
      ui.catalog = payload.commands || [];
      ui.selectors = payload.reference_selectors || [];
      ui.dynamicRefs = payload.dynamic_references || [];
    } catch (_) {
      ui.catalog = (window.ARLINE_COMMANDS || []).filter((item) => !item.custom);
    }
  }

  function installStyles() {
    if ($("#arlineV125CommandStyles")) return;
    const style = document.createElement("style");
    style.id = "arlineV125CommandStyles";
    style.textContent = `
      .command-center-view{padding:34px 38px 52px;max-width:1320px;margin:0 auto}.command-center-head{display:flex;justify-content:space-between;align-items:flex-end;gap:18px;margin-bottom:20px}.command-center-head h1{font-size:28px;letter-spacing:-.04em;margin:4px 0}.command-center-head p{margin:0;color:var(--muted);font-size:11px;max-width:720px}.command-center-actions{display:flex;gap:7px}.command-center-tabs{display:flex;gap:4px;padding:4px;border:1px solid var(--border);background:rgba(0,0,0,.08);border-radius:12px;margin-bottom:16px;overflow:auto}.command-center-tabs button{border:0;background:transparent;color:var(--muted);border-radius:8px;padding:8px 11px;font-size:10px;white-space:nowrap}.command-center-tabs button.active{background:var(--panel-2);color:var(--text)}.cc-grid{display:grid;grid-template-columns:minmax(260px,.72fr) minmax(0,1.28fr);gap:14px}.cc-card,.cc-panel{border:1px solid var(--border);background:rgba(41,43,41,.7);border-radius:15px}.cc-card{padding:14px}.cc-panel{padding:18px}.cc-list{display:flex;flex-direction:column;gap:4px;max-height:68vh;overflow:auto}.cc-command-row{width:100%;border:0;background:transparent;color:inherit;border-radius:10px;padding:10px;text-align:left;display:grid;grid-template-columns:34px 1fr auto;gap:9px;align-items:center}.cc-command-row:hover,.cc-command-row.active{background:var(--panel-2)}.cc-command-row code{width:34px;height:30px;border:1px solid var(--border);border-radius:8px;display:grid;place-items:center;color:#9ad9c6;background:rgba(47,155,129,.08)}.cc-command-row b{font-size:11px}.cc-command-row small{display:block;color:var(--muted);font-size:9px;margin-top:2px;line-height:1.35}.cc-command-row em{font-style:normal;font-size:8px;color:var(--muted-2);border:1px solid var(--border);padding:3px 6px;border-radius:999px}.cc-detail h2{font-size:22px;margin:2px 0 6px;letter-spacing:-.03em}.cc-detail>p{color:var(--muted);font-size:11px;line-height:1.6}.cc-detail-section{padding:14px 0;border-top:1px solid var(--border)}.cc-detail-section:first-of-type{border-top:0}.cc-detail-section h3{font-size:9px;color:var(--muted-2);text-transform:uppercase;letter-spacing:.08em;margin:0 0 9px}.cc-syntax{display:block;padding:10px 12px;background:#202220;border:1px solid var(--border);border-radius:10px;white-space:pre-wrap;color:#dbe6e1}.cc-schema-row{display:grid;grid-template-columns:140px 80px 1fr;gap:8px;padding:7px 0;border-bottom:1px solid rgba(255,255,255,.035);font-size:10px}.cc-schema-row code{color:#a9d9ca}.cc-schema-row span{color:var(--muted)}.cc-weight{display:grid;grid-template-columns:105px 1fr 38px;align-items:center;gap:8px;margin:6px 0;font-size:9px;color:var(--muted)}.cc-weight-track{height:5px;border-radius:999px;background:rgba(255,255,255,.05);overflow:hidden}.cc-weight-track i{display:block;height:100%;background:var(--accent);border-radius:inherit}.cc-authority{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}.cc-authority div{border:1px solid var(--border);border-radius:9px;padding:9px;font-size:9px}.cc-authority .ok{color:#95d4c0;background:rgba(47,155,129,.06)}.cc-authority .no{color:#df9d9d;background:rgba(223,114,114,.04)}.cc-examples{display:grid;gap:7px}.cc-example{display:flex;gap:10px;align-items:center;padding:8px 9px;border:1px solid var(--border);border-radius:10px}.cc-example code{flex:1;white-space:pre-wrap}.cc-hero-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.cc-hero{border:1px solid var(--border);background:rgba(41,43,41,.65);border-radius:15px;padding:16px;text-align:left;color:inherit}.cc-hero:hover{background:var(--panel-2)}.cc-hero span{font-size:20px;color:#8ed7c1}.cc-hero b{display:block;margin:10px 0 4px}.cc-hero small{color:var(--muted);line-height:1.5}.cc-overview-code{margin-top:14px;padding:16px;border:1px solid var(--border);border-radius:15px;background:#1f211f;display:grid;grid-template-columns:100px 1fr;gap:8px;font:10px ui-monospace,SFMono-Regular,Menlo,monospace}.cc-overview-code b{color:#9ad9c6}.cc-custom-toolbar{display:flex;justify-content:space-between;gap:10px;margin-bottom:12px}.cc-favorite{border:0;background:transparent;color:#d9b46f;font-size:16px}.cc-editor-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.cc-editor-grid label{display:grid;gap:5px;color:var(--muted);font-size:9px}.cc-editor-grid input,.cc-editor-grid select,.cc-editor-grid textarea{border:1px solid var(--border);background:#242624;color:var(--text);border-radius:9px;padding:8px;outline:0}.cc-editor-grid .full{grid-column:1/-1}.cc-step-list{display:grid;gap:7px}.cc-step{display:grid;grid-template-columns:95px 1fr auto;gap:7px;align-items:start;border:1px solid var(--border);border-radius:10px;padding:8px}.cc-step select,.cc-step textarea{width:100%;border:0;background:#232523;color:inherit;border-radius:7px;padding:7px}.cc-step textarea{min-height:52px;resize:vertical}.cc-step-remove{border:0;background:transparent;color:var(--danger);padding:6px}.cc-editor-actions{display:flex;justify-content:space-between;gap:8px;margin-top:12px}.cc-editor-actions>div{display:flex;gap:6px}.cc-dryrun{white-space:pre-wrap;max-height:320px;overflow:auto;background:#1e201e;border:1px solid var(--border);border-radius:10px;padding:12px;font:9.5px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace}.cc-history-row{padding:10px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;gap:10px}.cc-history-row small{display:block;color:var(--muted)}.cc-profile-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.cc-profile{border:1px solid var(--border);border-radius:12px;padding:12px}.cc-ref-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.cc-ref-grid code{display:block;border:1px solid var(--border);border-radius:8px;padding:7px 9px;margin:5px 0}.cc-landing-actions{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;max-width:650px;margin:20px auto 0}.cc-landing-actions button{border:1px solid var(--border);background:rgba(41,43,41,.5);color:var(--muted);border-radius:11px;padding:10px}.cc-landing-actions button:hover{background:var(--panel-2);color:var(--text)}
      @media(min-width:1100px){#inspector.open{width:min(760px,52vw);display:grid;grid-template-columns:215px minmax(0,1fr);grid-template-rows:auto 1fr}.inspector-head{grid-column:1/-1}.inspector-tabs.settings-nav{grid-column:1;grid-row:2;max-height:none;border-right:1px solid var(--border);border-bottom:0}.inspector-panel{grid-column:2;grid-row:2;overflow:auto}}
      @media(max-width:900px){.cc-grid{grid-template-columns:1fr}.cc-hero-grid,.cc-profile-grid,.cc-ref-grid{grid-template-columns:1fr}.command-center-view{padding:22px 16px}.cc-editor-grid{grid-template-columns:1fr}.cc-editor-grid .full{grid-column:auto}}
    `;
    document.head.appendChild(style);
  }

  function setCommandView(tab = ui.tab) {
    ui.tab = tab;
    const state = runtime();
    state.activeView = "commands";
    $$('[data-view-panel]').forEach((panel) => panel.classList.toggle("active", panel.dataset.viewPanel === "commands"));
    $$('[data-view]').forEach((button) => button.classList.toggle("active", button.dataset.view === "commands"));
    document.body.dataset.activeView = "commands";
    history.replaceState(null, "", "#/commands");
    syncCustomCommands();
    render();
  }

  function addNavigation() {
    const nav = $(".workspace-nav");
    if (nav && !$('[data-view="commands"]', nav)) {
      const button = document.createElement("button");
      button.className = "workspace-nav-item";
      button.dataset.view = "commands";
      button.innerHTML = "<span>⌘</span><b>Commands</b>";
      button.addEventListener("click", () => setCommandView("overview"));
      nav.appendChild(button);
    }
    const main = $("#mainStage");
    if (main && !$("#commandCenterView")) {
      const section = document.createElement("section");
      section.id = "commandCenterView";
      section.className = "workspace-view command-center-view";
      section.dataset.viewPanel = "commands";
      main.appendChild(section);
    }
    const settingsNav = $("#inspectorTabs");
    if (settingsNav && !$("#openCommandsSettings")) {
      const button = document.createElement("button");
      button.id = "openCommandsSettings";
      button.textContent = "Commands & Recipes";
      const context = $('[data-inspector-tab="context"]', settingsNav);
      context?.after(button);
      button.addEventListener("click", () => {
        $("#inspector")?.classList.remove("open");
        $("#inspector")?.setAttribute("aria-hidden", "true");
        $("#inspectorScrim")?.classList.add("hidden");
        setCommandView("custom");
      });
    }
    const landing = $(".chat-landing");
    if (landing && !$(".cc-landing-actions", landing)) {
      const actions = document.createElement("div");
      actions.className = "cc-landing-actions";
      actions.innerHTML = '<button data-cc-launch="builtin">⌘ Browse commands</button><button data-cc-launch="custom">＋ Custom command</button><button data-cc-launch="references">@ Reference guide</button>';
      landing.appendChild(actions);
      $$('[data-cc-launch]', actions).forEach((button) => button.addEventListener("click", () => setCommandView(button.dataset.ccLaunch)));
    }
  }

  function tabsHTML() {
    return ["overview", "builtin", "custom", "profiles", "references", "history"].map((name) => `<button class="${ui.tab === name ? "active" : ""}" data-cc-tab="${name}">${({overview:"Overview",builtin:"Built-in",custom:"Custom",profiles:"Profiles",references:"References",history:"History"})[name]}</button>`).join("");
  }

  function headerHTML() {
    return `<header class="command-center-head"><div><span class="eyebrow">Arline Studio · Command Runtime 1.2.5</span><h1>Command Center</h1><p>Commands are orchestration, not story facts. Browse what each command actually does, build repeatable recipes, inspect retrieval profiles, and keep Canon authority explicit.</p></div><div class="command-center-actions"><button class="secondary-btn" data-cc-action="import">Import pack</button><button class="primary-btn" data-cc-action="new">＋ Custom command</button></div></header><nav class="command-center-tabs">${tabsHTML()}</nav>`;
  }

  function renderOverview() {
    return `<div class="cc-hero-grid"><button class="cc-hero" data-cc-open="builtin"><span>⌘</span><b>Understand built-ins</b><small>Syntax, typed arguments, execution contracts, retrieval emphasis, examples, and authority boundaries.</small></button><button class="cc-hero" data-cc-open="custom"><span>＋</span><b>Build custom commands</b><small>Compose commands, context, and ordinary instruction into reusable project or global recipes.</small></button><button class="cc-hero" data-cc-open="references"><span>@</span><b>Reference language</b><small>Static references, selectors such as .voice, and request-time dynamic references such as @scene.</small></button></div><div class="cc-overview-code"><b>/</b><span>operation or reusable workflow</span><b>@</b><span>semantic grounding / referenced resource</span><b>key=value</b><span>structured modifier</span><b>"text"</b><span>semantic goal</span></div><div class="cc-panel" style="margin-top:14px"><span class="eyebrow">Runtime contract</span><h2 style="margin:5px 0 8px">One request, explicit orchestration</h2><p style="color:var(--muted);font-size:10px;line-height:1.6">A stack such as <code>/pov → /pace → /dia</code> compiles into one request contract. Custom recipes follow the same rule in v1.2.5, so a convenient macro does not quietly become six model calls or a Canon mutation.</p></div>`;
  }

  function commandListHTML() {
    const grouped = new Map();
    for (const command of ui.catalog) {
      const category = command.category || "Command";
      if (!grouped.has(category)) grouped.set(category, []);
      grouped.get(category).push(command);
    }
    return [...grouped].map(([category, items]) => `<div><span class="eyebrow" style="display:block;padding:8px 9px 4px">${esc(category)}</span>${items.map((command) => `<button class="cc-command-row ${ui.selectedBuiltIn === command.id ? "active" : ""}" data-cc-command="${esc(command.id)}"><code>/</code><span><b>${esc(command.label)}</b><small>${esc(command.description || "")}</small></span><em>${esc(command.role || "operation")}</em></button>`).join("")}</div>`).join("");
  }

  function detailHTML(command) {
    if (!command) return `<div class="cc-panel"><div class="empty-note">Select a command to inspect its runtime contract.</div></div>`;
    const args = command.arguments || [];
    const opts = command.options || [];
    const contract = command.execution_contract || {};
    const weights = contract.retrieval_weights || {};
    const examples = command.examples?.length ? command.examples : command.help?.examples?.map((x) => x.text) || [];
    return `<article class="cc-panel cc-detail"><span class="eyebrow">${esc(command.category || "Command")} · ${esc(command.role || "operation")}</span><h2>${esc(command.label)}</h2><p>${esc(command.description || "")}</p><section class="cc-detail-section"><h3>Why use this?</h3><p>${esc(command.why_use || "Use the typed command when you want Arline's runtime to choose a known context/deliberation profile instead of relying only on prose wording.")}</p></section><section class="cc-detail-section"><h3>Syntax</h3><code class="cc-syntax">${esc(command.syntax || command.text || command.label)}</code></section>${args.length ? `<section class="cc-detail-section"><h3>Arguments</h3>${args.map((arg) => `<div class="cc-schema-row"><code>${esc(arg.name)}</code><span>${esc(arg.kind)}${arg.required ? " · required" : ""}</span><span>${esc(arg.description || "")}</span></div>`).join("")}</section>` : ""}${opts.length ? `<section class="cc-detail-section"><h3>Options</h3>${opts.map((opt) => `<div class="cc-schema-row"><code>${esc(opt.name)}</code><span>${esc(opt.kind)}</span><span>${esc(opt.choices?.length ? opt.choices.join(" · ") : opt.description || "free value")}</span></div>`).join("")}</section>` : ""}<section class="cc-detail-section"><h3>What Arline does</h3>${Object.entries(weights).sort((a,b) => b[1]-a[1]).map(([key,value]) => `<div class="cc-weight"><span>${esc(key)}</span><span class="cc-weight-track"><i style="width:${Math.round(Number(value)*100)}%"></i></span><b>${Number(value).toFixed(2)}</b></div>`).join("")}<div class="cc-schema-row"><code>deliberation</code><span>profile</span><span>${esc(contract.deliberation_profile || command.deliberation_mode || "auto")}</span></div><div class="cc-schema-row"><code>realization</code><span>profile</span><span>${esc(contract.realization_profile || command.output_mode || "fiction")}</span></div></section><section class="cc-detail-section"><h3>Authority</h3><div class="cc-authority"><div class="ok">✓ User intent and temporary request steering</div><div class="ok">✓ Context grounding within ScopeGate</div><div class="no">✕ Cannot commit or overwrite Canon</div><div class="no">✕ Cannot silently resolve UNKNOWN/conflicts</div></div></section>${examples.length ? `<section class="cc-detail-section"><h3>Examples</h3><div class="cc-examples">${examples.map((text) => `<div class="cc-example"><code>${esc(text)}</code><button class="tiny-btn" data-cc-use="${esc(text)}">Use</button></div>`).join("")}</div></section>` : ""}</article>`;
  }

  function renderBuiltIn() {
    if (!ui.selectedBuiltIn && ui.catalog.length) ui.selectedBuiltIn = ui.catalog.find((item) => item.id === "dia")?.id || ui.catalog[0].id;
    const selected = ui.catalog.find((item) => item.id === ui.selectedBuiltIn);
    return `<div class="cc-grid"><aside class="cc-card cc-list">${commandListHTML()}</aside>${detailHTML(selected)}</div>`;
  }

  function newRecipe() {
    const s = scope();
    return { id: crypto.randomUUID?.() || `recipe-${Date.now()}`, command: "my-command", name: "My command", description: "", type: "preset", scope: "project", project_id: s.projectId, world_id: s.worldId, aliases: [], parameters: [], steps: [{ type: "command", value: "/continue @scene \"{{goal}}\"" }], favorite: false, version: 1, revisions: [] };
  }

  function recipeListHTML(recipes) {
    return recipes.map((recipe) => `<button class="cc-command-row ${ui.selectedCustom === recipe.id ? "active" : ""}" data-cc-recipe="${esc(recipe.id)}"><code>${recipe.favorite ? "★" : "/"}</code><span><b>/${esc(recipe.command)}</b><small>${esc(recipe.description || recipe.name)} · v${recipe.version || 1}</small></span><em>${esc(recipe.scope || "global")}</em></button>`).join("") || `<div class="empty-note">No custom commands yet. Create one instead of retyping the same ritual forever.</div>`;
  }

  function editorHTML(recipe) {
    if (!recipe) return `<div class="cc-panel"><div class="empty-note">Select a recipe or create a new custom command.</div></div>`;
    return `<div class="cc-panel"><div class="cc-custom-toolbar"><div><span class="eyebrow">Custom command · v${recipe.version || 1}</span><h2 style="margin:4px 0">/${esc(recipe.command)}</h2></div><button class="cc-favorite" data-cc-favorite title="Favorite">${recipe.favorite ? "★" : "☆"}</button></div><div class="cc-editor-grid"><label>Name<input data-cc-field="name" value="${esc(recipe.name)}"></label><label>Command<input data-cc-field="command" value="${esc(recipe.command)}"></label><label>Type<select data-cc-field="type"><option value="preset" ${recipe.type === "preset" ? "selected" : ""}>Preset · compile one execution</option><option value="workflow" ${recipe.type === "workflow" ? "selected" : ""}>Workflow · ordered recipe</option></select></label><label>Scope<select data-cc-field="scope"><option value="global" ${recipe.scope === "global" ? "selected" : ""}>Global</option><option value="project" ${recipe.scope === "project" ? "selected" : ""}>Project</option><option value="world" ${recipe.scope === "world" ? "selected" : ""}>World</option></select></label><label class="full">Description<textarea data-cc-field="description">${esc(recipe.description)}</textarea></label><label>Aliases<input data-cc-field="aliases" value="${esc((recipe.aliases || []).join(", "))}" placeholder="qt, slowtalk"></label><label>Parameters<input data-cc-field="parameters" value="${esc((recipe.parameters || []).map((p) => `${p.name}${p.default ? `=${p.default}` : ""}`).join(", "))}" placeholder="pace=slow, tension=medium"></label></div><div class="cc-detail-section"><h3>Recipe steps</h3><div class="cc-step-list">${(recipe.steps || []).map((step,index) => `<div class="cc-step" data-step-index="${index}"><select data-step-type><option value="command" ${step.type === "command" ? "selected" : ""}>Command</option><option value="instruction" ${step.type === "instruction" ? "selected" : ""}>Instruction</option><option value="context" ${step.type === "context" ? "selected" : ""}>Context</option></select><textarea data-step-value>${esc(step.value || "")}</textarea><button class="cc-step-remove" data-step-remove="${index}">×</button></div>`).join("")}</div><div style="display:flex;gap:6px;margin-top:8px"><button class="tiny-btn" data-step-add="command">＋ Command</button><button class="tiny-btn" data-step-add="instruction">＋ Instruction</button><button class="tiny-btn" data-step-add="context">＋ Context</button></div></div><div class="cc-editor-actions"><div><button class="secondary-btn" data-cc-dryrun>Dry run</button><button class="secondary-btn" data-cc-export-one>Export</button></div><div><button class="secondary-btn" data-cc-delete>Delete</button><button class="primary-btn" data-cc-save>Save revision</button></div></div><pre class="cc-dryrun" id="ccDryRun">Dry run compiles the recipe without calling the model or touching Canon.</pre></div>`;
  }

  function renderCustom() {
    const store = loadStore();
    const recipes = store.recipes.filter(recipeVisible);
    if (ui.editing && !recipes.some((x) => x.id === ui.editing.id)) recipes.unshift(ui.editing);
    if (!ui.selectedCustom && recipes.length) ui.selectedCustom = recipes[0].id;
    const recipe = ui.editing?.id === ui.selectedCustom ? ui.editing : recipes.find((x) => x.id === ui.selectedCustom);
    return `<div class="cc-grid"><aside class="cc-card"><div class="cc-custom-toolbar"><div><span class="eyebrow">Reusable orchestration</span><b style="display:block;margin-top:4px">Your commands</b></div><button class="tiny-btn" data-cc-new-inline>＋ New</button></div><div class="cc-list">${recipeListHTML(recipes)}</div></aside>${editorHTML(recipe)}</div>`;
  }

  function renderProfiles() {
    const profiles = new Map();
    for (const command of ui.catalog) {
      const contract = command.execution_contract || {};
      const key = contract.retrieval_profile;
      if (!key || profiles.has(key)) continue;
      profiles.set(key, contract);
    }
    return `<div class="cc-profile-grid">${[...profiles].map(([name,contract]) => `<article class="cc-profile"><span class="eyebrow">Retrieval profile</span><h3>${esc(name)}</h3>${Object.entries(contract.retrieval_weights || {}).sort((a,b)=>b[1]-a[1]).map(([key,value]) => `<div class="cc-weight"><span>${esc(key)}</span><span class="cc-weight-track"><i style="width:${Math.round(Number(value)*100)}%"></i></span><b>${Number(value).toFixed(2)}</b></div>`).join("")}<small style="color:var(--muted)">${esc(contract.deliberation_profile || "auto")} → ${esc(contract.realization_profile || "fiction")}</small></article>`).join("") || `<div class="empty-note">Runtime profiles load from the backend command schema.</div>`}</div>`;
  }

  function renderReferences() {
    const selectors = ui.selectors.length ? ui.selectors : ["voice","state","appearance","knowledge","beliefs","relationships","timeline","evidence","conflicts"];
    const dynamic = ui.dynamicRefs.length ? ui.dynamicRefs : ["scene","pov","location","cast","world","branch","threads","recent"];
    return `<div class="cc-ref-grid"><section class="cc-panel"><span class="eyebrow">Stable selectors</span><h2>@Reference.selector</h2><p style="color:var(--muted);font-size:10px">Selectors narrow what part of a stable semantic object matters without creating a second identity.</p>${selectors.map((name) => `<code>@Fila.${esc(name)}</code>`).join("")}</section><section class="cc-panel"><span class="eyebrow">Request-time references</span><h2>Dynamic @ refs</h2><p style="color:var(--muted);font-size:10px">These resolve when the request runs, so they follow the active scene instead of becoming stale pinned IDs.</p>${dynamic.map((name) => `<code>@${esc(name)}</code>`).join("")}</section></div>`;
  }

  function renderHistory() {
    const rows = loadStore().history.slice().reverse();
    return `<div class="cc-panel"><span class="eyebrow">Custom command executions</span><h2>History</h2>${rows.map((row) => `<div class="cc-history-row"><div><b>/${esc(row.command)}</b><small>${esc(row.invocation)}</small></div><small>${new Date(row.at).toLocaleString()}</small></div>`).join("") || `<div class="empty-note">Custom command execution history will appear here.</div>`}</div>`;
  }

  function render() {
    const host = $("#commandCenterView");
    if (!host) return;
    const body = ui.tab === "builtin" ? renderBuiltIn() : ui.tab === "custom" ? renderCustom() : ui.tab === "profiles" ? renderProfiles() : ui.tab === "references" ? renderReferences() : ui.tab === "history" ? renderHistory() : renderOverview();
    host.innerHTML = headerHTML() + body;
    bindView();
  }

  function useInComposer(text) {
    const input = $("#promptInput");
    if (!input) return;
    input.value = String(text || "");
    input.dispatchEvent(new Event("input", { bubbles: true }));
    const chat = $('[data-view="chat"]');
    chat?.click();
    setTimeout(() => input.focus(), 0);
  }

  function readEditor(recipe) {
    const host = $("#commandCenterView");
    const get = (name) => $(`[data-cc-field="${name}"]`, host)?.value || "";
    const params = get("parameters").split(",").map((x) => x.trim()).filter(Boolean).map((entry) => { const [name, ...rest] = entry.split("="); return { name: normalizeCommandName(name).replaceAll("-", "_"), kind: "text", default: rest.join("=") }; });
    return { ...recipe, name: get("name").trim() || "Custom command", command: normalizeCommandName(get("command")), type: get("type") || "preset", scope: get("scope") || "global", description: get("description").trim(), aliases: get("aliases").split(",").map((x) => normalizeCommandName(x)).filter(Boolean), parameters: params, steps: $$(".cc-step", host).map((node) => ({ type: $("[data-step-type]", node).value, value: $("[data-step-value]", node).value.trim() })).filter((step) => step.value) };
  }

  function lintRecipe(recipe, trail = []) {
    const issues = [];
    if (!recipe.command) issues.push("Command name is required.");
    if (!(recipe.steps || []).length) issues.push("Recipe has no steps.");
    if ((recipe.steps || []).length > MAX_STEPS) issues.push(`Recipe exceeds ${MAX_STEPS} expanded steps.`);
    const builtIns = new Set(ui.catalog.map((item) => item.id));
    const custom = loadStore().recipes;
    for (const step of recipe.steps || []) {
      if (step.type !== "command") continue;
      const match = String(step.value || "").match(/^\/([\w-]+)/);
      if (!match) { issues.push(`Command step must start with /: ${step.value}`); continue; }
      const id = match[1].toLowerCase();
      const nested = custom.find((item) => item.command === id || (item.aliases || []).includes(id));
      if (!builtIns.has(id) && !nested) issues.push(`Unknown command /${id}.`);
      if (nested && (trail.includes(nested.id) || nested.id === recipe.id)) issues.push(`Recursive custom command detected: /${nested.command}.`);
    }
    return issues;
  }

  function parseInvocation(text) {
    const first = String(text || "").splitlines?.()[0];
    const line = first || String(text || "").split(/\r?\n/)[0] || "";
    const match = line.match(/^\/([\w-]+)\s*(.*)$/);
    if (!match) return null;
    const rest = match[2] || "";
    const refs = [...rest.matchAll(/@([\w.:-]+)/g)].map((m) => `@${m[1]}`);
    const options = {};
    for (const m of rest.matchAll(/\b([\w-]+)=((?:"[^"]*")|(?:'[^']*')|[^\s]+)/g)) options[m[1]] = m[2].replace(/^['"]|['"]$/g, "");
    const quoted = [...rest.matchAll(/"([^"]+)"|'([^']+)'/g)];
    const goal = quoted.length ? (quoted[quoted.length - 1][1] || quoted[quoted.length - 1][2] || "") : "";
    return { command: match[1].toLowerCase(), refs, options, goal, raw: line.trim() };
  }

  function substitute(text, values) {
    return String(text || "").replace(/\{\{([\w-]+)\}\}/g, (_, key) => values[key] ?? `{{${key}}}`);
  }

  function compileRecipe(recipe, invocation, trail = [], depth = 0) {
    if (depth > MAX_DEPTH) throw new Error(`Custom command nesting exceeds depth ${MAX_DEPTH}.`);
    if (trail.includes(recipe.id)) throw new Error(`Recursive recipe /${recipe.command}.`);
    const values = { goal: invocation.goal || "", refs: invocation.refs.join(" "), ...invocation.options };
    invocation.refs.forEach((ref, index) => { values[`ref${index + 1}`] = ref; });
    for (const param of recipe.parameters || []) if (!(param.name in values)) values[param.name] = param.default || "";
    const store = loadStore();
    const lines = [];
    for (const step of recipe.steps || []) {
      if (lines.length >= MAX_STEPS) throw new Error(`Expanded recipe exceeds ${MAX_STEPS} steps.`);
      const value = substitute(step.value, values).trim();
      if (!value) continue;
      if (step.type === "command") {
        const nestedInvocation = parseInvocation(value);
        const nested = nestedInvocation && store.recipes.find((item) => item.command === nestedInvocation.command || (item.aliases || []).includes(nestedInvocation.command));
        if (nested) lines.push(...compileRecipe(nested, nestedInvocation, [...trail, recipe.id], depth + 1));
        else lines.push(value);
      } else if (step.type === "context") {
        lines.push(value.startsWith("@") ? `/continue ${value}` : value);
      } else {
        lines.push(value);
      }
    }
    if (lines.length > MAX_STEPS) throw new Error(`Expanded recipe exceeds ${MAX_STEPS} steps.`);
    return lines;
  }

  function dryRun(recipe, invocationText = null) {
    const current = readEditor(recipe);
    const issues = lintRecipe(current);
    const sample = invocationText || `/${current.command} @scene \"example goal\"`;
    const invocation = parseInvocation(sample);
    let compiled = [];
    let error = null;
    try { compiled = compileRecipe(current, invocation || { refs: [], options: {}, goal: "", command: current.command }); }
    catch (exc) { error = exc.message; }
    return { runtime: "1.2.5a1", invocation: sample, type: current.type, scope: current.scope, lint: issues, error, expanded_steps: compiled.length, writer_calls: compiled.length ? 1 : 0, canon_writes: 0, compiled_request: compiled.join("\n") };
  }

  function saveRecipe(recipe) {
    const next = readEditor(recipe);
    const issues = lintRecipe(next);
    if (issues.some((item) => item.startsWith("Recursive") || item.startsWith("Unknown") || item.includes("no steps"))) throw new Error(issues.join(" "));
    const store = loadStore();
    const index = store.recipes.findIndex((item) => item.id === next.id);
    const s = scope();
    next.project_id = next.scope === "global" ? null : s.projectId;
    next.world_id = next.scope === "world" ? s.worldId : null;
    if (index >= 0) {
      const old = store.recipes[index];
      next.revisions = [...(old.revisions || []), { version: old.version || 1, snapshot: { ...old, revisions: [] }, at: Date.now() }].slice(-20);
      next.version = (old.version || 1) + 1;
      store.recipes[index] = next;
    } else store.recipes.push(next);
    saveStore(store);
    ui.editing = null;
    ui.selectedCustom = next.id;
    syncCustomCommands();
    return next;
  }

  function deleteRecipe(recipe) {
    const store = loadStore();
    store.recipes = store.recipes.filter((item) => item.id !== recipe.id);
    saveStore(store);
    ui.selectedCustom = null;
    ui.editing = null;
    syncCustomCommands();
  }

  function exportJSON(data, filename) {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 500);
  }

  function importPack() {
    const input = document.createElement("input"); input.type = "file"; input.accept = ".json,application/json";
    input.addEventListener("change", async () => {
      const file = input.files?.[0]; if (!file) return;
      try {
        const data = JSON.parse(await file.text());
        const incoming = Array.isArray(data) ? data : data.recipes || [];
        const store = loadStore();
        for (const raw of incoming) {
          const recipe = { ...newRecipe(), ...raw, id: crypto.randomUUID?.() || `recipe-${Date.now()}-${Math.random()}`, command: normalizeCommandName(raw.command || raw.name), version: 1, revisions: [] };
          store.recipes.push(recipe);
        }
        saveStore(store); syncCustomCommands(); ui.tab = "custom"; render();
      } catch (error) { alert(`Import failed: ${error.message}`); }
    }, { once: true }); input.click();
  }

  function bindView() {
    const host = $("#commandCenterView");
    $$('[data-cc-tab]', host).forEach((button) => button.addEventListener("click", () => { ui.tab = button.dataset.ccTab; render(); }));
    $$('[data-cc-open]', host).forEach((button) => button.addEventListener("click", () => { ui.tab = button.dataset.ccOpen; render(); }));
    $$('[data-cc-command]', host).forEach((button) => button.addEventListener("click", () => { ui.selectedBuiltIn = button.dataset.ccCommand; render(); }));
    $$('[data-cc-use]', host).forEach((button) => button.addEventListener("click", () => useInComposer(button.dataset.ccUse)));
    $$('[data-cc-recipe]', host).forEach((button) => button.addEventListener("click", () => { ui.selectedCustom = button.dataset.ccRecipe; ui.editing = null; render(); }));
    const openNew = () => { ui.tab = "custom"; ui.editing = newRecipe(); ui.selectedCustom = ui.editing.id; render(); };
    $('[data-cc-action="new"]', host)?.addEventListener("click", openNew);
    $('[data-cc-new-inline]', host)?.addEventListener("click", openNew);
    $('[data-cc-action="import"]', host)?.addEventListener("click", importPack);
    const store = loadStore();
    const recipe = ui.editing?.id === ui.selectedCustom ? ui.editing : store.recipes.find((item) => item.id === ui.selectedCustom);
    if (!recipe) return;
    $('[data-cc-favorite]', host)?.addEventListener("click", () => { const current = readEditor(recipe); current.favorite = !recipe.favorite; ui.editing = current; render(); });
    $$('[data-step-add]', host).forEach((button) => button.addEventListener("click", () => { const current = readEditor(recipe); current.steps.push({ type: button.dataset.stepAdd, value: button.dataset.stepAdd === "command" ? "/continue @scene" : button.dataset.stepAdd === "context" ? "@recent @threads" : "Instruction for this generation." }); ui.editing = current; render(); }));
    $$('[data-step-remove]', host).forEach((button) => button.addEventListener("click", () => { const current = readEditor(recipe); current.steps.splice(Number(button.dataset.stepRemove), 1); ui.editing = current; render(); }));
    $('[data-cc-dryrun]', host)?.addEventListener("click", () => { const result = dryRun(recipe); $("#ccDryRun", host).textContent = pretty(result); });
    $('[data-cc-save]', host)?.addEventListener("click", () => { try { saveRecipe(recipe); render(); } catch (error) { $("#ccDryRun", host).textContent = `Cannot save\n${error.message}`; } });
    $('[data-cc-delete]', host)?.addEventListener("click", () => { if (confirm(`Delete /${recipe.command}?`)) { deleteRecipe(recipe); render(); } });
    $('[data-cc-export-one]', host)?.addEventListener("click", () => exportJSON({ format: "arline-command-pack", version: "1.2.5", recipes: [readEditor(recipe)] }, `${recipe.command}.arline-commands.json`));
  }

  function expandCustomPrompt() {
    const input = $("#promptInput"); if (!input) return false;
    const lines = input.value.split(/\r?\n/);
    const firstIndex = lines.findIndex((line) => /^\/[\w-]+/.test(line.trim()));
    if (firstIndex < 0) return false;
    const invocation = parseInvocation(lines[firstIndex].trim());
    if (!invocation) return false;
    const store = loadStore();
    const recipe = store.recipes.find((item) => recipeVisible(item) && (item.command === invocation.command || (item.aliases || []).includes(invocation.command)));
    if (!recipe) return false;
    try {
      const compiled = compileRecipe(recipe, invocation);
      const rest = lines.filter((_, index) => index !== firstIndex).join("\n").trim();
      input.value = [...compiled, ...(rest ? [rest] : [])].join("\n");
      input.dispatchEvent(new Event("input", { bubbles: true }));
      store.history = [...(store.history || []), { command: recipe.command, invocation: invocation.raw, compiled, at: Date.now() }].slice(-100);
      saveStore(store);
      return true;
    } catch (error) {
      alert(`Custom command could not compile: ${error.message}`);
      return false;
    }
  }

  function installCompilerHooks() {
    for (const id of ["generateBtn", "analyzeBtn"]) {
      $("#" + id)?.addEventListener("click", () => expandCustomPrompt(), true);
    }
    $("#promptInput")?.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter") expandCustomPrompt();
    }, true);
    window.addEventListener("focus", syncCustomCommands);
  }

  async function install() {
    installStyles();
    await loadCatalog();
    syncCustomCommands();
    addNavigation();
    installCompilerHooks();
    const onHash = () => { if (location.hash === "#/commands") setCommandView(ui.tab); };
    window.addEventListener("hashchange", onHash);
    if (location.hash === "#/commands") setCommandView("overview");
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", install, { once: true });
  else install();
})();
