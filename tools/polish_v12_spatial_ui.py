from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
js_path = ROOT / "src/interface/web/static/js/memory.js"
css_path = ROOT / "src/interface/web/static/arline.css"
js = js_path.read_text(encoding="utf-8")

js = js.replace(
    '<h3>Spatial neighborhood</h3><pre class="json-block">${escapeHTML(JSON.stringify(spatial, null, 2))}</pre>',
    '<div class="memory-section-head"><h3>Spatial neighborhood</h3><button id="memoryAddSpatialBtn" class="primary-btn">＋ Add linked space or item</button></div><pre class="json-block">${escapeHTML(JSON.stringify(spatial, null, 2))}</pre>',
)
js = js.replace(
    '      compare.showModal();\n    } catch (error) {',
    '      compare.showModal();\n      byId("memoryAddSpatialBtn")?.addEventListener("click", () => openSpatialLinkDialog(type, id, () => openResourceMemory(familyId, variantId)));\n    } catch (error) {',
    1,
)

anchor = '  document.addEventListener("DOMContentLoaded", () => {'
if "async function openSpatialLinkDialog" not in js:
    addition = r'''  async function openSpatialLinkDialog(sourceType, sourceId, onDone) {
    const existing = byId("memorySpatialLinkDialog");
    if (existing) existing.remove();
    const dialog = document.createElement("dialog");
    dialog.id = "memorySpatialLinkDialog";
    dialog.className = "form-dialog memory-spatial-dialog";
    dialog.innerHTML = `
      <form method="dialog" class="form-shell">
        <div class="form-head"><div><span class="eyebrow">Linked Library structure</span><h2>Add spatial link</h2><p>Folders organize your Library. These links describe how the fictional world is actually arranged.</p></div><button value="cancel" class="icon-btn">×</button></div>
        <div class="form-grid">
          <label>Relation<select id="memorySpatialRelation">
            <option value="contains">contains</option>
            <option value="part_of">part of</option>
            <option value="stored_in">stored in</option>
            <option value="inside">inside</option>
            <option value="on">on</option>
            <option value="under">under</option>
            <option value="mounted_on">mounted on</option>
            <option value="adjacent_to">adjacent to</option>
            <option value="connected_to">connected to</option>
            <option value="opens_into">opens into</option>
          </select></label>
          <label class="full">Find target<input id="memorySpatialSearch" autocomplete="off" placeholder="Bedroom, Wardrobe, Black Dress…" /></label>
          <div id="memorySpatialResults" class="memory-spatial-results full"><div class="empty-note">Search an existing Library object. Quick Create can create it first when it does not exist.</div></div>
          <label class="settings-toggle-row full"><span><b>Structural link</b><small>Use for rooms, containers, building structure, and persistent connections. Turn off for a temporary placement.</small></span><input id="memorySpatialStructural" type="checkbox" checked /></label>
        </div>
        <div class="dialog-actions"><button value="cancel" class="secondary-btn">Cancel</button><button id="memorySpatialCreateBtn" type="button" class="primary-btn" disabled>Create link</button></div>
      </form>`;
    document.body.appendChild(dialog);
    let selected = null;
    let timer = null;
    const input = byId("memorySpatialSearch");
    const results = byId("memorySpatialResults");
    const create = byId("memorySpatialCreateBtn");
    input.addEventListener("input", () => {
      clearTimeout(timer);
      selected = null; create.disabled = true;
      const query = input.value.trim();
      if (!query) return;
      timer = setTimeout(async () => {
        try {
          const params = new URLSearchParams({q: query});
          if (window.state?.activeProject?.id) params.set("project_id", window.state.activeProject.id);
          const payload = await request(`/api/search?${params}`);
          const items = (payload.results || []).filter((item) => ["entity_family", "entity_variant"].includes(item.type)).slice(0, 12);
          results.innerHTML = items.length ? items.map((item, index) => `<button type="button" class="memory-spatial-result" data-index="${index}"><b>${escapeHTML(item.label || item.name || item.id)}</b><small>${escapeHTML(item.type)} · ${escapeHTML(item.description || item.summary || "Library object")}</small></button>`).join("") : `<div class="empty-note">No matching Library object. Create it with Quick Create, then search again.</div>`;
          results.querySelectorAll("button").forEach((button) => button.addEventListener("click", () => {
            results.querySelectorAll("button").forEach((item) => item.classList.remove("active"));
            button.classList.add("active"); selected = items[Number(button.dataset.index)]; create.disabled = false;
          }));
        } catch (error) {
          results.innerHTML = `<div class="empty-note">${escapeHTML(error.message)}</div>`;
        }
      }, 180);
    });
    create.addEventListener("click", async () => {
      if (!selected || !window.state?.activeWorld?.id) return;
      create.disabled = true; create.textContent = "Linking…";
      try {
        await request("/api/memory/spatial", {method:"POST", body:JSON.stringify({
          world_id: window.state.activeWorld.id,
          branch_id: window.state.activeBranch?.kind === "main" ? null : window.state.activeBranch?.id || null,
          subject_type: sourceType, subject_id: sourceId,
          relation: byId("memorySpatialRelation").value,
          object_type: selected.type, object_id: selected.id,
          structural: byId("memorySpatialStructural").checked,
        })});
        dialog.close(); dialog.remove(); window.toast?.("Spatial link created"); onDone?.();
      } catch (error) {
        create.disabled = false; create.textContent = "Create link"; window.toast?.(error.message, 6000);
      }
    });
    dialog.addEventListener("close", () => dialog.remove(), {once:true});
    dialog.showModal(); setTimeout(() => input.focus(), 0);
  }

'''
    if anchor not in js:
        raise RuntimeError("Memory UI bootstrap anchor missing")
    js = js.replace(anchor, addition + anchor, 1)
js_path.write_text(js, encoding="utf-8")

css = css_path.read_text(encoding="utf-8")
if ".memory-spatial-results" not in css:
    css += r'''

.memory-section-head{display:flex;align-items:center;justify-content:space-between;gap:12px}.memory-section-head h3{margin:0}
.memory-spatial-dialog{width:min(680px,calc(100vw - 32px))}.memory-spatial-results{display:grid;gap:6px;max-height:280px;overflow:auto;padding:4px;border:1px solid var(--line);border-radius:12px}
.memory-spatial-result{display:grid;gap:3px;text-align:left;padding:10px 12px;border:1px solid transparent;border-radius:10px;background:transparent;color:inherit}
.memory-spatial-result:hover,.memory-spatial-result.active{background:var(--soft);border-color:var(--line-strong)}.memory-spatial-result small{color:var(--muted)}
'''
css_path.write_text(css, encoding="utf-8")
print("Polished v1.2 linked spatial Library workflow")
