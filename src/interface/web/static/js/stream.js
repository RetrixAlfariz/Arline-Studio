"use strict";

(function () {
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
