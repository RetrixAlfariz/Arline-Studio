from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from src.history.store import HistoryStore


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/interface/web/static"


class V125ScrollRuntimeTests(unittest.TestCase):
    def test_chat_scroll_runtime_is_explicitly_loaded(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertIn("/static/chat-runtime-v125.css?v=1.2.5-scroll", html)
        self.assertIn("/static/js/core/events.js?v=1.2.5-scroll", html)
        self.assertIn("/static/js/chat/scroll-controller.js?v=1.2.5-scroll", html)
        self.assertIn("/static/js/chat/message-runtime.js?v=1.2.5-scroll", html)
        self.assertLess(html.index("scroll-controller.js"), html.index("/static/arline.js"))
        self.assertGreater(html.index("message-runtime.js"), html.index("/static/arline.js"))

    def test_scroll_controller_owns_policy_and_anchor_state(self):
        source = (STATIC / "js/chat/scroll-controller.js").read_text(encoding="utf-8")
        for token in (
            'FOLLOWING: "following"',
            'READING: "reading"',
            'ANCHORED: "anchored"',
            'RESTORING: "restoring"',
            "IntersectionObserver",
            "ResizeObserver",
            "captureAnchor",
            "restoreAnchor",
            "withMutation",
            "preserveLayoutChange",
            "beginSession",
            "finishSessionRender",
            "revealMessage",
            "renderRail",
            "arline:chat-scroll:v1",
        ):
            self.assertIn(token, source)

    def test_message_runtime_removes_renderer_scroll_authority(self):
        source = (STATIC / "js/chat/message-runtime.js").read_text(encoding="utf-8")
        self.assertIn("window.renderConversation = function renderConversationAnchored", source)
        self.assertIn("window.createLiveTurn = function createLiveTurnAnchored", source)
        self.assertIn("node.scrollIntoView =", source)
        self.assertIn("legacyScrollRequest", source)
        self.assertIn("deleteTurnMessage", source)
        self.assertIn("data-message-id", source)
        self.assertIn("arline:manuscript-scroll:v1", source)
        self.assertIn("chat:reveal-message", source)
        self.assertIn("window.setGenerateRunning =", source)

    def test_native_scrollbar_remains_visible_and_styled(self):
        css = (STATIC / "chat-runtime-v125.css").read_text(encoding="utf-8")
        self.assertIn("scrollbar-gutter:stable", css)
        self.assertIn("scrollbar-width:thin", css)
        self.assertIn("::-webkit-scrollbar-thumb", css)
        self.assertNotIn("scrollbar-width:none", css.replace(" ", ""))
        self.assertIn("jump-to-latest", css)
        self.assertIn("chat-scroll-rail", css)
        self.assertIn("grid-template-rows:minmax(0,1fr) auto", css)

    def test_turn_delete_preserves_fork_anchor_integrity(self):
        with tempfile.TemporaryDirectory() as td:
            history = HistoryStore(Path(td) / "history.db", backup_before_migration=False)
            session = history.create_session(prompt="start")
            first = history.add_turn(
                session["id"], run_id="RUN-1", user_prompt="one", story="first",
                model="fixture", mode="smart_hybrid", reasoning="off", projection_mode="off",
            )
            second = history.add_turn(
                session["id"], run_id="RUN-2", user_prompt="two", story="second",
                model="fixture", mode="smart_hybrid", reasoning="off", projection_mode="off",
            )

            removed = history.delete_turn(second["id"])
            self.assertEqual(removed["id"], second["id"])
            self.assertEqual([turn["id"] for turn in history.get_session(session["id"])["turns"]], [first["id"]])

            fork = history.fork_session(session["id"], through_turn_id=first["id"])
            self.assertEqual(fork["forked_from_turn_id"], first["id"])
            with self.assertRaises(ValueError):
                history.delete_turn(first["id"])

    def test_backend_turn_delete_invalidates_derived_layers(self):
        app = (ROOT / "src/interface/web/app.py").read_text(encoding="utf-8")
        memory = (ROOT / "src/memory/service.py").read_text(encoding="utf-8")
        discovery = (ROOT / "src/discovery/web.py").read_text(encoding="utf-8")
        self.assertIn('@app.delete("/api/turns/{turn_id}")', app)
        self.assertIn("history.delete_turn(turn_id)", app)
        self.assertIn("memory_service.forget_turn(turn_id)", app)
        self.assertIn("def forget_turn", memory)
        self.assertIn('mark_source_status("chat_window", turn_id, "deleted")', memory)
        self.assertIn('"history.turn_deleted"', discovery)
        self.assertIn("source_turn_id=?", discovery)


if __name__ == "__main__":
    unittest.main()
