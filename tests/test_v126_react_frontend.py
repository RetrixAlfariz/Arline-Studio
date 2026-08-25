from pathlib import Path
import json
import re
import unittest

from fastapi.testclient import TestClient
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.interface.react_app import _register_frontend_mime_types


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


class V126ReactFrontendTests(unittest.TestCase):
    def test_react_vite_frontend_is_first_class_source(self):
        required = [
            FRONTEND / "package.json",
            FRONTEND / "vite.config.ts",
            FRONTEND / "index.html",
            FRONTEND / "src" / "main.tsx",
            FRONTEND / "src" / "App.tsx",
            FRONTEND / "src" / "api.ts",
            FRONTEND / "src" / "types.ts",
            FRONTEND / "src" / "styles.css",
        ]
        for path in required:
            self.assertTrue(path.is_file(), path)

        package = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
        self.assertIn("react", package["dependencies"])
        self.assertIn("react-dom", package["dependencies"])
        self.assertIn("vite", package["devDependencies"])
        self.assertIn("typescript", package["devDependencies"])
        self.assertEqual(package["scripts"]["build"], "tsc -b && vite build")

    def test_node_and_generated_frontend_outputs_are_ignored(self):
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for token in (
            "node_modules/",
            "frontend/node_modules/",
            "frontend/dist/",
            "frontend/.vite/",
            "*.tsbuildinfo",
            "npm-debug.log*",
        ):
            self.assertIn(token, ignored)

    def test_python_wrapper_prefers_built_react_and_keeps_legacy_fallback(self):
        wrapper = (ROOT / "src/interface/react_app.py").read_text(encoding="utf-8")
        launcher = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('FRONTEND_DIST = FRONTEND_ROOT / "dist"', wrapper)
        self.assertIn('"mode": "react" if react_ready else "legacy-fallback"', wrapper)
        self.assertIn('app.mount(', wrapper)
        self.assertIn('"/assets"', wrapper)
        self.assertIn("create_backend_app", wrapper)
        self.assertIn("from src.interface.react_app import launch_ui", launcher)
        self.assertTrue((ROOT / "src/interface/web/static/index.html").is_file())

    def test_typescript_uses_backend_contracts_instead_of_mock_state(self):
        api = (FRONTEND / "src/api.ts").read_text(encoding="utf-8")
        app = (FRONTEND / "src/App.tsx").read_text(encoding="utf-8")
        chat = (FRONTEND / "src/views/ChatView.tsx").read_text(encoding="utf-8")
        for endpoint in (
            "/api/workspace/bootstrap",
            "/api/projects",
            "/api/world-bible",
            "/api/sessions",
            "/api/documents",
            "/api/quick-create",
            "/api/generate/stream",
        ):
            self.assertIn(endpoint, api)
        self.assertIn("studioApi.bootstrap", app)
        self.assertIn("streamGeneration", chat)
        self.assertNotIn("const mock", app.lower())

    def test_storage_reset_is_guarded_in_the_react_settings_ui(self):
        settings = (FRONTEND / "src" / "components" / "SettingsDrawer.tsx").read_text(encoding="utf-8")
        api = (FRONTEND / "src" / "api.ts").read_text(encoding="utf-8")
        self.assertIn('resetStorage: (mode: "database" | "complete"', api)
        self.assertIn("/api/storage/reset", api)
        self.assertIn("RESET DATABASE", settings)
        self.assertIn("DELETE EVERYTHING", settings)
        self.assertIn("Complete reset", settings)

    def test_integrated_build_serves_es_modules_with_javascript_mime(self):
        index = FRONTEND / "dist" / "index.html"
        if not index.is_file():
            self.skipTest("frontend production build is not present")
        match = re.search(r'src="(/assets/[^"]+\.js)"', index.read_text(encoding="utf-8"))
        self.assertIsNotNone(match)
        _register_frontend_mime_types()
        app = FastAPI()
        app.mount("/assets", StaticFiles(directory=FRONTEND / "dist" / "assets"))
        response = TestClient(app).get(match.group(1))
        self.assertEqual(response.status_code, 200)
        self.assertIn("javascript", response.headers.get("content-type", ""))


if __name__ == "__main__":
    unittest.main()
