"use strict";

// Central command metadata. Execution lives in the single command dispatcher in arline.js.
// Rich `help` metadata is intentionally shared by Ctrl+K and composer slash discovery.
window.ARLINE_COMMANDS = [
  { id: "continue", label: "/continue", description: "Continue the active scene", action: "insert", text: "/continue " },
  { id: "rewrite", label: "/rewrite", description: "Rewrite selected/current material", action: "insert", text: "/rewrite " },
  {
    id: "mono",
    label: "/mono",
    category: "Character Rails",
    description: "Character-aware monologue or expression seed; internal by default, audible delivery supported",
    action: "insert",
    text: "/mono @characterA \"intent or thought\" ",
    help: {
      title: "Monologue / Expression Rail",
      about: "Express a semantic thought or intent through one character while preserving that character's profile, current state, POV, and voice. The seed is not copied literally unless you request literal wording.",
      syntax: "/mono @characterA [internal|spoken|whisper|murmur|mutter] [pacing] \"intent\"",
      examples: [
        { label: "Internal thought", text: "/mono @characterA \"I should not have said that\"" },
        { label: "Quiet audible speech", text: "/mono @characterA whisper \"don't tell @characterB\"" },
        { label: "Slow internal processing", text: "/mono @characterA internal slow \"why hasn't @characterB arrived?\"" },
      ],
      parameters: [
        ["@characterA", "Character whose expression should be realized."],
        ["internal / spoken", "Private thought versus audible lexical speech."],
        ["whisper / murmur / mutter", "Audible delivery; these are not internal thoughts."],
        ["pacing", "auto · immediate · fast · natural · slow · lingering"],
        ["\"intent\"", "Semantic seed. Add literal when wording itself must be preserved."],
      ],
      behavior: [
        "Internal thought remains private to the active POV.",
        "Audible delivery may be heard or reacted to when scene context permits.",
        "Character personality, voice, relationship state, and temporal state constrain realization.",
      ],
      memory: ["Generation only", "Does not assert a canon fact", "Does not commit canon"],
    },
  },
  {
    id: "dia",
    label: "/dia",
    category: "Character Rails",
    description: "Character-aware interaction rail; adaptive beats instead of fixed alternating turns",
    action: "insert",
    text: "/dia @characterA @characterB \"topic or interaction goal\" ",
    help: {
      title: "Dialogue / Interaction Rail",
      about: "Generate a character-aware interaction around a semantic topic or goal. Speaker order is adaptive: one character may speak repeatedly, remain silent, interrupt, act, or internally react when POV allows it.",
      syntax: "/dia @characterA @characterB [pacing] [curve=...] [length=...] [until=\"...\"] \"topic\"",
      examples: [
        { label: "Casual topic", text: "/dia @characterA @characterB \"play a game together\"" },
        { label: "Slow awkward exchange", text: "/dia @characterA @characterB slow \"an awkward apology\"" },
        { label: "Changing intensity", text: "/dia @characterA @characterB slow curve=wave \"discuss moving away\"" },
      ],
      parameters: [
        ["@characterA@characterB", "Participants. More than two characters may be supplied when needed."],
        ["pacing", "auto · immediate · fast · natural · slow · lingering"],
        ["curve=...", "auto · flat · rising · falling · wave · spike"],
        ["length=...", "auto · short · medium · long; a soft shape hint, never a turn quota."],
        ["until=\"...\"", "Optional natural stopping target."],
        ["\"topic\"", "Semantic interaction seed, not literal dialogue."],
      ],
      behavior: [
        "Speaker order is adaptive rather than A → B → A → B.",
        "Actions, silence, interruptions, and non-lexical vocalization are valid beats.",
        "Internal thoughts may appear only for POV-authorized characters.",
        "Pacing controls meaningful intermediate reactions, not filler word count.",
      ],
      memory: ["Generation only", "The topic does not mean the conversation already happened", "Only accepted generated prose may later reach extractor/review"],
    },
  },
  {
    id: "ambience",
    label: "/ambience",
    category: "Scene Rails",
    description: "Guide scene atmosphere, sensory palette, and pacing without changing canon",
    action: "insert",
    text: "/ambience slow \"scene atmosphere\" ",
    help: {
      title: "Ambience Rail",
      about: "Temporarily steer atmosphere and sensory emphasis for the current generation without silently turning descriptive flavor into persistent world truth.",
      syntax: "/ambience [@locationA] [pacing] \"atmosphere\"",
      examples: [
        { label: "General atmosphere", text: "/ambience slow \"rain outside, dim lighting, distant traffic\"" },
        { label: "Location-focused", text: "/ambience @locationA lingering \"quiet after closing time, sparse footsteps, cold fluorescent light\"" },
      ],
      parameters: [
        ["@locationA", "Optional scene/location reference when a specific place should anchor the ambience."],
        ["pacing", "Controls how much room ambience receives between meaningful scene beats."],
        ["\"atmosphere\"", "Sensory palette or environmental emphasis."],
      ],
      behavior: [
        "May guide soundscape, lighting, temperature, background motion, and descriptive density.",
        "Must remain compatible with the active scene and scoped world evidence.",
        "Does not silently create persistent location facts."],
      memory: ["Generation only", "Not a World Bible update", "Accepted prose is handled by the normal review path"],
    },
  },
  {
    id: "intimacy",
    label: "/intimacy",
    category: "Scene Rails",
    description: "Guide character-aware intimate scene dynamics, pacing, and aftermath",
    action: "insert",
    text: "/intimacy @characterA slow \"scene intent\" ",
    help: {
      title: "Intimacy Scene Rail",
      about: "Steer an intimate scene through the same character-aware Scene Dynamics system as dialogue: pacing, reactions, silence, internal thought, ambience, and aftermath remain constrained by character and scene state.",
      syntax: "/intimacy @characterA[@characterB] [solo] [pacing] [curve=...] \"scene intent\"",
      examples: [
        { label: "Two-character scene", text: "/intimacy @characterA @characterB slow \"reconciliation and emotional vulnerability\"" },
        { label: "Solo scene", text: "/intimacy @characterA solo lingering \"vulnerability and quiet aftermath\"" },
      ],
      parameters: [
        ["@characterA[@characterB]", "One or more participants."],
        ["solo", "Explicitly selects a one-character scene."],
        ["pacing", "auto · immediate · fast · natural · slow · lingering"],
        ["curve=...", "How scene intensity changes over meaningful beats."],
        ["\"scene intent\"", "Narrative purpose or emotional seed."],
      ],
      behavior: [
        "Uses adaptive Scene Dynamics rather than fixed choreography.",
        "Preserves POV, character agency, continuity, and meaningful aftermath.",
        "Expression channels may include speech, internal thought, action, silence, ambience, and contextual vocalization."],
      memory: ["Generation only", "Command does not prove an intimate event occurred", "Persistent consequences require accepted prose and review"],
    },
  },
  { id: "intuition", label: "/intuition", category: "Deliberation", description: "Ask what most naturally follows without making it Canon", action: "insert", text: "/intuition @scene \"what should naturally happen next?\" " },
  { id: "alternatives", label: "/alternatives", category: "Deliberation", description: "Generate several non-canonical next-beat alternatives", action: "insert", text: "/alternatives @scene count=4 \"next beat\" " },
  { id: "describe", label: "/describe", category: "Writing", description: "Describe a subject using selector-aware grounding", action: "insert", text: "/describe @characterA.appearance detail=high " },
  { id: "pov", label: "/pov", category: "Writing", description: "Temporarily emphasize a POV for this generation", action: "insert", text: "/pov @characterA \"scene intent\" " },
  { id: "pace", label: "/pace", category: "Writing", description: "Temporarily steer narrative pacing", action: "insert", text: "/pace slow \"scene goal\" " },
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

function escapeCommandHTML(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function commandHelpRuntimeState() {
  return window.ArlineRuntime?.getState?.() || null;
}

function commandHelpItemForIndex(index) {
  const state = commandHelpRuntimeState();
  return state?.commandResults?.[index] || null;
}

function hideCommandHelp() {
  const dialog = document.getElementById("commandDialog");
  const card = document.getElementById("commandHelpCard");
  if (!dialog || !card) return;
  dialog.classList.remove("has-command-help");
  card.hidden = true;
  card.replaceChildren();
}

function insertCommandHelpExample(text) {
  const dialog = document.getElementById("commandDialog");
  const input = document.getElementById("promptInput");
  if (!input) return;
  const start = Number.isInteger(input.selectionStart) ? input.selectionStart : input.value.length;
  const end = Number.isInteger(input.selectionEnd) ? input.selectionEnd : start;
  const before = input.value.slice(0, start);
  const after = input.value.slice(end);
  const prefix = before && !/\s$/.test(before) ? "\n" : "";
  const suffix = after && !/^\s/.test(after) ? "\n" : "";
  const inserted = String(text || "").trimEnd();
  const insertStart = before.length + prefix.length;
  input.value = before + prefix + inserted + suffix + after;

  const placeholder = inserted.match(/@(character|location|item|organization)[A-Z]?/);
  if (placeholder && placeholder.index != null) {
    const selectStart = insertStart + placeholder.index + 1;
    input.setSelectionRange(selectStart, selectStart + placeholder[0].length - 1);
  } else {
    const cursor = insertStart + inserted.length;
    input.setSelectionRange(cursor, cursor);
  }
  input.dispatchEvent(new Event("input", { bubbles: true }));
  dialog?.close();
  input.focus();
}

function showCommandHelp(item) {
  if (!item?.help) return;
  const dialog = document.getElementById("commandDialog");
  const card = document.getElementById("commandHelpCard");
  if (!dialog || !card) return;
  const help = item.help;
  const examples = (help.examples || []).map((example, index) => `
    <article class="command-help-example">
      <div><small>${escapeCommandHTML(example.label || `Example ${index + 1}`)}</small><code>${escapeCommandHTML(example.text)}</code></div>
      <button type="button" class="command-help-use" data-command-example="${index}">Use</button>
    </article>`).join("");
  const parameters = (help.parameters || []).map(([name, description]) => `
    <div class="command-help-parameter"><code>${escapeCommandHTML(name)}</code><span>${escapeCommandHTML(description)}</span></div>`).join("");
  const behavior = (help.behavior || []).map((line) => `<li>${escapeCommandHTML(line)}</li>`).join("");
  const memory = (help.memory || []).map((line) => `<li>${escapeCommandHTML(line)}</li>`).join("");

  card.innerHTML = `
    <header class="command-help-head">
      <div><span class="command-help-category">${escapeCommandHTML(item.category || "Command")}</span><h3>${escapeCommandHTML(item.label)} <small>${escapeCommandHTML(help.title || "Guide")}</small></h3></div>
      <button type="button" class="command-help-close" aria-label="Close command guide">×</button>
    </header>
    <p class="command-help-about">${escapeCommandHTML(help.about || item.description || "")}</p>
    <section><span class="command-help-label">Syntax</span><code class="command-help-syntax">${escapeCommandHTML(help.syntax || item.text || item.label)}</code></section>
    <section><span class="command-help-label">Examples</span><div class="command-help-examples">${examples}</div></section>
    ${parameters ? `<section><span class="command-help-label">Parameters</span><div class="command-help-parameters">${parameters}</div></section>` : ""}
    ${behavior ? `<section><span class="command-help-label">Behavior</span><ul>${behavior}</ul></section>` : ""}
    ${memory ? `<section class="command-help-memory"><span class="command-help-label">Memory & canon</span><ul>${memory}</ul></section>` : ""}
    <footer><button type="button" class="command-help-insert">Insert template</button></footer>`;

  card.hidden = false;
  dialog.classList.add("has-command-help");
  card.querySelector(".command-help-close")?.addEventListener("click", hideCommandHelp);
  card.querySelector(".command-help-insert")?.addEventListener("click", () => insertCommandHelpExample(item.text || item.label));
  card.querySelectorAll("[data-command-example]").forEach((button) => button.addEventListener("click", () => {
    const example = help.examples?.[Number(button.dataset.commandExample)];
    if (example?.text) insertCommandHelpExample(example.text);
  }));
}

function enhanceCommandHelpRows() {
  const host = document.getElementById("commandResults");
  if (!host) return;
  host.querySelectorAll(".command-item[data-index]").forEach((row) => {
    const index = Number(row.dataset.index);
    const item = commandHelpItemForIndex(index);
    const existing = row.querySelector(".command-info-button");
    if (!item?.help) {
      existing?.remove();
      return;
    }
    if (existing) return;
    const info = document.createElement("span");
    info.className = "command-info-button";
    info.setAttribute("role", "button");
    info.setAttribute("tabindex", "0");
    info.setAttribute("aria-label", `Show ${item.label} usage guide`);
    info.title = "Usage guide";
    info.innerHTML = "<span aria-hidden=\"true\">ⓘ</span>";
    const activate = (event) => {
      event.preventDefault();
      event.stopPropagation();
      showCommandHelp(item);
    };
    info.addEventListener("pointerdown", (event) => event.stopPropagation());
    info.addEventListener("click", activate);
    info.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") activate(event);
    });
    row.appendChild(info);
  });

  const card = document.getElementById("commandHelpCard");
  if (card && !card.hidden) {
    const visibleIds = new Set((commandHelpRuntimeState()?.commandResults || []).map((item) => item.id));
    const activeId = card.dataset.commandId;
    if (activeId && !visibleIds.has(activeId)) hideCommandHelp();
  }
}

function installCommandHelpStyles() {
  if (document.getElementById("arlineCommandHelpStyles")) return;
  const style = document.createElement("style");
  style.id = "arlineCommandHelpStyles";
  style.textContent = `
    .command-dialog.has-command-help{width:min(980px,calc(100vw - 32px));max-width:980px}
    .command-body-layout{display:grid;grid-template-columns:minmax(0,1fr);min-height:0}
    .command-dialog.has-command-help .command-body-layout{grid-template-columns:minmax(280px,.85fr) minmax(360px,1.15fr)}
    .command-dialog.has-command-help .command-results{border-right:1px solid var(--border,rgba(255,255,255,.1))}
    .command-item{position:relative}
    .command-info-button{display:grid;place-items:center;flex:0 0 30px;width:30px;height:30px;margin-left:6px;border-radius:8px;color:var(--muted,#9ca3af);font-size:15px;cursor:pointer;transition:background .15s ease,color .15s ease}
    .command-info-button:hover,.command-info-button:focus{background:var(--surface-2,rgba(127,127,127,.14));color:var(--text,#f5f5f5);outline:none}
    .command-help-card{padding:18px 20px;max-height:min(68vh,680px);overflow:auto;background:var(--panel,#181a18);color:var(--text,#f4f4f4)}
    .command-help-card[hidden]{display:none!important}
    .command-help-head{display:flex;justify-content:space-between;gap:14px;align-items:flex-start;margin-bottom:12px}
    .command-help-head h3{margin:3px 0 0;font-size:18px;line-height:1.25}.command-help-head h3 small{display:block;margin-top:3px;color:var(--muted,#9ca3af);font-size:12px;font-weight:500}
    .command-help-category,.command-help-label{display:block;color:var(--muted,#9ca3af);font-size:10px;font-weight:700;letter-spacing:.09em;text-transform:uppercase}
    .command-help-close{border:0;background:transparent;color:var(--muted,#9ca3af);font-size:20px;cursor:pointer}
    .command-help-about{margin:0 0 16px;color:var(--muted-strong,#c6c9c6);line-height:1.55;font-size:13px}
    .command-help-card section{margin:0 0 16px}.command-help-syntax{display:block;margin-top:7px;padding:10px 12px;border:1px solid var(--border,rgba(255,255,255,.1));border-radius:9px;background:var(--surface-2,rgba(0,0,0,.18));white-space:pre-wrap;overflow-wrap:anywhere}
    .command-help-examples{display:grid;gap:7px;margin-top:7px}.command-help-example{display:flex;align-items:center;gap:10px;padding:9px 10px;border:1px solid var(--border,rgba(255,255,255,.1));border-radius:9px;background:var(--surface-2,rgba(0,0,0,.14))}
    .command-help-example>div{display:grid;gap:3px;min-width:0;flex:1}.command-help-example small{color:var(--muted,#9ca3af)}.command-help-example code{white-space:pre-wrap;overflow-wrap:anywhere;color:inherit}
    .command-help-use,.command-help-insert{border:1px solid var(--border,rgba(255,255,255,.14));border-radius:8px;background:var(--surface-3,rgba(127,127,127,.12));color:inherit;padding:6px 10px;cursor:pointer}.command-help-use:hover,.command-help-insert:hover{background:var(--surface-4,rgba(127,127,127,.2))}
    .command-help-parameters{display:grid;gap:7px;margin-top:7px}.command-help-parameter{display:grid;grid-template-columns:minmax(110px,.42fr) 1fr;gap:10px;font-size:12px;line-height:1.4}.command-help-parameter span{color:var(--muted-strong,#c6c9c6)}
    .command-help-card ul{margin:7px 0 0;padding-left:18px;color:var(--muted-strong,#c6c9c6);font-size:12px;line-height:1.5}.command-help-memory{padding:11px 12px;border-radius:9px;background:var(--surface-2,rgba(127,127,127,.08))}
    .command-help-card footer{display:flex;justify-content:flex-end;padding-top:2px}.command-help-insert{font-weight:700;padding:8px 12px}
    @media(max-width:720px){.command-dialog.has-command-help .command-body-layout{grid-template-columns:1fr}.command-dialog.has-command-help .command-results{display:none}.command-help-card{max-height:72vh;border-right:0}.command-help-parameter{grid-template-columns:1fr}.command-dialog.has-command-help{width:calc(100vw - 20px)}}
  `;
  document.head.appendChild(style);
}

function installCommandHelpUI() {
  const dialog = document.getElementById("commandDialog");
  const host = document.getElementById("commandResults");
  if (!dialog || !host || document.getElementById("commandHelpCard")) return;
  installCommandHelpStyles();
  const layout = document.createElement("div");
  layout.className = "command-body-layout";
  host.before(layout);
  layout.appendChild(host);
  const card = document.createElement("aside");
  card.id = "commandHelpCard";
  card.className = "command-help-card";
  card.hidden = true;
  card.setAttribute("aria-live", "polite");
  layout.appendChild(card);

  const observer = new MutationObserver(enhanceCommandHelpRows);
  observer.observe(host, { childList: true, subtree: true });
  dialog.addEventListener("close", hideCommandHelp);
  enhanceCommandHelpRows();
}

function loadCommandCenterV125() {
  if (document.querySelector('script[data-arline-command-center]')) return;
  const script = document.createElement("script");
  script.src = "/static/js/command-center.js?v=1.2.5-command-center";
  script.async = false;
  script.dataset.arlineCommandCenter = "1";
  document.head.appendChild(script);
}

if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", installCommandHelpUI, { once: true });
else installCommandHelpUI();

window.addEventListener("load", loadCommandCenterV125, { once: true });
