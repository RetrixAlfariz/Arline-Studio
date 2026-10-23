from pathlib import Path
from tempfile import TemporaryDirectory
import re
import unittest

from fastapi.testclient import TestClient

from src.interface.web.app import create_app
from src.runtime_config import RuntimeConfig


ROOT = Path(__file__).resolve().parents[1]


class StorageResetTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = self.root / "data" / "studio.db"
        self.datasets = self.root / "data" / "datasets"
        self.output = self.root / "output"
        source = (ROOT / "config" / "arline.toml").read_text(encoding="utf-8")
        source = re.sub(r'(?m)^database_path\s*=.*$', f'database_path = "{self.db.as_posix()}"', source)
        source = re.sub(r'(?m)^dataset_root\s*=.*$', f'dataset_root = "{self.datasets.as_posix()}"', source)
        source = re.sub(r'(?m)^output_root\s*=.*$', f'output_root = "{self.output.as_posix()}"', source)
        source = re.sub(r'(?m)^saved_root\s*=.*$', f'saved_root = "{(self.output / "saved").as_posix()}"', source)
        self.config = self.root / "arline.toml"
        self.config.write_text(source, encoding="utf-8")
        parsed = RuntimeConfig.load(self.config)
        self.assertEqual(parsed.history.database_path.resolve(), self.db.resolve())
        self.assertEqual(parsed.workspace.database_path.resolve(), self.db.resolve())
        self.client = TestClient(create_app(self.config))

    def tearDown(self):
        self.temp.cleanup()

    def test_database_reset_requires_phrase_keeps_backup_and_reseeds(self):
        self.client.get("/api/workspace/bootstrap")
        created = self.client.post("/api/projects", json={"name": "Disposable"})
        self.assertEqual(created.status_code, 200, created.text)

        denied = self.client.post(
            "/api/storage/reset",
            json={"mode": "database", "confirmation": "reset"},
        )
        self.assertEqual(denied.status_code, 400)

        reset = self.client.post(
            "/api/storage/reset",
            json={"mode": "database", "confirmation": "RESET DATABASE"},
        )
        self.assertEqual(reset.status_code, 200, reset.text)
        payload = reset.json()
        self.assertEqual(payload["mode"], "database")
        self.assertEqual(len(payload["backups"]), 1)
        self.assertTrue(Path(payload["backups"][0]).is_file())

        empty = self.client.get("/api/workspace/bootstrap?create_default=false").json()
        self.assertEqual(empty["projects"], [])
        fresh = self.client.get("/api/workspace/bootstrap").json()
        self.assertEqual([item["name"] for item in fresh["projects"]], ["My Stories"])

    def test_complete_reset_removes_related_storage_but_preserves_config(self):
        self.client.get("/api/workspace/bootstrap")
        targets = [
            self.root / "data" / "media" / "image.bin",
            self.root / "data" / "backups" / "old.db",
            self.datasets / "export.jsonl",
            self.output / "saved" / "story.zip",
        ]
        for target in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"fixture")

        reset = self.client.post(
            "/api/storage/reset",
            json={"mode": "complete", "confirmation": "DELETE EVERYTHING"},
        )
        self.assertEqual(reset.status_code, 200, reset.text)
        payload = reset.json()
        self.assertEqual(payload["mode"], "complete")
        self.assertEqual(payload["backups"], [])
        self.assertTrue(self.db.is_file())
        self.assertTrue(self.config.is_file())
        for target in targets:
            self.assertFalse(target.exists(), target)


if __name__ == "__main__":
    unittest.main()
