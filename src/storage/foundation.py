from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from src.workspace.foundation import FoundationStore as PythonFoundationStore

from .backend import BlobStore


class NativeAwareFoundationStore(PythonFoundationStore):
    """FoundationStore adapter that moves opaque media bytes into BlobStore.

    The SQL schema remains the existing FoundationStore schema. Only the file
    hot path changes: incoming temporary media files are hashed, atomically
    placed into a content-addressed object tree, and deduplicated. Multiple SQL
    media rows may safely reference one blob; the blob is deleted only after
    the final reference disappears.

    This deliberately does *not* move Canon, continuity, or authority rules to
    Rust. Those semantics stay in their existing Python layers.
    """

    STORAGE_ADAPTER_VERSION = "0.1.0"

    def __init__(self, database_path: Path | str, *, storage_backend: str | None = None):
        super().__init__(database_path)
        self.storage_backend = str(
            storage_backend or os.getenv("ARLINE_STORAGE_BACKEND", "auto")
        ).strip().casefold()
        self._blob_stores: dict[Path, BlobStore] = {}

    def _blob_store_for(self, storage_path: Path | str) -> BlobStore:
        source = Path(storage_path).resolve()
        # App uploads arrive as temporary files in the media directory. Keep
        # the content-addressed tree next to them so existing backup/export
        # boundaries continue to capture the bytes.
        root = source.parent / "objects"
        store = self._blob_stores.get(root)
        if store is None:
            store = BlobStore(root, backend=self.storage_backend)
            self._blob_stores[root] = store
        return store

    def storage_status(self) -> dict[str, Any]:
        stores = [store.status() for store in self._blob_stores.values()]
        return {
            "adapter": self.STORAGE_ADAPTER_VERSION,
            "preference": self.storage_backend,
            "stores": stores,
            "active_backend": stores[0]["backend"] if stores else (
                "rust" if self.storage_backend == "rust" else "auto"
            ),
        }

    def create_media(
        self,
        resource_type: str,
        resource_id: str,
        *,
        storage_path: str,
        mime_type: str,
        original_name: str = "",
        media_type: str = "image",
        kind: str = "reference",
        caption: str = "",
        description: str = "",
        description_source: str = "manual",
        is_cover: bool = False,
        sort_order: int = 0,
    ) -> dict[str, Any]:
        source = Path(storage_path).resolve()
        final_path = source
        if source.is_file():
            store = self._blob_store_for(source)
            blob = store.put_file(source)
            final_path = blob.path
            if source != final_path:
                try:
                    source.unlink(missing_ok=True)
                except OSError:
                    # The canonical copy already exists. A failed cleanup is a
                    # harmless orphan temp file, not a reason to lose metadata.
                    pass

        return super().create_media(
            resource_type,
            resource_id,
            storage_path=str(final_path),
            mime_type=mime_type,
            original_name=original_name,
            media_type=media_type,
            kind=kind,
            caption=caption,
            description=description,
            description_source=description_source,
            is_cover=is_cover,
            sort_order=sort_order,
        )

    def delete_media(self, media_id: str) -> None:
        item = self.get_media(media_id)
        storage_path = str(item.get("storage_path") or "")
        with self._lock, self._connection() as con:
            con.execute("DELETE FROM resource_media WHERE id=?", (media_id,))
            remaining = con.execute(
                "SELECT COUNT(*) FROM resource_media WHERE storage_path=?",
                (storage_path,),
            ).fetchone()[0]
        if remaining:
            return
        try:
            Path(storage_path).unlink(missing_ok=True)
        except OSError:
            pass
