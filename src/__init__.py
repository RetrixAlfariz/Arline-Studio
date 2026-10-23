"""Public Arline package surface.

The top-level package intentionally stays lightweight.  v1.2.5 introduced a
native deterministic storage layer that must be importable without waking the
AI/runtime stack (LM Studio, HTTP clients, planner, writer, and web concerns).

PEP 562 lazy attribute loading preserves the historical ``from src import X``
API while allowing focused modules such as ``src.storage.backend`` to remain
isolated and usable in minimal/native environments.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any


_EXPORTS: dict[str, tuple[str, str]] = {
    "ArlineAnalyticalPipeline": (".pipeline", "ArlineAnalyticalPipeline"),
    "PipelineResult": (".pipeline", "PipelineResult"),
    "AIFCompiler": (".context_compiler", "AIFCompiler"),
    "CompiledContext": (".context_compiler", "CompiledContext"),
    "RuntimeConfig": (".runtime_config", "RuntimeConfig"),
    "ArlineService": (".service", "ArlineService"),
    "AnalysisBundle": (".service", "AnalysisBundle"),
    "GenerationBundle": (".service", "GenerationBundle"),
    "WriterContextBuilder": (".context", "WriterContextBuilder"),
    "WCFRenderer": (".context", "WCFRenderer"),
    "WCFValidator": (".context", "WCFValidator"),
    "SemanticCoreBuilder": (".core", "SemanticCoreBuilder"),
    "WorldRuntimeBuilder": (".core", "WorldRuntimeBuilder"),
    "NarrativeRuntimeBuilder": (".narrative", "NarrativeRuntimeBuilder"),
    "ProjectionEngine": (".analytical_system", "ProjectionEngine"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    value = getattr(import_module(module_name, __name__), attribute)
    # Cache the resolved public symbol so repeated access has no import lookup
    # overhead and behaves like the old eager module attribute.
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
