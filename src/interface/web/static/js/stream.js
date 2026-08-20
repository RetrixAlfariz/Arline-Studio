"use strict";

(function () {
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

// Browser-only progressive feature loader. The guard deliberately keeps this
// module executable in the standalone Node transport smoke used by CI.
if (typeof document !== "undefined" && typeof window.addEventListener === "function") {
  window.addEventListener("load", () => {
    if (document.querySelector('script[data-arline-command-center]')) return;
    const script = document.createElement("script");
    script.src = "/static/js/command-center.js?v=1.2.5-command-center";
    script.async = false;
    script.dataset.arlineCommandCenter = "1";
    document.head.appendChild(script);
  }, { once: true });
}
