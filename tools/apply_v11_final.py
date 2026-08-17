from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    (ROOT / rel).write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing anchor: {label}")
    return text.replace(old, new, 1)


def skip_string(text: str, i: int, quote: str) -> int:
    i += 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == quote:
            return i + 1
        i += 1
    return i


def skip_comment(text: str, i: int) -> int:
    if text.startswith("//", i):
        j = text.find("\n", i + 2)
        return len(text) if j < 0 else j + 1
    j = text.find("*/", i + 2)
    return len(text) if j < 0 else j + 2


def find_function(text: str, name: str) -> tuple[int, int]:
    m = re.search(rf"(?m)^(?:async\s+)?function\s+{re.escape(name)}\s*\(", text)
    if not m:
        raise SystemExit(f"function not found: {name}")
    i = m.end()
    paren = 1
    bracket = 0
    while i < len(text):
        if text.startswith("//", i) or text.startswith("/*", i):
            i = skip_comment(text, i); continue
        if text[i] in "'\"`":
            i = skip_string(text, i, text[i]); continue
        ch = text[i]
        if ch == "(": paren += 1
        elif ch == ")": paren = max(0, paren - 1)
        elif ch == "[": bracket += 1
        elif ch == "]": bracket = max(0, bracket - 1)
        elif ch == "{" and paren == 0 and bracket == 0:
            body = i; break
        i += 1
    else:
        raise SystemExit(f"body not found: {name}")
    depth = 0; i = body
    while i < len(text):
        if text.startswith("//", i) or text.startswith("/*", i):
            i = skip_comment(text, i); continue
        if text[i] in "'\"`":
            i = skip_string(text, i, text[i]); continue
        if text[i] == "{": depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return m.start(), i + 1
        i += 1
    raise SystemExit(f"unbalanced body: {name}")


def replace_function(text: str, name: str, replacement: str) -> str:
    start, end = find_function(text, name)
    return text[:start] + replacement.rstrip() + text[end:]


# ---------------------------------------------------------------------------
# HTML: simplify primary navigation, move context out of the narrow rail,
# group Settings/Developer, add focus mode, and load the SSE module.
# ---------------------------------------------------------------------------
html = read("src/interface/web/static/index.html")

nav_pattern = re.compile(r'<nav class="workspace-nav" aria-label="Workspace views">.*?</nav>', re.S)
nav_new = '''<nav class="workspace-nav" aria-label="Workspace views">
        <button data-view="chat" class="workspace-nav-item"><span>◉</span><b>Chat</b></button>
        <button data-view="draft" class="workspace-nav-item"><span>✎</span><b>Manuscript</b></button>
        <button data-view="world" class="workspace-nav-item"><span>◇</span><b>Library</b></button>
      </nav>'''
html, n = nav_pattern.subn(nav_new, html, count=1)
if n != 1: raise SystemExit("workspace nav patch failed")

context_pattern = re.compile(r'\n\s*<div class="context-stack-card" id="contextStackCard">.*?</div>\n\s*<div id="sidebarScroll"', re.S)
html, n = context_pattern.subn('\n\n      <div id="sidebarScroll"', html, count=1)
if n != 1: raise SystemExit("sidebar context-card removal failed")

html = html.replace('<section class="sidebar-section">\n          <div class="section-title-row">\n            <span class="section-label">Library</span>', '<section class="sidebar-section" data-sidebar-domain="world">\n          <div class="section-title-row">\n            <span class="section-label">Library</span>', 1)
html = html.replace('<section class="sidebar-section">\n          <div class="section-title-row">\n            <span class="section-label">Project files</span>', '<section class="sidebar-section" data-sidebar-domain="draft">\n          <div class="section-title-row">\n            <span class="section-label">Project files</span>', 1)
html = html.replace('<section id="tagSection" class="sidebar-section hidden">', '<section id="tagSection" class="sidebar-section hidden" data-sidebar-domain="chat">', 1)
html = html.replace('<section id="pinnedSection" class="sidebar-section hidden">', '<section id="pinnedSection" class="sidebar-section hidden" data-sidebar-domain="chat">', 1)
html = html.replace('<section class="sidebar-section history-section">', '<section class="sidebar-section history-section" data-sidebar-domain="chat">', 1)

footer_pattern = re.compile(r'<div class="sidebar-footer">.*?</div>\n\s*</aside>', re.S)
footer_new = '''<div class="sidebar-footer">
        <button id="settingsBtn" class="sidebar-utility-btn" title="Settings"><span>⚙</span><b>Settings</b></button>
      </div>
    </aside>'''
html, n = footer_pattern.subn(footer_new, html, count=1)
if n != 1: raise SystemExit("sidebar footer patch failed")

html = replace_once(
    html,
    '<button id="saveDraftBtn" class="primary-btn" title="Create a meaningful revision checkpoint">Checkpoint</button>',
    '<button id="focusModeBtn" class="secondary-btn" title="Distraction-free writing">Focus</button><button id="saveDraftBtn" class="primary-btn" title="Create a meaningful revision checkpoint">Checkpoint</button>',
    "focus mode button",
)

html = replace_once(
    html,
    '<div class="inspector-head"><div><span class="eyebrow">Developer</span><h2>Inspector</h2></div><button id="closeInspectorBtn" class="icon-btn">×</button></div>',
    '<div class="inspector-head"><div><span class="eyebrow">Arline Studio</span><h2>Settings</h2></div><button id="closeInspectorBtn" class="icon-btn">×</button></div>',
    "settings heading",
)

inspector_nav = re.compile(r'<nav class="inspector-tabs" id="inspectorTabs">.*?</nav>', re.S)
inspector_nav_new = '''<nav class="inspector-tabs settings-nav" id="inspectorTabs">
        <label class="settings-search"><span>⌕</span><input id="settingsSearch" placeholder="Search settings" /></label>
        <span class="settings-group-label">Settings</span>
        <button data-inspector-tab="general">General</button>
        <button class="active" data-inspector-tab="runtime">Models & Runtime</button>
        <button data-inspector-tab="sampling">Generation</button>
        <button data-inspector-tab="context">Context</button>
        <button data-inspector-tab="storage">Data & Storage</button>
        <span class="settings-group-label">Developer</span>
        <button data-inspector-tab="review">Review & Evals</button>
        <button data-inspector-tab="trace">Trace</button>
        <button data-inspector-tab="validator">Validator</button>
        <button data-inspector-tab="contract">Contract</button>
        <button data-inspector-tab="debug">Debug</button>
      </nav>'''
html, n = inspector_nav.subn(inspector_nav_new, html, count=1)
if n != 1: raise SystemExit("settings nav patch failed")

general_panel = '''      <div class="inspector-panel" data-inspector-panel="general">
        <span class="eyebrow">Interface</span><h3>Workspace appearance</h3>
        <label>Density<select id="settingsDensity"><option value="comfortable">Comfortable</option><option value="compact">Compact</option></select></label>
        <label>Sidebar default<select id="settingsSidebarMode"><option value="expanded">Expanded</option><option value="collapsed">Compact rail</option></select></label>
        <div class="info-card"><b>Navigation and AI context are separate.</b><br>Opening a Library sheet never adds it to model context unless you reference or pin it.</div>
        <div class="shortcut-grid"><span>⌘/Ctrl K</span><b>Search</b><span>⌘/Ctrl N</span><b>Quick create</b><span>Ctrl Shift F</span><b>Focus mode</b></div>
      </div>\n'''
html = replace_once(html, '      <div class="inspector-panel active" data-inspector-panel="runtime">', general_panel + '      <div class="inspector-panel active" data-inspector-panel="runtime">', "general settings panel")

storage_review = '''      <div class="inspector-panel" data-inspector-panel="storage">
        <span class="eyebrow">Local-first data</span><h3>Data & Storage</h3>
        <div id="storageSummary" class="info-card">Loading storage information…</div>
        <div class="section-title-row"><span class="section-label">Migration backups</span><button id="refreshBackupsBtn" class="tiny-btn">Refresh</button></div>
        <div id="backupList" class="settings-list"><div class="empty-note">No backups loaded.</div></div>
        <p class="settings-help">Backups are created before schema migrations. Restore remains an explicit manual safety operation in v1.1.</p>
      </div>
      <div class="inspector-panel" data-inspector-panel="review">
        <span class="eyebrow">Developer</span><h3>Review & Evals</h3>
        <p class="settings-help">Output review, comparisons, SFT/preference exports, and evaluator artifacts live here instead of the primary writing navigation.</p>
        <div id="developerReviewSummary" class="info-card">Open Review & Evals to inspect generated candidates.</div>
        <button id="openFeedbackLabBtn" class="primary-btn wide">Open Review & Evals</button>
      </div>\n'''
html = replace_once(html, '      <div class="inspector-panel" data-inspector-panel="trace">', storage_review + '      <div class="inspector-panel" data-inspector-panel="trace">', "storage/review panels")

html = replace_once(html, '  <script src="/static/arline.js" defer></script>', '  <script src="/static/js/stream.js" defer></script>\n  <script src="/static/arline.js" defer></script>', "stream script")
write("src/interface/web/static/index.html", html)


# ---------------------------------------------------------------------------
# CSS: contextual rail, grouped settings, inline streaming, focus mode.
# ---------------------------------------------------------------------------
css = read("src/interface/web/static/arline.css")
css += r'''

/* v1.1 final polish: navigation is a rail, not an information column. */
.workspace-nav{grid-template-columns:repeat(3,1fr)}
.sidebar-utility-btn{width:100%;border:0;background:transparent;color:var(--muted);border-radius:9px;display:flex;align-items:center;gap:9px;padding:8px 9px}.sidebar-utility-btn:hover{background:var(--sidebar-hover);color:#fff}.sidebar-utility-btn span{font-size:14px}.sidebar-utility-btn b{font-size:9.5px;font-weight:600}
.sidebar-section[data-sidebar-domain]{display:none}
body[data-active-view="chat"] .sidebar-section[data-sidebar-domain="chat"],body[data-active-view="draft"] .sidebar-section[data-sidebar-domain="draft"],body[data-active-view="world"] .sidebar-section[data-sidebar-domain="world"]{display:block}
body.sidebar-collapsed .context-stack-card,body.sidebar-collapsed .sidebar-scroll,body.sidebar-collapsed .sidebar-primary,body.sidebar-collapsed .sidebar-utility-btn b{display:none!important}
body.sidebar-collapsed .workspace-nav{grid-template-columns:1fr;padding-top:12px}body.sidebar-collapsed .workspace-nav-item{min-height:45px}body.sidebar-collapsed .sidebar-utility-btn{justify-content:center;padding:8px}

/* Settings uses user intent grouping; developer tools are a subsection. */
.inspector{width:min(780px,calc(100vw - 24px));display:grid;grid-template-columns:210px minmax(0,1fr);grid-template-rows:auto minmax(0,1fr);overflow:hidden}
.inspector-head{grid-column:1/-1}.inspector-tabs.settings-nav{grid-column:1;grid-row:2;display:flex;flex-direction:column;align-items:stretch;gap:2px;padding:12px;border-right:1px solid var(--border);border-bottom:0;overflow:auto}.inspector-tabs.settings-nav button{width:100%;text-align:left;justify-content:flex-start;border-radius:8px;padding:8px 9px}.inspector-tabs.settings-nav button.active{background:var(--accent-soft);color:#c9eee4}.settings-group-label{font-size:8px;text-transform:uppercase;letter-spacing:.09em;color:var(--muted-2);padding:13px 8px 5px;font-weight:700}.settings-search{display:flex!important;align-items:center!important;gap:7px!important;border:1px solid var(--border);border-radius:10px;padding:7px 9px!important;margin-bottom:4px;background:#252825}.settings-search input{border:0!important;background:transparent!important;padding:0!important;min-width:0;width:100%;outline:0;color:var(--text)!important}.inspector-panel{grid-column:2;grid-row:2;overflow:auto;min-width:0;padding:18px 20px}.settings-help{color:var(--muted);font-size:10px;line-height:1.55}.settings-list{display:flex;flex-direction:column;gap:6px}.settings-list-item{border:1px solid var(--border);border-radius:10px;padding:9px 10px;display:flex;align-items:center;justify-content:space-between;gap:10px}.settings-list-item b{font-size:10px}.settings-list-item small{display:block;color:var(--muted-2);font-size:8.5px}.shortcut-grid{display:grid;grid-template-columns:auto 1fr;gap:6px 10px;margin-top:14px;color:var(--muted);font-size:9px}.shortcut-grid b{color:var(--text-soft);font-weight:550}

/* Inline AI run state replaces full-screen loading for chat generation. */
.turn.live-turn{opacity:1}.live-run-shell{position:relative}.live-stage-row{display:flex;align-items:center;gap:8px;color:var(--muted);font-size:9.5px;margin:2px 0 10px}.live-stage-dot{width:7px;height:7px;border-radius:50%;background:var(--accent);box-shadow:0 0 0 4px rgba(47,155,129,.09);animation:runPulse 1.3s ease-in-out infinite}.live-stage-progress{height:2px;flex:1;max-width:120px;border-radius:99px;background:rgba(255,255,255,.07);overflow:hidden}.live-stage-progress i{display:block;height:100%;background:var(--accent);width:18%;transition:width .18s ease}.thinking-panel{border-left:2px solid rgba(163,139,226,.32);margin:6px 0 14px;padding-left:10px;color:var(--muted)}.thinking-panel summary{cursor:pointer;font-size:9.5px;color:#b8b0cc;list-style:none}.thinking-panel summary::-webkit-details-marker{display:none}.thinking-panel pre{white-space:pre-wrap;word-break:break-word;font:9.5px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace;color:#969d98;max-height:220px;overflow:auto;margin:8px 0 0}.story-output.live-output{white-space:pre-wrap}.stream-caret::after{content:"";display:inline-block;width:7px;height:1.05em;margin-left:3px;vertical-align:-2px;background:var(--accent);animation:caretBlink .85s steps(1) infinite}.generate-btn.generating{background:#414541;color:#eee}.quality-chip{border:1px solid rgba(78,193,156,.18);border-radius:999px;padding:4px 7px;color:#87cbb6;font:8.5px ui-monospace,SFMono-Regular,Menlo,monospace}.quality-chip.warning{color:#dfb66f;border-color:rgba(230,175,92,.23)}.turn-status-badge{border:1px solid var(--border);border-radius:999px;padding:4px 7px;color:var(--muted);font-size:8.5px}.turn-status-badge.cancelled,.turn-status-badge.failed{color:#dc9b76;border-color:rgba(223,114,114,.2)}
@keyframes runPulse{0%,100%{opacity:.45;transform:scale(.8)}50%{opacity:1;transform:scale(1)}}@keyframes caretBlink{0%,45%{opacity:1}46%,100%{opacity:0}}
@media (prefers-reduced-motion:reduce){.live-stage-dot,.stream-caret::after{animation:none}}

/* Manuscript focus mode. */
body.focus-mode .workspace-sidebar,body.focus-mode .topbar,body.focus-mode .draft-sidecar,body.focus-mode .document-rail{display:none!important}body.focus-mode .workbench{margin-left:0!important}body.focus-mode #draftView .three-pane-layout{display:block}body.focus-mode .draft-editor-pane{max-width:900px;margin:0 auto;min-height:100vh;border:0}body.focus-mode .draft-toolbar{position:sticky;top:0;background:rgba(32,34,32,.94);backdrop-filter:blur(14px);z-index:2}

@media(max-width:760px){.inspector{grid-template-columns:1fr;grid-template-rows:auto auto minmax(0,1fr)}.inspector-tabs.settings-nav{grid-column:1;grid-row:2;flex-direction:row;overflow:auto;border-right:0;border-bottom:1px solid var(--border)}.inspector-tabs.settings-nav .settings-group-label,.inspector-tabs.settings-nav .settings-search{display:none!important}.inspector-panel{grid-column:1;grid-row:3}.workspace-nav{grid-template-columns:repeat(3,1fr)}}
'''
write("src/interface/web/static/arline.css", css)


# ---------------------------------------------------------------------------
# JS: view-aware rail, settings grouping, inline stream, quality/retry/thinking,
# focus mode, and stable deep-link view hashes.
# ---------------------------------------------------------------------------
js = read("src/interface/web/static/arline.js")
js = replace_once(js, '  draftTimer: null,\n};', '  draftTimer: null,\n  activeGenerationController: null,\n  liveRun: null,\n};', "streaming state")
js = replace_once(js, '  state.activeView = view;\n', '  state.activeView = view;\n  document.body.dataset.activeView = view;\n  const routeName = view === "draft" ? "manuscript" : view === "world" ? "library" : view;\n  if (!options.fromHash && location.hash !== `#/${routeName}`) history.replaceState(null, "", `#/${routeName}`);\n', "setView route state")

new_turn_html = r'''function turnHTML(turn) {
  const story = turn.feedback_status === "edited_accept" && turn.edited_story ? turn.edited_story : turn.story;
  const stats = turn.stats || {};
  const total = stats.total_output_tokens || 0;
  const reason = stats.reasoning_output_tokens || 0;
  const visible = Math.max(0, total - reason);
  const quality = turn.post_validation?.quality_report || null;
  const runStatus = stats.run_status || "completed";
  const thinking = turn.reasoning_text && state.config?.show_reasoning !== false
    ? `<details class="thinking-panel"><summary>Thinking${reason ? ` · ${reason} tokens` : ""}</summary><pre>${escapeHTML(turn.reasoning_text)}</pre></details>` : "";
  const qualityChip = quality ? `<button class="quality-chip quality-turn ${quality.issue_count ? "warning" : ""}">Quality ${quality.score ?? "—"}${quality.issue_count ? ` · ${quality.issue_count} issues` : ""}</button>` : "";
  return `<article class="turn" data-turn-id="${turn.id}">
    <div class="turn-user"><div class="user-bubble">${escapeHTML(turn.user_prompt)}</div></div>
    <div class="turn-assistant"><div class="assistant-head"><div class="assistant-meta"><span class="run-chip">${escapeHTML(turn.run_id)}</span><span>${escapeHTML(turn.model || "model")}</span><span>${escapeHTML(turn.mode)} · ${escapeHTML(turn.reasoning)}</span>${runStatus !== "completed" ? `<span class="turn-status-badge ${escapeHTML(runStatus)}">${escapeHTML(runStatus)}</span>` : ""}${turn.feedback_status && turn.feedback_status !== "unreviewed" ? `<span class="feedback-badge ${turn.feedback_status}">${escapeHTML(turn.feedback_status)}</span>` : ""}${qualityChip}</div><div class="assistant-actions"><button class="tiny-btn retry-turn">↻ Retry</button><button class="tiny-btn fork-turn">↗ Fork here</button><button class="tiny-btn state-turn">∆ State</button><button class="tiny-btn copy-turn">Copy</button><button class="tiny-btn inspect-turn">Inspect</button><button class="tiny-btn save-turn">Save run</button></div></div>
    ${thinking}${turn.feedback_status === "edited_accept" ? `<div class="edited-marker">Human-edited accepted version</div>` : ""}<div class="story-output">${storyHTML(story)}</div>
    <div class="usage-strip">${stats.input_tokens ? `<span class="usage-pill">${stats.input_tokens} in</span>` : ""}${visible ? `<span class="usage-pill">${visible} story</span>` : ""}${reason ? `<span class="usage-pill warning">${reason} reasoning</span>` : ""}${stats.tokens_per_second ? `<span class="usage-pill">${Number(stats.tokens_per_second).toFixed(1)} tok/s</span>` : ""}</div>
    <div class="feedback-row"><button class="accept">✓ Accept</button><button class="edit-accept">✎ Edit & Accept</button><button class="reject">✕ Reject</button><button class="quick-from-turn">＋ Create from prose</button><button class="promote">＋ Stage canon change</button></div></div>
  </article>`;
}'''
js = replace_function(js, "turnHTML", new_turn_html)

new_bind = r'''function bindTurnActions() {
  $$(".turn").forEach((node) => {
    const turnId = node.dataset.turnId;
    if (!turnId) return;
    const storyNode = $(".story-output", node);
    const turn = state.activeSession?.turns?.find?.((item) => item.id === turnId);
    $(".copy-turn", node)?.addEventListener("click", () => navigator.clipboard.writeText(storyNode.innerText).then(() => toast("Copied")));
    $(".inspect-turn", node)?.addEventListener("click", () => inspectTurn(turnId));
    $(".save-turn", node)?.addEventListener("click", () => saveRunFromTurn(turnId));
    $(".fork-turn", node)?.addEventListener("click", () => state.activeSession && forkSession(state.activeSession.id, turnId));
    $(".state-turn", node)?.addEventListener("click", () => reviewStateProposals(turnId, storyNode.innerText));
    $(".retry-turn", node)?.addEventListener("click", () => {
      if (!turn) return;
      byId("promptInput").value = turn.user_prompt || "";
      refreshPromptHighlight(); updateBudgetUI(); byId("promptInput").focus();
      generateStory();
    });
    $(".quality-turn", node)?.addEventListener("click", () => turn && showQualityReport(turn));
    $(".quick-from-turn", node)?.addEventListener("click", () => openQuickCreate(window.getSelection()?.toString().trim() || storyNode.innerText.slice(0, 600)));
    $(".accept", node)?.addEventListener("click", () => openFeedback(turnId, "accepted"));
    $(".edit-accept", node)?.addEventListener("click", () => openFeedback(turnId, "edited_accept", storyNode.innerText));
    $(".reject", node)?.addEventListener("click", () => openFeedback(turnId, "rejected"));
    $(".promote", node)?.addEventListener("click", () => openStagedChangeForm(turnId, window.getSelection()?.toString().trim() || storyNode.innerText.slice(0, 300)));
  });
}'''
js = replace_function(js, "bindTurnActions", new_bind)

stream_helpers = r'''function showQualityReport(turn) {
  const report = turn?.post_validation?.quality_report;
  if (!report) return toast("No prose-quality report stored for this turn");
  byId("compareTitle").textContent = `Prose quality · ${report.score ?? "—"}/100`;
  byId("compareBody").innerHTML = report.issues?.length
    ? `<div class="proposal-list">${report.issues.map((issue) => `<article><div><b>${escapeHTML(issue.kind.replaceAll("_", " "))}</b><small>${escapeHTML(issue.severity)}</small></div><p>${escapeHTML(issue.message)}</p>${issue.terms ? `<pre>${escapeHTML(pretty(issue.terms))}</pre>` : ""}</article>`).join("")}</div>`
    : `<div class="empty-state small"><b>No notable surface warnings.</b><span>The validator intentionally flags suspicious prose without rewriting story facts.</span></div>`;
  byId("compareDialog").showModal();
}

function createLiveTurn(payload) {
  byId("chatLanding")?.classList.add("hidden");
  byId("conversationSection")?.classList.remove("hidden");
  const feed = byId("conversationFeed");
  const node = document.createElement("article");
  node.className = "turn live-turn";
  node.innerHTML = `<div class="turn-user"><div class="user-bubble">${escapeHTML(payload.prompt)}</div></div><div class="turn-assistant live-run-shell"><div class="assistant-head"><div class="assistant-meta"><span class="run-chip live-run-id">RUN</span><span>${escapeHTML(payload.model || "model")}</span></div><div class="assistant-actions"><button class="tiny-btn live-copy">Copy partial</button></div></div><div class="live-stage-row"><span class="live-stage-dot"></span><b class="live-stage">Preparing context</b><span class="live-stage-progress"><i></i></span></div><details class="thinking-panel live-thinking hidden"><summary>Thinking</summary><pre></pre></details><div class="story-output live-output stream-caret"></div><div class="feedback-row live-recovery hidden"><button class="live-retry">↻ Retry</button><button class="live-copy-partial">Copy partial</button></div></div>`;
  feed.appendChild(node); node.scrollIntoView({ behavior: "smooth", block: "end" });
  const live = { node, prompt: payload.prompt, answer: "", reasoning: "", quality: null, sessionId: null, runId: null };
  $(".live-copy", node)?.addEventListener("click", () => navigator.clipboard.writeText(live.answer).then(() => toast("Partial response copied")));
  $(".live-copy-partial", node)?.addEventListener("click", () => navigator.clipboard.writeText(live.answer).then(() => toast("Partial response copied")));
  $(".live-retry", node)?.addEventListener("click", () => { byId("promptInput").value = live.prompt; refreshPromptHighlight(); generateStory(); });
  return live;
}

function updateLiveStage(live, message, progress = null) {
  if (!live?.node) return;
  $(".live-stage", live.node).textContent = message || "Working";
  if (progress != null) $(".live-stage-progress i", live.node).style.width = `${Math.max(4, Math.min(100, Number(progress) * 100))}%`;
}

function setGenerateRunning(running) {
  const button = byId("generateBtn");
  button?.classList.toggle("generating", running);
  if (button) { button.textContent = running ? "■" : "↑"; button.setAttribute("aria-label", running ? "Stop generation" : "Generate"); }
}

async function finalizeGenerationResult(result, payload) {
  state.activeRunId = result.run_id;
  state.activeSession = { id: result.session_id, title: result.session_title, workspace_refs: payload.references, scratch_mode: result.scratch_mode };
  state.activeTurn = { id: result.turn_id };
  state.scratchMode = Boolean(result.scratch_mode);
  loadContextResult(result);
  byId("postValidation").textContent = pretty(result.post_validation || {});
  byId("reasoningOutput").textContent = result.reasoning || "No separate reasoning output.";
  byId("statsOutput").textContent = pretty(result.stats || {});
  await Promise.all([loadSessions(), openSession(result.session_id), loadDatasetStats()]);
  updateBudgetUI();
}

async function generateStory() {
  if (state.activeGenerationController) {
    state.activeGenerationController.abort();
    return;
  }
  const payload = promptPayload();
  if (!payload.prompt.trim()) return toast("Write a prompt first");
  if (!payload.model) return toast("Select a model first");
  const live = createLiveTurn(payload);
  state.liveRun = live;
  byId("promptInput").value = ""; refreshPromptHighlight(); updateBudgetUI();
  setGenerateRunning(true);

  try {
    if (payload.generation_mode === "beats") {
      updateLiveStage(live, "Writing story beats");
      const result = await api("/api/generate", { method: "POST", body: payload });
      live.answer = result.story || "";
      $(".live-output", live.node).classList.remove("stream-caret");
      $(".live-output", live.node).innerHTML = storyHTML(live.answer);
      await finalizeGenerationResult(result, payload);
      return;
    }

    const controller = new AbortController();
    state.activeGenerationController = controller;
    const response = await fetch("/api/generate/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    let finalResult = null;
    await window.ArlineStream.consume(response, async ({ type, data }) => {
      if (type === "run.start") {
        live.sessionId = data.session_id; live.runId = data.run_id;
        $(".live-run-id", live.node).textContent = data.run_id || "RUN";
      } else if (type === "stage") {
        updateLiveStage(live, data.content || data.state || "Working", data.progress);
      } else if (type === "reasoning.delta") {
        live.reasoning += data.content || "";
        const panel = $(".live-thinking", live.node);
        panel?.classList.remove("hidden");
        $("pre", panel).textContent = live.reasoning;
      } else if (type === "answer.delta") {
        live.answer += data.content || "";
        const output = $(".live-output", live.node); output.textContent = live.answer;
        live.node.scrollIntoView({ behavior: "auto", block: "end" });
      } else if (type === "quality") {
        live.quality = data;
      } else if (type === "done") {
        finalResult = data;
      } else if (type === "error") {
        throw new Error(data.message || data.detail || "Generation failed");
      }
    });
    if (!finalResult) throw new Error("Generation stream ended without a final result");
    $(".live-output", live.node).classList.remove("stream-caret");
    $(".live-output", live.node).innerHTML = storyHTML(finalResult.story || live.answer);
    updateLiveStage(live, "Complete", 1);
    await finalizeGenerationResult(finalResult, payload);
  } catch (error) {
    const aborted = error?.name === "AbortError";
    updateLiveStage(live, aborted ? "Stopped" : "Generation interrupted");
    $(".live-output", live.node)?.classList.remove("stream-caret");
    $(".live-recovery", live.node)?.classList.remove("hidden");
    toast(aborted ? "Generation stopped; partial prose is preserved when available" : `Generation failed: ${error.message}`, 6000);
    if (live.sessionId) setTimeout(() => openSession(live.sessionId).catch(() => {}), 650);
  } finally {
    state.activeGenerationController = null; state.liveRun = null; setGenerateRunning(false);
  }
}'''
js = replace_function(js, "generateStory", stream_helpers)

# add UI helpers before attachEvents
helpers = r'''function applySettingsFilter() {
  const query = (byId("settingsSearch")?.value || "").trim().toLowerCase();
  $$("#inspectorTabs [data-inspector-tab]").forEach((button) => {
    button.classList.toggle("hidden", Boolean(query) && !button.textContent.toLowerCase().includes(query));
  });
}

async function loadBackups() {
  if (!byId("backupList")) return;
  try {
    const data = await api("/api/backups");
    byId("storageSummary").innerHTML = `<b>${escapeHTML(data.database_name)}</b><br>${Number(data.database_bytes || 0).toLocaleString()} bytes · ${data.backups.length} migration backup(s)`;
    byId("backupList").innerHTML = data.backups.length ? data.backups.map((item) => `<div class="settings-list-item"><div><b>${escapeHTML(item.name)}</b><small>${formatDate(item.modified_at)} · ${Number(item.bytes).toLocaleString()} bytes</small></div><span class="revision-badge">backup</span></div>`).join("") : `<div class="empty-note">No migration backups yet.</div>`;
  } catch (error) { byId("backupList").innerHTML = `<div class="empty-note">${escapeHTML(error.message)}</div>`; }
}

function toggleFocusMode(force = null) {
  const next = force == null ? !document.body.classList.contains("focus-mode") : Boolean(force);
  document.body.classList.toggle("focus-mode", next);
  if (byId("focusModeBtn")) byId("focusModeBtn").textContent = next ? "Exit focus" : "Focus";
  saveLocalPrefs({ focusMode: next });
}

'''
attach_start = js.index("function attachEvents()")
js = js[:attach_start] + helpers + js[attach_start:]

js = replace_once(js, '  on("activityBtn", "click", openActivityCenter);', '  on("activityBtn", "click", openActivityCenter);\n  on("brandBtn", "click", () => setView("home"));', "brand home binding")
js = js.replace('  on("datasetFooterBtn", "click", () => setView("data"));\n', '', 1)
js = replace_once(js, '  on("settingsBtn", "click", () => openInspector("runtime"));', '  on("settingsBtn", "click", () => openInspector("runtime"));\n  on("openFeedbackLabBtn", "click", () => { closeInspector(); setView("data"); });\n  on("settingsSearch", "input", applySettingsFilter);\n  on("refreshBackupsBtn", "click", loadBackups);\n  on("settingsDensity", "change", (event) => { document.body.dataset.density = event.target.value; saveLocalPrefs({ density:event.target.value }); });\n  on("settingsSidebarMode", "change", (event) => { const collapsed=event.target.value === "collapsed"; document.body.classList.toggle("sidebar-collapsed",collapsed); saveLocalPrefs({sidebarCollapsed:collapsed}); });', "settings bindings")
js = replace_once(js, '  on("saveDraftBtn", "click", () => saveDraft("checkpoint"));', '  on("saveDraftBtn", "click", () => saveDraft("checkpoint"));\n  on("focusModeBtn", "click", () => toggleFocusMode());', "focus binding")
js = replace_once(js, '    if (mod && key === "s" && state.activeView === "draft") { event.preventDefault(); if (state.activeDocument) saveDraft("checkpoint"); else toast("Open a manuscript document first"); return; }', '    if (mod && event.shiftKey && key === "f" && state.activeView === "draft") { event.preventDefault(); toggleFocusMode(); return; }\n    if (mod && key === "s" && state.activeView === "draft") { event.preventDefault(); if (state.activeDocument) saveDraft("checkpoint"); else toast("Open a manuscript document first"); return; }', "focus shortcut")
js = replace_once(js, '  refreshPromptHighlight(); updateScratchUI(); updateNavigationButtons();', '  const prefs = localPrefs();\n  if (byId("settingsDensity")) byId("settingsDensity").value = prefs.density || "comfortable";\n  if (byId("settingsSidebarMode")) byId("settingsSidebarMode").value = prefs.sidebarCollapsed ? "collapsed" : "expanded";\n  if (prefs.focusMode && state.activeView === "draft") toggleFocusMode(true);\n  refreshPromptHighlight(); updateScratchUI(); updateNavigationButtons();', "attach final state")
js = replace_once(js, '    const preferred = localPrefs().lastView || "home";\n    setView(preferred, { record: false });', '    const route = location.hash.replace(/^#\//, "");\n    const routeView = route === "manuscript" ? "draft" : route === "library" ? "world" : ["home","chat"].includes(route) ? route : null;\n    const preferred = routeView || localPrefs().lastView || "home";\n    setView(preferred, { record: false, fromHash: true });', "initial deep link")
js = replace_once(js, '  on("inspectorScrim", "click", closeInspector);', '  on("inspectorScrim", "click", closeInspector);\n  window.addEventListener("hashchange", () => { const route=location.hash.replace(/^#\//,""); const view=route==="manuscript"?"draft":route==="library"?"world":route; if(["home","chat","draft","world","data"].includes(view) && view!==state.activeView) setView(view,{record:false,fromHash:true}); });', "hashchange")
write("src/interface/web/static/arline.js", js)


# ---------------------------------------------------------------------------
# Python app: quality report on all generations, SSE streaming endpoint,
# model capability metadata, and backup-manager read API.
# ---------------------------------------------------------------------------
app = read("src/interface/web/app.py")
app = replace_once(app, 'from collections import OrderedDict\n', 'from collections import OrderedDict\nimport asyncio\n', "asyncio import")
app = replace_once(app, 'from fastapi import FastAPI, HTTPException, Query\nfrom fastapi.responses import FileResponse\n', 'from fastapi import FastAPI, HTTPException, Query\nfrom fastapi.responses import FileResponse, StreamingResponse\n', "streaming response import")
app = replace_once(app, 'from src.service import ArlineService, ArtifactStore, make_run_id\n', 'from src.service import ArlineService, ArtifactStore, make_run_id\nfrom src.service.streaming import StreamingArlineService\nfrom src.writer.quality import ProseQualityAnalyzer\n', "streaming service import")

# enrich model metadata in both model-list endpoints
model_snippet = '''                    "reasoning": (item.get("capabilities") or {}).get("reasoning") or item.get("reasoning") or {},
                    "format": item.get("format"),'''
model_replacement = '''                    "reasoning": (item.get("capabilities") or {}).get("reasoning") or item.get("reasoning") or {},
                    "format": item.get("format"),
                    "capabilities": {
                        "provider": "lmstudio",
                        "context_window": item.get("max_context_length"),
                        "streaming": True,
                        "separate_reasoning_stream": bool(((item.get("capabilities") or {}).get("reasoning") or item.get("reasoning") or {}).get("allowed_options")),
                        "reasoning_modes": list((((item.get("capabilities") or {}).get("reasoning") or item.get("reasoning") or {}).get("allowed_options") or [])),
                        "sampling_controls": ["temperature", "top_p", "top_k", "min_p", "repeat_penalty"],
                    },'''
if app.count(model_snippet) != 2: raise SystemExit(f"model capability anchors={app.count(model_snippet)}")
app = app.replace(model_snippet, model_replacement)

backup_endpoint = '''    @app.get("/api/backups")
    def list_backups():
        cfg = RuntimeConfig.load(config_path)
        database_path = Path(cfg.workspace.database_path)
        backup_dir = database_path.parent / "backups"
        rows = []
        if backup_dir.exists():
            for path in sorted(backup_dir.glob("*"), key=lambda item: item.stat().st_mtime, reverse=True):
                if not path.is_file():
                    continue
                stat = path.stat()
                rows.append({"name": path.name, "bytes": stat.st_size, "modified_at": __import__("datetime").datetime.fromtimestamp(stat.st_mtime, __import__("datetime").timezone.utc).isoformat()})
        return {
            "database_name": database_path.name,
            "database_bytes": database_path.stat().st_size if database_path.exists() else 0,
            "backups": rows,
        }

'''
app = replace_once(app, '    @app.get("/api/models")\n', backup_endpoint + '    @app.get("/api/models")\n', "backup endpoint")

# sync generation quality report
app = replace_once(app, '        post = bundle.post_validation.to_dict() if bundle.post_validation else {}\n', '        post = bundle.post_validation.to_dict() if bundle.post_validation else {}\n        quality_report = ProseQualityAnalyzer().analyze(bundle.story)\n        post["quality_report"] = quality_report\n', "sync quality report")
app = replace_once(app, '            "post_validation": post,\n', '            "post_validation": post,\n            "quality_report": quality_report,\n', "sync quality response")

stream_endpoint = r'''    @app.post("/api/generate/stream")
    async def generate_stream(payload: PromptPayload):
        if not payload.prompt.strip():
            raise HTTPException(400, "Prompt is empty")
        if payload.generation_mode != "single":
            raise HTTPException(400, "Inline streaming currently supports single-response mode; beats use the normal generation endpoint")

        async def events():
            existing_session = None
            if payload.session_id:
                try:
                    existing_session = history.get_session_meta(payload.session_id)
                except KeyError:
                    yield _sse("error", {"message": "Session not found"})
                    return
            cfg = _apply_payload(RuntimeConfig.load(config_path), payload)
            project_id = payload.project_id or (existing_session or {}).get("project_id")
            world_id = payload.world_id or (existing_session or {}).get("world_id")
            branch_id = payload.branch_id or (existing_session or {}).get("branch_id")
            refs = [item.model_dump() for item in payload.references]
            if not refs and existing_session:
                refs = existing_session.get("workspace_refs") or []

            ws_context = None
            if cfg.workspace.context_enabled and (project_id or world_id):
                try:
                    ws_context = workspace_context.resolve(project_id=project_id, world_id=world_id, branch_id=branch_id, references=refs, recipe_id=payload.context_recipe_id)
                except (KeyError, ValueError) as exc:
                    yield _sse("error", {"message": f"Workspace context error: {exc}"})
                    return
            session_context = ""
            if existing_session is not None and cfg.history.smart_hybrid_continuity and payload.input_mode == "smart_hybrid":
                context_policy = (ws_context.scope.get("context_policy") if ws_context else {}) or {}
                requested_turns = context_policy.get("recent_turns", cfg.history.continuity_turns)
                try: requested_turns = max(1, min(50, int(requested_turns)))
                except (TypeError, ValueError): requested_turns = cfg.history.continuity_turns
                session_context = history.build_continuity_context(existing_session["id"], max_turns=requested_turns, max_chars=cfg.history.continuity_chars)

            if existing_session is not None:
                session = existing_session
                history.update_session(session["id"], project_id=project_id, world_id=world_id, branch_id=branch_id, folder_id=None, workspace_refs=refs, scratch_mode=payload.scratch_mode)
            else:
                session = history.create_session(prompt=payload.prompt, project_id=project_id, world_id=world_id, branch_id=branch_id, folder_id=None, session_kind="chat", workspace_refs=refs, scratch_mode=payload.scratch_mode)

            run_id = make_run_id(payload.input_mode, payload.reasoning, payload.timezone)
            base = run_id; index = 2
            while saved_cache.get(run_id) is not None:
                run_id = f"{base}-{index:02d}"; index += 1
            yield _sse("run.start", {"run_id": run_id, "session_id": session["id"], "session_title": session["title"]})

            prepared = None
            partial_story = ""
            partial_reasoning = ""
            try:
                streamer = StreamingArlineService(cfg)
                async for event in streamer.stream(payload.prompt, mode=payload.input_mode, session_context=session_context or None, workspace_context=ws_context):
                    event_type = event.get("type")
                    if event_type == "_prepared":
                        prepared = event["prepared"]
                        continue
                    if event_type == "answer.delta": partial_story += event.get("content", "")
                    if event_type == "reasoning.delta": partial_reasoning += event.get("content", "")
                    if event_type != "_complete":
                        yield _sse(event_type or "message", event)
                        continue

                    bundle = event["bundle"]
                    quality_report = event["quality"]
                    post = bundle.post_validation.to_dict() if bundle.post_validation else {}
                    post["quality_report"] = quality_report
                    saved_cache.put(CachedRun(config=cfg, bundle=bundle, run_id=run_id))
                    lineage = {
                        "application_version": STUDIO_VERSION,
                        "wcf_version": bundle.analysis.writer_context.version,
                        "aif_core_profile": "teacher",
                        "projection_mode": cfg.projection.mode,
                        "narrative_runtime_version": bundle.analysis.narrative_runtime.version,
                        "narrative_brief_version": bundle.analysis.narrative_brief.version,
                        "workspace_context_version": ws_context.version if ws_context else None,
                        "validator_version": post.get("metrics", {}).get("validator_version") if post else None,
                        "model": cfg.lmstudio.model,
                        "run_status": "completed",
                    }
                    turn = history.add_turn(
                        session["id"], run_id=run_id, user_prompt=payload.prompt, story=bundle.story,
                        model=cfg.lmstudio.model, mode=cfg.writer.input_mode, reasoning=cfg.generation.reasoning,
                        projection_mode=cfg.projection.mode, reasoning_text=bundle.reasoning or "", stats=bundle.stats,
                        wcf=bundle.analysis.rendered_context.text, aif_core=bundle.analysis.aif_core,
                        session_context=session_context, workspace_context=ws_context.text if ws_context else "",
                        workspace_scope=ws_context.scope if ws_context else {}, workspace_refs=refs, lineage=lineage,
                        projections=[x.to_dict() for x in bundle.analysis.writer_context.projections], post_validation=post,
                        wcf_validation=bundle.analysis.wcf_validation.to_dict(),
                    )
                    final_session = history.get_session_meta(session["id"])
                    result = {
                        "run_id": run_id, "session_id": final_session["id"], "session_title": final_session["title"], "turn_id": turn["id"],
                        "continuity_context_used": bool(session_context), "story": bundle.story,
                        "wcf": bundle.analysis.rendered_context.text, "aif_core": bundle.analysis.aif_core,
                        "narrative_brief": bundle.analysis.narrative_brief.to_dict(), "workspace_context": ws_context.to_dict() if ws_context else {},
                        "context_breakdown": _context_breakdown(cfg, bundle.analysis, session_context=session_context),
                        "projections": [x.to_dict() for x in bundle.analysis.writer_context.projections],
                        "reasoning": bundle.reasoning if cfg.ui.show_reasoning else "", "stats": bundle.stats,
                        "post_validation": post, "quality_report": quality_report,
                        "wcf_validation": bundle.analysis.wcf_validation.to_dict(), "summary": _analysis_summary(bundle.analysis),
                        "trace_choices": _trace_choices(bundle.analysis), "scratch_mode": payload.scratch_mode,
                    }
                    yield _sse("quality", quality_report)
                    yield _sse("done", result)
            except asyncio.CancelledError:
                if partial_story and prepared is not None:
                    quality_report = ProseQualityAnalyzer().analyze(partial_story)
                    try:
                        history.add_turn(
                            session["id"], run_id=run_id, user_prompt=payload.prompt, story=partial_story,
                            model=cfg.lmstudio.model, mode=cfg.writer.input_mode, reasoning=cfg.generation.reasoning,
                            projection_mode=cfg.projection.mode, reasoning_text=partial_reasoning,
                            stats={"run_status": "cancelled", "partial": True}, wcf=prepared.analysis.rendered_context.text,
                            aif_core=prepared.analysis.aif_core, session_context=session_context,
                            workspace_context=ws_context.text if ws_context else "", workspace_scope=ws_context.scope if ws_context else {},
                            workspace_refs=refs, lineage={"application_version": STUDIO_VERSION, "run_status": "cancelled", "model": cfg.lmstudio.model},
                            projections=[x.to_dict() for x in prepared.analysis.writer_context.projections],
                            post_validation={"quality_report": quality_report}, wcf_validation=prepared.analysis.wcf_validation.to_dict(),
                        )
                    except Exception:
                        pass
                raise
            except Exception as exc:
                if partial_story and prepared is not None:
                    try:
                        history.add_turn(
                            session["id"], run_id=run_id, user_prompt=payload.prompt, story=partial_story,
                            model=cfg.lmstudio.model, mode=cfg.writer.input_mode, reasoning=cfg.generation.reasoning,
                            projection_mode=cfg.projection.mode, reasoning_text=partial_reasoning,
                            stats={"run_status": "failed", "partial": True, "error": str(exc)}, wcf=prepared.analysis.rendered_context.text,
                            aif_core=prepared.analysis.aif_core, session_context=session_context,
                            workspace_context=ws_context.text if ws_context else "", workspace_scope=ws_context.scope if ws_context else {},
                            workspace_refs=refs, lineage={"application_version": STUDIO_VERSION, "run_status": "failed", "model": cfg.lmstudio.model},
                            projections=[x.to_dict() for x in prepared.analysis.writer_context.projections],
                            post_validation={"quality_report": ProseQualityAnalyzer().analyze(partial_story)}, wcf_validation=prepared.analysis.wcf_validation.to_dict(),
                        )
                    except Exception:
                        pass
                yield _sse("error", {"message": str(exc)})

        return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

'''
# local helper available to both endpoint and tests
sse_helper = '''    def _sse(event: str, payload: dict[str, Any]) -> str:\n        return f"event: {event}\\ndata: {json.dumps(payload, ensure_ascii=False, default=str)}\\n\\n"\n\n'''
app = replace_once(app, '    @app.post("/api/generate")\n', sse_helper + stream_endpoint + '    @app.post("/api/generate")\n', "streaming endpoint")
write("src/interface/web/app.py", app)


# ---------------------------------------------------------------------------
# Writer contract: stronger language realization without semantic rewriting.
# ---------------------------------------------------------------------------
prompt = read("config/writer_system.txt")
quality_rules = '''
22. Preserve the requested narrative person and pronoun system. Do not drift from first person to second/third person unless dialogue or an explicit POV transition requires it.
23. Produce grammatically complete, idiomatic prose in the user's requested language. Never emit malformed word fragments, accidental suffix corruption, or translationese when a natural construction exists.
24. Prefer concrete action, sensory detail, and spatial description over generic evaluation such as repeated "very", "perfect", "stunning", "sangat", "sempurna", or "memukau".
25. Vary sentence openings and paragraph rhythm. Avoid repeatedly restating the same body feature, visual effect, emotion, or conclusion using near-synonyms.
26. Preserve temporal continuity. If the scene moves from afternoon to evening/night or otherwise jumps in time, provide a natural transition rather than silently changing the time label.
27. Unusual transformations, anatomy, physics, or mechanisms must follow established context. Do not "repair" an intentional fantastical event, but do not invent a new mechanism merely to make it plausible.
28. Perform a silent surface-language check before finalizing: grammar, spelling, pronouns, POV, repetition, and sentence completeness. This check may improve phrasing but must not alter canonical facts or event outcomes.
'''
if "22. Preserve the requested narrative person" not in prompt:
    prompt = prompt.replace("21. The final answer is fiction prose only: no planning notes, constraint discussion, refusals, context commentary, or statements about what you will/will not invent.\n", "21. The final answer is fiction prose only: no planning notes, constraint discussion, refusals, context commentary, or statements about what you will/will not invent.\n" + quality_rules)
write("config/writer_system.txt", prompt)


# ---------------------------------------------------------------------------
# Export quality/inference primitives.
# ---------------------------------------------------------------------------
writer_init = read("src/writer/__init__.py")
if "ProseQualityAnalyzer" not in writer_init:
    writer_init = writer_init.replace('from .validator import PostWriteValidator, PostWriteReport\n', 'from .validator import PostWriteValidator, PostWriteReport\nfrom .quality import ProseQualityAnalyzer\n')
    writer_init = writer_init.replace('"PostWriteReport"]', '"PostWriteReport","ProseQualityAnalyzer"]')
write("src/writer/__init__.py", writer_init)

inference_init = read("src/inference/__init__.py")
if "ModelCapabilities" not in inference_init:
    inference_init += '\nfrom .provider import InferenceProvider, ModelCapabilities\n'
write("src/inference/__init__.py", inference_init)

service_init = read("src/service/__init__.py")
if "StreamingArlineService" not in service_init:
    service_init += '\nfrom .streaming import StreamingArlineService\n'
write("src/service/__init__.py", service_init)


# ---------------------------------------------------------------------------
# Regression tests for final v1.1 boundaries.
# ---------------------------------------------------------------------------
test = r'''from __future__ import annotations

from pathlib import Path
import unittest

from src.runtime.run_state import RunState
from src.writer.quality import ProseQualityAnalyzer

ROOT = Path(__file__).resolve().parents[1]


class V11FinalFoundationTests(unittest.TestCase):
    def test_run_lifecycle_has_terminal_states(self):
        self.assertEqual(RunState.COMPLETED.value, "completed")
        self.assertEqual(RunState.CANCELLED.value, "cancelled")
        self.assertEqual(RunState.FAILED.value, "failed")

    def test_quality_analyzer_flags_pov_and_repetition_without_rewriting(self):
        text = "Aku melihat kamar itu. Aku masuk perlahan. Aku sangat kagum. Aku sangat kagum. Kamu lalu melihatku pada malam hari setelah sore yang sunyi."
        report = ProseQualityAnalyzer().analyze(text)
        self.assertIn("issues", report)
        self.assertEqual(report["policy"], "flag_surface_and_narrative_suspicion_without_rewriting_story_facts")
        self.assertGreaterEqual(report["issue_count"], 1)

    def test_primary_nav_excludes_feedback_lab_and_context_card(self):
        html = (ROOT / "src/interface/web/static/index.html").read_text(encoding="utf-8")
        nav = html.split('<nav class="workspace-nav"', 1)[1].split('</nav>', 1)[0]
        self.assertIn('data-view="chat"', nav)
        self.assertIn('data-view="draft"', nav)
        self.assertIn('data-view="world"', nav)
        self.assertNotIn('data-view="data"', nav)
        self.assertNotIn('data-view="home"', nav)
        self.assertNotIn('id="contextStackCard"', html)
        self.assertIn('data-inspector-tab="review"', html)

    def test_streaming_frontend_and_endpoint_are_wired(self):
        html = (ROOT / "src/interface/web/static/index.html").read_text(encoding="utf-8")
        js = (ROOT / "src/interface/web/static/arline.js").read_text(encoding="utf-8")
        app = (ROOT / "src/interface/web/app.py").read_text(encoding="utf-8")
        self.assertIn('/static/js/stream.js', html)
        self.assertIn('/api/generate/stream', js)
        self.assertIn('@app.post("/api/generate/stream")', app)
        self.assertNotIn('loading(true,payload.generation_mode', js)

    def test_writer_contract_contains_surface_quality_rules(self):
        prompt = (ROOT / "config/writer_system.txt").read_text(encoding="utf-8")
        self.assertIn("Preserve the requested narrative person", prompt)
        self.assertIn("silent surface-language check", prompt)

    def test_grouped_settings_include_storage_and_developer_review(self):
        html = (ROOT / "src/interface/web/static/index.html").read_text(encoding="utf-8")
        self.assertIn('data-inspector-tab="storage"', html)
        self.assertIn('data-inspector-tab="review"', html)
        self.assertIn('id="settingsSearch"', html)


if __name__ == "__main__":
    unittest.main()
'''
write("tests/test_v11_final_foundation.py", test)

# Temporary script deletes itself before the branch commit.
Path(__file__).unlink()
print("v1.1 finalization patch applied")
