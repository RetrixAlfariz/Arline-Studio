(() => {
  const byId = (id) => document.getElementById(id);
  const escapeHTML = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));

  const memoryState = {
    lens: localStorage.getItem("arline.contextLens") || "scene",
    worldTime: null,
    storyOrder: null,
    povVariantId: null,
    status: null,
    discoveries: [],
    discoveryCounts: {},
  };
  window.ArlineMemory = memoryState;

  function appState() {
    return window.ArlineRuntime?.getState?.() || {};
  }

  function activeScope() {
    const current = appState();
    const scope = window.ArlineRuntime?.getScope?.() || {};
    const activeDocumentId = current.activeScene?.document_id || null;
    const sceneCard = (current.sceneCards || []).find((item) => item.document_id === activeDocumentId) || null;
    return {
      projectId: scope.projectId || null,
      worldId: scope.worldId || null,
      branchId: scope.branchId || null,
      sessionId: scope.sessionId || null,
      storyOrder: memoryState.storyOrder ?? sceneCard?.sort_order ?? current.activeDocument?.sort_order ?? null,
      worldTime: memoryState.worldTime ?? current.activeScene?.narrative_time ?? sceneCard?.narrative_time ?? null,
      povVariantId: memoryState.povVariantId ?? current.activeScene?.pov_variant_id ?? sceneCard?.pov_variant_id ?? null,
    };
  }

  async function request(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: {"Content-Type":"application/json", ...(options.headers || {})},
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || `${response.status} ${response.statusText}`);
    }
    return response.json();
  }

  function injectSettings() {
    const panel = document.querySelector('[data-inspector-panel="context"]');
    if (!panel || byId("memorySettingsCard")) return;
    const section = document.createElement("section");
    section.id = "memorySettingsCard";
    section.className = "memory-settings-card";
    section.innerHTML = `
      <span class="eyebrow">v1.2 Memory Query Engine</span>
      <h3>Evidence, scope & viewpoint</h3>
      <label>Context lens
        <select id="memoryContextLens">
          <option value="author">Author — may use accepted future canon</option>
          <option value="scene">Scene — only evidence valid up to this scene</option>
          <option value="pov">POV — scene truth plus character knowledge/beliefs</option>
        </select>
      </label>
      <div id="memoryRuntimeStatus" class="info-card">Checking memory indexes…</div>
      <div class="memory-settings-actions">
        <button id="memoryRefreshBtn" class="secondary-btn">Refresh status</button>
        <button id="memoryBackfillBtn" class="primary-btn">Index existing workspace</button>
      </div>
      <details class="memory-debugger">
        <summary>Memory query debugger</summary>
        <label>Query<input id="memoryDebugQuery" placeholder="Where is the black dress?" /></label>
        <button id="memoryPlanBtn" class="secondary-btn wide">Compile & retrieve</button>
        <pre id="memoryDebugOutput" class="json-block">No query run.</pre>
      </details>`;
    panel.appendChild(section);
    byId("memoryContextLens").value = memoryState.lens;
    byId("memoryContextLens").addEventListener("change", (event) => {
      memoryState.lens = event.target.value;
      localStorage.setItem("arline.contextLens", memoryState.lens);
    });
    byId("memoryRefreshBtn").addEventListener("click", loadStatus);
    byId("memoryBackfillBtn").addEventListener("click", backfill);
    byId("memoryPlanBtn").addEventListener("click", debugQuery);
    loadStatus();
  }

  async function loadStatus() {
    const card = byId("memoryRuntimeStatus");
    if (!card) return;
    card.textContent = "Checking memory indexes…";
    try {
      const status = await request("/api/memory/status");
      memoryState.status = status;
      const discovery = status.discovery || {};
      card.innerHTML = `
        <div><span>Status</span><strong>${status.enabled ? "Enabled" : "Disabled"}</strong></div>
        <div><span>Evidence chunks</span><strong>${Number(status.chunks || 0).toLocaleString()}</strong></div>
        <div><span>FTS5</span><strong>${status.fts_available ? "Ready" : "Unavailable"}</strong></div>
        <div><span>Dense retrieval</span><strong>${status.embedding_available ? "LM Studio ready" : "Structured + FTS fallback"}</strong></div>
        <div><span>Spatial links</span><strong>${Number(status.spatial_edges || 0).toLocaleString()}</strong></div>
        <div><span>Narrative discoveries</span><strong>${Number(discovery.propositions || 0).toLocaleString()}</strong></div>
        <small>Embedding: ${escapeHTML(status.config?.embedding?.model || "not configured")}. Reranking stays optional. Discovery never grants canon automatically.</small>`;
    } catch (error) {
      card.innerHTML = `<b>Memory service unavailable</b><small>${escapeHTML(error.message)}</small>`;
    }
  }

  async function backfill() {
    const button = byId("memoryBackfillBtn");
    if (!button) return;
    button.disabled = true;
    button.textContent = "Indexing…";
    try {
      const projectId = activeScope().projectId;
      if (!projectId) throw new Error("Open a project before running scoped Memory backfill.");
      const result = await request("/api/memory/backfill", {
        method: "POST",
        body: JSON.stringify({project_id: projectId, background: true}),
      });
      if (result.job?.id) {
        let job = result.job;
        while (!["done", "failed"].includes(job.status)) {
          await new Promise((resolve) => setTimeout(resolve, 350));
          job = await request(`/api/memory/jobs/${encodeURIComponent(job.id)}`);
          button.textContent = `${Math.round((job.progress || 0) * 100)}% · ${job.message || "Indexing"}`;
        }
        if (job.status === "failed") throw new Error(job.message || "Memory indexing failed");
        button.textContent = `Indexed ${job.result?.chunks || 0} chunks`;
      } else {
        button.textContent = `Indexed ${result.chunks || 0} chunks`;
      }
      await loadStatus();
    } catch (error) {
      button.textContent = "Index failed";
      window.toast?.(error.message, 6000);
    } finally {
      setTimeout(() => { button.disabled = false; button.textContent = "Index existing workspace"; }, 1800);
    }
  }

  function currentScope(query) {
    const scope = activeScope();
    const refs = typeof window.collectPromptReferences === "function" ? window.collectPromptReferences() : [];
    return {
      query,
      project_id: scope.projectId,
      world_id: scope.worldId,
      branch_id: scope.branchId,
      session_id: scope.sessionId,
      context_lens: memoryState.lens,
      story_order: scope.storyOrder,
      world_time: scope.worldTime,
      pov_variant_id: scope.povVariantId,
      explicit_references: refs,
    };
  }

  async function debugQuery() {
    const query = byId("memoryDebugQuery")?.value?.trim();
    if (!query) return;
    const output = byId("memoryDebugOutput");
    output.textContent = "Compiling query plan…";
    try {
      const result = await request("/api/memory/query", {
        method: "POST",
        body: JSON.stringify(currentScope(query)),
      });
      output.textContent = JSON.stringify(result, null, 2);
    } catch (error) {
      output.textContent = error.message;
    }
  }

  function wrapPromptPayload() {
    const original = window.promptPayload;
    if (typeof original !== "function" || original.__memoryWrapped) return;
    const wrapped = function(...args) {
      const payload = original.apply(this, args);
      return {
        ...payload,
        context_lens: memoryState.lens,
        world_time: memoryState.worldTime,
        story_order: memoryState.storyOrder,
        pov_variant_id: memoryState.povVariantId,
      };
    };
    wrapped.__memoryWrapped = true;
    window.promptPayload = wrapped;
  }

  function attachEntityMemoryTools() {
    const original = window.openEntitySheet;
    if (typeof original !== "function" || original.__memoryWrapped) return;
    const wrapped = async function(familyId, variantId = null) {
      const result = await original.apply(this, arguments);
      const footer = byId("sheetFooter");
      if (!footer || footer.querySelector(".memory-entity-btn")) return result;
      const button = document.createElement("button");
      button.className = "secondary-btn memory-entity-btn";
      button.textContent = "Memory & spatial";
      button.addEventListener("click", () => openResourceMemory(familyId, variantId));
      footer.prepend(button);
      return result;
    };
    wrapped.__memoryWrapped = true;
    window.openEntitySheet = wrapped;
  }

  async function openResourceMemory(familyId, variantId) {
    const scope = activeScope();
    const worldId = scope.worldId;
    const branchId = scope.branchId;
    const type = variantId ? "entity_variant" : "entity_family";
    const id = variantId || familyId;
    if (!worldId) return window.toast?.("Open a world first");
    const params = new URLSearchParams({world_id: worldId, resource_type: type, resource_id: id, depth: "3"});
    if (branchId) params.set("branch_id", branchId);
    try {
      const [spatial, chunks, threads] = await Promise.all([
        request(`/api/memory/spatial/neighborhood?${params}`),
        request(`/api/memory/chunks?resource_type=${encodeURIComponent(type)}&resource_id=${encodeURIComponent(id)}`),
        request(`/api/memory/threads?world_id=${encodeURIComponent(worldId)}&branch_id=${encodeURIComponent(branchId || "")}&resource_type=${encodeURIComponent(type)}&resource_id=${encodeURIComponent(id)}`),
      ]);
      const compare = byId("compareDialog");
      byId("compareTitle").textContent = "Memory & spatial links";
      byId("compareBody").innerHTML = `
        <h3>Spatial neighborhood</h3><pre class="json-block">${escapeHTML(JSON.stringify(spatial, null, 2))}</pre>
        <h3>Linked evidence</h3><pre class="json-block">${escapeHTML(JSON.stringify(chunks.items || [], null, 2))}</pre>
        <h3>Story threads</h3><pre class="json-block">${escapeHTML(JSON.stringify(threads.items || [], null, 2))}</pre>`;
      compare.showModal();
    } catch (error) {
      window.toast?.(error.message, 6000);
    }
  }

  function discoveryScopeParams() {
    const scope = activeScope();
    const params = new URLSearchParams();
    if (scope.projectId) params.set("project_id", scope.projectId);
    if (scope.worldId) params.set("world_id", scope.worldId);
    if (scope.branchId) params.set("branch_id", scope.branchId);
    if (scope.sessionId) params.set("session_id", scope.sessionId);
    return params;
  }

  function discoveryDecisionPayload() {
    const scope = activeScope();
    return {
      project_id: scope.projectId,
      world_id: scope.worldId,
      branch_id: scope.branchId,
      session_id: scope.sessionId,
      story_order: scope.storyOrder,
      world_time: scope.worldTime,
      note: "Explicit user decision from Library discovery review",
    };
  }

  function discoveryValue(item) {
    if (item.predicate === "entity.exists") {
      return `${item.value?.entity_type || item.subject_type || "entity"} candidate`;
    }
    if (item.operation === "relation" && item.object_label) {
      return `${item.predicate.replaceAll("_", " ")} → ${item.object_label}`;
    }
    const value = item.value;
    if (value == null) return "—";
    if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
    const text = JSON.stringify(value);
    return text.length > 160 ? `${text.slice(0, 157)}…` : text;
  }

  function discoveryStatusIcon(state) {
    return ({detected:"◌", reviewed:"◇", canon:"◆", dismissed:"×"})[state] || "◌";
  }

  function discoveryStatusLabel(item) {
    const state = item.knowledge_state || "detected";
    const support = Number(item.qualified_support_count || 0);
    if (state === "reviewed") return `Reviewed · ${support} user-backed sources`;
    if (state === "canon") return item.provenance_state === "orphaned" ? "Canon · source provenance orphaned" : "Canon · user-authorized";
    if (state === "dismissed") return "Dismissed";
    return `Detected · ${Number(item.support_count || 0)} active source${Number(item.support_count || 0) === 1 ? "" : "s"}`;
  }

  async function loadDiscoveries({render = true} = {}) {
    const scope = activeScope();
    if (!scope.projectId || !scope.worldId) {
      memoryState.discoveries = [];
      memoryState.discoveryCounts = {};
      if (render) renderDiscoveryGrid();
      return [];
    }
    try {
      const result = await request(`/api/memory/discoveries?${discoveryScopeParams()}`);
      memoryState.discoveries = result.items || [];
      memoryState.discoveryCounts = result.counts || {};
      const badge = byId("discoveryTabCount");
      if (badge) {
        const pending = Number(result.counts?.detected || 0) + Number(result.counts?.reviewed || 0);
        badge.textContent = pending ? String(pending) : "";
        badge.classList.toggle("hidden", !pending);
      }
      if (render) renderDiscoveryGrid();
      return memoryState.discoveries;
    } catch (error) {
      if (render) {
        const grid = byId("worldGrid");
        if (grid) grid.innerHTML = `<div class="discovery-empty"><b>Narrative Discovery unavailable</b><span>${escapeHTML(error.message)}</span></div>`;
      }
      return [];
    }
  }

  function renderDiscoveryGrid() {
    if (appState().activeWorldTab !== "discoveries") return;
    const grid = byId("worldGrid");
    const empty = byId("worldEmpty");
    if (!grid) return;
    const search = (byId("worldSearch")?.value || "").trim().toLowerCase();
    const items = memoryState.discoveries.filter((item) => {
      if (!search) return true;
      return `${item.subject_label} ${item.subject_type} ${item.predicate} ${discoveryValue(item)} ${item.knowledge_state}`.toLowerCase().includes(search);
    });
    grid.classList.add("discovery-grid");
    grid.innerHTML = items.map((item) => `
      <article class="world-card discovery-card" data-discovery-id="${escapeHTML(item.id)}" tabindex="0">
        <div class="discovery-card-head">
          <span class="discovery-state ${escapeHTML(item.knowledge_state)}">${discoveryStatusIcon(item.knowledge_state)} ${escapeHTML(item.knowledge_state)}</span>
          <small>${escapeHTML(item.operation.replaceAll("_", " "))}</small>
        </div>
        <h3>${escapeHTML(item.subject_label)}</h3>
        <code class="discovery-path">${escapeHTML(item.predicate)}</code>
        <p>${escapeHTML(discoveryValue(item))}</p>
        <div class="discovery-support"><span>${escapeHTML(discoveryStatusLabel(item))}</span><span>${escapeHTML(item.provenance_state)}</span></div>
      </article>`).join("");
    if (empty) empty.classList.toggle("hidden", items.length > 0);
    if (!items.length) {
      grid.innerHTML = `<div class="discovery-empty"><b>No discoveries in this narrative lineage.</b><span>Write naturally in Chat. Arline will detect reusable characters, locations, items, relations, and state changes without making them canon.</span></div>`;
      if (empty) empty.classList.add("hidden");
    }
    grid.querySelectorAll("[data-discovery-id]").forEach((card) => {
      card.addEventListener("click", () => openDiscoveryDetail(card.dataset.discoveryId));
      card.addEventListener("keydown", (event) => { if (event.key === "Enter") openDiscoveryDetail(card.dataset.discoveryId); });
    });
  }

  async function openDiscoveryDetail(id) {
    try {
      const item = await request(`/api/memory/discoveries/${encodeURIComponent(id)}?${discoveryScopeParams()}`);
      const visible = new Set(item.visible_instance_ids || []);
      const instances = (item.instances || []).filter((instance) => visible.has(instance.id));
      byId("sheetEyebrow").textContent = `Narrative Discovery · ${item.knowledge_state}`;
      byId("sheetTitle").textContent = item.subject_label || "Discovery";
      byId("sheetSubtitle").textContent = `${item.subject_type} · ${item.provenance_state} provenance · ${item.support_count} active support`;
      byId("sheetBody").innerHTML = `
        <section class="sheet-section discovery-overview">
          <div class="sheet-section-head"><h3>Proposition</h3><span class="discovery-state ${escapeHTML(item.knowledge_state)}">${discoveryStatusIcon(item.knowledge_state)} ${escapeHTML(item.knowledge_state)}</span></div>
          <code>${escapeHTML(item.predicate)}</code>
          <pre class="json-block">${escapeHTML(JSON.stringify(item.value, null, 2))}</pre>
          <p>${escapeHTML(discoveryStatusLabel(item))}. Canon authority is never inferred from frequency or model confidence.</p>
        </section>
        <section class="sheet-section">
          <div class="sheet-section-head"><h3>Evidence lineage</h3><span>${instances.length} visible · ${Number(item.out_of_scope_support_count || 0)} outside this lineage</span></div>
          ${instances.length ? instances.map((instance) => `
            <article class="discovery-source ${instance.qualifies_review ? "qualified" : "supporting"}">
              <div><b>${escapeHTML(instance.source_kind.replaceAll("_", " "))}</b><span>${instance.qualifies_review ? "user-backed" : "support only"}</span></div>
              <small>message ${escapeHTML(instance.source_turn_id || "unknown")} · branch ${escapeHTML(instance.branch_id || "main")}</small>
              ${instance.span_text ? `<blockquote>${escapeHTML(instance.span_text)}</blockquote>` : ""}
            </article>`).join("") : `<div class="empty-note">No active source text is visible in this lineage. ${item.knowledge_state === "canon" ? "User-authorized canon remains valid even when provenance is orphaned." : ""}</div>`}
          ${Number(item.inactive_support_count || 0) ? `<p class="discovery-muted">${Number(item.inactive_support_count)} source instance(s) were invalidated by deletion, revision, feedback, or lifecycle changes.</p>` : ""}
        </section>
        <section class="sheet-section">
          <div class="sheet-section-head"><h3>Authority boundary</h3></div>
          <p><b>Detected</b> means Arline observed it. <b>Reviewed</b> means it was reinforced by independent user-backed sources in this valid lineage. <b>Canon</b> exists only after your explicit decision.</p>
        </section>`;
      const footer = byId("sheetFooter");
      if (item.knowledge_state === "canon") {
        footer.innerHTML = `<span class="protected-note">◆ User-authorized canon</span>`;
      } else if (item.knowledge_state === "dismissed") {
        footer.innerHTML = `<button class="secondary-btn discovery-reset">Restore to detected</button>`;
      } else {
        footer.innerHTML = `<button class="danger-text-btn discovery-dismiss">Dismiss</button><button class="primary-btn discovery-canon">◆ Make Canon</button>`;
      }
      footer.querySelector(".discovery-canon")?.addEventListener("click", () => makeDiscoveryCanon(item));
      footer.querySelector(".discovery-dismiss")?.addEventListener("click", () => dismissDiscovery(item));
      footer.querySelector(".discovery-reset")?.addEventListener("click", () => resetDiscovery(item));
      window.openSheet?.();
    } catch (error) {
      window.toast?.(error.message, 6000);
    }
  }

  async function makeDiscoveryCanon(item) {
    if (!confirm(`Make “${item.subject_label} · ${item.predicate}” canon?\n\nThis is an explicit user authority decision. Source frequency alone never performs this action.`)) return;
    try {
      await request(`/api/memory/discoveries/${encodeURIComponent(item.id)}/canon`, {
        method: "POST", body: JSON.stringify(discoveryDecisionPayload()),
      });
      window.closeSheet?.();
      if (typeof window.loadProjectData === "function") await window.loadProjectData();
      await loadDiscoveries();
      window.toast?.("Discovery promoted to user-authorized canon");
    } catch (error) { window.toast?.(error.message, 6000); }
  }

  async function dismissDiscovery(item) {
    if (!confirm(`Dismiss this discovery?\n\nArline will keep the provenance decision so the same weak observation does not keep resurfacing.`)) return;
    try {
      await request(`/api/memory/discoveries/${encodeURIComponent(item.id)}/dismiss`, {
        method: "POST", body: JSON.stringify(discoveryDecisionPayload()),
      });
      window.closeSheet?.();
      await loadDiscoveries();
    } catch (error) { window.toast?.(error.message, 6000); }
  }

  async function resetDiscovery(item) {
    try {
      await request(`/api/memory/discoveries/${encodeURIComponent(item.id)}/reset`, {
        method: "POST", body: JSON.stringify(discoveryDecisionPayload()),
      });
      window.closeSheet?.();
      await loadDiscoveries();
    } catch (error) { window.toast?.(error.message, 6000); }
  }

  function injectDiscoveryStyles() {
    if (byId("discoveryStyles")) return;
    const style = document.createElement("style");
    style.id = "discoveryStyles";
    style.textContent = `
      #discoveryTabCount{display:inline-flex;min-width:18px;height:18px;padding:0 5px;margin-left:5px;align-items:center;justify-content:center;border-radius:999px;background:color-mix(in srgb,var(--accent) 20%,transparent);font-size:10px}.discovery-grid{align-content:start}.discovery-card{cursor:pointer;min-height:188px}.discovery-card-head,.discovery-support,.discovery-source>div{display:flex;justify-content:space-between;gap:10px;align-items:center}.discovery-state{display:inline-flex;align-items:center;gap:5px;text-transform:capitalize;font-weight:700;font-size:11px}.discovery-state.detected{opacity:.72}.discovery-state.reviewed{color:var(--accent)}.discovery-state.canon{font-weight:800}.discovery-state.dismissed{opacity:.55}.discovery-path{display:block;margin:7px 0;font-size:11px;opacity:.72}.discovery-support{margin-top:auto;padding-top:10px;border-top:1px solid var(--line);font-size:11px;opacity:.7}.discovery-empty{grid-column:1/-1;display:flex;flex-direction:column;gap:7px;padding:28px;border:1px dashed var(--line);border-radius:14px}.discovery-source{padding:12px 0;border-bottom:1px solid var(--line)}.discovery-source>div span{font-size:10px;opacity:.65}.discovery-source small{display:block;margin-top:4px;opacity:.65}.discovery-source blockquote{margin:8px 0 0;padding:8px 10px;border-left:2px solid var(--line);font-size:12px;white-space:pre-wrap}.discovery-source.qualified blockquote{border-left-color:var(--accent)}.discovery-muted{opacity:.6;font-size:12px}`;
    document.head.appendChild(style);
  }

  function installDiscoveryLibrary() {
    const tabs = byId("worldTabs");
    if (!tabs || byId("discoveryWorldTab")) return;
    const button = document.createElement("button");
    button.id = "discoveryWorldTab";
    button.dataset.worldTab = "discoveries";
    button.innerHTML = `Discoveries <span id="discoveryTabCount" class="hidden"></span>`;
    const worlds = tabs.querySelector('[data-world-tab="worlds"]');
    tabs.insertBefore(button, worlds || null);
    button.addEventListener("click", async () => {
      const state = appState();
      state.activeWorldTab = "discoveries";
      tabs.querySelectorAll("[data-world-tab]").forEach((tab) => tab.classList.toggle("active", tab === button));
      await loadDiscoveries();
    });

    const originalRender = window.renderWorldGrid;
    if (typeof originalRender === "function" && !originalRender.__discoveryWrapped) {
      const wrapped = function(...args) {
        if (appState().activeWorldTab === "discoveries") {
          loadDiscoveries();
          return;
        }
        const grid = byId("worldGrid");
        grid?.classList.remove("discovery-grid");
        return originalRender.apply(this, args);
      };
      wrapped.__discoveryWrapped = true;
      window.renderWorldGrid = wrapped;
    }

    // Keep the badge useful without changing the active Library view.
    loadDiscoveries({render:false});
  }

  // Tiny executable surface used by the runtime smoke test and future feature
  // modules. It deliberately returns a snapshot instead of exposing mutable state.
  window.ArlineMemoryRuntime = Object.freeze({ currentScope, activeScope });

  document.addEventListener("DOMContentLoaded", () => {
    injectSettings();
    injectDiscoveryStyles();
    setTimeout(() => {
      wrapPromptPayload();
      attachEntityMemoryTools();
      installDiscoveryLibrary();
    }, 0);
  });
})();