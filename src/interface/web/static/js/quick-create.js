"use strict";

(function () {
  const ENTITY_TYPES = ["character", "location", "item", "organization", "lore", "world_rule"];
  const DOCUMENT_TYPES = ["scene", "chapter", "note", "research", "outline"];
  const RELATION_KEYWORDS = [
    [/\b(?:saudara\s+angkat|adopted\s+sibling)\b/i, "adopted_sibling"],
    [/\b(?:saudara|sibling)\b/i, "sibling"],
    [/\b(?:menikah|married|spouse|suami|istri)\b/i, "married"],
    [/\b(?:pacar|dating|boyfriend|girlfriend|lover)\b/i, "dating"],
    [/\b(?:mencintai|loves?|in love with)\b/i, "loves"],
    [/\b(?:teman|friend)\b/i, "friend"],
    [/\b(?:musuh|enemy)\b/i, "enemy"],
    [/\b(?:rival)\b/i, "rival"],
    [/\b(?:ayah|ibu|father|mother|parent)\b/i, "parent"],
    [/\b(?:anak|child|son|daughter)\b/i, "child"],
    [/\b(?:mentor)\b/i, "mentor"],
    [/\b(?:anggota|member)\b/i, "member"],
  ];

  function decodeCreateAs(value) {
    const raw = String(value || "");
    if (!raw) return { kind: null, entity_type: null, document_type: null };
    if (raw.startsWith("entity:")) return { kind: "entity", entity_type: raw.slice(7), document_type: null };
    if (raw.startsWith("document:")) return { kind: "document", entity_type: null, document_type: raw.slice(9) };
    if (raw === "relationship") return { kind: "relationship", entity_type: null, document_type: null };
    return { kind: raw, entity_type: null, document_type: null };
  }

  function inferRelationship(text, variants) {
    const source = String(text || "").trim();
    const lower = source.toLocaleLowerCase();
    const hits = (variants || [])
      .map((variant) => {
        const label = String(variant.display_name || variant.name || "").trim();
        return { variant, label, index: label ? lower.indexOf(label.toLocaleLowerCase()) : -1 };
      })
      .filter((item) => item.index >= 0)
      .sort((a, b) => a.index - b.index || b.label.length - a.label.length);
    const unique = [];
    const used = new Set();
    for (const hit of hits) {
      const key = hit.variant.id || hit.label.toLocaleLowerCase();
      if (used.has(key)) continue;
      used.add(key); unique.push(hit);
    }
    let relation = "";
    for (const [pattern, normalized] of RELATION_KEYWORDS) {
      if (pattern.test(source)) { relation = normalized; break; }
    }
    if (!relation && unique.length >= 2) {
      const first = unique[0], second = unique[1];
      const before = source.slice(first.index + first.label.length, second.index).trim();
      const after = source.slice(second.index + second.label.length).trim();
      relation = (before || after)
        .replace(/^(?:dan|and|dengan|with|adalah|merupakan|is|are)\s+/i, "")
        .replace(/\s+(?:dan|and|dengan|with)$/i, "")
        .trim()
        .replace(/\s+/g, "_")
        .toLowerCase();
    }
    return {
      subject_id: unique[0]?.variant?.id || null,
      object_id: unique[1]?.variant?.id || null,
      relation_type: relation,
      resolved: unique.length >= 2 && Boolean(relation),
    };
  }

  window.ArlineQuickCreate = { decodeCreateAs, inferRelationship, preparePayload, previewOverride };
  if (typeof document === "undefined") return;

  const originalFetch = window.fetch.bind(window);
  let bootstrapCache = null;
  let libraryCache = null;
  let relationTouched = false;

  function byId(id) { return document.getElementById(id); }
  function activeBranchKind() {
    return byId("quickCreateBranch")?.selectedOptions?.[0]?.dataset.kind || "main";
  }
  function currentScopeValue(id) { return byId(id)?.value || ""; }
  function runtimeScope() { return window.ArlineRuntime?.getScope?.() || {}; }

  async function fetchJSON(url, init = undefined) {
    const response = await originalFetch(url, init);
    if (!response.ok) {
      let message = `${response.status} ${response.statusText}`;
      try { const data = await response.json(); message = data.detail || data.message || message; } catch (_) {}
      throw new Error(message);
    }
    return response.json();
  }

  function flattenFolders(items, prefix = "") {
    const out = [];
    for (const item of items || []) {
      const path = prefix ? `${prefix} / ${item.name}` : item.name;
      out.push({ ...item, path });
      out.push(...flattenFolders(item.children || [], path));
    }
    return out;
  }

  function selectedMode() { return decodeCreateAs(byId("quickCreateKind")?.value || ""); }

  function scopePayload(mode = selectedMode()) {
    const projectId = byId("quickCreateProject")?.value || runtimeScope().projectId || null;
    const worldId = byId("quickCreateWorld")?.value || runtimeScope().worldId || null;
    const branchId = byId("quickCreateBranch")?.value || runtimeScope().branchId || null;
    const main = activeBranchKind() === "main";
    const folderId = byId("quickCreateFolder")?.value || null;
    if (mode.kind === "project") return { project_id: null, world_id: null, branch_id: null, folder_id: null };
    if (mode.kind === "world") return { project_id: projectId, world_id: null, branch_id: null, folder_id: null };
    if (mode.kind === "folder") return { project_id: projectId, world_id: null, branch_id: null, folder_id: folderId };
    return { project_id: projectId, world_id: worldId, branch_id: main ? null : branchId, folder_id: folderId };
  }

  function normalizeLegacySelection() {
    const select = byId("quickCreateKind");
    if (!select) return;
    if (select.value === "entity") {
      const tab = document.querySelector('[data-world-tab].active')?.dataset.worldTab;
      select.value = ENTITY_TYPES.includes(tab) ? `entity:${tab}` : "entity:character";
    } else if (select.value === "document") select.value = "document:scene";
  }

  function installCreateAsOptions() {
    const select = byId("quickCreateKind");
    if (!select || select.dataset.enhanced === "true") return;
    select.dataset.enhanced = "true";
    const label = select.closest("label");
    if (label?.firstChild?.nodeType === Node.TEXT_NODE) label.firstChild.nodeValue = "Create as";
    select.innerHTML = `
      <option value="">Auto detect</option>
      <optgroup label="Library">
        <option value="entity:character">Character</option>
        <option value="entity:location">Location</option>
        <option value="entity:item">Item</option>
        <option value="entity:organization">Organization</option>
        <option value="entity:lore">Lore</option>
        <option value="entity:world_rule">World rule</option>
        <option value="relationship">Relationship</option>
      </optgroup>
      <optgroup label="Manuscript">
        <option value="document:scene">Scene</option>
        <option value="document:chapter">Chapter</option>
        <option value="document:note">Note</option>
        <option value="document:research">Research</option>
        <option value="document:outline">Outline</option>
      </optgroup>
      <optgroup label="Workspace">
        <option value="world">World</option>
        <option value="project">Project</option>
        <option value="folder">Project folder</option>
      </optgroup>
      <option value="entity" hidden>Entity compatibility</option>
      <option value="document" hidden>Document compatibility</option>`;
  }

  function installDestinationUI() {
    if (byId("quickCreateDestination")) return;
    const anchor = document.querySelector(".quick-create-options");
    if (!anchor) return;
    const panel = document.createElement("section");
    panel.id = "quickCreateDestination";
    panel.className = "quick-create-destination";
    panel.innerHTML = `
      <div class="quick-create-destination-head"><span>Destination</span><b id="quickCreateDestinationSummary">Current scope</b></div>
      <div class="quick-create-destination-grid">
        <label id="quickCreateProjectLabel">Project<select id="quickCreateProject"></select></label>
        <label id="quickCreateWorldLabel">World<select id="quickCreateWorld"></select></label>
        <label id="quickCreateBranchLabel">Branch<select id="quickCreateBranch"></select></label>
        <label id="quickCreateFolderLabel">Folder<select id="quickCreateFolder"><option value="">No folder</option></select></label>
      </div>
      <div id="quickCreateRelationshipFields" class="quick-create-relationship hidden">
        <div class="quick-create-destination-head"><span>Relationship resolver</span><b>Existing Library entities only</b></div>
        <div class="quick-create-relationship-grid">
          <label>Subject<select id="quickCreateRelationSubject"></select></label>
          <label>Relation<input id="quickCreateRelationType" placeholder="friend / sibling / married" /></label>
          <label>Object<select id="quickCreateRelationObject"></select></label>
        </div>
        <small id="quickCreateRelationNote">Arline will not silently create missing characters here. Create them first or choose existing entities.</small>
      </div>`;
    anchor.insertAdjacentElement("afterend", panel);

    const style = document.createElement("style");
    style.id = "quickCreateEnhancementStyle";
    style.textContent = `
      .quick-create-destination{margin:10px 0 2px;padding:10px;border:1px solid var(--border,#515650);border-radius:10px;background:color-mix(in srgb,var(--panel,#252825) 92%,transparent)}
      .quick-create-destination-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:8px;font-size:12px}.quick-create-destination-head span{font-weight:700}.quick-create-destination-head b{font-weight:500;opacity:.72;text-align:right}
      .quick-create-destination-grid,.quick-create-relationship-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.quick-create-destination label,.quick-create-relationship label{display:grid;gap:4px;font-size:11px;opacity:.9}.quick-create-destination select,.quick-create-destination input{width:100%}
      .quick-create-relationship{margin-top:10px;padding-top:10px;border-top:1px solid var(--border,#515650)}.quick-create-relationship-grid{grid-template-columns:1fr 1.1fr 1fr}.quick-create-relationship small{display:block;margin-top:7px;opacity:.65}.quick-create-relationship.hidden{display:none}
      @media(max-width:700px){.quick-create-destination-grid,.quick-create-relationship-grid{grid-template-columns:1fr}}
    `;
    document.head.appendChild(style);
  }

  async function loadBootstrap() {
    const stack = typeof window.contextStackId === "function" ? window.contextStackId() : "default";
    bootstrapCache = await fetchJSON(`/api/workspace/bootstrap?stack_id=${encodeURIComponent(stack)}`);
    return bootstrapCache;
  }

  function fillSelect(select, rows, value, labelOf) {
    if (!select) return;
    select.innerHTML = (rows || []).map((row) => `<option value="${String(row.id).replaceAll('"','&quot;')}">${labelOf(row)}</option>`).join("");
    if (value && [...select.options].some((option) => option.value === value)) select.value = value;
  }

  async function refreshProjectsAndWorlds() {
    const data = bootstrapCache || await loadBootstrap();
    const projectSelect = byId("quickCreateProject");
    const currentProject = runtimeScope().projectId || data.active?.project?.id || data.projects?.[0]?.id || "";
    fillSelect(projectSelect, data.projects || [], currentProject, (row) => row.name);

    let worlds = data.worlds || [];
    const projectId = projectSelect?.value;
    if (projectId) {
      try {
        const project = await fetchJSON(`/api/projects/${encodeURIComponent(projectId)}`);
        if (project.worlds?.length) worlds = project.worlds;
      } catch (_) {}
    }
    const currentWorld = runtimeScope().worldId || data.active?.world?.id || data.world_bible?.default_world_id || worlds[0]?.id || "";
    fillSelect(byId("quickCreateWorld"), worlds, currentWorld, (row) => `${row.name}${row.canon_status ? ` · ${row.canon_status}` : ""}`);
    await refreshBranches();
  }

  async function refreshBranches() {
    const worldId = byId("quickCreateWorld")?.value;
    const branchSelect = byId("quickCreateBranch");
    if (!worldId) { if (branchSelect) branchSelect.innerHTML = ""; return; }
    try {
      const world = await fetchJSON(`/api/worlds/${encodeURIComponent(worldId)}`);
      const currentBranch = runtimeScope().branchId || world.branches?.find((b) => b.kind === "main")?.id || world.branches?.[0]?.id || "";
      if (branchSelect) {
        branchSelect.innerHTML = (world.branches || []).map((branch) => `<option value="${branch.id}" data-kind="${branch.kind || "main"}">${branch.name} · ${branch.kind || "main"}</option>`).join("");
        if ([...branchSelect.options].some((option) => option.value === currentBranch)) branchSelect.value = currentBranch;
      }
    } catch (_) { if (branchSelect) branchSelect.innerHTML = ""; }
    await refreshFolderOptions();
  }

  async function loadLibraryScope() {
    const scope = scopePayload(selectedMode());
    if (!scope.world_id) return { folders: [], folder_tree: [], variants: [], families: [] };
    const params = new URLSearchParams({
      ...(scope.project_id ? { project_id: scope.project_id } : {}),
      world_id: scope.world_id,
      ...(scope.branch_id ? { branch_id: scope.branch_id } : {}),
    });
    libraryCache = await fetchJSON(`/api/world-bible?${params}`);
    return libraryCache;
  }

  function scopedVariants(bible) {
    const worldId = byId("quickCreateWorld")?.value;
    const branchId = byId("quickCreateBranch")?.value;
    const branchKind = activeBranchKind();
    const candidates = (bible?.variants || []).filter((v) => v.world_id === worldId && (v.branch_id == null || (branchKind !== "main" && v.branch_id === branchId)));
    const byFamily = new Map();
    for (const variant of candidates) {
      const previous = byFamily.get(variant.family_id);
      if (!previous || (branchKind !== "main" && variant.branch_id === branchId)) byFamily.set(variant.family_id, variant);
    }
    return [...byFamily.values()].sort((a, b) => String(a.display_name || "").localeCompare(String(b.display_name || "")));
  }

  async function refreshFolderOptions() {
    const mode = selectedMode();
    const folder = byId("quickCreateFolder");
    const folderLabel = byId("quickCreateFolderLabel");
    const scope = scopePayload(mode);
    if (!folder) return;
    let rows = [];
    if (mode.kind === "entity") {
      try { const bible = await loadLibraryScope(); rows = flattenFolders(bible.folder_tree || bible.folders || []); } catch (_) {}
      if (folderLabel) folderLabel.childNodes[0].nodeValue = "Library folder";
    } else if (mode.kind === "document" || mode.kind === "folder") {
      try {
        if (scope.project_id) {
          const params = new URLSearchParams({ ...(scope.world_id ? { world_id: scope.world_id } : {}), ...(scope.branch_id ? { branch_id: scope.branch_id } : {}) });
          const tree = await fetchJSON(`/api/projects/${encodeURIComponent(scope.project_id)}/tree?${params}`);
          rows = flattenFolders(tree.folder_tree || tree.folders || []);
        }
      } catch (_) {}
      if (folderLabel) folderLabel.childNodes[0].nodeValue = mode.kind === "folder" ? "Parent folder" : "Project folder";
    }
    folder.innerHTML = `<option value="">${mode.kind === "folder" ? "Project root" : "No folder"}</option>${rows.map((row) => `<option value="${row.id}">${row.path}</option>`).join("")}`;
    folder.disabled = !["entity", "document", "folder"].includes(mode.kind);
    await refreshRelationshipResolver();
    updateDestinationSummary();
  }

  async function refreshRelationshipResolver() {
    const mode = selectedMode();
    const box = byId("quickCreateRelationshipFields");
    if (!box) return;
    box.classList.toggle("hidden", mode.kind !== "relationship");
    if (mode.kind !== "relationship") return;
    let bible = libraryCache;
    try { bible = await loadLibraryScope(); } catch (_) { bible = { variants: [] }; }
    const variants = scopedVariants(bible);
    const subject = byId("quickCreateRelationSubject"), object = byId("quickCreateRelationObject");
    const options = variants.map((variant) => `<option value="${variant.id}">${variant.display_name}</option>`).join("");
    if (subject) subject.innerHTML = options;
    if (object) object.innerHTML = options;
    if (object && variants.length > 1) object.value = variants[1].id;
    relationTouched = false;
    applyRelationshipInference(variants);
    const note = byId("quickCreateRelationNote");
    if (note) note.textContent = variants.length < 2
      ? "Create at least two Library entities in this world/branch before creating a relationship. Arline will not create missing identities silently."
      : "Subject and object resolve to existing Library variants. No duplicate identities are created automatically.";
  }

  function applyRelationshipInference(variants = scopedVariants(libraryCache || {})) {
    if (selectedMode().kind !== "relationship") return;
    const inference = inferRelationship(byId("quickCreateInput")?.value || "", variants);
    const subject = byId("quickCreateRelationSubject"), object = byId("quickCreateRelationObject"), relation = byId("quickCreateRelationType");
    if (inference.subject_id && subject && [...subject.options].some((o) => o.value === inference.subject_id)) subject.value = inference.subject_id;
    if (inference.object_id && object && [...object.options].some((o) => o.value === inference.object_id)) object.value = inference.object_id;
    if (!relationTouched && inference.relation_type && relation) relation.value = inference.relation_type;
  }

  function updateVisibility() {
    const mode = selectedMode();
    const project = byId("quickCreateProjectLabel"), world = byId("quickCreateWorldLabel"), branch = byId("quickCreateBranchLabel"), folder = byId("quickCreateFolderLabel");
    if (project) project.hidden = mode.kind === "project";
    if (world) world.hidden = ["project", "world", "folder"].includes(mode.kind);
    if (branch) branch.hidden = ["project", "world", "folder"].includes(mode.kind);
    if (folder) folder.hidden = !["entity", "document", "folder"].includes(mode.kind);
    byId("quickCreateRelationshipFields")?.classList.toggle("hidden", mode.kind !== "relationship");
    updateDestinationSummary();
  }

  function updateDestinationSummary() {
    const mode = selectedMode();
    const summary = byId("quickCreateDestinationSummary");
    if (!summary) return;
    const project = byId("quickCreateProject")?.selectedOptions?.[0]?.textContent || "Workspace";
    const world = byId("quickCreateWorld")?.selectedOptions?.[0]?.textContent?.split(" · ")[0] || "";
    const branch = byId("quickCreateBranch")?.selectedOptions?.[0]?.textContent?.split(" · ")[0] || "";
    const folder = byId("quickCreateFolder")?.selectedOptions?.[0]?.textContent || "";
    if (mode.kind === "project") summary.textContent = "New workspace";
    else if (mode.kind === "world") summary.textContent = project;
    else if (mode.kind === "folder") summary.textContent = `${project}${folder && folder !== "Project root" ? ` · ${folder}` : ""}`;
    else if (mode.kind === "entity" || mode.kind === "relationship") summary.textContent = `Library · ${world}${branch ? ` / ${branch}` : ""}${folder && folder !== "No folder" ? ` · ${folder}` : ""}`;
    else if (mode.kind === "document") summary.textContent = `${project} · Manuscript${folder && folder !== "No folder" ? ` / ${folder}` : ""}`;
    else summary.textContent = `${project}${world ? ` · ${world}` : ""}`;
  }

  async function refreshDestination() {
    normalizeLegacySelection();
    await refreshProjectsAndWorlds();
    updateVisibility();
    await refreshFolderOptions();
  }

  function preparePayload(body = {}) {
    const next = { ...body };
    const mode = decodeCreateAs(byId("quickCreateKind")?.value || next.forced_kind || "");
    if (mode.kind) next.forced_kind = mode.kind;
    if (mode.entity_type) next.entity_type = mode.entity_type;
    if (mode.document_type) next.document_type = mode.document_type;
    Object.assign(next, scopePayload(mode));
    return next;
  }

  function previewOverride(body = {}) {
    const mode = decodeCreateAs(byId("quickCreateKind")?.value || body.forced_kind || "");
    if (mode.kind !== "relationship") return null;
    const variants = scopedVariants(libraryCache || {});
    const inferred = inferRelationship(body.text || "", variants);
    const subject = variants.find((v) => v.id === inferred.subject_id);
    const object = variants.find((v) => v.id === inferred.object_id);
    return {
      kind: "relationship",
      entity_type: null,
      name: subject && object ? `${subject.display_name} ↔ ${object.display_name}` : (String(body.text || "").trim() || "Relationship"),
      description: inferred.relation_type || "Choose subject, relation, and object below",
      confidence: inferred.resolved ? 0.95 : 0.55,
      attributes: {},
      shared_core: {},
      document_type: null,
      warnings: inferred.resolved ? [] : ["Resolve two existing entities and a relationship type before creating."],
      detected: inferred.relation_type ? [inferred.relation_type] : [],
    };
  }

  async function submitRelationship(event) {
    if (selectedMode().kind !== "relationship") return;
    event.preventDefault(); event.stopImmediatePropagation();
    if (event.submitter?.value === "cancel") { byId("quickCreateDialog")?.close(); return; }
    const subject = byId("quickCreateRelationSubject")?.value;
    const object = byId("quickCreateRelationObject")?.value;
    const relation = byId("quickCreateRelationType")?.value.trim();
    const scope = scopePayload({ kind: "relationship" });
    if (!scope.world_id) return window.toast?.("Choose a destination world first");
    if (!subject || !object) return window.toast?.("Choose two existing Library entities");
    if (subject === object) return window.toast?.("Subject and object must be different entities");
    if (!relation) return window.toast?.("Relationship type is required");
    try {
      const response = await originalFetch("/api/relationships", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          world_id: scope.world_id, branch_id: scope.branch_id,
          subject_variant_id: subject, object_variant_id: object,
          relation_type: relation, status: "current",
          canon_status: scope.branch_id ? "what_if" : "draft", attributes: {},
        }),
      });
      if (!response.ok) {
        let message = `${response.status} ${response.statusText}`;
        try { const data = await response.json(); message = data.detail || data.message || message; } catch (_) {}
        throw new Error(message);
      }
      const result = await response.json();
      byId("quickCreateDialog")?.close();
      if (typeof window.loadProjectData === "function") await window.loadProjectData();
      if (typeof window.openRelationshipSheet === "function" && result.id) await window.openRelationshipSheet(result.id);
      window.toast?.(`Created relationship: ${relation}`);
    } catch (error) { window.toast?.(`Relationship create failed: ${error.message}`, 6000); }
  }

  function interceptAdvanced(event) {
    const mode = selectedMode();
    if (!mode.entity_type && !mode.document_type && mode.kind !== "relationship") return;
    event.preventDefault(); event.stopImmediatePropagation();
    if (mode.entity_type && typeof window.openEntityForm === "function") {
      byId("quickCreateDialog")?.close(); window.openEntityForm(mode.entity_type); return;
    }
    if (mode.document_type && typeof window.openDocumentForm === "function") {
      const folder = byId("quickCreateFolder")?.value || null;
      byId("quickCreateDialog")?.close(); window.openDocumentForm(folder, mode.document_type); return;
    }
    if (mode.kind === "relationship") byId("quickCreateRelationType")?.focus();
  }

  function wireEvents() {
    const dialog = byId("quickCreateDialog"), form = byId("quickCreateForm"), kind = byId("quickCreateKind");
    if (!dialog || !form || !kind) return;
    const nativeShow = dialog.showModal.bind(dialog);
    dialog.showModal = function () {
      nativeShow();
      queueMicrotask(() => refreshDestination().catch((error) => window.toast?.(`Destination load failed: ${error.message}`, 5000)));
    };
    kind.addEventListener("change", async () => {
      normalizeLegacySelection(); relationTouched = false; libraryCache = null;
      updateVisibility(); await refreshFolderOptions();
    });
    byId("quickCreateProject")?.addEventListener("change", async () => { bootstrapCache = null; libraryCache = null; await refreshProjectsAndWorlds(); await refreshFolderOptions(); });
    byId("quickCreateWorld")?.addEventListener("change", async () => { libraryCache = null; await refreshBranches(); });
    byId("quickCreateBranch")?.addEventListener("change", async () => { libraryCache = null; await refreshFolderOptions(); });
    byId("quickCreateFolder")?.addEventListener("change", updateDestinationSummary);
    byId("quickCreateInput")?.addEventListener("input", () => applyRelationshipInference());
    byId("quickCreateRelationType")?.addEventListener("input", () => { relationTouched = true; });
    form.addEventListener("submit", submitRelationship, true);
    byId("quickCreateAdvancedBtn")?.addEventListener("click", interceptAdvanced, true);
  }

  installCreateAsOptions();
  installDestinationUI();
  wireEvents();
})();
