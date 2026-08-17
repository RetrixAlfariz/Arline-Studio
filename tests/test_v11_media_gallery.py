from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from src.inference.lmstudio import LMStudioClient
from src.workspace.foundation import FoundationStore
from src.workspace.store import WORKSPACE_SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[1]


class V11MediaGalleryTests(unittest.TestCase):
    def test_schema_and_media_cover_lifecycle(self):
        self.assertEqual(WORKSPACE_SCHEMA_VERSION, 7)
        self.assertEqual(FoundationStore.SCHEMA_VERSION, 7)
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = FoundationStore(root / "workspace.db")
            first_file = root / "first.png"; first_file.write_bytes(b"first")
            second_file = root / "second.png"; second_file.write_bytes(b"second")
            first = store.create_media("entity_family", "FAM-A", storage_path=str(first_file), mime_type="image/png", is_cover=True)
            second = store.create_media("entity_family", "FAM-A", storage_path=str(second_file), mime_type="image/png", is_cover=True)
            items = store.list_media(resource_type="entity_family", resource_id="FAM-A")
            covers = [item for item in items if item["is_cover"]]
            self.assertEqual([item["id"] for item in covers], [second["id"]])
            self.assertFalse(store.get_media(first["id"])["is_cover"])
            store.merge_resource_refs("entity_family", "FAM-A", "FAM-B")
            moved = store.list_media(resource_type="entity_family", resource_id="FAM-B")
            self.assertEqual(len(moved), 2)
            store.delete_media(first["id"])
            self.assertFalse(first_file.exists())

    def test_lmstudio_native_chat_accepts_image_data_urls(self):
        client = LMStudioClient(base_url="http://127.0.0.1:1234")
        fake = {"output": [{"type": "message", "content": "A black dress."}], "stats": {}}
        with patch.object(client, "_request", return_value=fake) as request:
            result = client.chat(
                model="vision-model", input_text="Describe this", system_prompt="visual",
                images=["data:image/png;base64,AA=="], reasoning=None, max_tokens=64,
            )
        payload = request.call_args.kwargs["payload"]
        self.assertEqual(payload["input"][0]["type"], "message")
        self.assertEqual(payload["input"][1]["type"], "image")
        self.assertEqual(payload["input"][1]["data_url"], "data:image/png;base64,AA==")
        self.assertEqual(result.text, "A black dress.")

    def test_ui_and_api_expose_gallery_and_reviewable_vision(self):
        html = (ROOT / "src/interface/web/static/index.html").read_text(encoding="utf-8")
        css = (ROOT / "src/interface/web/static/arline.css").read_text(encoding="utf-8")
        js = (ROOT / "src/interface/web/static/arline.js").read_text(encoding="utf-8")
        app = (ROOT / "src/interface/web/app.py").read_text(encoding="utf-8")
        provider = (ROOT / "src/inference/provider.py").read_text(encoding="utf-8")
        self.assertIn('data-library-view="gallery"', html)
        self.assertRegex(html, r'arline\.css\?v=[^"\s]+')
        self.assertIn('.world-grid.view-gallery', css)
        self.assertIn('renderEntityMediaSheet', js)
        self.assertIn('reviewVisionDescription', js)
        self.assertIn('description_source: `vision:${result.model}`', js)
        self.assertIn('@app.post("/api/media/{media_id}/describe")', app)
        self.assertIn('"canon_changed": False', app)
        self.assertIn('"vision": bool((item.get("capabilities") or {}).get("vision"))', app)
        self.assertIn('vision: bool = False', provider)

    def test_home_review_handler_is_not_double_bound(self):
        js = (ROOT / "src/interface/web/static/arline.js").read_text(encoding="utf-8")
        binding = '$$(\'[data-home-review]\',byId("homeView")).forEach'
        self.assertEqual(js.count(binding), 1)


if __name__ == "__main__":
    unittest.main()
