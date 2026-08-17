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
      lastUndo = { type: "restore_bulk", resources: moved };
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

  function loadQuickCreateEnhancements() {
    if (typeof document === "undefined" || typeof document.querySelector !== "function") return;
    if (document.querySelector('script[data-arline-quick-create="1"]')) return;
    const script = document.createElement("script");
    script.src = "/static/js/quick-create.js?v=1.1.4-qc";
    script.dataset.arlineQuickCreate = "1";
    document.body.appendChild(script);
  }

  function installRuntimeCompatibility() {
    if (typeof document !== "undefined") {
      let host = document.getElementById("legacyScopeCompatibility");
      if (!host) {
        host = document.createElement("div");
        host.id = "legacyScopeCompatibility";
        host.hidden = true;
        host.setAttribute("aria-hidden", "true");
        document.body.appendChild(host);
      }

      for (const id of ["projectSelect", "worldSelect", "branchSelect"]) {
        if (document.getElementById(id)) continue;
        const select = document.createElement("select");
        select.id = id;
        select.hidden = true;
        select.tabIndex = -1;
        select.setAttribute("aria-hidden", "true");
        host.appendChild(select);
      }
      installBulkTrashCompatibility();

      // Load feature-level Quick Create enhancements only after every deferred
      // frontend script has executed, so its capture hooks augment the existing
      // v1.1 handlers instead of racing them during startup.
      if (document.readyState === "complete") loadQuickCreateEnhancements();
      else if (typeof document.addEventListener === "function") document.addEventListener("DOMContentLoaded", loadQuickCreateEnhancements, { once: true });
      else if (typeof setTimeout === "function") setTimeout(loadQuickCreateEnhancements, 0);
    }

    // v1.1's streaming generation path clears the sent Composer draft with an
    // unqualified `sentDraftKey` identifier, but the local binding was dropped
    // during the final UI refactor. Keep that identifier live until arline.js
    // owns the fix directly; the getter always resolves the current scope key.
    if (!Object.prototype.hasOwnProperty.call(globalThis, "sentDraftKey")) {
      Object.defineProperty(globalThis, "sentDraftKey", {
        configurable: true,
        get() {
          return typeof globalThis.composerDraftKey === "function"
            ? globalThis.composerDraftKey()
            : null;
        },
      });
    }

    // Deferred scripts execute in document order; a zero-delay task runs after
    // arline.js has installed the original undo function and its lexical state.
    if (typeof setTimeout === "function") setTimeout(installBulkUndoBridge, 0);
  }

  installRuntimeCompatibility();

  async function consume(response, onEvent) {
    if (!response.ok) {
      let message = `${response.status} ${response.statusText}`;
      try {
        const payload = await response.json();
        message = payload.detail || payload.message || message;
      } catch (_) {}
      throw new Error(message);
    }
    if (!response.body) throw new Error("Streaming response body is unavailable");

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    const dispatchFrame = async (frame) => {
      if (!frame.trim()) return;
      let eventName = "message";
      const dataLines = [];
      for (const rawLine of frame.split(/\r?\n/)) {
        if (rawLine.startsWith("event:")) eventName = rawLine.slice(6).trim() || "message";
        else if (rawLine.startsWith("data:")) dataLines.push(rawLine.slice(5).trimStart());
      }
      if (!dataLines.length) return;
      const raw = dataLines.join("\n");
      let data = raw;
      try { data = JSON.parse(raw); } catch (_) {}
      await onEvent({ type: eventName, data });
    };

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary;
      while ((boundary = buffer.search(/\r?\n\r?\n/)) >= 0) {
        const frame = buffer.slice(0, boundary);
        const match = buffer.slice(boundary).match(/^\r?\n\r?\n/);
        buffer = buffer.slice(boundary + (match ? match[0].length : 2));
        await dispatchFrame(frame);
      }
    }
    buffer += decoder.decode();
    if (buffer.trim()) await dispatchFrame(buffer);
  }

  window.ArlineStream = { consume };
})();
