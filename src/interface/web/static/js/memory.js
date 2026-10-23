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

  function appState() { return window.ArlineRuntime?.getState?.() || {}; }

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
        <small>Embedding: ${escapeHTML(status.config?.embedding?.model || "not configured")}. Discovery never grants canon automatically.</small>`;
    } catch (error) {
      card.innerHTML = `<b>Memory service unavailable</b><small>${escapeHTML(error.message)}</small>`;
    }
  }

  async function scanExistingDiscoveries({announce = true} = {}) {
    const scope = activeScope();
    if (!scope.projectId) throw new Error("Open a project before scanning existing chats.");
    const result = await request(`/api/memory/discoveries/backfill?project_id=${encodeURIComponent(scope.projectId)}`, {method:"POST"});
    await loadDiscoveries({render: appState().activeWorldTab === "discoveries"});
    await loadStatus();
    if (announce) window.toast?.(`Discovery scan: ${result.turns || 0} turns · ${result.instances || 0} evidence instances`, 5000);
    return result;
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
        method: "POST", body: JSON.stringify({project_id: projectId, background: true}),
      });
      if (result.job?.id) {
        let job = result.job;
        while (!["done", "failed"].includes(job.status)) {
          await new Promise((resolve) => setTimeout(resolve, 350));
          job = await request(`/api/memory/jobs/${encodeURIComponent(job.id)}`);
          button.textContent = `${Math.round((job.progress || 0) * 100)}% · ${job.message || "Indexing"}`;
        }
        if (job.status === "failed") throw new Error(job.message || "Memory indexing failed");
      }
      button.textContent = "Scanning narrative discoveries…";
      const discovery = await scanExistingDiscoveries({announce:false});
      button.textContent = `Ready · ${discovery.instances || 0} discovery evidence`;
      await loadStatus();
    } catch (error) {
      button.textContent = "Index failed";
      window.toast?.(error.message, 6000);
    } finally {
      setTimeout(() => { button.disabled = false; button.textContent = "Index existing workspace"; }, 2200);
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
      const result = await request("/api/memory/query", {method:"POST", body:JSON.stringify(currentScope(query))});
      output.textContent = JSON.stringify(result, null, 2);
    } catch (error) { output.textContent = error.message; }
  }

  function wrapPromptPayload() {
    const original = window.promptPayload;
    if (typeof original !== "function" || original.__memoryWrapped) return;
    const wrapped = function(...args) {
      const payload = original.apply(this, args);
      return {...payload, context_lens:memoryState.lens, world_time:memoryState.worldTime, story_order:memoryState.storyOrder, pov_variant_id:memoryState.povVariantId};
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
    if (!scope.worldId) return window.toast?.("Open a world first");
    const type = variantId ? "entity_variant" : "entity_family";
    const id = variantId || familyId;
    const params = new URLSearchParams({world_id:scope.worldId, resource_type:type, resource_id:id, depth:"3"});
    if (scope.branchId) params.set("branch_id", scope.branchId);
    try {
      const [spatial, chunks, threads] = await Promise.all([
        request(`/api/memory/spatial/neighborhood?${params}`),
        request(`/api/memory/chunks?resource_type=${encodeURIComponent(type)}&resource_id=${encodeURIComponent(id)}`),
        request(`/api/memory/threads?world_id=${encodeURIComponent(scope.worldId)}&branch_id=${encodeURIComponent(scope.branchId || "")}&resource_type=${encodeURIComponent(type)}&resource_id=${encodeURIComponent(id)}`),
      ]);
      byId("compareTitle").textContent = "Memory & spatial links";
      byId("compareBody").innerHTML = `<h3>Spatial neighborhood</h3><pre class="json-block">${escapeHTML(JSON.stringify(spatial,null,2))}</pre><h3>Linked evidence</h3><pre class="json-block">${escapeHTML(JSON.stringify(chunks.items||[],null,2))}</pre><h3>Story threads</h3><pre class="json-block">${escapeHTML(JSON.stringify(threads.items||[],null,2))}</pre>`;
      byId("compareDialog")?.showModal();
    } catch (error) { window.toast?.(error.message,6000); }
  }

  function discoveryScopeParams() {
    const scope = activeScope();
    const params = new URLSearchParams();
    if (scope.projectId) params.set("project_id",scope.projectId);
    if (scope.worldId) params.set("world_id",scope.worldId);
    if (scope.branchId) params.set("branch_id",scope.branchId);
    if (scope.sessionId) params.set("session_id",scope.sessionId);
    return params;
  }

  function discoveryDecisionPayload() {
    const scope = activeScope();
    return {project_id:scope.projectId,world_id:scope.worldId,branch_id:scope.branchId,session_id:scope.sessionId,story_order:scope.storyOrder,world_time:scope.worldTime,note:"Explicit user decision from Library discovery review"};
  }

  function discoveryValue(item) {
    if (item.predicate === "entity.exists") return `${item.value?.entity_type || item.subject_type || "entity"} candidate`;
    if (item.operation === "relation" && item.object_label) return `${item.predicate.replaceAll("_"," ")} → ${item.object_label}`;
    const value = item.value;
    if (value == null) return "—";
    if (["string","number","boolean"].includes(typeof value)) return String(value);
    const text = JSON.stringify(value);
    return text.length > 160 ? `${text.slice(0,157)}…` : text;
  }

  function discoveryStatusIcon(state) { return ({detected:"◌",reviewed:"◇",canon:"◆",dismissed:"×"})[state] || "◌"; }

  function discoveryStatusLabel(item) {
    const state = item.knowledge_state || "detected";
    const support = Number(item.qualified_support_count || 0);
    if (state === "reviewed") return `Reviewed · ${support} user-backed sources`;
    if (state === "canon") return item.provenance_state === "orphaned" ? "Canon · source provenance orphaned" : "Canon · user-authorized";
    if (state === "dismissed") return "Dismissed";
    return `Detected · ${Number(item.support_count||0)} active source${Number(item.support_count||0)===1?"":"s"}`;
  }

  function updateDiscoveryBadges(counts = {}) {
    const pending = Number(counts.detected || 0) + Number(counts.reviewed || 0);
    for (const id of ["discoveryTabCount","discoverySidebarCount"]) {
      const badge = byId(id);
      if (!badge) continue;
      badge.textContent = pending ? String(pending) : "0";
      badge.classList.toggle("hidden", id === "discoveryTabCount" && !pending);
    }
  }

  async function loadDiscoveries({render = true} = {}) {
    const scope = activeScope();
    if (!scope.projectId || !scope.worldId) {
      memoryState.discoveries = []; memoryState.discoveryCounts = {}; updateDiscoveryBadges({});
      if (render) renderDiscoveryGrid();
      return [];
    }
    try {
      const result = await request(`/api/memory/discoveries?${discoveryScopeParams()}`);
      memoryState.discoveries = result.items || [];
      memoryState.discoveryCounts = result.counts || {};
      updateDiscoveryBadges(memoryState.discoveryCounts);
      if (render) renderDiscoveryGrid();
      return memoryState.discoveries;
    } catch (error) {
      if (render && appState().activeWorldTab === "discoveries") {
        const grid = byId("worldGrid");
        if (grid) grid.innerHTML = `<div class="discovery-empty"><b>Narrative Discovery unavailable</b><span>${escapeHTML(error.message)}</span></div>`;
      }
      return [];
    }
  }

  function bindDiscoveryCards() {
    byId("worldGrid")?.querySelectorAll("[data-discovery-id]").forEach((card) => {
      card.addEventListener("click",()=>openDiscoveryDetail(card.dataset.discoveryId));
      card.addEventListener("keydown",(event)=>{if(event.key==="Enter")openDiscoveryDetail(card.dataset.discoveryId);});
    });
    byId("discoveryScanExistingBtn")?.addEventListener("click",async()=>{
      const button=byId("discoveryScanExistingBtn");
      button.disabled=true;button.textContent="Scanning…";
      try{await scanExistingDiscoveries();}catch(error){window.toast?.(error.message,6000);}finally{button.disabled=false;button.textContent="Scan existing chats";}
    });
  }

  function renderDiscoveryGrid() {
    if (appState().activeWorldTab !== "discoveries") return;
    const grid = byId("worldGrid"), empty = byId("worldEmpty");
    if (!grid) return;
    const search=(byId("worldSearch")?.value||"").trim().toLowerCase();
    const items=memoryState.discoveries.filter((item)=>!search||`${item.subject_label} ${item.subject_type} ${item.predicate} ${discoveryValue(item)} ${item.knowledge_state}`.toLowerCase().includes(search));
    grid.classList.add("discovery-grid");
    if (!items.length) {
      grid.innerHTML=`<div class="discovery-empty"><b>No discoveries in this narrative lineage yet.</b><span>New Chat turns are captured automatically. If this project already contained chats before Narrative Discovery was added, scan them once.</span><button id="discoveryScanExistingBtn" class="secondary-btn">Scan existing chats</button></div>`;
      empty?.classList.add("hidden"); bindDiscoveryCards(); return;
    }
    grid.innerHTML=items.map((item)=>`<article class="world-card discovery-card" data-discovery-id="${escapeHTML(item.id)}" tabindex="0"><div class="discovery-card-head"><span class="discovery-state ${escapeHTML(item.knowledge_state)}">${discoveryStatusIcon(item.knowledge_state)} ${escapeHTML(item.knowledge_state)}</span><small>${escapeHTML(item.operation.replaceAll("_"," "))}</small></div><h3>${escapeHTML(item.subject_label)}</h3><code class="discovery-path">${escapeHTML(item.predicate)}</code><p>${escapeHTML(discoveryValue(item))}</p><div class="discovery-support"><span>${escapeHTML(discoveryStatusLabel(item))}</span><span>${escapeHTML(item.provenance_state)}</span></div></article>`).join("");
    empty?.classList.add("hidden"); bindDiscoveryCards();
  }

  async function openDiscoveryDetail(id) {
    try {
      const item=await request(`/api/memory/discoveries/${encodeURIComponent(id)}?${discoveryScopeParams()}`);
      const visible=new Set(item.visible_instance_ids||[]);
      const instances=(item.instances||[]).filter((instance)=>visible.has(instance.id));
      byId("sheetEyebrow").textContent=`Narrative Discovery · ${item.knowledge_state}`;
      byId("sheetTitle").textContent=item.subject_label||"Discovery";
      byId("sheetSubtitle").textContent=`${item.subject_type} · ${item.provenance_state} provenance · ${item.support_count} active support`;
      byId("sheetBody").innerHTML=`<section class="sheet-section discovery-overview"><div class="sheet-section-head"><h3>Proposition</h3><span class="discovery-state ${escapeHTML(item.knowledge_state)}">${discoveryStatusIcon(item.knowledge_state)} ${escapeHTML(item.knowledge_state)}</span></div><code>${escapeHTML(item.predicate)}</code><pre class="json-block">${escapeHTML(JSON.stringify(item.value,null,2))}</pre><p>${escapeHTML(discoveryStatusLabel(item))}. Canon authority is never inferred from frequency or model confidence.</p></section><section class="sheet-section"><div class="sheet-section-head"><h3>Evidence lineage</h3><span>${instances.length} visible · ${Number(item.out_of_scope_support_count||0)} outside this lineage</span></div>${instances.length?instances.map((instance)=>`<article class="discovery-source ${instance.qualifies_review?"qualified":"supporting"}"><div><b>${escapeHTML(instance.source_kind.replaceAll("_"," "))}</b><span>${instance.qualifies_review?"user-backed":"support only"}</span></div><small>message ${escapeHTML(instance.source_turn_id||"unknown")} · branch ${escapeHTML(instance.branch_id||"main")}</small>${instance.span_text?`<blockquote>${escapeHTML(instance.span_text)}</blockquote>`:""}</article>`).join(""):`<div class="empty-note">No active source text is visible in this lineage. ${item.knowledge_state==="canon"?"User-authorized canon remains valid even when provenance is orphaned.":""}</div>`}${Number(item.inactive_support_count||0)?`<p class="discovery-muted">${Number(item.inactive_support_count)} source instance(s) were invalidated by deletion, revision, feedback, or lifecycle changes.</p>`:""}</section><section class="sheet-section"><div class="sheet-section-head"><h3>Authority boundary</h3></div><p><b>Detected</b> means Arline observed it. <b>Reviewed</b> means independent user-backed evidence reinforced it in this lineage. <b>Canon</b> exists only after your explicit decision.</p></section>`;
      const footer=byId("sheetFooter");
      footer.innerHTML=item.knowledge_state==="canon"?`<span class="protected-note">◆ User-authorized canon</span>`:item.knowledge_state==="dismissed"?`<button class="secondary-btn discovery-reset">Restore to detected</button>`:`<button class="danger-text-btn discovery-dismiss">Dismiss</button><button class="primary-btn discovery-canon">◆ Make Canon</button>`;
      footer.querySelector(".discovery-canon")?.addEventListener("click",()=>makeDiscoveryCanon(item));
      footer.querySelector(".discovery-dismiss")?.addEventListener("click",()=>dismissDiscovery(item));
      footer.querySelector(".discovery-reset")?.addEventListener("click",()=>resetDiscovery(item));
      window.openSheet?.();
    } catch(error){window.toast?.(error.message,6000);}
  }

  async function makeDiscoveryCanon(item) {
    if(!confirm(`Make “${item.subject_label} · ${item.predicate}” canon?\n\nThis is an explicit user authority decision. Source frequency alone never performs this action.`))return;
    try{await request(`/api/memory/discoveries/${encodeURIComponent(item.id)}/canon`,{method:"POST",body:JSON.stringify(discoveryDecisionPayload())});window.closeSheet?.();if(typeof window.loadProjectData==="function")await window.loadProjectData();await loadDiscoveries();window.toast?.("Discovery promoted to user-authorized canon");}catch(error){window.toast?.(error.message,6000);}
  }
  async function dismissDiscovery(item){if(!confirm("Dismiss this discovery? Arline keeps the decision so weak evidence does not keep resurfacing."))return;try{await request(`/api/memory/discoveries/${encodeURIComponent(item.id)}/dismiss`,{method:"POST",body:JSON.stringify(discoveryDecisionPayload())});window.closeSheet?.();await loadDiscoveries();}catch(error){window.toast?.(error.message,6000);}}
  async function resetDiscovery(item){try{await request(`/api/memory/discoveries/${encodeURIComponent(item.id)}/reset`,{method:"POST",body:JSON.stringify(discoveryDecisionPayload())});window.closeSheet?.();await loadDiscoveries();}catch(error){window.toast?.(error.message,6000);}}

  function injectDiscoveryStyles() {
    if(byId("discoveryStyles"))return;
    const style=document.createElement("style");style.id="discoveryStyles";style.textContent=`#discoveryTabCount{display:inline-flex;min-width:18px;height:18px;padding:0 5px;margin-left:5px;align-items:center;justify-content:center;border-radius:999px;background:color-mix(in srgb,var(--accent) 20%,transparent);font-size:10px}.discovery-sidebar-count{margin-left:auto}.discovery-turn-notice{width:min(760px,calc(100% - 24px));margin:0 auto 8px;padding:10px 14px;border:1px solid color-mix(in srgb,var(--accent) 34%,var(--line));border-radius:12px;background:color-mix(in srgb,var(--accent) 7%,var(--panel));text-align:left;cursor:pointer}.discovery-turn-notice b{display:block}.discovery-turn-notice small{display:block;margin-top:2px;opacity:.7}.discovery-grid{align-content:start}.discovery-card{cursor:pointer;min-height:188px}.discovery-card-head,.discovery-support,.discovery-source>div{display:flex;justify-content:space-between;gap:10px;align-items:center}.discovery-state{display:inline-flex;align-items:center;gap:5px;text-transform:capitalize;font-weight:700;font-size:11px}.discovery-state.detected{opacity:.72}.discovery-state.reviewed{color:var(--accent)}.discovery-state.canon{font-weight:800}.discovery-state.dismissed{opacity:.55}.discovery-path{display:block;margin:7px 0;font-size:11px;opacity:.72}.discovery-support{margin-top:auto;padding-top:10px;border-top:1px solid var(--line);font-size:11px;opacity:.7}.discovery-empty{grid-column:1/-1;display:flex;flex-direction:column;align-items:flex-start;gap:9px;padding:28px;border:1px dashed var(--line);border-radius:14px}.discovery-source{padding:12px 0;border-bottom:1px solid var(--line)}.discovery-source>div span{font-size:10px;opacity:.65}.discovery-source small{display:block;margin-top:4px;opacity:.65}.discovery-source blockquote{margin:8px 0 0;padding:8px 10px;border-left:2px solid var(--line);font-size:12px;white-space:pre-wrap}.discovery-source.qualified blockquote{border-left-color:var(--accent)}.discovery-muted{opacity:.6;font-size:12px}`;document.head.appendChild(style);
  }

  function openDiscoveryView(){const state=appState();state.activeWorldTab="discoveries";window.setView?.("world");const tabs=byId("worldTabs");tabs?.querySelectorAll("[data-world-tab]").forEach((tab)=>tab.classList.toggle("active",tab.dataset.worldTab==="discoveries"));loadDiscoveries();}

  function ensureDiscoveryNotice(){const dock=byId("composerDock");if(!dock||byId("discoveryTurnNotice"))return;const button=document.createElement("button");button.id="discoveryTurnNotice";button.className="discovery-turn-notice hidden";button.type="button";button.addEventListener("click",openDiscoveryView);dock.prepend(button);}

  function showDiscoveryNotice(report){ensureDiscoveryNotice();const node=byId("discoveryTurnNotice");if(!node)return;const count=Number(report?.propositions||0);if(!count){node.classList.add("hidden");return;}node.innerHTML=`<b>◇ ${count} narrative discover${count===1?"y":"ies"} from this turn</b><small>${Number(report.instances||0)} source-backed evidence instance${Number(report.instances||0)===1?"":"s"} · click to review in Library</small>`;node.classList.remove("hidden");}

  async function refreshAfterTurn(result){if(!result?.turn_id)return;let report=null;try{report=await request(`/api/memory/discoveries/capture-turn/${encodeURIComponent(result.turn_id)}`,{method:"POST"});}catch(error){console.warn("Narrative Discovery recapture failed",error);}await loadDiscoveries({render:appState().activeWorldTab==="discoveries"});if(report)showDiscoveryNotice(report);}

  function wrapGenerationFinalize(){const original=window.finalizeGenerationResult;if(typeof original!=="function"||original.__discoveryWrapped)return;const wrapped=async function(result,payload){const value=await original.apply(this,arguments);await refreshAfterTurn(result);return value;};wrapped.__discoveryWrapped=true;window.finalizeGenerationResult=wrapped;}

  function wrapProjectLoad(){const original=window.loadProjectData;if(typeof original!=="function"||original.__discoveryWrapped)return;const wrapped=async function(...args){const value=await original.apply(this,args);await loadDiscoveries({render:appState().activeWorldTab==="discoveries"});return value;};wrapped.__discoveryWrapped=true;window.loadProjectData=wrapped;}

  function installDiscoveryLibrary(){const tabs=byId("worldTabs");if(!tabs)return;if(!byId("discoveryWorldTab")){const button=document.createElement("button");button.id="discoveryWorldTab";button.dataset.worldTab="discoveries";button.innerHTML=`Discoveries <span id="discoveryTabCount" class="hidden"></span>`;const worlds=tabs.querySelector('[data-world-tab="worlds"]');tabs.insertBefore(button,worlds||null);button.addEventListener("click",openDiscoveryView);}
    const links=document.querySelector(".library-links");if(links&&!byId("discoverySidebarBtn")){const side=document.createElement("button");side.id="discoverySidebarBtn";side.type="button";side.innerHTML=`<span>◌</span><b>Discoveries</b><em id="discoverySidebarCount" class="discovery-sidebar-count">0</em>`;side.addEventListener("click",openDiscoveryView);links.appendChild(side);}
    const originalRender=window.renderWorldGrid;if(typeof originalRender==="function"&&!originalRender.__discoveryWrapped){const wrapped=function(...args){if(appState().activeWorldTab==="discoveries"){loadDiscoveries();return;}byId("worldGrid")?.classList.remove("discovery-grid");return originalRender.apply(this,args);};wrapped.__discoveryWrapped=true;window.renderWorldGrid=wrapped;}
    ensureDiscoveryNotice();setTimeout(()=>loadDiscoveries({render:false}),1200);
  }

  window.ArlineMemoryRuntime=Object.freeze({currentScope,activeScope,loadDiscoveries,scanExistingDiscoveries,openDiscoveryView,refreshAfterTurn});

  document.addEventListener("DOMContentLoaded",()=>{injectSettings();injectDiscoveryStyles();setTimeout(()=>{wrapPromptPayload();attachEntityMemoryTools();installDiscoveryLibrary();wrapGenerationFinalize();wrapProjectLoad();},0);});
})();
