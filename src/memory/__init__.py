from .config import EmbeddingConfig, MemoryConfig, RerankerConfig
from .contracts import (
    EvidenceSpan,
    MemoryProposalsV1,
    MemorySummaryV1,
    SCHEMA_MODELS,
    schema_document,
    validate_structured_output,
)
from .embedding import (
    DisabledEmbeddingProvider,
    DisabledRerankerProvider,
    EmbeddingProvider,
    LMStudioEmbeddingProvider,
    RerankerProvider,
)
from .index import MemoryIndexer, StructuralChunker
from .models import (
    Authority,
    ContextLens,
    MemoryCandidate,
    MemoryQueryContext,
    QueryPlan,
    QueryRoute,
    RetrievalLane,
    RetrievalResult,
    SemanticClass,
    SemanticStatus,
    TrustLevel,
)
from .profiles import MemoryTaskProfile, TASK_PROFILES, get_task_profile
from .query import MemoryQueryEngine, QueryCompiler
from .scope import ScopeGate
from .security import HygieneReport, evidence_wrapper, inspect_retrieved_text
from .service import MemoryService
from .spatial import SpatialMemory
from .store import MEMORY_SCHEMA_VERSION, MemoryStore
from .temporal import TemporalMemory
from .v121 import (
    V121_EXTENSION_VERSION,
    compare_world_time,
    install_v121,
    normalize_world_time,
    world_time_in_interval,
)

# v1.2.x stays on one development line. Install the v1.2.1 behavior over the
# stable v1.2.0 foundation without changing the public Memory API.
install_v121()

__all__ = [
    "Authority", "ContextLens", "DisabledEmbeddingProvider",
    "DisabledRerankerProvider", "EmbeddingConfig", "EmbeddingProvider",
    "EvidenceSpan", "HygieneReport", "LMStudioEmbeddingProvider",
    "MEMORY_SCHEMA_VERSION", "MemoryCandidate", "MemoryConfig", "MemoryIndexer",
    "MemoryProposalsV1", "MemoryQueryContext", "MemoryQueryEngine",
    "MemoryService", "MemoryStore", "MemorySummaryV1", "MemoryTaskProfile",
    "QueryCompiler", "QueryPlan", "QueryRoute", "RerankerConfig",
    "RerankerProvider", "RetrievalLane", "RetrievalResult", "SCHEMA_MODELS",
    "ScopeGate", "SemanticClass", "SemanticStatus", "SpatialMemory",
    "StructuralChunker", "TASK_PROFILES", "TemporalMemory", "TrustLevel",
    "V121_EXTENSION_VERSION", "compare_world_time", "evidence_wrapper",
    "get_task_profile", "inspect_retrieved_text", "normalize_world_time",
    "schema_document", "validate_structured_output", "world_time_in_interval",
]
