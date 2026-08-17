
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from src.interface.web.app import create_app


class V120MemoryFoundationTests(unittest.TestCase):
    def _app(self, root: Path) -> TestClient:
        db = root / "arline.db"
        cfg = root / "arline.toml"
        (root / "writer_system.txt").write_text("Write the requested fiction.", encoding="utf-8")
        (root / "reasoning_guard.txt").write_text("Keep reasoning bounded.", encoding="utf-8")
        config_text = f"""[lmstudio]
base_url = "http://127.0.0.1:1"
model = ""
api_key = ""
timeout_seconds = 0.2
auto_load = false

[history]
database_path = "{db.as_posix()}"
dataset_root = "{(root / 'datasets').as_posix()}"
recent_limit = 100
continuity_turns = 2
continuity_chars = 12000
smart_hybrid_continuity = true

[workspace]
database_path = "{db.as_posix()}"
default_project_id = ""
context_enabled = true
mention_limit = 20
pinned_context_limit = 24
autosave_drafts = true
language_mode = "follow_prompt"

[writer]
input_mode = "smart_hybrid"
system_prompt_file = "writer_system.txt"
story_filename = "story.txt"
save_request_packet = false
post_validate = false

[reasoning_runtime]
enforce_model_capabilities = false
guard_prompt_file = "reasoning_guard.txt"

[memory]
enabled = true
fts_enabled = true
dense_enabled = false
automatic_context = true
default_lens = "scene"
chunk_chars = 700
chunk_overlap_chars = 40
max_candidates = 40
final_k = 8
max_per_source = 3
rrf_k = 60
trace_enabled = true

[memory.embedding]
enabled = false
provider = "lmstudio"
model = "intfloat/multilingual-e5-base"
dimension = 768
query_prefix = "query: "
passage_prefix = "passage: "
"""
        cfg.write_text(config_text, encoding="utf-8")
        return TestClient(create_app(cfg))

    def test_memory_vertical_slice_and_scope_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            client = self._app(Path(td))
            bootstrap = client.get("/api/workspace/bootstrap").json()
            project = bootstrap["active"]["project"]
            world = bootstrap["active"]["world"]
            branch = bootstrap["active"]["branch"]

            phrase = "obsidian-lantern-seven"
            body = (f"Vian keeps the {phrase} on the bedroom desk. " * 90).strip()
            created = client.post("/api/documents", json={
                "project_id": project["id"], "world_id": world["id"],
                "branch_id": branch["id"], "title": "Memory fixture",
                "document_type": "scene", "content": body,
            })
            self.assertEqual(created.status_code, 200, created.text)
            document_id = created.json()["id"]

            refreshed = client.post("/api/memory/refresh", json={"document_id": document_id})
            self.assertEqual(refreshed.status_code, 200, refreshed.text)
            chunks = client.get(f"/api/memory/chunks?source_type=document&source_id={document_id}").json()["items"]
            self.assertGreater(len(chunks), 1, "multi-chunk documents must keep every current chunk active")

            # Re-indexing an unchanged revision must be idempotent.
            again = client.post("/api/memory/refresh", json={"document_id": document_id})
            self.assertEqual(again.status_code, 200, again.text)
            chunks_again = client.get(f"/api/memory/chunks?source_type=document&source_id={document_id}").json()["items"]
            self.assertEqual(len(chunks_again), len(chunks))

            second_project = client.post("/api/projects", json={"name": "Other Story"}).json()
            second_world = client.get(f"/api/projects/{second_project['id']}").json()["worlds"][0]
            hidden_doc = client.post("/api/documents", json={
                "project_id": second_project["id"], "world_id": second_world["id"],
                "title": "Wrong project", "document_type": "scene",
                "content": f"The {phrase} is secretly on Mars.",
            }).json()
            client.post("/api/memory/refresh", json={"document_id": hidden_doc["id"]})

            result = client.post("/api/memory/query", json={
                "query": phrase,
                "project_id": project["id"], "world_id": world["id"],
                "branch_id": branch["id"], "context_lens": "scene",
            })
            self.assertEqual(result.status_code, 200, result.text)
            payload = result.json()
            self.assertTrue(payload["selected"], payload)
            self.assertTrue(all(item.get("project_id") in {None, project["id"]} for item in payload["selected"]))
            self.assertTrue(any(item["decision"]["rule"] == "project" for item in payload["excluded"]), payload["excluded"])

            trace = client.get(f"/api/memory/retrieval/{payload['run_id']}")
            self.assertEqual(trace.status_code, 200, trace.text)

            status = client.get("/api/memory/status")
            self.assertEqual(status.status_code, 200, status.text)
            self.assertTrue(status.json()["fts_available"])

    def test_deleted_document_leaves_no_active_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            client = self._app(Path(td))
            bootstrap = client.get("/api/workspace/bootstrap").json()
            project = bootstrap["active"]["project"]
            world = bootstrap["active"]["world"]
            doc = client.post("/api/documents", json={
                "project_id": project["id"], "world_id": world["id"],
                "title": "Disposable", "content": "rare-delete-fixture", "document_type": "scene",
            }).json()
            client.post("/api/memory/refresh", json={"document_id": doc["id"]})
            self.assertTrue(client.get(f"/api/memory/chunks?source_type=document&source_id={doc['id']}").json()["items"])
            self.assertEqual(client.delete(f"/api/documents/{doc['id']}").status_code, 200)
            self.assertFalse(client.get(f"/api/memory/chunks?source_type=document&source_id={doc['id']}").json()["items"])


if __name__ == "__main__":
    unittest.main()
