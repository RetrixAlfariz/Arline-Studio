(() => {
  const byId = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? "").replace(/[&<>'"]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
  const icon = (state) => ({detected:"◌",reviewed:"◇",canon:"◆",dismissed:"×"})[state] || "◌";

  function scopeParams() {
    const scope = window.ArlineMemoryRuntime?.activeScope?.() || {};
    const params = new URLSearchParams();
    if (scope.projectId) params.set("project_id", scope.projectId);
    if (scope.worldId) params.set("world_id", scope.worldId);
    if (scope.branchId) params.set("branch_id", scope.branchId);
    if (scope.sessionId) params.set("session_id", scope.sessionId);
    if (scope.storyOrder != null) params.set("story_order", String(scope.storyOrder));
    return params;
  }

  async function getJSON(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return response.json();
  }

  function valueText(value) {
    if (value == null) return "—";
    if (["string","number","boolean"].includes(typeof value)) return String(value);
    return JSON.stringify(value);
  }

  function styles() {
    if (byId("provisionalSheetStyles")) return;
    const style = document.createElement("style");
    style.id = "provisionalSheetStyles";
    style.textContent = `.prov-banner{padding:11px;border:1px solid color-mix(in srgb,var(--accent) 35%,var(--line));border-radius:10px;margin-bottom:12px}.prov-banner small,.prov-row small{display:block;opacity:.65;margin-top:3px}.prov-path{display:flex;flex-wrap:wrap;gap:6px;padding:8px 0}.prov-path span:not(:last-child)::after{content:'›';opacity:.45;margin-left:6px}.prov-list{display:grid;gap:7px}.prov-row{padding:9px;border:1px solid var(--line);border-radius:9px}.prov-row-head{display:flex;justify-content:space-between;gap:8px}.prov-row code{font-size:9px;opacity:.55}.prov-value{display:block;margin-top:4px;word-break:break-word}.prov-change{padding:7px 0;border-bottom:1px solid var(--line)}`;
    document.head.appendChild(style);
  }

  async function decorate(familyId) {
    const body = byId("sheetBody");
    if (!body) return;
    body.querySelector("#provisionalDiscoverySection")?.remove();
    try {
      const data = await getJSON(`/api/memory/discoveries/resource/entity_family/${encodeURIComponent(familyId)}?${scopeParams()}`);
      if (!data.provisional && !(data.claims || []).length && !(data.relations || []).length) return;
      const claims = (data.claims || []).filter((item) => item.predicate !== "entity.exists");
      const relations = data.relations || [];
      const changes = data.changes || [];
      const path = data.spatial_path || [];
      const section = document.createElement("section");
      section.id = "provisionalDiscoverySection";
      section.className = "sheet-section";
      section.innerHTML = `
        <div class="prov-banner"><b>${icon(data.knowledge_state)} ${esc(data.knowledge_state || "detected")} Library sheet</b><small>The sheet ID is stable. Each detected value keeps its own claim ID and provenance; none becomes Canon without an explicit user action.</small></div>
        ${path.length > 1 ? `<div class="sheet-section-head"><h3>Spatial path</h3></div><div class="prov-path">${path.map((node) => `<span><b>${esc(node.label)}</b>${node.zone_kind ? ` <small>${esc(node.zone_kind)}</small>` : ""}</span>`).join("")}</div>` : ""}
        <div class="sheet-section-head"><h3>Discovered knowledge</h3><span>${claims.length}</span></div>
        <div class="prov-list">${claims.length ? claims.map((claim) => `<div class="prov-row"><div class="prov-row-head"><b>${icon(claim.knowledge_state)} ${esc(claim.predicate)}</b><code>${esc(claim.id)}</code></div><span class="prov-value">${esc(valueText(claim.value))}</span><small>${esc(claim.knowledge_state)} · ${Number(claim.support_count || 0)} active source${Number(claim.support_count || 0) === 1 ? "" : "s"}</small></div>`).join("") : `<div class="empty-note">No scoped discovered fields.</div>`}</div>
        ${relations.length ? `<div class="sheet-section-head gap"><h3>Relations</h3><span>${relations.length}</span></div><div class="prov-list">${relations.map((rel) => `<div class="prov-row"><div class="prov-row-head"><b>${icon(rel.knowledge_state)} ${esc(rel.subject_label)} ${esc(String(rel.predicate || "related_to").replaceAll("_"," "))} ${esc(rel.object_label || rel.object_key || "?")}</b><code>${esc(rel.id)}</code></div><small>${esc(rel.knowledge_state)} · source-backed provisional relation</small></div>`).join("")}</div>` : ""}
        ${changes.length ? `<div class="sheet-section-head gap"><h3>Change history</h3><span>${changes.length}</span></div>${changes.map((change) => `<div class="prov-change"><b>${esc(change.change_kind.replaceAll("_"," "))}</b><small>${esc(change.from_proposition_id)} → ${esc(change.to_proposition_id)}</small><code>${esc(change.id)}</code></div>`).join("")}` : ""}`;
      body.appendChild(section);
    } catch (error) {
      console.warn("Provisional Discovery sheet unavailable", error);
    }
  }

  function wrap() {
    const original = window.openEntitySheet;
    if (typeof original !== "function" || original.__provSheetWrapped) return;
    const wrapped = async function(familyId) {
      const result = await original.apply(this, arguments);
      await decorate(familyId);
      return result;
    };
    wrapped.__provSheetWrapped = true;
    window.openEntitySheet = wrapped;
  }

  window.ArlineProvisionalSheets = Object.freeze({decorate});
  document.addEventListener("DOMContentLoaded", () => { styles(); setTimeout(wrap, 0); });
})();