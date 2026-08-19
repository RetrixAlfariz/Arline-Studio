"use strict";

(function () {
  function installBulkUndoBridge() {
    if (typeof globalThis.undoLastAction !== "function" || globalThis.undoLastAction.__arlineBulkWrapped) return;
    const originalUndo = globalThis.undoLastAction;
    const wrappedUndo = async function () {
      if (typeof lastUndo !== "undefined" && lastUndo?.type === "restore_bulk") {
        const action = lastUndo;
        lastUndo = null;
        const failed = [];
        for (const resource of action.resources || []) {
          try {
            await api("/api/lifecycle/restore", {
              method: "POST",
              body: { resource_type: resource.resourceType, resource_id: resource.resourceId },
            });
          } catch (error) {
            failed.push({ ...resource, error });
          }
        }
        await loadProjectData();
        if (failed.length) {
          toast(`Restored ${(action.resources || []).length - failed.length}/${(action.resources || []).length} sheets · ${failed.length} failed`, 6000);
        } else {
          toast(`Restored ${(action.resources || []).length} Library sheets`);
        }
        return;
      }
      return originalUndo();
    };
    wrappedUndo.__arlineBulkWrapped = true;
    globalThis.undoLastAction = wrappedUndo;
  }

  async function bulkTrashSelectedCompat() {
    installBulkUndoBridge();
    const ids = [...state.worldSelection];
    if (!ids.length) return;
    if (!confirm(`Move ${ids.length} selected Library sheets to Trash?\n\nThey remain recoverable from Activity Center, or immediately with Ctrl+Z.`)) return;

    const selectedIds = new Set(ids);
    const selectedVariantIds = new Set(
      (state.variants || []).filter((variant) => selectedIds.has(variant.family_id)).map((variant) => variant.id),
    );
    const resources = ids.map((id) => {
      const family = (state.families || []).find((item) => item.id === id);
      return { resourceType: "entity_family", resourceId: id, label: family?.name || id };
    });
    const moved = [];
    const failed = [];

    for (const resource of resources) {
      try {
        await api("/api/lifecycle/trash", {
          method: "POST",
          body: { resource_type: resource.resourceType, resource_id: resource.resourceId },
        });
        moved.push(resource);
      } catch (error) {
        failed.push({ ...resource, error });
      }
    }

    if (moved.length) {
      const movedIds = new Set(moved.map((item) => item.resourceId));
      lastUndo = { type:"restore_bulk", resources:moved };
      state.selectedReferences = (state.selectedReferences || []).filter((ref) => {
        if (ref.type === "entity_family" && movedIds.has(ref.id)) return false;
        if (ref.type === "entity_variant" && selectedVariantIds.has(ref.id)) return false;
        return true;
      });
      updateContextChipUI();
      scheduleContextStackSync();
    }

    state.worldSelection = new Set(failed.map((item) => item.resourceId));
    await loadProjectData();
    updateWorldBulkBar();

    if (failed.length) {
      toast(`Moved ${moved.length}/${resources.length} sheets to Trash · ${failed.length} failed`, 6000);
    } else {
      toast(`Moved ${moved.length} Library sheets to Trash · Ctrl+Z to undo`, 5000);
    }
  }

  function installBulkTrashCompatibility() {
    if (typeof document === "undefined") return;
    const bar = document.getElementById("worldBulkBar");
    if (!bar || document.getElementById("bulkTrashBtn")) return;
    const button = document.createElement("button");
    button.id = "bulkTrashBtn";
    button.type = "button";
    button.className = "tiny-danger-btn";
    button.textContent = "Trash";
    const clearButton = document.getElementById("bulkClearBtn");
    if (clearButton && typeof bar.insertBefore === "function") bar.insertBefore(button, clearButton);
    else bar.appendChild(button);
    button.addEventListener("click", bulkTrashSelectedCompat);
  }

  function installQuickCreateProjectScopeBridge() {
    if (typeof document === "undefined") return;
    const projectSelect = document.getElementById("quickCreateProject");
    const worldSelect = document.getElementById("quickCreateWorld");
    if (!projectSelect || !worldSelect || projectSelect.dataset.scopeBridge === "1") return;
    projectSelect.dataset.scopeBridge = "1";
    projectSelect.addEventListener("change", async (event) => {
      event.stopImmediatePropagation();
      const projectId = projectSelect.value;
      if (!projectId) return;
      try {
        const response = await window.fetch(`/api/projects/${encodeURIComponent(projectId)}`);
        if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
        const project = await response.json();
        const previousWorld = worldSelect.value;
        const worlds = project.worlds || [];
        worldSelect.innerHTML = "";
        for (const world of worlds) {
          const option = document.createElement("option");
          option.value = world.id;
          option.textContent = `${world.name}${world.canon_status ? ` · ${world.canon_status}` : ""}`;
          worldSelect.appendChild(option);
        }
        if ([...worldSelect.options].some((option) => option.value === previousWorld)) worldSelect.value = previousWorld;
        worldSelect.dispatchEvent(new Event("change", { bubbles: true }));
      } catch (error) {
        if (typeof globalThis.toast === "function") globalThis.toast(`Destination project failed: ${error.message}`, 5000);
      }
    }, true);
  }

  function loadQuickCreateEnhancements() {
    if (typeof document === "undefined" || typeof document.querySelector !== "function") return;
    if (document.querySelector('script[data-arline-quick-create="1"]')) return;
    const script = document.createElement("script");
    script.src = "/static/js/quick-create.js?v=1.1.4-qc";
    script.dataset.arlineQuickCreate = "1";
    if (typeof script.addEventListener === "function") {
      script.addEventListener("load", installQuickCreateProjectScopeBridge, { once: true });
    } else if (typeof setTimeout === "function") {
      setTimeout(installQuickCreateProjectScopeBridge, 0);
    }
    document.body.appendChild(script);
  }

  function loadProvisionalSheetEnhancements() {
    if (typeof document === "undefined" || typeof document.querySelector !== "function") return;
    if (document.querySelector('script[data-arline-provisional-sheets="1"]')) return;
    const script = document.createElement("script");
    script.src = "/static/js/discovery-sheets.js?v=1.2.1-physical-items";
    script.dataset.arlineProvisionalSheets = "1";
    document.body.appendChild(script);
  }

  function installRuntimeCompatibility() {
    if (typeof document !== "undefined") {
      installBulkTrashCompatibility();

      const loadEnhancements = () => {
        loadQuickCreateEnhancements();
        loadProvisionalSheetEnhancements();
      };
      if (document.readyState === "complete") loadEnhancements();
      else if (typeof document.addEventListener === "function") document.addEventListener("DOMContentLoaded", loadEnhancements, { once: true });
      else if (typeof setTimeout === "function") setTimeout(loadEnhancements, 0);
    }


    if (typeof setTimeout === "function") setTimeout(installBulkUndoBridge, 0);
  }

  installRuntimeCompatibility();

})();
