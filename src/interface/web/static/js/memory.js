(() => {
  const byId = (id) => document.getElementById(id);
  const escapeHTML = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[char]));

  const memoryState = {
    lens: localStorage.getItem("arline.contextLens") || "scene",
    worldTime: null,
    storyOrder: null,
    povVariantId: null,
    status: null,
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
      card.innerHTML = `
        <div><span>Status</span><strong>${status.enabled ? "Enabled" : "Disabled"}</strong></div>
        <div><span>Evidence chunks</span><strong>${Number(status.chunks || 0).toLocaleString()}</strong></div>
        <div><span>FTS5</span><strong>${status.fts_available ? "Ready" : "Unavailable"}</strong></div>
        <div><span>Dense retrieval</span><strong>${status.embedding_available ? "LM Studio ready" : "Structured + FTS fallback"}</strong></div>
        <div><span>Spatial links</span><strong>${Number(status.spatial_edges || 0).toLocaleString()}</strong></div>
        <small>Embedding: ${escapeHTML(status.config?.embedding?.model || "not configured")}. Reranking stays optional.</small>`;
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

  // Tiny executable surface used by the runtime smoke test and future feature
  // modules. It deliberately returns a snapshot instead of exposing mutable state.
  window.ArlineMemoryRuntime = Object.freeze({ currentScope, activeScope });

  document.addEventListener("DOMContentLoaded", () => {
    injectSettings();
    setTimeout(() => {
      wrapPromptPayload();
      attachEntityMemoryTools();
    }, 0);
  });
})();
