"use strict";

(() => {
  const runtimeState = () => window.ArlineRuntime?.getState?.() || null;
  const viewport = () => window.ArlineChatViewport || null;
  const byId = (id) => document.getElementById(id);
  const qs = (selector, root = document) => root.querySelector(selector);
  const qsa = (selector, root = document) => [...root.querySelectorAll(selector)];
  const esc = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  const baseTurnHTML = window.turnHTML;
  const baseBindTurnActions = window.bindTurnActions;
  const baseSetGenerateRunning = window.setGenerateRunning;
  const baseOpenDocument = window.openDocument;
  const baseChooseCommand = window.chooseCommand;
  const baseSetView = window.setView;

  function stableTurnHTML(turn) {
    let html = typeof baseTurnHTML === "function" ? baseTurnHTML(turn) : "";
    const open = `<article class="turn" data-turn-id="${turn.id}">`;
    const stable = `<article class="turn" data-turn-id="${turn.id}" data-message-id="${turn.id}" tabindex="-1">`;
    if (html.includes(open)) html = html.replace(open, stable);
    if (!html.includes("delete-turn")) {
      html = html.replace(
        '<button class="tiny-btn save-turn">Save run</button>',
        '<button class="tiny-btn save-turn">Save run</button><button class="tiny-danger-btn delete-turn" title="Delete this turn">Delete</button>',
      );
    }
    return html;
  }

  if (typeof baseTurnHTML === "function") window.turnHTML = stableTurnHTML;

  async function deleteTurnMessage(turnId) {
    const state = runtimeState();
    const node = document.querySelector(`.turn[data-turn-id="${CSS.escape(turnId)}"]`);
    if (!state?.activeSession || !node) return;
    if (!confirm("Delete this message pair from the chat? Memory and Discovery evidence derived from this turn will be invalidated.")) return;

    const controller = viewport();
    const perform = async () => {
      const response = await fetch(`/api/turns/${encodeURIComponent(turnId)}`, { method: "DELETE" });
      if (!response.ok) {
        let message = `${response.status} ${response.statusText}`;
        try {
          const data = await response.json();
          message = data.detail || data.message || message;
        } catch (_) {}
        throw new Error(message);
      }
      state.activeSession.turns = (state.activeSession.turns || []).filter((turn) => turn.id !== turnId);
      if (state.activeTurn?.id === turnId) state.activeTurn = null;
      node.remove();
      window.ArlineEvents?.emit("chat:turn-deleted", { turnId, sessionId: state.activeSession.id });
      controller?.renderRail();
      Promise.resolve(window.loadSessions?.()).catch(() => {});
      Promise.resolve(window.loadDatasetStats?.()).catch(() => {});
    };

    try {
      if (controller) await controller.withMutation(perform, { preferredAnchorId: turnId, reason: "delete-turn" });
      else await perform();
      window.toast?.("Message deleted; reading position preserved");
    } catch (error) {
      window.toast?.(`Delete failed: ${error.message}`, 6000);
    }
  }

  function bindDeleteActions() {
    qsa(".turn[data-turn-id]").forEach((node) => {
      const button = qs(".delete-turn", node);
      if (!button || button.dataset.boundDelete === "1") return;
      button.dataset.boundDelete = "1";
      button.addEventListener("click", () => deleteTurnMessage(node.dataset.turnId));
    });
  }

  if (typeof baseBindTurnActions === "function") {
    window.bindTurnActions = function bindTurnActionsWithStableMutations(...args) {
      const result = baseBindTurnActions.apply(this, args);
      bindDeleteActions();
      return result;
    };
  }

  window.renderConversation = function renderConversationAnchored(turns = []) {
    const state = runtimeState();
    const feed = byId("conversationFeed");
    if (!feed || !state) return;
    const controller = viewport();
    controller?.initialize();
    const sessionId = state.activeSession?.id || null;
    const token = controller?.beginSession(sessionId) || null;
    const total = turns.length;
    const limit = Math.max(20, Number(state.conversationRenderLimit || 80));
    const start = Math.max(0, total - limit);
    const visible = turns.slice(start);
    feed.innerHTML = `${start > 0 ? `<button class="load-earlier-turns" data-remaining="${start}">Load earlier messages · ${start} hidden</button>` : ""}${visible.map((turn) => window.turnHTML(turn)).join("")}`;
    feed.querySelector(".load-earlier-turns")?.addEventListener("click", () => {
      state.conversationRenderLimit += 80;
      window.renderConversation(turns);
    });
    window.bindTurnActions?.();
    bindDeleteActions();
    controller?.finishSessionRender(token, { defaultToBottom: true });
    window.ArlineEvents?.emit("chat:rendered", { sessionId, total, visible: visible.length });
  };

  window.createLiveTurn = function createLiveTurnAnchored(payload) {
    byId("chatLanding")?.classList.add("hidden");
    byId("conversationSection")?.classList.remove("hidden");
    window.updateComposerSessionMode?.(true);
    const feed = byId("conversationFeed");
    const node = document.createElement("article");
    const liveId = `live:${Date.now()}:${Math.random().toString(16).slice(2)}`;
    node.className = "turn live-turn";
    node.dataset.messageId = liveId;
    node.tabIndex = -1;
    node.innerHTML = `<div class="turn-user"><div class="user-bubble">${esc(payload.prompt)}</div></div><div class="turn-assistant live-run-shell"><div class="assistant-head"><div class="assistant-meta"><span class="run-chip live-run-id">RUN</span><span>${esc(payload.model || "model")}</span></div><div class="assistant-actions"><button class="tiny-btn live-copy">Copy partial</button></div></div><div class="live-stage-row"><span class="live-stage-dot"></span><b class="live-stage">Preparing context</b><span class="live-stage-progress"><i></i></span></div><details class="thinking-panel live-thinking hidden"><summary>Thinking</summary><pre></pre></details><div class="story-output live-output stream-caret"></div><div class="feedback-row live-recovery hidden"><button class="live-retry">↻ Retry</button><button class="live-copy-partial">Copy partial</button></div></div>`;
    feed?.appendChild(node);

    const live = { node, prompt: payload.prompt, answer: "", reasoning: "", quality: null, sessionId: null, runId: null };
    node.scrollIntoView = (options) => viewport()?.legacyScrollRequest(node, options || {});
    qs(".live-copy", node)?.addEventListener("click", () => navigator.clipboard.writeText(live.answer).then(() => window.toast?.("Partial response copied")));
    qs(".live-copy-partial", node)?.addEventListener("click", () => navigator.clipboard.writeText(live.answer).then(() => window.toast?.("Partial response copied")));
    qs(".live-retry", node)?.addEventListener("click", () => {
      const input = byId("promptInput");
      if (input) input.value = live.prompt;
      window.refreshPromptHighlight?.();
      window.generateStory?.();
    });
    viewport()?.contentChanged({ source: "live-start" });
    viewport()?.renderRail();
    return live;
  };

  if (typeof baseSetGenerateRunning === "function") {
    window.setGenerateRunning = function setGenerateRunningWithViewport(running, ...args) {
      const result = baseSetGenerateRunning.call(this, running, ...args);
      viewport()?.markGenerating(Boolean(running));
      return result;
    };
  }

  if (typeof baseSetView === "function") {
    window.setView = function setViewWithScrollMemory(view, ...args) {
      if (view !== "chat") viewport()?.saveSession();
      return baseSetView.call(this, view, ...args);
    };
  }

  function draftScrollKey(documentId) {
    return documentId ? `arline:manuscript-scroll:v1:${documentId}` : null;
  }

  function saveDraftScroll(documentId = runtimeState()?.activeDocument?.id || null) {
    const editor = byId("draftEditor");
    const key = draftScrollKey(documentId);
    if (!editor || !key) return;
    try {
      localStorage.setItem(key, JSON.stringify({
        scrollTop: editor.scrollTop,
        selectionStart: editor.selectionStart,
        selectionEnd: editor.selectionEnd,
        updatedAt: Date.now(),
      }));
    } catch (_) {}
  }

  function restoreDraftScroll(documentId) {
    const editor = byId("draftEditor");
    const key = draftScrollKey(documentId);
    if (!editor || !key) return;
    try {
      const saved = JSON.parse(localStorage.getItem(key) || "null");
      if (!saved) return;
      requestAnimationFrame(() => {
        editor.scrollTop = Number(saved.scrollTop || 0);
        if (Number.isInteger(saved.selectionStart) && Number.isInteger(saved.selectionEnd)) {
          editor.setSelectionRange(saved.selectionStart, saved.selectionEnd);
        }
      });
    } catch (_) {}
  }

  if (typeof baseOpenDocument === "function") {
    window.openDocument = async function openDocumentWithScrollRestore(id, ...args) {
      saveDraftScroll();
      const result = await baseOpenDocument.call(this, id, ...args);
      restoreDraftScroll(id);
      return result;
    };
  }

  byId("draftEditor")?.addEventListener("scroll", () => saveDraftScroll(), { passive: true });
  byId("draftEditor")?.addEventListener("select", () => saveDraftScroll(), { passive: true });

  if (typeof baseChooseCommand === "function") {
    window.chooseCommand = async function chooseCommandWithMessageReveal(index, ...args) {
      const state = runtimeState();
      const item = state?.commandResults?.[index];
      const result = await baseChooseCommand.call(this, index, ...args);
      const turnId = item?.turn_id || item?.source_turn_id || null;
      if (turnId) await viewport()?.revealMessage(turnId);
      return result;
    };
  }

  window.ArlineEvents?.on("chat:reveal-message", (event) => {
    if (event.detail?.messageId) viewport()?.revealMessage(event.detail.messageId, event.detail.options || {});
  });

  // Capture before the legacy New Chat click handler clears the feed.
  byId("newChatBtn")?.addEventListener("click", () => viewport()?.saveSession(), { capture: true });

  // A sidebar resize, inspector transition, font reflow, image load, or command
  // panel resize is handled by ResizeObserver in the viewport controller.
  const mutationObserver = new MutationObserver(() => {
    viewport()?.renderRail();
  });
  const feed = byId("conversationFeed");
  if (feed) mutationObserver.observe(feed, { childList: true, subtree: false });

  window.ArlineMessageRuntime = Object.freeze({
    deleteTurnMessage,
    bindDeleteActions,
    saveDraftScroll,
    restoreDraftScroll,
  });
})();
