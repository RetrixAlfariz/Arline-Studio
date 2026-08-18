from .store import DISCOVERY_SCHEMA_VERSION, DiscoveryStore
from .service import CaptureReport, DiscoveryService
from .memory import install_discovery_memory_bridge
# Import side effect: wraps provisional installation with scoped spatial/branch repair.
from . import provisional_autopatch as _provisional_autopatch  # noqa: F401

__all__ = [
    "CaptureReport",
    "DISCOVERY_SCHEMA_VERSION",
    "DiscoveryService",
    "DiscoveryStore",
    "install_discovery_memory_bridge",
]
