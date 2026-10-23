from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import re
from threading import get_ident
from typing import Any


STORAGE_LAYER_VERSION = "0.1.0"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


try:  # Optional native extension built by crates/arline-native.
    import _arline_native as _native  # type: ignore
except Exception as exc:  # pragma: no cover - exact loader errors are platform specific.
    _native = None
    _NATIVE_IMPORT_ERROR: Exception | None = exc
else:
    _NATIVE_IMPORT_ERROR = None


@dataclass(frozen=True, slots=True)
class BlobRecord:
    digest: str
    path: Path
    size: int
    created: bool
    backend: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "digest": self.digest,
            "path": str(self.path),
            "size": self.size,
            "created": self.created,
            "backend": self.backend,
        }


def native_available() -> bool:
    return _native is not None


def native_import_error() -> str | None:
    return None if _NATIVE_IMPORT_ERROR is None else str(_NATIVE_IMPORT_ERROR)


class BlobStore:
    """Content-addressed blob store with an optional Rust hot path.

    `auto` prefers the `_arline_native` PyO3 extension and falls back to the
    byte-for-byte compatible Python implementation. `rust` is strict and
    raises when the extension is unavailable. `python` is useful for tests and
    for platforms where a native wheel has not been built yet.

    Storage semantics are intentionally independent from Canon semantics. This
    layer only owns opaque bytes, atomic placement, deduplication and lookup.
    """

    def __init__(self, root: Path | str, *, backend: str | None = None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        preference = str(backend or os.getenv("ARLINE_STORAGE_BACKEND", "auto")).strip().casefold()
        if preference not in {"auto", "rust", "python"}:
            raise ValueError("ARLINE_STORAGE_BACKEND must be auto, rust, or python")
        self._native_store = None
        if preference in {"auto", "rust"} and _native is not None:
            self._native_store = _native.BlobStore(str(self.root))
            self.backend_name = "rust"
        elif preference == "rust":
            detail = native_import_error() or "native extension is not installed"
            raise RuntimeError(f"Rust storage backend requested but unavailable: {detail}")
        else:
            self.backend_name = "python"

    @staticmethod
    def digest_bytes(data: bytes | bytearray | memoryview) -> str:
        payload = bytes(data)
        if _native is not None:
            try:
                return str(_native.sha256_hex(payload))
            except Exception:
                pass
        return sha256(payload).hexdigest()

    @staticmethod
    def _validate_digest(digest: str) -> str:
        value = str(digest or "").strip().casefold()
        if not _DIGEST.fullmatch(value):
            raise ValueError("Blob digest must be a 64-character lowercase SHA-256 hex string")
        return value

    def resolve(self, digest: str) -> Path:
        digest = self._validate_digest(digest)
        if self._native_store is not None:
            return Path(str(self._native_store.resolve(digest))).resolve()
        return (self.root / digest[:2] / digest[2:4] / digest).resolve()

    def exists(self, digest: str) -> bool:
        digest = self._validate_digest(digest)
        if self._native_store is not None:
            return bool(self._native_store.exists(digest))
        return self.resolve(digest).is_file()

    def put_bytes(self, data: bytes | bytearray | memoryview) -> BlobRecord:
        payload = bytes(data)
        if not payload:
            raise ValueError("Cannot store an empty blob")
        if self._native_store is not None:
            digest, path, created, size = self._native_store.put_bytes(payload)
            return BlobRecord(str(digest), Path(str(path)).resolve(), int(size), bool(created), "rust")

        digest = sha256(payload).hexdigest()
        target = self.resolve(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file():
            return BlobRecord(digest, target, len(payload), False, "python")

        temp = target.with_name(f".{digest}.{os.getpid()}.{get_ident()}.tmp")
        try:
            with temp.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            # The digest guarantees that a concurrent winner contains the same
            # bytes. os.replace is therefore safe even on a race.
            os.replace(temp, target)
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
        return BlobRecord(digest, target, len(payload), True, "python")

    def put_file(self, path: Path | str) -> BlobRecord:
        source = Path(path)
        if not source.is_file():
            raise FileNotFoundError(source)
        if self._native_store is not None:
            digest, stored_path, created, size = self._native_store.put_file(str(source))
            return BlobRecord(str(digest), Path(str(stored_path)).resolve(), int(size), bool(created), "rust")
        return self.put_bytes(source.read_bytes())

    def read_bytes(self, digest: str) -> bytes:
        path = self.resolve(digest)
        if not path.is_file():
            raise FileNotFoundError(path)
        return path.read_bytes()

    def remove(self, digest: str) -> bool:
        digest = self._validate_digest(digest)
        if self._native_store is not None:
            return bool(self._native_store.remove(digest))
        path = self.resolve(digest)
        try:
            path.unlink()
        except FileNotFoundError:
            return False
        for parent in (path.parent, path.parent.parent):
            try:
                parent.rmdir()
            except OSError:
                break
        return True

    def status(self) -> dict[str, Any]:
        return {
            "version": STORAGE_LAYER_VERSION,
            "backend": self.backend_name,
            "native_available": native_available(),
            "native_import_error": native_import_error(),
            "root": str(self.root),
            "content_addressed": True,
            "hash": "sha256",
            "atomic_writes": True,
        }
