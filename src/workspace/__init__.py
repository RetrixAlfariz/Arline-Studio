from .store import (
    BRANCH_KINDS,
    CANON_STATUSES,
    DOCUMENT_TYPES,
    ENTITY_TYPES,
    WORLD_BIBLE_PROJECT_ID,
    WORLD_BIBLE_WORLD_ID,
    WORLD_BIBLE_BRANCH_ID,
    SnapshotResult,
    WorkspaceStore,
)
from .quick_create import QuickCreatePreview, parse_quick_create
from .context import WorkspaceContext, WorkspaceContextResolver
from .foundation import FoundationStore as PythonFoundationStore
from .native_foundation import NativeAwareFoundationStore

# Keep the original implementation explicitly available for compatibility and
# parity tests, while routing normal application imports through the storage
# adapter. The adapter falls back to Python when `_arline_native` is absent.
FoundationStore = NativeAwareFoundationStore

__all__ = [
    "QuickCreatePreview",
    "parse_quick_create",
    "BRANCH_KINDS",
    "CANON_STATUSES",
    "DOCUMENT_TYPES",
    "ENTITY_TYPES",
    "WORLD_BIBLE_PROJECT_ID",
    "WORLD_BIBLE_WORLD_ID",
    "WORLD_BIBLE_BRANCH_ID",
    "SnapshotResult",
    "WorkspaceStore",
    "WorkspaceContext",
    "WorkspaceContextResolver",
    "PythonFoundationStore",
    "FoundationStore",
]
