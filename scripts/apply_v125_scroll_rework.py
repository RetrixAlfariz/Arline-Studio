from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"Expected patch anchor missing in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def apply_index() -> None:
    replace_once(
        "src/interface/web/static/index.html",
        '  <link rel="stylesheet" href="/static/brand-v125.css?v=1.2.5-brand" />',
        '  <link rel="stylesheet" href="/static/brand-v125.css?v=1.2.5-brand" />\n'
        '  <link rel="stylesheet" href="/static/chat-runtime-v125.css?v=1.2.5-scroll" />',
    )
    replace_once(
        "src/interface/web/static/index.html",
        '  <script src="/static/js/commands.js?v=1.2.5-brand" defer></script>\n'
        '  <script src="/static/arline.js?v=1.2.5-brand" defer></script>',
        '  <script src="/static/js/commands.js?v=1.2.5-brand" defer></script>\n'
        '  <script src="/static/js/core/events.js?v=1.2.5-scroll" defer></script>\n'
        '  <script src="/static/js/chat/scroll-controller.js?v=1.2.5-scroll" defer></script>\n'
        '  <script src="/static/arline.js?v=1.2.5-brand" defer></script>\n'
        '  <script src="/static/js/chat/message-runtime.js?v=1.2.5-scroll" defer></script>',
    )


def apply_history() -> None:
    anchor = '''    def delete_session(self, session_id: str) -> None:\n        with self._lock, self._connection() as con:\n'''
    replacement = '''    def delete_turn(self, turn_id: str) -> dict[str, Any]:\n        """Delete one conversation turn without damaging fork provenance.\n\n        Forks copy their historical turns, but the parent source turn remains the\n        lineage anchor used to explain where the fork came from. Deleting such an\n        anchor is therefore rejected instead of silently producing dangling\n        provenance. Derived Memory/Discovery cleanup is handled by subscribers to\n        ``history.turn_deleted``.\n        """\n        with self._lock, self._connection() as con:\n            row = con.execute("SELECT * FROM turns WHERE id=?", (turn_id,)).fetchone()\n            if row is None:\n                raise KeyError(turn_id)\n            fork_rows = con.execute(\n                "SELECT id,title FROM sessions WHERE forked_from_turn_id=? ORDER BY created_at",\n                (turn_id,),\n            ).fetchall()\n            if fork_rows:\n                labels = ", ".join(str(item["title"] or item["id"]) for item in fork_rows[:3])\n                extra = "" if len(fork_rows) <= 3 else f" (+{len(fork_rows) - 3} more)"\n                raise ValueError(\n                    f"Turn is a fork lineage anchor for {labels}{extra}; delete or rebase those forks first"\n                )\n            deleted = self._turn_row(row, include_context=True)\n            session_id = str(row["session_id"])\n            con.execute("DELETE FROM turns WHERE id=?", (turn_id,))\n            con.execute("UPDATE sessions SET updated_at=? WHERE id=?", (utc_now(), session_id))\n        emit_domain_event(\n            self.path,\n            "history.turn_deleted",\n            {"turn_id": turn_id, "session_id": deleted["session_id"]},\n        )\n        return deleted\n\n    def delete_session(self, session_id: str) -> None:\n        with self._lock, self._connection() as con:\n'''
    replace_once("src/history/store.py", anchor, replacement)


def apply_memory() -> None:
    anchor = '''    def forget_session(self, session_id: str) -> int:\n        self.cancel_session_refreshes(session_id)\n        return self.store.mark_session_status(session_id, "deleted")\n\n    def _enrich_context(self, context: MemoryQueryContext) -> MemoryQueryContext:\n'''
    replacement = '''    def forget_session(self, session_id: str) -> int:\n        self.cancel_session_refreshes(session_id)\n        return self.store.mark_session_status(session_id, "deleted")\n\n    def forget_turn(self, turn_id: str) -> int:\n        self._cancel(f"turn:{turn_id}")\n        return self.store.mark_source_status("chat_window", turn_id, "deleted")\n\n    def _enrich_context(self, context: MemoryQueryContext) -> MemoryQueryContext:\n'''
    replace_once("src/memory/service.py", anchor, replacement)


def apply_discovery() -> None:
    anchor = '''    def session_deleted(event):\n        session_id = event.payload.get("session_id")\n        if not session_id:\n            return\n        try:\n            discovery.set_session_active(session_id, active=False, reason="source_deleted")\n        except Exception as exc:\n            report_failure(f"session:{session_id}", exc)\n\n    def scope_deleted(event):\n'''
    replacement = '''    def turn_deleted(event):\n        turn_id = event.payload.get("turn_id")\n        if not turn_id:\n            return\n        try:\n            with discovery.store._lock, discovery.store.connection() as con:\n                con.execute(\n                    "UPDATE discovery_instances SET active=0,invalidation_reason='source_deleted',updated_at=datetime('now') "\n                    "WHERE source_turn_id=? AND active=1",\n                    (turn_id,),\n                )\n        except Exception as exc:\n            report_failure(f"turn-delete:{turn_id}", exc)\n\n    def session_deleted(event):\n        session_id = event.payload.get("session_id")\n        if not session_id:\n            return\n        try:\n            discovery.set_session_active(session_id, active=False, reason="source_deleted")\n        except Exception as exc:\n            report_failure(f"session:{session_id}", exc)\n\n    def scope_deleted(event):\n'''
    replace_once("src/discovery/web.py", anchor, replacement)
    replace_once(
        "src/discovery/web.py",
        '''        ("history.feedback_changed", feedback_changed, "discovery.feedback"),\n        ("history.session_deleted", session_deleted, "discovery.delete"),\n''',
        '''        ("history.feedback_changed", feedback_changed, "discovery.feedback"),\n        ("history.turn_deleted", turn_deleted, "discovery.turn-delete"),\n        ("history.session_deleted", session_deleted, "discovery.delete"),\n''',
    )


def apply_api() -> None:
    anchor = '''    @app.get("/api/turns/{turn_id}")\n    def get_turn(turn_id: str):\n        try:\n            return history.get_turn(turn_id)\n        except KeyError as exc:\n            raise HTTPException(404, "Turn not found") from exc\n\n    @app.post("/api/turns/{turn_id}/feedback")\n'''
    replacement = '''    @app.get("/api/turns/{turn_id}")\n    def get_turn(turn_id: str):\n        try:\n            return history.get_turn(turn_id)\n        except KeyError as exc:\n            raise HTTPException(404, "Turn not found") from exc\n\n    @app.delete("/api/turns/{turn_id}")\n    def delete_turn(turn_id: str):\n        try:\n            deleted = history.delete_turn(turn_id)\n        except KeyError as exc:\n            raise HTTPException(404, "Turn not found") from exc\n        except ValueError as exc:\n            raise HTTPException(409, str(exc)) from exc\n        try:\n            memory_service.forget_turn(turn_id)\n        except Exception as exc:\n            memory_service._report_refresh_failure(f"turn-delete:{turn_id}", exc)\n        return {"ok": True, "turn_id": turn_id, "session_id": deleted.get("session_id")}\n\n    @app.post("/api/turns/{turn_id}/feedback")\n'''
    replace_once("src/interface/web/app.py", anchor, replacement)


def apply_ci() -> None:
    replace_once(
        ".github/workflows/ci.yml",
        '''          node --check src/interface/web/static/js/commands.js\n          node --check src/interface/web/static/js/command-center.js\n          node --check src/interface/web/static/js/stream.js\n''',
        '''          node --check src/interface/web/static/js/commands.js\n          node --check src/interface/web/static/js/command-center.js\n          node --check src/interface/web/static/js/core/events.js\n          node --check src/interface/web/static/js/chat/scroll-controller.js\n          node --check src/interface/web/static/js/chat/message-runtime.js\n          node --check src/interface/web/static/js/stream.js\n''',
    )


def apply_browser_smoke() -> None:
    anchor = '''  await page.waitForFunction(() => window.ArlineRuntime?.getState?.().commandRegistryVersion === "1.2.4a1");\n  if (!(await page.locator("#deliberationOutput").count())) throw new Error("Intuition inspector panel is missing");\n\n  await page.fill("#promptInput", "/intu");\n'''
    replacement = '''  await page.waitForFunction(() => window.ArlineRuntime?.getState?.().commandRegistryVersion === "1.2.4a1");\n  if (!(await page.locator("#deliberationOutput").count())) throw new Error("Intuition inspector panel is missing");\n  await page.waitForFunction(() => Boolean(window.ArlineChatViewport?.initialized && window.ArlineMessageRuntime));\n\n  const scrollContract = await page.evaluate(async () => {\n    const controller = window.ArlineChatViewport;\n    const feed = document.getElementById("conversationFeed");\n    const section = document.getElementById("conversationSection");\n    const landing = document.getElementById("chatLanding");\n    const wasLandingHidden = landing.classList.contains("hidden");\n    const wasSectionHidden = section.classList.contains("hidden");\n    landing.classList.add("hidden");\n    section.classList.remove("hidden");\n    const token = controller.beginSession("SCROLL-SMOKE");\n    feed.innerHTML = Array.from({ length: 24 }, (_, index) => (\n      `<article class="turn" data-turn-id="SMOKE-${index}" data-message-id="SMOKE-${index}" style="min-height:140px"><div class="turn-assistant">smoke ${index}</div></article>`\n    )).join("");\n    await controller.finishSessionRender(token, { defaultToBottom: true });\n    controller.renderRail();\n    await new Promise((resolve) => setTimeout(resolve, 40));\n    const viewport = document.getElementById("chatViewport");\n    viewport.dispatchEvent(new WheelEvent("wheel", { deltaY: -500, bubbles: true }));\n    viewport.scrollTop = Math.max(0, viewport.scrollHeight - viewport.clientHeight - 620);\n    viewport.dispatchEvent(new Event("scroll"));\n    await new Promise((resolve) => setTimeout(resolve, 40));\n    const before = controller.captureAnchor();\n    const readingMode = controller.debugState().mode;\n    const removal = feed.querySelector('[data-message-id="SMOKE-1"]');\n    await controller.withMutation(() => removal?.remove(), { reason: "browser-smoke-delete" });\n    const after = controller.captureAnchor(before?.anchorMessageId);\n    const drift = before && after ? Math.abs(Number(after.offset) - Number(before.offset)) : 999;\n    const railMarkers = document.querySelectorAll("#chatScrollRail .chat-scroll-marker").length;\n    const jumpVisible = !document.getElementById("jumpToLatestBtn").classList.contains("hidden");\n    feed.innerHTML = "";\n    if (!wasLandingHidden) landing.classList.remove("hidden");\n    if (wasSectionHidden) section.classList.add("hidden");\n    controller.beginSession(null);\n    return { readingMode, drift, railMarkers, jumpVisible, state: controller.debugState() };\n  });\n  if (scrollContract.readingMode !== "reading") throw new Error(`Scroll controller did not enter reading mode: ${JSON.stringify(scrollContract)}`);\n  if (scrollContract.drift > 2) throw new Error(`Anchor drifted during mutation: ${JSON.stringify(scrollContract)}`);\n  if (scrollContract.railMarkers < 20) throw new Error(`Scroll rail markers missing: ${JSON.stringify(scrollContract)}`);\n  if (!scrollContract.jumpVisible) throw new Error(`Jump-to-latest did not appear in reading mode: ${JSON.stringify(scrollContract)}`);\n\n  await page.fill("#promptInput", "/intu");\n'''
    replace_once("tests/frontend/browser_smoke.mjs", anchor, replacement)


def main() -> None:
    apply_index()
    apply_history()
    apply_memory()
    apply_discovery()
    apply_api()
    apply_ci()
    apply_browser_smoke()


if __name__ == "__main__":
    main()
