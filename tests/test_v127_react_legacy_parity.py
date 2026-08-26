from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "src"


class ReactLegacyParityTests(unittest.TestCase):
    def test_react_api_exposes_legacy_workflow_families(self):
        api = (FRONTEND / "api.ts").read_text(encoding="utf-8")
        required = (
            "/api/activity", "/api/issues", "/api/context-stack", "/api/favorites",
            "/api/import/manuscript/preview", "/api/export/project/", "/api/feedback/queue",
            "/api/dataset/stats", "/api/contract", "/api/ablation", "/api/memory/status",
            "/api/projects/${encodeURIComponent(projectId)}/active-scene", "/api/scenes/",
            "/api/revisions/", "/api/facts", "/api/retcon/preview", "/api/timeline/state",
            "/api/worlds/compare/", "/api/branches/compare/", "/api/library/entity-merge",
            "/api/collections", "/api/saved-views", "/api/media/",
        )
        for endpoint in required:
            self.assertIn(endpoint, api)

    def test_partial_library_integrations_are_repaired(self):
        library = (FRONTEND / "views" / "LibraryView.tsx").read_text(encoding="utf-8")
        api = (FRONTEND / "api.ts").read_text(encoding="utf-8")
        self.assertIn("timelineResult.events", library)
        self.assertNotIn("timelineResult.items", library)
        self.assertIn("studioApi.continuity(projectId", library)
        self.assertIn("/continuity${qs", api)
        for label in ("Move", "Collection", "Merge", "Archive", "Trash"):
            self.assertIn(f">{label}<", library)

    def test_parity_surfaces_are_first_class_react_components(self):
        app = (FRONTEND / "App.tsx").read_text(encoding="utf-8")
        chat = (FRONTEND / "views" / "ChatView.tsx").read_text(encoding="utf-8")
        manuscript = (FRONTEND / "views" / "ManuscriptView.tsx").read_text(encoding="utf-8")
        commands = (FRONTEND / "views" / "CommandCenterView.tsx").read_text(encoding="utf-8")
        tools = (FRONTEND / "components" / "StudioToolsDrawer.tsx").read_text(encoding="utf-8")
        self.assertIn("StudioToolsDrawer", app)
        for token in ("scratch_mode", "Stage canon", "Save current run profile", "Context recipe"):
            self.assertIn(token, chat)
        for token in ("restoreRevision", "sceneDependencies", "setActiveScene", "focus-mode"):
            self.assertIn(token, manuscript)
        for token in ("custom", "profiles", "references", "history", "Recursive custom command"):
            self.assertIn(token, commands)
        for token in ("selectedCommandId", "Why use this?", "Syntax", "Arguments", "Options", "What Arline does", "Authority", "Examples", "Use command"):
            self.assertIn(token, commands)
        for token in ("Feedback Lab", "Import & export", "Contract & diagnostics", "Memory & discovery"):
            self.assertIn(token, tools)

    def test_reference_guide_interactions_are_integrated(self):
        app = (FRONTEND / "App.tsx").read_text(encoding="utf-8")
        shell = (FRONTEND / "components" / "Shell.tsx").read_text(encoding="utf-8")
        palette = (FRONTEND / "components" / "GlobalPalette.tsx").read_text(encoding="utf-8")
        manuscript = (FRONTEND / "views" / "ManuscriptView.tsx").read_text(encoding="utf-8")
        api = (FRONTEND / "api.ts").read_text(encoding="utf-8")
        self.assertIn("GlobalPalette", app)
        self.assertIn("onPalette", shell)
        for token in ("Search Arline", "Ctrl Enter", "Add to Chat", "Inspect", "palette-preview"):
            self.assertIn(token, palette)
        for token in ("corkboard", "outliner", "reorderScene", "saveSceneCard", "scene-outliner"):
            self.assertIn(token, manuscript)
        self.assertIn("scene_cards", api)


if __name__ == "__main__":
    unittest.main()
