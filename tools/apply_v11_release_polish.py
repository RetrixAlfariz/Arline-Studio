from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing anchor: {label}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# HTML: add final v1.1 polish surfaces without creating new top-level domains.
# ---------------------------------------------------------------------------
html_path = "src/interface/web/static/index.html"
html = read(html_path)

html = replace_once(
    html,
    '''        <label>Sidebar default<select id="settingsSidebarMode"><option value="expanded">Expanded</option><option value="collapsed">Compact rail</option></select></label>
        <div class="info-card"><b>Navigation and AI context are separate.</b><br>Opening a Library sheet never adds it to model context unless you reference or pin it.</div>''',
    '''        <label>Sidebar default<select id="settingsSidebarMode"><option value="expanded">Expanded</option><option value="collapsed">Compact rail</option></select></label>
        <label class="settings-toggle-row"><span><b>Developer tools</b><small>Show Review & Evals, Trace, Validator, Contract, and Debug settings.</small></span><input id="developerToolsToggle" type="checkbox" checked /></label>
        <div id="aboutCard" class="info-card about-card"><b>Arline Studio</b><div><span>Version</span><strong id="aboutVersion">1.1.0</strong></div><div><span>Workspace schema</span><strong id="aboutSchema">—</strong></div><div><span>Migration backups</span><strong id="aboutBackups">—</strong></div></div>
        <div class="info-card"><b>Navigation and AI context are separate.</b><br>Opening a Library sheet never adds it to model context unless you reference or pin it.</div>''',
    "general settings additions",
)

html = html.replace('<span class="settings-group-label">Developer</span>', '<span class="settings-group-label" data-settings-group="developer">Developer</span>', 1)

html = replace_once(
    html,
    '''        <div id="backupList" class="settings-list"><div class="empty-note">No backups loaded.</div></div>
        <p class="settings-help">Backups are created before schema migrations. Restore remains an explicit manual safety operation in v1.1.</p>''',
    '''        <div id="backupList" class="settings-list"><div class="empty-note">No backups loaded.</div></div>
        <div class="section-title-row settings-doctor-head"><span class="section-label">Workspace health</span><button id="runDataDoctorBtn" class="tiny-btn">Run check</button></div>
        <div id="dataDoctorResult" class="info-card data-doctor-result"><b>Not checked yet.</b><br>Doctor is read-only: it reports dangling references, duplicate identities, and stale workspace pointers without repairing canon automatically.</div>
        <p class="settings-help">Backups are created before schema migrations. Restore remains an explicit manual safety operation in v1.1.</p>''',
    "data doctor surface",
)

recovery_and_welcome = '''
    <dialog id="welcomeDialog" class="welcome-dialog">
      <div class="dialog-head"><div><span class="eyebrow">Welcome to Arline</span><h2>What do you want to do first?</h2><p>Start naturally. The structured workspace is created underneath.</p></div><button id="welcomeSkipX" class="icon-btn">×</button></div>
      <div class="welcome-actions">
        <button id="welcomeStartStory"><span>✎</span><div><b>Start a story</b><small>Create your first scene in Manuscript.</small></div></button>
        <button id="welcomeBuildWorld"><span>◇</span><div><b>Build the Library</b><small>Create a character, location, item, or world naturally.</small></div></button>
        <button id="welcomeImport"><span>⇩</span><div><b>Import existing writing</b><small>Bring Markdown or plain text into Manuscript.</small></div></button>
      </div>
      <div class="dialog-actions"><button id="welcomeSkipBtn" class="secondary-btn">Not now</button></div>
    </dialog>

    <div id="startupRecovery" class="startup-recovery hidden" role="alert">
      <div><span class="eyebrow">Recovery</span><b id="startupRecoveryTitle">Arline could not finish starting.</b><small id="startupRecoveryDetail">Your data has not been modified by this screen.</small></div>
      <div><button id="startupOpenSettingsBtn" class="secondary-btn">Data & Storage</button><button id="startupReloadBtn" class="primary-btn">Reload</button></div>
    </div>
'''
html = replace_once(html, '    <div id="toast" class="toast hidden"></div>', recovery_and_welcome + '    <div id="toast" class="toast hidden"></div>', "welcome/recovery surfaces")

html = html.replace('arline.css?v=1.1.1-settings', 'arline.css?v=1.1.2-polish')
html = html.replace('stream.js?v=1.1.1-settings', 'stream.js?v=1.1.2-polish')
html = html.replace('arline.js?v=1.1.1-settings', 'arline.js?v=1.1.2-polish')
write(html_path, html)


# ---------------------------------------------------------------------------
# CSS: adaptive compact Composer + final resilience polish.
# ---------------------------------------------------------------------------
css_path = "src/interface/web/static/arline.css"
css = read(css_path)
css += r'''

/* v1.1 release polish ------------------------------------------------------ */
html,body,.app-shell,.workbench,.main-stage,.workspace-view,.inspector,.sheet-panel{max-width:100%;overflow-x:hidden}
.composer-card,.conversation-feed,.composer-footer,.composer-profile-controls,.inspector-panel{min-width:0}

/* Composer is spacious on the landing screen and compact once a chat exists. */
body.chat-session-active #chatView{padding-top:18px;padding-bottom:12px}
body.chat-session-active .chat-landing{display:none!important}
body.chat-session-active .conversation-feed{padding-bottom:10px}
body.chat-session-active .composer-dock{position:sticky;bottom:8px;z-index:22;margin-top:4px;padding-bottom:2px}
body.chat-session-active .composer-card{border-radius:16px;padding:7px 10px 6px;box-shadow:0 14px 48px rgba(0,0,0,.2)}
body.chat-session-active .composer-editor-shell{min-height:0}
body.chat-session-active #promptInput{min-height:46px!important;max-height:116px!important;padding:8px 7px!important;resize:none;overflow:auto}
body.chat-session-active .prompt-highlight{padding:8px 7px!important}
body.chat-session-active .composer-footer{padding-top:4px;gap:6px}
body.chat-session-active .composer-profile-controls{gap:4px}
body.chat-session-active .composer-tool-btn{width:30px;height:30px}
body.chat-session-active .composer-actions{gap:4px}
body.chat-session-active .composer-actions .secondary-btn{padding:6px 9px}
body.chat-session-active .generate-btn{width:34px;height:34px}
body.chat-session-active .context-chips{margin:0 0 4px;max-height:56px;overflow:auto}
body.chat-session-active .reference-preview-bar{max-height:42px;overflow:auto}
body.chat-session-active .composer-card:not(.details-open) .length-control,
body.chat-session-active .composer-card:not(.details-open) .composer-budget,
body.chat-session-active .composer-card:not(.details-open) .composer-notes,
body.chat-session-active .composer-card:not(.details-open) #reasoningNote{display:none!important}
body.chat-session-active .composer-card.details-open .length-control{margin-top:7px}
body.chat-session-active .composer-card.details-open .composer-budget{margin-top:6px}
body.chat-session-active .composer-card.details-open .composer-notes{margin-top:4px}

/* Long chats render progressively instead of dumping thousands of turns into DOM. */
.load-earlier-turns{width:100%;border:1px solid var(--border);background:rgba(255,255,255,.02);color:var(--muted);border-radius:10px;padding:8px;font-size:9px;margin-bottom:8px}
.load-earlier-turns:hover{background:rgba(255,255,255,.05);color:var(--text)}

.settings-toggle-row{display:flex!important;align-items:center;justify-content:space-between;gap:16px;border:1px solid var(--border);background:#242625;border-radius:11px;padding:10px 11px!important}
.settings-toggle-row>span{display:flex;flex-direction:column;gap:2px}.settings-toggle-row b{font-size:10px;color:var(--text)}.settings-toggle-row small{font-size:8.5px;color:var(--muted)}
.settings-toggle-row input{width:auto!important;margin:0!important;accent-color:var(--accent)}
.about-card>div{display:flex;align-items:center;justify-content:space-between;border-top:1px solid rgba(255,255,255,.045);padding-top:7px;margin-top:7px}.about-card span{color:var(--muted-2)}.about-card strong{font:9px ui-monospace,SFMono-Regular,Menlo,monospace;color:#d8ddd9}
.settings-doctor-head{margin-top:16px}.data-doctor-result.good{border-color:rgba(78,193,156,.24);background:rgba(47,155,129,.055)}.data-doctor-result.warn{border-color:rgba(230,175,92,.25);background:rgba(230,175,92,.045)}.doctor-issue{display:grid;grid-template-columns:auto 1fr;gap:7px;margin-top:7px;padding-top:7px;border-top:1px solid rgba(255,255,255,.045)}.doctor-issue>span{font:8px ui-monospace,monospace;color:var(--warning)}.doctor-issue b{display:block;color:var(--text-soft);font-size:9px}.doctor-issue small{display:block;color:var(--muted);font-size:8px;margin-top:2px}
body.developer-tools-hidden [data-settings-group="developer"],
body.developer-tools-hidden [data-inspector-tab="review"],
body.developer-tools-hidden [data-inspector-tab="trace"],
body.developer-tools-hidden [data-inspector-tab="validator"],
body.developer-tools-hidden [data-inspector-tab="contract"],
body.developer-tools-hidden [data-inspector-tab="debug"]{display:none!important}

.welcome-dialog{width:min(680px,calc(100vw - 28px));border-radius:18px;padding:17px}.welcome-actions{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.welcome-actions>button{border:1px solid var(--border);background:#282b28;color:var(--text);border-radius:14px;padding:14px;text-align:left;display:flex;gap:10px;min-height:108px}.welcome-actions>button:hover{background:#303330;border-color:var(--border-strong)}.welcome-actions>button>span{font-size:20px;color:#9ed6c6}.welcome-actions b{display:block;font-size:11px}.welcome-actions small{display:block;color:var(--muted);font-size:8.5px;line-height:1.45;margin-top:4px}
.startup-recovery{position:fixed;left:50%;bottom:20px;transform:translateX(-50%);z-index:120;width:min(720px,calc(100vw - 28px));border:1px solid rgba(230,175,92,.25);background:rgba(31,33,31,.96);backdrop-filter:blur(16px);box-shadow:0 18px 70px rgba(0,0,0,.4);border-radius:14px;padding:12px 14px;display:flex;align-items:center;justify-content:space-between;gap:16px}.startup-recovery>div:first-child{min-width:0}.startup-recovery b{display:block;font-size:10.5px;margin:3px 0}.startup-recovery small{display:block;color:var(--muted);font-size:8.5px}.startup-recovery>div:last-child{display:flex;gap:6px;flex:none}

@media(max-width:680px){.welcome-actions{grid-template-columns:1fr}.startup-recovery{align-items:flex-start;flex-direction:column}.startup-recovery>div:last-child{width:100%}.startup-recovery>div:last-child button{flex:1}body.chat-session-active .composer-profile-summary{display:none}}
'''
write(css_path, css)


# ---------------------------------------------------------------------------
# JS: compact composer, onboarding, doctor, developer toggle, restoration.
# ---------------------------------------------------------------------------
js_path = "src/interface/web/static/arline.js"
js = read(js_path)

js = replace_once(js, '  worldSelection: new Set(),\n};', '  worldSelection: new Set(),\n  conversationRenderLimit: 80,\n};', "conversation render limit state")

old_render_conversation = '''function renderConversation(turns) {
  const feed = byId("conversationFeed");
  feed.innerHTML = turns.map((turn) => turnHTML(turn)).join("");
  bindTurnActions();
  feed.lastElementChild?.scrollIntoView({ behavior: "smooth", block: "end" });
}'''
new_render_conversation = '''function renderConversation(turns) {
  const feed = byId("conversationFeed");
  const total = turns.length;
  const limit = Math.max(20, Number(state.conversationRenderLimit || 80));
  const start = Math.max(0, total - limit);
  const visible = turns.slice(start);
  feed.innerHTML = `${start > 0 ? `<button class="load-earlier-turns" data-remaining="${start}">Load earlier messages · ${start} hidden</button>` : ""}${visible.map((turn) => turnHTML(turn)).join("")}`;
  $(".load-earlier-turns", feed)?.addEventListener("click", () => {
    state.conversationRenderLimit += 80;
    renderConversation(turns);
  });
  bindTurnActions();
  feed.lastElementChild?.scrollIntoView({ behavior: "smooth", block: "end" });
}'''
js = replace_once(js, old_render_conversation, new_render_conversation, "progressive conversation rendering")

js = replace_once(js, 'async function openSession(id) {\n  saveComposerDraft();', 'async function openSession(id) {\n  const switchingSession = state.activeSession?.id !== id;\n  if (switchingSession) state.conversationRenderLimit = 80;\n  saveComposerDraft();', "openSession prelude")
js = replace_once(js, '    renderConversation(session.turns || []); setView("chat"); renderSessions(); restoreComposerDraft();', '    renderConversation(session.turns || []); setView("chat"); renderSessions(); restoreComposerDraft(); updateComposerSessionMode(); resizeComposerInput(); saveLocalPrefs({ lastSessionId:id });', "openSession compact state")
js = replace_once(js, '  byId("promptInput").focus();\n}', '  updateComposerSessionMode(); resizeComposerInput(); byId("promptInput").focus();\n}', "newChat compact reset")
js = replace_once(js, '  byId("chatLanding")?.classList.add("hidden");\n  byId("conversationSection")?.classList.remove("hidden");', '  byId("chatLanding")?.classList.add("hidden");\n  byId("conversationSection")?.classList.remove("hidden");\n  updateComposerSessionMode(true);', "live turn compact state")
js = replace_once(js, '  renderManuscriptSuggestions(doc);\n  setView("draft");', '  renderManuscriptSuggestions(doc);\n  saveLocalPrefs({ lastDocumentId:doc.id });\n  setView("draft");', "document restoration preference")

# Keep the old data route as compatibility redirect only; eliminate direct callers.
js = js.replace('  data: () => setView("data"),', '  data: () => { openInspector("review"); loadFeedbackLab(); },')
js = js.replace('data-home-view="data"', 'data-home-review="1"')
js = replace_once(js, '  $$(\'[data-home-view]\',byId("homeView")).forEach((b)=>b.addEventListener("click",()=>setView(b.dataset.homeView)));', '  $$(\'[data-home-view]\',byId("homeView")).forEach((b)=>b.addEventListener("click",()=>setView(b.dataset.homeView)));\n  $$(\'[data-home-review]\',byId("homeView")).forEach((b)=>b.addEventListener("click",()=>{openInspector("review");loadFeedbackLab();}));', "home review route")
js = js.replace('["home","chat","draft","world","data"].includes(view)', '["home","chat","draft","world"].includes(view)')

old_settings_filter = '''function applySettingsFilter() {
  const query = (byId("settingsSearch")?.value || "").trim().toLowerCase();
  $$("#inspectorTabs [data-inspector-tab]").forEach((button) => {
    button.classList.toggle("hidden", Boolean(query) && !button.textContent.toLowerCase().includes(query));
  });
}'''
new_settings_filter = '''function applySettingsFilter() {
  const query = (byId("settingsSearch")?.value || "").trim().toLowerCase();
  const buttons = $$("#inspectorTabs [data-inspector-tab]");
  for (const button of buttons) {
    const panel = document.querySelector(`[data-inspector-panel="${button.dataset.inspectorTab}"]`);
    const haystack = `${button.textContent} ${panel?.textContent || ""}`.toLowerCase();
    button.classList.toggle("hidden", Boolean(query) && !haystack.includes(query));
  }
  const devLabel = document.querySelector('[data-settings-group="developer"]');
  if (devLabel) {
    const devTabs = ["review","trace","validator","contract","debug"];
    devLabel.classList.toggle("hidden", Boolean(query) && !devTabs.some((id)=>!document.querySelector(`[data-inspector-tab="${id}"]`)?.classList.contains("hidden")));
  }
}'''
js = replace_once(js, old_settings_filter, new_settings_filter, "settings content search")

helpers = r'''

function updateComposerSessionMode(force = null) {
  const active = force == null
    ? Boolean(state.activeSession || state.liveRun || !byId("conversationSection")?.classList.contains("hidden"))
    : Boolean(force);
  document.body.classList.toggle("chat-session-active", active);
  if (!active) byId("composerDock")?.querySelector(".composer-card")?.classList.remove("details-open");
}

function resizeComposerInput() {
  const input = byId("promptInput");
  if (!input) return;
  input.style.height = "auto";
  const max = document.body.classList.contains("chat-session-active") ? 116 : 210;
  const min = document.body.classList.contains("chat-session-active") ? 46 : 118;
  input.style.height = `${Math.max(min, Math.min(max, input.scrollHeight))}px`;
}

function setDeveloperToolsVisible(enabled) {
  document.body.classList.toggle("developer-tools-hidden", !enabled);
  if (byId("developerToolsToggle")) byId("developerToolsToggle").checked = enabled;
  saveLocalPrefs({ developerTools: enabled });
  if (!enabled && ["review","trace","validator","contract","debug"].some((tab)=>document.querySelector(`[data-inspector-tab="${tab}"]`)?.classList.contains("active"))) activateInspectorTab("general");
}

async function loadAboutInfo() {
  if (!byId("aboutCard")) return;
  const version = state.config?.studio_version || state.config?.version || "1.1.0";
  const schema = state.bootstrap?.schema_version || state.bootstrap?.workspace_schema_version || state.bootstrap?.schema?.workspace || "6";
  byId("aboutVersion").textContent = version;
  byId("aboutSchema").textContent = String(schema);
  try {
    const backups = await api("/api/backups");
    byId("aboutBackups").textContent = String(backups.backups?.length || 0);
  } catch (_) { byId("aboutBackups").textContent = "—"; }
}

function knownResourceIds() {
  return {
    project: new Set(state.projects.map((x)=>x.id)),
    world: new Set(state.worlds.map((x)=>x.id)),
    document: new Set(state.documents.map((x)=>x.id)),
    entity_family: new Set(state.families.map((x)=>x.id)),
    entity_variant: new Set(state.variants.map((x)=>x.id)),
    relationship: new Set(state.relationships.map((x)=>x.id)),
    fact: new Set(state.facts.map((x)=>x.id)),
  };
}

function runWorkspaceDoctor() {
  const issues = [];
  const ids = knownResourceIds();
  const projectFolders = new Set(flattenFolders(state.projectTree?.folders || []).map((f)=>f.id));
  const bibleFolders = new Set((state.worldBibleFolders || []).map((f)=>f.id));
  const familyIds = ids.entity_family;
  const variantIds = ids.entity_variant;
  const worldIds = ids.world;

  for (const doc of state.documents) if (doc.folder_id && !projectFolders.has(doc.folder_id)) issues.push({kind:"orphan_document_folder",label:doc.title,detail:`folder ${doc.folder_id} is missing`});
  for (const family of state.families) if (family.folder_id && !bibleFolders.has(family.folder_id)) issues.push({kind:"orphan_library_folder",label:family.name,detail:`folder ${family.folder_id} is missing`});
  for (const variant of state.variants) {
    if (!familyIds.has(variant.family_id)) issues.push({kind:"orphan_variant_family",label:variant.display_name,detail:`family ${variant.family_id} is missing`});
    if (variant.world_id && !worldIds.has(variant.world_id)) issues.push({kind:"orphan_variant_world",label:variant.display_name,detail:`world ${variant.world_id} is missing`});
  }
  for (const rel of state.relationships) {
    if (!variantIds.has(rel.subject_variant_id)) issues.push({kind:"orphan_relationship_subject",label:rel.relation_type,detail:`subject ${rel.subject_variant_id} is missing`});
    if (!variantIds.has(rel.object_variant_id)) issues.push({kind:"orphan_relationship_object",label:rel.relation_type,detail:`object ${rel.object_variant_id} is missing`});
  }
  const duplicateMap = new Map();
  for (const family of state.families) {
    const key = `${family.entity_type}:${String(family.name).trim().toLowerCase()}`;
    duplicateMap.set(key, [...(duplicateMap.get(key)||[]), family]);
  }
  for (const group of duplicateMap.values()) if (group.length > 1) issues.push({kind:"possible_duplicate_identity",label:group.map((x)=>x.name).join(" / "),detail:`${group.length} same-type identities share this normalized name`});
  if (state.activeScene?.document_id && !ids.document.has(state.activeScene.document_id)) issues.push({kind:"stale_active_scene",label:"Active scene",detail:`document ${state.activeScene.document_id} is missing`});
  for (const ref of state.selectedReferences || []) if (ids[ref.type] && !ids[ref.type].has(ref.id)) issues.push({kind:"stale_context_reference",label:ref.label || ref.id,detail:`${ref.type} no longer exists`});

  const host = byId("dataDoctorResult");
  if (!host) return issues;
  host.classList.toggle("good", issues.length === 0);
  host.classList.toggle("warn", issues.length > 0);
  host.innerHTML = issues.length
    ? `<b>${issues.length} workspace health warning${issues.length===1?"":"s"}</b><small>Read-only report; nothing was changed.</small>${issues.slice(0,20).map((issue)=>`<div class="doctor-issue"><span>!</span><div><b>${escapeHTML(issue.kind.replaceAll("_"," "))} · ${escapeHTML(issue.label)}</b><small>${escapeHTML(issue.detail)}</small></div></div>`).join("")}${issues.length>20?`<small>…and ${issues.length-20} more.</small>`:""}`
    : `<b>Workspace looks healthy.</b><br><small>No dangling references, stale scene pointers, or exact-name duplicate identities were detected in the loaded scope.</small>`;
  return issues;
}

function maybeShowOnboarding() {
  if (localStorage.getItem("arline.onboarding.v1.1") === "done") return;
  const empty = state.documents.length === 0 && state.sessions.length === 0 && state.families.length === 0;
  if (empty && byId("welcomeDialog") && !byId("welcomeDialog").open) byId("welcomeDialog").showModal();
}

function dismissOnboarding() {
  localStorage.setItem("arline.onboarding.v1.1", "done");
  byId("welcomeDialog")?.close();
}

function showStartupRecovery(error) {
  const card = byId("startupRecovery");
  if (!card) return;
  byId("startupRecoveryTitle").textContent = "Arline could not finish starting.";
  byId("startupRecoveryDetail").textContent = error?.message || String(error || "Unknown startup error");
  card.classList.remove("hidden");
}

function hideStartupRecovery() { byId("startupRecovery")?.classList.add("hidden"); }
'''
js = replace_once(js, '\nfunction attachEvents() {', helpers + '\nfunction attachEvents() {', "release polish helpers")

# Event wiring and interaction polish.
js = replace_once(js, '  on("settingsBtn", "click", () => openInspector("runtime"));', '  on("settingsBtn", "click", () => { openInspector("runtime"); loadAboutInfo(); });', "settings about load")
js = replace_once(js, '  on("settingsSearch", "input", applySettingsFilter);', '  on("settingsSearch", "input", applySettingsFilter);\n  on("settingsSearch", "keydown", (event) => { if (event.key === "Enter") { const first = $("#inspectorTabs [data-inspector-tab]:not(.hidden)"); if (first) { event.preventDefault(); activateInspectorTab(first.dataset.inspectorTab); } } });\n  on("developerToolsToggle", "change", (event) => setDeveloperToolsVisible(event.target.checked));\n  on("runDataDoctorBtn", "click", runWorkspaceDoctor);', "settings final controls")
js = replace_once(js, '  on("refreshBackupsBtn", "click", loadBackups);', '  on("refreshBackupsBtn", "click", async () => { await loadBackups(); await loadAboutInfo(); });', "backup about sync")
js = replace_once(js, '  on("composerProfileBtn", "click", () => byId("composerAdvanced")?.classList.toggle("hidden"));', '  on("composerProfileBtn", "click", () => { const advanced=byId("composerAdvanced"); advanced?.classList.toggle("hidden"); byId("composerDock")?.querySelector(".composer-card")?.classList.toggle("details-open", !advanced?.classList.contains("hidden")); resizeComposerInput(); });', "composer details toggle")
js = replace_once(js, '  on("promptInput", "input", () => { saveComposerDraft(); updateAutocomplete(); refreshPromptHighlight(); updateBudgetUI(); });', '  on("promptInput", "input", () => { saveComposerDraft(); updateAutocomplete(); refreshPromptHighlight(); updateBudgetUI(); resizeComposerInput(); });', "composer auto resize")
js = replace_once(js, '  on("closeCompareBtn", "click", () => byId("compareDialog").close());', '  on("closeCompareBtn", "click", () => byId("compareDialog").close());\n  on("welcomeSkipBtn", "click", dismissOnboarding); on("welcomeSkipX", "click", dismissOnboarding);\n  on("welcomeStartStory", "click", () => { dismissOnboarding(); setView("draft"); openDocumentForm(null,"scene"); });\n  on("welcomeBuildWorld", "click", () => { dismissOnboarding(); setView("world"); openQuickCreate("","entity"); });\n  on("welcomeImport", "click", () => { dismissOnboarding(); openManuscriptImport(); });\n  on("startupReloadBtn", "click", () => location.reload());\n  on("startupOpenSettingsBtn", "click", () => { hideStartupRecovery(); openInspector("storage"); loadBackups(); runWorkspaceDoctor(); });', "onboarding/recovery event wiring")

old_escape = '    if (event.key === "Escape") { hideAutocomplete(); closeContextMenu(); scheduleHideReferencePeek(); }'
new_escape = '''    if (event.key === "Escape") {
      hideAutocomplete(); closeContextMenu(); scheduleHideReferencePeek();
      if (byId("sheetPanel")?.classList.contains("open")) closeSheet();
      else if (byId("inspector")?.classList.contains("open")) closeInspector();
    }'''
js = replace_once(js, old_escape, new_escape, "Escape closes top surfaces")

# Apply persisted developer preference and compact mode after listeners exist.
js = replace_once(js, '  const prefs = localPrefs();\n  if (byId("settingsDensity"))', '  const prefs = localPrefs();\n  setDeveloperToolsVisible(prefs.developerTools !== false);\n  if (byId("settingsDensity"))', "developer preference restore")
js = replace_once(js, '  refreshPromptHighlight(); updateScratchUI(); updateNavigationButtons();', '  refreshPromptHighlight(); updateScratchUI(); updateNavigationButtons(); updateComposerSessionMode(); resizeComposerInput();', "initial composer mode")

# Restore the last meaningful workspace location on startup and surface recovery.
old_init_tail = '''    const preferred = routeView || localPrefs().lastView || "home";
    setView(preferred, { record: false, fromHash: true });
    if (preferred === "home") await loadHome();
    updateNavigationButtons(); updateContextStackUI();
  } catch (error) { toast(`Startup failed: ${error.message}`, 7000); }
  finally { loading(false); }
}'''
new_init_tail = '''    const prefs = localPrefs();
    const preferred = routeView || prefs.lastView || "home";
    setView(preferred, { record: false, fromHash: true });
    if (preferred === "chat" && prefs.lastSessionId && state.sessions.some((s)=>s.id===prefs.lastSessionId)) await openSession(prefs.lastSessionId);
    else if (preferred === "draft" && prefs.lastDocumentId && state.documents.some((d)=>d.id===prefs.lastDocumentId)) await openDocument(prefs.lastDocumentId);
    else if (preferred === "home") await loadHome();
    updateNavigationButtons(); updateContextStackUI(); updateComposerSessionMode(); resizeComposerInput(); hideStartupRecovery(); maybeShowOnboarding(); loadAboutInfo();
  } catch (error) { toast(`Startup failed: ${error.message}`, 7000); showStartupRecovery(error); }
  finally { loading(false); }
}'''
js = replace_once(js, old_init_tail, new_init_tail, "startup restoration/recovery")

write(js_path, js)


# ---------------------------------------------------------------------------
# Tests: release-polish primitives must stay in v1.1 after this pass.
# ---------------------------------------------------------------------------
test_path = ROOT / "tests/test_v11_release_polish.py"
test_path.write_text(
    '''from pathlib import Path\nimport unittest\n\nROOT = Path(__file__).resolve().parents[1]\n\n\nclass V11ReleasePolishTests(unittest.TestCase):\n    def test_compact_composer_is_session_adaptive(self):\n        css = (ROOT / "src/interface/web/static/arline.css").read_text(encoding="utf-8")\n        js = (ROOT / "src/interface/web/static/arline.js").read_text(encoding="utf-8")\n        self.assertIn("body.chat-session-active", css)\n        self.assertIn("updateComposerSessionMode", js)\n        self.assertIn("resizeComposerInput", js)\n        self.assertIn("details-open", css)\n\n    def test_release_safety_and_onboarding_surfaces_exist(self):\n        html = (ROOT / "src/interface/web/static/index.html").read_text(encoding="utf-8")\n        js = (ROOT / "src/interface/web/static/arline.js").read_text(encoding="utf-8")\n        for token in ("welcomeDialog", "startupRecovery", "runDataDoctorBtn", "developerToolsToggle", "aboutCard"):\n            self.assertIn(f'id="{token}"', html)\n        self.assertIn("runWorkspaceDoctor", js)\n        self.assertIn("maybeShowOnboarding", js)\n        self.assertIn("showStartupRecovery", js)\n\n    def test_feedback_lab_has_no_direct_main_navigation_callers(self):\n        js = (ROOT / "src/interface/web/static/arline.js").read_text(encoding="utf-8")\n        self.assertNotIn('data: () => setView("data")', js)\n        self.assertNotIn('data-home-view="data"', js)\n        self.assertIn('openInspector("review")', js)\n\n    def test_chat_rendering_has_performance_guardrail(self):\n        js = (ROOT / "src/interface/web/static/arline.js").read_text(encoding="utf-8")\n        self.assertIn("conversationRenderLimit", js)\n        self.assertIn("load-earlier-turns", js)\n\n    def test_settings_search_scans_panel_content(self):\n        js = (ROOT / "src/interface/web/static/arline.js").read_text(encoding="utf-8")\n        self.assertIn('panel?.textContent', js)\n        self.assertIn('developer-tools-hidden', (ROOT / "src/interface/web/static/arline.css").read_text(encoding="utf-8"))\n\n\nif __name__ == "__main__":\n    unittest.main()\n''',
    encoding="utf-8",
)

print("V11_RELEASE_POLISH_APPLIED")
