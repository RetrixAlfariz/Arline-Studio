from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.storage.backend import BlobStore, STORAGE_LAYER_VERSION
from src.workspace.native_foundation import NativeAwareFoundationStore
from src.workspace.foundation import FoundationStore as PythonFoundationStore
from src.workspace import FoundationStore as ApplicationFoundationStore


ROOT = Path(__file__).resolve().parents[1]


class V125NativeStorageTests(unittest.TestCase):
    def test_python_blob_store_is_content_addressed_and_deduplicates(self):
        with TemporaryDirectory() as td:
            store = BlobStore(Path(td) / "objects", backend="python")
            payload = b"arline-native-storage"
            first = store.put_bytes(payload)
            second = store.put_bytes(payload)
            expected = sha256(payload).hexdigest()

            self.assertEqual(first.digest, expected)
            self.assertEqual(second.digest, expected)
            self.assertEqual(first.path, second.path)
            self.assertTrue(first.created)
            self.assertFalse(second.created)
            self.assertEqual(store.read_bytes(expected), payload)
            self.assertEqual(first.path.name, expected)
            self.assertEqual(first.path.parent.name, expected[2:4])
            self.assertEqual(first.path.parent.parent.name, expected[:2])
            self.assertEqual(store.status()["hash"], "sha256")
            self.assertEqual(store.status()["version"], STORAGE_LAYER_VERSION)

    def test_digest_validation_blocks_path_traversal(self):
        with TemporaryDirectory() as td:
            store = BlobStore(Path(td) / "objects", backend="python")
            for bad in ("../secret", "a" * 63, "g" * 64, ""):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    store.resolve(bad)

    def test_native_aware_foundation_deduplicates_media_and_refcounts_blob(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            media = root / "media"
            media.mkdir()
            store = NativeAwareFoundationStore(root / "workspace.db", storage_backend="python")

            first_upload = media / "first.png"
            second_upload = media / "second.png"
            first_upload.write_bytes(b"same-image-bytes")
            second_upload.write_bytes(b"same-image-bytes")

            first = store.create_media(
                "entity_family", "FAM-A",
                storage_path=str(first_upload), mime_type="image/png",
            )
            second = store.create_media(
                "entity_family", "FAM-B",
                storage_path=str(second_upload), mime_type="image/png",
            )

            first_blob = Path(first["storage_path"])
            second_blob = Path(second["storage_path"])
            self.assertEqual(first_blob, second_blob)
            self.assertTrue(first_blob.is_file())
            self.assertFalse(first_upload.exists())
            self.assertFalse(second_upload.exists())

            store.delete_media(first["id"])
            self.assertTrue(first_blob.exists(), "shared blob must survive while another row references it")
            store.delete_media(second["id"])
            self.assertFalse(first_blob.exists(), "final reference deletion may remove the blob")

    def test_application_workspace_exports_native_aware_adapter(self):
        self.assertIs(ApplicationFoundationStore, NativeAwareFoundationStore)
        self.assertTrue(issubclass(ApplicationFoundationStore, PythonFoundationStore))

    def test_rust_crate_declares_pyo3_abi3_and_storage_contract(self):
        cargo = (ROOT / "crates/arline-native/Cargo.toml").read_text(encoding="utf-8")
        rust = (ROOT / "crates/arline-native/src/lib.rs").read_text(encoding="utf-8")
        self.assertIn('name = "_arline_native"', cargo)
        self.assertIn('abi3-py311', cargo)
        self.assertIn('pyo3', cargo)
        self.assertIn('sha2', cargo)
        self.assertIn('struct BlobStore', rust)
        self.assertIn('fn atomic_put', rust)
        self.assertIn('fn sha256_hex', rust)
        self.assertIn('#[pymodule]', rust)


if __name__ == "__main__":
    unittest.main()
