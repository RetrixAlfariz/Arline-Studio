(() => {
  const byId = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? "").replace(/[&<>'"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
  const icon = (state) => ({detected:"◌",reviewed:"◇",canon:"◆",dismissed:"×"})[state] || "◌";

  function appState() { return window.ArlineRuntime?.getState?.() || {}; }
  function scope() { return window.ArlineMemoryRuntime?.activeScope?.() || {}; }

  function scopeParams() {
    const current = scope();
    const params = new URLSearchParams();
    if (current.projectId) params.set("project_id", current.projectId);
    if (current.worldId) params.set("world_id", current.worldId);
    if (current.branchId) params.set("branch_id", current.branchId);
    if (current.sessionId) params.set("session_id", current.sessionId);
    if (current.storyOrder != null) params.set("story_order", String(current.storyOrder));
    return params;
  }

  async function request(url, options = {}) {
    const response = await fetch(url, {
      ...options,
      headers: {"Content-Type":"application/json", ...(options.headers || {})},
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || `${response.status} ${response.statusText}`);
    }
    return response.json();
  }

  function valueText(value) {
    if (value == null) return "—";
    if (["string","number","boolean"].includes(typeof value)) return String(value);
    return JSON.stringify(value);
  }

  function parseValue(raw) {
    const text = String(raw ?? "").trim();
    if (!text) return "";
    try { return JSON.parse(text); }
    catch (_) { return text; }
  }

  function semanticText(item) {
    const semantics = item?.semantics || {};
    const group = String(semantics.group || "knowledge").replaceAll("_", " ");
    const target = String(semantics.canon_target || "fact").replaceAll("_", " ");
    return `${group} · ${target}`;
  }

  function physicalIdentity(resource) {
    const core = resource?.shared_core || {};
    const meta = core?._discovery || {};
    const itemId = String(meta.physical_item_id || "").trim();
    if (!itemId) return null;
    const garmentType = String(core?.garment?.type || "garment").replaceAll("_", " ");
    return {
      id: itemId,
      subjectKey: String(meta.subject_key || `item:${itemId}`),
      classification: `Item › Garment › ${garmentType}`,
      identityModel: String(meta.identity_model || "physical_instance_v1"),
    };
  }

  function relationPhysicalId(relation) {
    const key = String(relation?.object_key || "");
    return key.startsWith("item:ITEM-") ? key.slice(5) : "";
  }

  function decisionPayload(extra = {}) {
    const current = scope();
    return {
      project_id: current.projectId || null,
      world_id: current.worldId || null,
      branch_id: current.branchId || null,
      session_id: current.sessionId || null,
      story_order: current.storyOrder ?? null,
      world_time: current.worldTime ?? null,
      ...extra,
    };
  }

  function isProvisional(family) {
    return Boolean(family?.shared_core?._discovery?.provisional);
  }

  function activeBranchLineageIds() {
    const state = appState();
    const branches = state.activeWorld?.branches || [];
    const lineage = new Set();
    let cursor = state.activeBranch?.id || null;
    while (cursor && !lineage.has(cursor)) {
      lineage.add(cursor);
      const branch = state.activeBranch?.id === cursor
        ? state.activeBranch
        : branches.find((item) => item.id === cursor);
      cursor = branch?.parent_branch_id || null;
    }
    return lineage;
  }

  function provisionalVisible(family) {
    if (!isProvisional(family)) return true;
    const state = appState();
    const meta = family?.shared_core?._discovery || {};
    const worldId = state.activeWorld?.id || null;
    const branchId = state.activeBranch?.id || null;
    if (!worldId || !branchId) return false;
    if (meta.source_world_id && meta.source_world_id !== worldId) return false;

    const sourceBranchIds = Array.isArray(meta.source_branch_ids) ? meta.source_branch_ids : [];
    if (sourceBranchIds.length) {
      const lineage = activeBranchLineageIds();
      return sourceBranchIds.some((id) => lineage.has(id));
    }

    const variants = (state.variants || []).filter((variant) => variant.family_id === family.id && variant.world_id === worldId);
    return variants.some((variant) => !variant.branch_id || variant.branch_id === branchId);
  }

  function installVisibilityGuards() {
    const originalFiltered = window.filteredWorldFamilies;
    if (typeof originalFiltered === "function" && !originalFiltered.__provisionalVisibilityWrapped) {
      const wrapped = function(...args) {
        const rows = originalFiltered.apply(this, args);
        return Array.isArray(rows) ? rows.filter(provisionalVisible) : rows;
      };
      wrapped.__provisionalVisibilityWrapped = true;
      window.filteredWorldFamilies = wrapped;
    }
    const originalRegistry = window.referenceRegistry;
    if (typeof originalRegistry === "function" && !originalRegistry.__provisionalVisibilityWrapped) {
      const wrapped = function(...args) {
        const rows = originalRegistry.apply(this, args);
        if (!Array.isArray(rows)) return rows;
        const state = appState();
        const hiddenFamilies = new Set((state.families || []).filter((family) => isProvisional(family) && !provisionalVisible(family)).map((family) => family.id));
        const hiddenVariants = new Set((state.variants || []).filter((variant) => hiddenFamilies.has(variant.family_id)).map((variant) => variant.id));
        return rows.filter((row) => !(
          (row.type === "entity_family" && hiddenFamilies.has(row.id)) ||
          (row.type === "entity_variant" && hiddenVariants.has(row.id))
        ));
      };
      wrapped.__provisionalVisibilityWrapped = true;
      window.referenceRegistry = wrapped;
    }
  }

  function styles() {
    if (byId("provisionalSheetStyles")) return;
    const style = document.createElement("style");
    style.id = "provisionalSheetStyles";
    style.textContent = `.prov-banner{padding:11px;border:1px solid color-mix(in srgb,var(--accent) 35%,var(--line));border-radius:10px;margin-bottom:12px}.prov-banner small,.prov-row small{display:block;opacity:.65;margin-top:3px}.prov-physical{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:8px}.prov-physical code{font-size:10px;padding:3px 6px;border:1px solid var(--line);border-radius:6px}.prov-physical span{font-size:11px;opacity:.72;text-transform:capitalize}.prov-path{display:flex;flex-wrap:wrap;gap:6px;padding:8px 0}.prov-path span:not(:last-child)::after{content:'›';opacity:.45;margin-left:6px}.prov-list{display:grid;gap:7px}.prov-row{padding:9px;border:1px solid var(--line);border-radius:9px}.prov-row-head{display:flex;justify-content:space-between;gap:8px}.prov-row code{font-size:9px;opacity:.55}.prov-value{display:block;margin-top:4px;word-break:break-word}.prov-actions{display:flex;gap:6px;flex-wrap:wrap;margin-top:7px}.prov-change{padding:7px 0;border-bottom:1px solid var(--line)}.prov-help{font-size:11px;opacity:.7;line-height:1.5;margin:4px 0 9px}.prov-zone-note{font-size:11px;opacity:.62;margin-top:6px}.cont-grid{display:grid;gap:7px}.cont-state{display:grid;grid-template-columns:minmax(120px,.7fr) 1fr;gap:8px;padding:7px 0;border-bottom:1px solid var(--line)}.cont-event,.cont-conflict{padding:9px;border:1px solid var(--line);border-radius:9px}.cont-event small,.cont-conflict small{display:block;opacity:.65;margin-top:4px}.cont-ambiguous{border-style:dashed}.prov-semantic{display:inline-flex;gap:4px;align-items:center;text-transform:capitalize}.prov-relation-item-id{font-family:monospace;font-size:9px;opacity:.55;margin-left:5px}`;
    document.head.appendChild(style);
  }

  async function editClaim(claim, familyId, mode) {
    const modeLabel = mode === "story_change" ? "new story-state value" : "corrected value";
    const raw = window.prompt(`Enter ${modeLabel} for ${claim.predicate}.\n\nCorrection means the previous value was wrong. Story change means the previous value stays historically true.`, valueText(claim.value));
    if (raw == null) return;
    try {
      await request(`/api/memory/discoveries/${encodeURIComponent(claim.id)}/edit`, {
        method: "POST",
        body: JSON.stringify(decisionPayload({
          value: parseValue(raw),
          mode,
          note: mode === "story_change" ? "Explicit story change from provisional sheet" : "Explicit correction from provisional sheet",
        })),
      });
      window.toast?.(mode === "story_change" ? "Story change recorded with a new claim/change ID" : "Correction recorded as user-reviewed knowledge", 4500);
      await decorate(familyId);
      await window.ArlineMemoryRuntime?.loadDiscoveries?.({render:false});
    } catch (error) { window.toast?.(error.message, 6000); }
  }

  async function makeCanon(claim, familyId) {
    if (claim?.semantics?.canonizable === false) {
      return window.toast?.("This structural edge is not directly canonizable. Use its canonical scalar/entity relation instead.", 5500);
    }
    if (!confirm(`Make “${claim.predicate} = ${valueText(claim.value)}” canon?\n\nOnly this claim is promoted. Other detected or reviewed fields remain non-canon. Future changes to this canonical value use the canonical Retcon/Delete workflow.`)) return;
    try {
      const result = await request(`/api/memory/discoveries/${encodeURIComponent(claim.id)}/canon`, {
        method: "POST",
        body: JSON.stringify(decisionPayload({note:"Explicit user canon promotion from provisional sheet"})),
      });
      const projection = result?.projection?.status === "applied" ? result.projection.target : null;
      window.toast?.(projection ? `Canon saved · projected to ${projection}` : "Claim promoted to user-authorized canon", 5000);
      await decorate(familyId);
      await window.ArlineMemoryRuntime?.loadDiscoveries?.({render:false});
    } catch (error) { window.toast?.(error.message, 6000); }
  }

  async function resolveContinuityConflict(conflict, familyId, action, fromId = null, toId = null) {
    try {
      await request(`/api/memory/discoveries/continuity/conflicts/${encodeURIComponent(conflict.id)}/resolve`, {
        method: "POST",
        body: JSON.stringify(decisionPayload({
          action, from_proposition_id: fromId, to_proposition_id: toId,
          note: "Explicit user continuity resolution from Library sheet",
        })),
      });
      window.toast?.("Continuity conflict resolved without granting Canon", 4500);
      await decorate(familyId);
    } catch (error) { window.toast?.(error.message, 6000); }
  }

  async function makeRelationCanon(relation, familyId) {
    if (relation?.semantics?.canonizable === false || relation.object_type === "spatial_zone") {
      return window.toast?.("Floor/slot zone edges stay lightweight. Canonize floor_number and the direct containment relation instead.", 5500);
    }
    if (!confirm(`Make relation “${relation.subject_label} ${String(relation.predicate || "related_to").replaceAll("_"," ")} ${relation.object_label || relation.object_key}” canon?\n\nFuture changes to a canonical relation use the canonical relation/retcon workflow.`)) return;
    try {
      await request(`/api/memory/discoveries/${encodeURIComponent(relation.id)}/canon`, {
        method: "POST",
        body: JSON.stringify(decisionPayload({note:"Explicit user canon promotion of provisional relation"})),
      });
      window.toast?.("Relation promoted to user-authorized canon", 4000);
      await decorate(familyId);
    } catch (error) { window.toast?.(error.message, 6000); }
  }

  async function decorate(familyId) {
    const body = byId("sheetBody");
    if (!body) return;
    body.querySelector("#provisionalDiscoverySection")?.remove();
    try {
      const data = await request(`/api/memory/discoveries/resource/entity_family/${encodeURIComponent(familyId)}?${scopeParams()}`);
      if (!data.provisional && !(data.claims || []).length && !(data.relations || []).length) return;
      const claims = (data.claims || []).filter((item) => !["entity.exists","zone.exists"].includes(item.predicate));
      const relations = data.relations || [];
      const changes = data.changes || [];
      const path = data.spatial_path || [];
      const physical = physicalIdentity(data.resource);
      const continuity = data.continuity || {};
      const currentHeads = continuity.current?.heads || [];
      const currentAmbiguous = continuity.current?.ambiguous || [];
      const forms = continuity.forms || [];
      const history = continuity.history || [];
      const events = continuity.events || [];
      const conflicts = (continuity.conflicts || []).filter((item) => item.status === "open");
      const section = document.createElement("section");
      section.id = "provisionalDiscoverySection";
      section.className = "sheet-section";
      section.innerHTML = `
        <div class="prov-banner"><b>${icon(data.knowledge_state)} ${esc(data.knowledge_state || "detected")} Library sheet</b><small>${physical ? "Physical ITEM identity is stable even when its descriptive label or attributes change." : "The sheet ID is stable and callable with @. Each value/relation keeps its own proposition ID and provenance; sheet existence never implies Canon."}</small>${physical ? `<div class="prov-physical"><code>${esc(physical.id)}</code><span>${esc(physical.classification)}</span></div>` : ""}</div>
        ${path.length > 1 ? `<div class="sheet-section-head"><h3>Spatial path</h3></div><div class="prov-path">${path.map((node) => `<span><b>${esc(node.label)}</b>${node.zone_kind ? ` <small>${esc(node.zone_kind)}</small>` : ""}</span>`).join("")}</div>` : ""}
        <div class="sheet-section-head"><h3>Discovered knowledge</h3><span>${claims.length}</span></div>
        <p class="prov-help"><b>Correct</b> replaces a wrong observation. <b>Story change</b> preserves the old observation historically and creates a transition. A manual edit becomes Reviewed; only <b>Make Canon</b> grants Canon authority. Once Canon, changes leave Discovery and use the canonical retcon/delete workflow.</p>
        <div class="prov-list">${claims.length ? claims.map((claim) => `<div class="prov-row" data-prov-claim="${esc(claim.id)}"><div class="prov-row-head"><b>${icon(claim.knowledge_state)} ${esc(claim.predicate)}</b><code>${esc(claim.id)}</code></div><span class="prov-value">${esc(valueText(claim.value))}</span><small><span class="prov-semantic">${esc(semanticText(claim))}</span> · ${esc(claim.knowledge_state)} · ${Number(claim.support_count || 0)} active source${Number(claim.support_count || 0) === 1 ? "" : "s"} · ${esc(claim.provenance_state || "active")}</small><div class="prov-actions">${claim.knowledge_state !== "canon" ? `<button class="tiny-btn" data-prov-action="correct">Correct</button><button class="tiny-btn" data-prov-action="story">Story change</button>${claim.semantics?.canonizable === false ? `<span class="protected-note">structural only</span>` : `<button class="tiny-btn" data-prov-action="canon">Make Canon</button>`}` : `<span class="protected-note">◆ Canon · use retcon for changes</span>`}</div></div>`).join("") : `<div class="empty-note">No scoped discovered fields.</div>`}</div>
        ${(currentHeads.length || currentAmbiguous.length) ? `<div class="sheet-section-head gap"><h3>Current State</h3><span>${currentHeads.length}</span></div><p class="prov-help">Derived continuity view. It can reconstruct and abstain, but it cannot grant Canon.</p><div class="cont-grid">${currentHeads.map((head) => `<div class="cont-state"><b>${esc(String(head.predicate || "").replace(/^state\./,""))}</b><span>${esc(valueText(head.value))}</span></div>`).join("")}${currentAmbiguous.map((item) => `<div class="cont-conflict cont-ambiguous"><b>Ambiguous · ${esc(item.predicate)}</b><small>${esc((item.proposition_ids || []).join(" ↔ "))}</small></div>`).join("")}</div>` : ""}
        ${forms.length ? `<div class="sheet-section-head gap"><h3>Forms</h3><span>${forms.length}</span></div><div class="cont-grid">${forms.map((form) => `<div class="cont-event"><b>${esc(form.reason === "state_transition" ? "State form" : "Observed baseline")}</b><small>${esc(form.id)}${form.parent_form_id ? ` · from ${esc(form.parent_form_id)}` : ""}</small><span class="prov-value">${esc(valueText(form.state || {}))}</span></div>`).join("")}</div>` : ""}
        ${history.length ? `<div class="sheet-section-head gap"><h3>Change History</h3><span>${history.length}</span></div><div class="cont-grid">${history.map((item) => `<div class="cont-event"><b>${esc(String(item.predicate || "").replace(/^state\./,""))} · ${esc(String(item.kind || "change").replaceAll("_"," "))}</b><span class="prov-value">${esc(valueText(item.before?.value))} → ${esc(valueText(item.after?.value))}</span>${item.event ? `<small>${esc(item.event.id)} · ${esc(item.event.summary || item.event.event_type)}</small>` : ""}</div>`).join("")}</div>` : ""}
        ${events.length ? `<div class="sheet-section-head gap"><h3>Events & Causes</h3><span>${events.length}</span></div><div class="cont-grid">${events.map((event) => `<div class="cont-event"><b>${esc(event.summary || event.event_type)}</b><small>${esc(event.id)} · ${Number((event.causal_links || []).length)} causal link${Number((event.causal_links || []).length) === 1 ? "" : "s"}</small></div>`).join("")}</div>` : ""}
        ${conflicts.length ? `<div class="sheet-section-head gap"><h3>Conflicts</h3><span>${conflicts.length}</span></div><p class="prov-help">Arline abstained. Choose only when you know whether this is a correction or an actual story transition.</p><div class="cont-grid">${conflicts.map((conflict) => `<div class="cont-conflict" data-cont-conflict="${esc(conflict.id)}"><b>${esc(conflict.predicate)}</b><span class="prov-value">${esc(valueText(conflict.left?.value))} ↔ ${esc(valueText(conflict.right?.value))}</span><small>${esc(conflict.reason)}</small><div class="prov-actions"><button class="tiny-btn" data-cont-action="left-correct">Left corrects right</button><button class="tiny-btn" data-cont-action="right-correct">Right corrects left</button><button class="tiny-btn" data-cont-action="left-to-right">Left → Right story change</button><button class="tiny-btn" data-cont-action="right-to-left">Right → Left story change</button><button class="tiny-btn" data-cont-action="dismiss">Leave unresolved</button></div></div>`).join("")}</div>` : ""}
        ${relations.length ? `<div class="sheet-section-head gap"><h3>Relations</h3><span>${relations.length}</span></div><div class="prov-list">${relations.map((rel) => { const itemId = relationPhysicalId(rel); return `<div class="prov-row" data-prov-relation="${esc(rel.id)}"><div class="prov-row-head"><b>${icon(rel.knowledge_state)} ${esc(rel.subject_label)} ${esc(String(rel.predicate || "related_to").replaceAll("_"," "))} ${esc(rel.object_label || rel.object_key || "?")}${itemId ? ` <span class="prov-relation-item-id">${esc(itemId)}</span>` : ""}</b><code>${esc(rel.id)}</code></div><small><span class="prov-semantic">${esc(semanticText(rel))}</span> · ${esc(rel.knowledge_state)} · source-backed provisional relation</small>${rel.semantics?.canonizable === false || rel.object_type === "spatial_zone" ? `<div class="prov-zone-note">Lightweight spatial-zone edge · review via the scalar floor/slot claim and direct entity containment.</div>` : rel.knowledge_state !== "canon" ? `<div class="prov-actions"><button class="tiny-btn" data-rel-action="canon">Make Canon</button></div>` : `<div class="prov-zone-note">◆ Canon · future changes use the canonical relation/retcon workflow.</div>`}</div>`; }).join("")}</div>` : ""}
        ${changes.length ? `<div class="sheet-section-head gap"><h3>Change history</h3><span>${changes.length}</span></div>${changes.map((change) => `<div class="prov-change"><b>${esc(change.change_kind.replaceAll("_"," "))}</b><small>${esc(change.from_proposition_id)} → ${esc(change.to_proposition_id)}</small><code>${esc(change.id)}</code></div>`).join("")}` : ""}`;
      body.appendChild(section);

      section.querySelectorAll("[data-cont-conflict]").forEach((row) => {
        const conflict = conflicts.find((item) => item.id === row.dataset.contConflict);
        if (!conflict) return;
        row.querySelectorAll("[data-cont-action]").forEach((button) => button.addEventListener("click", () => {
          const action = button.dataset.contAction;
          if (action === "dismiss") return resolveContinuityConflict(conflict, familyId, "dismiss");
          if (action === "left-correct") return resolveContinuityConflict(conflict, familyId, "correction", conflict.right_proposition_id, conflict.left_proposition_id);
          if (action === "right-correct") return resolveContinuityConflict(conflict, familyId, "correction", conflict.left_proposition_id, conflict.right_proposition_id);
          if (action === "left-to-right") return resolveContinuityConflict(conflict, familyId, "story_change", conflict.left_proposition_id, conflict.right_proposition_id);
          if (action === "right-to-left") return resolveContinuityConflict(conflict, familyId, "story_change", conflict.right_proposition_id, conflict.left_proposition_id);
        }));
      });

      const claimMap = new Map((data.claims || []).map((item) => [item.id, item]));
      section.querySelectorAll("[data-prov-action]").forEach((button) => button.addEventListener("click", async () => {
        const row = button.closest("[data-prov-claim]");
        const claim = claimMap.get(row?.dataset.provClaim);
        if (!claim) return;
        if (button.dataset.provAction === "correct") await editClaim(claim, familyId, "correction");
        else if (button.dataset.provAction === "story") await editClaim(claim, familyId, "story_change");
        else if (button.dataset.provAction === "canon") await makeCanon(claim, familyId);
      }));
      const relationMap = new Map(relations.map((item) => [item.id, item]));
      section.querySelectorAll("[data-rel-action='canon']").forEach((button) => button.addEventListener("click", async () => {
        const row = button.closest("[data-prov-relation]");
        const relation = relationMap.get(row?.dataset.provRelation);
        if (relation) await makeRelationCanon(relation, familyId);
      }));
    } catch (error) {
      console.warn("Provisional Discovery sheet unavailable", error);
    }
  }

  function wrapSheet() {
    const original = window.openEntitySheet;
    if (typeof original !== "function" || original.__provSheetWrapped) return;
    const wrapped = async function(familyId) {
      const family = (appState().families || []).find((item) => item.id === familyId);
      if (family && !provisionalVisible(family)) {
        window.toast?.("This provisional sheet belongs to another branch lineage.", 4500);
        return;
      }
      const result = await original.apply(this, arguments);
      await decorate(familyId);
      return result;
    };
    wrapped.__provSheetWrapped = true;
    window.openEntitySheet = wrapped;
  }

  function init() {
    styles();
    installVisibilityGuards();
    if (typeof setTimeout === "function") setTimeout(() => { installVisibilityGuards(); wrapSheet(); }, 0);
    else wrapSheet();
  }

  window.ArlineProvisionalSheets = Object.freeze({decorate, provisionalVisible, activeBranchLineageIds, physicalIdentity});
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, {once:true});
  else init();
})();
