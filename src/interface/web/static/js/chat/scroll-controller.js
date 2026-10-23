"use strict";

(() => {
  const MODES = Object.freeze({
    FOLLOWING: "following",
    READING: "reading",
    ANCHORED: "anchored",
    RESTORING: "restoring",
  });

  const nextFrame = () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

  class AnchorViewportController {
    constructor({ viewId, feedId, storagePrefix = "arline:viewport:v1", threshold = 120 } = {}) {
      this.viewId = viewId;
      this.feedId = feedId;
      this.storagePrefix = storagePrefix;
      this.threshold = threshold;
      this.viewport = null;
      this.feed = null;
      this.sentinel = null;
      this.jumpButton = null;
      this.rail = null;
      this.sessionId = null;
      this.mode = MODES.FOLLOWING;
      this.atBottom = true;
      this.generating = false;
      this.programmaticDepth = 0;
      this.userIntentUntil = 0;
      this.lastAnchor = null;
      this.resizePending = false;
      this.saveTimer = null;
      this.bottomObserver = null;
      this.resizeObserver = null;
      this.viewportResizeObserver = null;
      this.initialized = false;
      this.mutationDepth = 0;
    }

    initialize() {
      if (this.initialized) return true;
      const view = document.getElementById(this.viewId);
      const feed = document.getElementById(this.feedId);
      if (!view || !feed) return false;
      this.feed = feed;
      this._ensureStructure(view);
      this._bindIntent();
      this._bindObservers();
      this.initialized = true;
      this._syncAnchor();
      this._updateUI();
      this.renderRail();
      window.ArlineEvents?.emit("chat:viewport-ready", { controller: this });
      return true;
    }

    _ensureStructure(view) {
      view.classList.add("chat-scroll-runtime-ready");
      let viewport = document.getElementById("chatViewport");
      if (!viewport) {
        viewport = document.createElement("div");
        viewport.id = "chatViewport";
        viewport.className = "chat-viewport";
        viewport.tabIndex = -1;
        const composer = document.getElementById("composerDock");
        const movable = ["chatLanding", "conversationSection", "analysisStrip"]
          .map((id) => document.getElementById(id))
          .filter(Boolean);
        if (movable.length) view.insertBefore(viewport, composer || null);
        for (const node of movable) viewport.appendChild(node);
      }
      this.viewport = viewport;

      let sentinel = document.getElementById("chatBottomSentinel");
      if (!sentinel) {
        sentinel = document.createElement("div");
        sentinel.id = "chatBottomSentinel";
        sentinel.className = "chat-bottom-sentinel";
        sentinel.setAttribute("aria-hidden", "true");
        viewport.appendChild(sentinel);
      }
      this.sentinel = sentinel;

      let jump = document.getElementById("jumpToLatestBtn");
      if (!jump) {
        jump = document.createElement("button");
        jump.id = "jumpToLatestBtn";
        jump.className = "jump-to-latest hidden";
        jump.type = "button";
        jump.innerHTML = '<span class="jump-arrow">↓</span><span class="jump-label">Latest</span><span class="jump-generation-dot" aria-hidden="true"></span>';
        jump.addEventListener("click", () => this.scrollToLatest({ behavior: "smooth", explicit: true }));
        view.appendChild(jump);
      }
      this.jumpButton = jump;

      let rail = document.getElementById("chatScrollRail");
      if (!rail) {
        rail = document.createElement("div");
        rail.id = "chatScrollRail";
        rail.className = "chat-scroll-rail";
        rail.setAttribute("aria-label", "Conversation position map");
        view.appendChild(rail);
      }
      this.rail = rail;
    }

    _bindIntent() {
      const markIntent = () => { this.userIntentUntil = performance.now() + 450; };
      this.viewport.addEventListener("wheel", markIntent, { passive: true });
      this.viewport.addEventListener("touchstart", markIntent, { passive: true });
      this.viewport.addEventListener("pointerdown", (event) => {
        if (event.pointerType !== "mouse" || event.button === 0) markIntent();
      }, { passive: true });
      this.viewport.addEventListener("keydown", (event) => {
        if (["ArrowUp", "PageUp", "Home", "ArrowDown", "PageDown", "End", " "].includes(event.key)) markIntent();
      });
      this.viewport.addEventListener("scroll", () => this._onScroll(), { passive: true });
      window.addEventListener("beforeunload", () => this.saveSession());
      document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "hidden") this.saveSession();
      });
    }

    _bindObservers() {
      if ("IntersectionObserver" in window) {
        this.bottomObserver = new IntersectionObserver((entries) => {
          const entry = entries[0];
          if (!entry) return;
          const visible = entry.isIntersecting && entry.intersectionRatio > 0;
          this.atBottom = visible || this.distanceFromBottom() <= this.threshold;
          if (this.atBottom && this.mode === MODES.READING && performance.now() <= this.userIntentUntil) {
            this.mode = MODES.FOLLOWING;
          }
          this._updateUI();
        }, { root: this.viewport, threshold: [0, 0.01, 1] });
        this.bottomObserver.observe(this.sentinel);
      }

      if ("ResizeObserver" in window) {
        this.resizeObserver = new ResizeObserver(() => this._onContentResize());
        this.resizeObserver.observe(this.feed);
        this.viewportResizeObserver = new ResizeObserver(() => this._onViewportResize());
        this.viewportResizeObserver.observe(this.viewport);
      }
    }

    _onScroll() {
      const bottom = this.distanceFromBottom();
      this.atBottom = bottom <= this.threshold;
      const userDriven = performance.now() <= this.userIntentUntil && this.programmaticDepth === 0;
      if (userDriven) {
        if (this.atBottom) this.mode = MODES.FOLLOWING;
        else this.mode = MODES.READING;
      }
      this._syncAnchor();
      this._scheduleSave();
      this._updateUI();
      this.renderRailViewport();
      window.ArlineEvents?.emit("chat:scroll", this.debugState());
    }

    _onContentResize() {
      if (!this.initialized || this.mutationDepth > 0 || this.resizePending) return;
      this.resizePending = true;
      requestAnimationFrame(async () => {
        try {
          if (this.mode === MODES.FOLLOWING) {
            this.scrollToLatest({ behavior: "auto" });
          } else if (this.mode === MODES.READING && this.lastAnchor) {
            await this.restoreAnchor(this.lastAnchor, { preserveMode: true });
          }
          this.renderRail();
        } finally {
          this.resizePending = false;
        }
      });
    }

    _onViewportResize() {
      if (!this.initialized || this.resizePending) return;
      const anchor = this.mode === MODES.READING ? (this.lastAnchor || this.captureAnchor()) : null;
      requestAnimationFrame(() => {
        if (anchor) this.restoreAnchor(anchor, { preserveMode: true });
        else if (this.mode === MODES.FOLLOWING) this.scrollToLatest({ behavior: "auto" });
      });
    }

    distanceFromBottom() {
      if (!this.viewport) return 0;
      return Math.max(0, this.viewport.scrollHeight - this.viewport.clientHeight - this.viewport.scrollTop);
    }

    _messageNodes() {
      if (!this.feed) return [];
      return [...this.feed.querySelectorAll(".turn[data-message-id], .turn[data-turn-id]")];
    }

    _messageId(node) {
      return node?.dataset?.messageId || node?.dataset?.turnId || null;
    }

    captureAnchor(preferredId = null) {
      if (!this.viewport || !this.feed) return null;
      const nodes = this._messageNodes();
      if (!nodes.length) {
        return {
          anchorMessageId: null,
          offset: 0,
          bottomDistance: this.distanceFromBottom(),
          wasFollowing: this.mode === MODES.FOLLOWING || this.atBottom,
          fallbackNextId: null,
          fallbackPrevId: null,
        };
      }
      const viewportRect = this.viewport.getBoundingClientRect();
      let index = -1;
      if (preferredId) index = nodes.findIndex((node) => this._messageId(node) === preferredId);
      if (index < 0) {
        index = nodes.findIndex((node) => {
          const rect = node.getBoundingClientRect();
          return rect.bottom > viewportRect.top + 8 && rect.top < viewportRect.bottom - 8;
        });
      }
      if (index < 0) index = this.atBottom ? nodes.length - 1 : 0;
      const node = nodes[index];
      const rect = node.getBoundingClientRect();
      return {
        anchorMessageId: this._messageId(node),
        offset: rect.top - viewportRect.top,
        bottomDistance: this.distanceFromBottom(),
        wasFollowing: this.mode === MODES.FOLLOWING || this.atBottom,
        fallbackNextId: this._messageId(nodes[index + 1]),
        fallbackPrevId: this._messageId(nodes[index - 1]),
      };
    }

    _findAnchorNode(snapshot) {
      if (!snapshot) return null;
      const ids = [snapshot.anchorMessageId, snapshot.fallbackNextId, snapshot.fallbackPrevId].filter(Boolean);
      const nodes = this._messageNodes();
      for (const id of ids) {
        const node = nodes.find((candidate) => this._messageId(candidate) === id);
        if (node) return node;
      }
      return null;
    }

    async restoreAnchor(snapshot, { preserveMode = false, defaultToBottom = false } = {}) {
      if (!this.viewport || !snapshot) return;
      const previousMode = this.mode;
      this.mode = MODES.RESTORING;
      await nextFrame();
      this.programmaticDepth += 1;
      try {
        if (snapshot.wasFollowing || defaultToBottom) {
          this.viewport.scrollTop = this.viewport.scrollHeight;
          this.atBottom = true;
          this.mode = MODES.FOLLOWING;
        } else {
          const node = this._findAnchorNode(snapshot);
          if (node) {
            const viewportRect = this.viewport.getBoundingClientRect();
            const currentOffset = node.getBoundingClientRect().top - viewportRect.top;
            this.viewport.scrollTop += currentOffset - Number(snapshot.offset || 0);
          } else {
            this.viewport.scrollTop = Math.max(0, this.viewport.scrollHeight - this.viewport.clientHeight - Number(snapshot.bottomDistance || 0));
          }
          this.atBottom = this.distanceFromBottom() <= this.threshold;
          this.mode = preserveMode && previousMode !== MODES.RESTORING ? previousMode : MODES.READING;
          if (this.atBottom) this.mode = MODES.FOLLOWING;
        }
      } finally {
        requestAnimationFrame(() => { this.programmaticDepth = Math.max(0, this.programmaticDepth - 1); });
      }
      this._syncAnchor();
      this._updateUI();
      this._scheduleSave();
    }

    async withMutation(callback, { preferredAnchorId = null, reason = "mutation" } = {}) {
      const snapshot = this.captureAnchor(preferredAnchorId);
      const previousMode = this.mode;
      this.mutationDepth += 1;
      this.mode = MODES.ANCHORED;
      try {
        const result = await callback(snapshot);
        await this.restoreAnchor(snapshot, { preserveMode: false });
        if (snapshot && !snapshot.wasFollowing && previousMode === MODES.READING && !this.atBottom) this.mode = MODES.READING;
        window.ArlineEvents?.emit("chat:mutation-complete", { reason, snapshot });
        return result;
      } finally {
        this.mutationDepth = Math.max(0, this.mutationDepth - 1);
        this._syncAnchor();
        this.renderRail();
        this._updateUI();
      }
    }

    async preserveLayoutChange(callback, reason = "layout") {
      const snapshot = this.captureAnchor();
      const result = callback?.();
      await nextFrame();
      if (snapshot) await this.restoreAnchor(snapshot, { preserveMode: true });
      window.ArlineEvents?.emit("chat:layout-preserved", { reason });
      return result;
    }

    scrollToLatest({ behavior = "auto", explicit = false } = {}) {
      if (!this.viewport) return;
      this.mode = MODES.FOLLOWING;
      this.programmaticDepth += 1;
      try {
        this.viewport.scrollTo({ top: this.viewport.scrollHeight, behavior });
      } catch (_) {
        this.viewport.scrollTop = this.viewport.scrollHeight;
      }
      requestAnimationFrame(() => {
        this.programmaticDepth = Math.max(0, this.programmaticDepth - 1);
        this.atBottom = true;
        this._syncAnchor();
        this._updateUI();
        this._scheduleSave();
      });
      if (explicit) window.ArlineEvents?.emit("chat:follow-latest", { sessionId: this.sessionId });
    }

    legacyScrollRequest(node, options = {}) {
      if (this.mode !== MODES.FOLLOWING) {
        this._updateUI();
        return;
      }
      this.scrollToLatest({ behavior: options?.behavior === "smooth" ? "smooth" : "auto" });
    }

    contentChanged({ source = "render" } = {}) {
      if (this.mode === MODES.FOLLOWING) this.scrollToLatest({ behavior: source === "stream" ? "auto" : "auto" });
      else this._updateUI();
      this.renderRail();
      window.ArlineEvents?.emit("chat:content-changed", { source, mode: this.mode });
    }

    markGenerating(generating) {
      this.generating = Boolean(generating);
      this._updateUI();
      this.renderRail();
    }

    _syncAnchor() {
      if (this.mode === MODES.READING || this.mode === MODES.ANCHORED || this.mode === MODES.RESTORING) {
        this.lastAnchor = this.captureAnchor();
      } else if (this.mode === MODES.FOLLOWING) {
        this.lastAnchor = this.captureAnchor();
      }
    }

    _storageKey(sessionId = this.sessionId) {
      return sessionId ? `${this.storagePrefix}:${sessionId}` : null;
    }

    _scheduleSave() {
      clearTimeout(this.saveTimer);
      this.saveTimer = setTimeout(() => this.saveSession(), 120);
    }

    saveSession() {
      const key = this._storageKey();
      if (!key || !this.viewport) return;
      const anchor = this.captureAnchor();
      try {
        localStorage.setItem(key, JSON.stringify({
          ...anchor,
          mode: this.mode,
          scrollTop: this.viewport.scrollTop,
          updatedAt: Date.now(),
        }));
      } catch (_) {}
    }

    loadSession(sessionId) {
      if (!sessionId) return null;
      try {
        const value = JSON.parse(localStorage.getItem(this._storageKey(sessionId)) || "null");
        return value && typeof value === "object" ? value : null;
      } catch (_) { return null; }
    }

    beginSession(sessionId) {
      if (this.sessionId === sessionId) return { switching: false, snapshot: this.captureAnchor() };
      this.saveSession();
      const previousSessionId = this.sessionId;
      this.sessionId = sessionId || null;
      this.mode = MODES.RESTORING;
      this.lastAnchor = null;
      return { switching: true, previousSessionId, saved: this.loadSession(sessionId) };
    }

    async finishSessionRender(token, { defaultToBottom = true } = {}) {
      if (!token?.switching) {
        if (token?.snapshot) await this.restoreAnchor(token.snapshot, { preserveMode: true });
        else this.contentChanged({ source: "render" });
        return;
      }
      const saved = token.saved;
      if (saved?.anchorMessageId || Number.isFinite(saved?.bottomDistance)) {
        this.mode = saved.mode === MODES.FOLLOWING ? MODES.FOLLOWING : MODES.READING;
        await this.restoreAnchor(saved, { preserveMode: false });
      } else if (defaultToBottom) {
        this.scrollToLatest({ behavior: "auto" });
      } else {
        this.mode = MODES.READING;
      }
      this.renderRail();
    }

    async revealMessage(messageId, { center = true, flash = true } = {}) {
      const node = this._messageNodes().find((candidate) => this._messageId(candidate) === messageId);
      if (!node || !this.viewport) return false;
      this.mode = MODES.ANCHORED;
      const viewportRect = this.viewport.getBoundingClientRect();
      const nodeRect = node.getBoundingClientRect();
      const targetOffset = center ? (viewportRect.height - nodeRect.height) / 2 : 24;
      const delta = nodeRect.top - viewportRect.top - targetOffset;
      this.programmaticDepth += 1;
      this.viewport.scrollTo({ top: this.viewport.scrollTop + delta, behavior: "smooth" });
      setTimeout(() => {
        this.programmaticDepth = Math.max(0, this.programmaticDepth - 1);
        this.mode = MODES.READING;
        this._syncAnchor();
        this._updateUI();
        this.saveSession();
      }, 360);
      if (flash) {
        node.classList.remove("scroll-target-flash");
        requestAnimationFrame(() => node.classList.add("scroll-target-flash"));
        setTimeout(() => node.classList.remove("scroll-target-flash"), 1400);
      }
      return true;
    }

    renderRail() {
      if (!this.rail || !this.viewport) return;
      const nodes = this._messageNodes();
      const total = Math.max(1, this.viewport.scrollHeight);
      this.rail.replaceChildren();
      nodes.forEach((node, index) => {
        const id = this._messageId(node);
        if (!id) return;
        const marker = document.createElement("button");
        marker.type = "button";
        marker.className = `chat-scroll-marker${node.classList.contains("live-turn") ? " live" : ""}`;
        marker.style.top = `${clamp((node.offsetTop / total) * 100, 1, 99)}%`;
        marker.title = node.classList.contains("live-turn") ? "Current generation" : `Turn ${index + 1}`;
        marker.dataset.messageId = id;
        marker.addEventListener("click", () => this.revealMessage(id));
        this.rail.appendChild(marker);
      });
      this.renderRailViewport();
    }

    renderRailViewport() {
      if (!this.rail || !this.viewport) return;
      let indicator = this.rail.querySelector(".chat-scroll-viewport-indicator");
      if (!indicator) {
        indicator = document.createElement("div");
        indicator.className = "chat-scroll-viewport-indicator";
        this.rail.appendChild(indicator);
      }
      const total = Math.max(1, this.viewport.scrollHeight);
      indicator.style.top = `${clamp((this.viewport.scrollTop / total) * 100, 0, 100)}%`;
      indicator.style.height = `${clamp((this.viewport.clientHeight / total) * 100, 3, 100)}%`;
    }

    _updateUI() {
      if (!this.jumpButton) return;
      const show = !this.atBottom || this.mode === MODES.READING;
      this.jumpButton.classList.toggle("hidden", !show);
      this.jumpButton.classList.toggle("generating", this.generating);
      const label = this.jumpButton.querySelector(".jump-label");
      if (label) label.textContent = this.generating ? "Latest · generating" : "Latest";
      this.viewport?.setAttribute("data-scroll-mode", this.mode);
    }

    debugState() {
      return {
        mode: this.mode,
        atBottom: this.atBottom,
        generating: this.generating,
        sessionId: this.sessionId,
        distanceFromBottom: Math.round(this.distanceFromBottom()),
        anchor: this.lastAnchor,
      };
    }
  }

  window.ArlineScroll = Object.freeze({ MODES, AnchorViewportController });
  const chat = new AnchorViewportController({ viewId: "chatView", feedId: "conversationFeed", storagePrefix: "arline:chat-scroll:v1" });
  window.ArlineChatViewport = chat;

  const boot = () => chat.initialize();
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot, { once: true });
  else boot();
})();
