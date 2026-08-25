from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src/discovery/performance.py"

old = '''def _install_physical_item_index(service, physical_items_module) -> None:\n    if getattr(physical_items_module, "_PERFORMANCE_ITEM_INDEX_INSTALLED", False):\n        return\n    scope_cache: OrderedDict[tuple[Any, ...], list[Any]] = OrderedDict()\n    service._physical_item_scope_cache = scope_cache\n\n    def clone(item):\n'''
new = '''def _install_physical_item_index(service, physical_items_module) -> None:\n    # The wrapper is module-global, but cache ownership is service-local. A\n    # captured cache from the first DiscoveryService leaked entries and, more\n    # importantly, could not be invalidated by later services. Python/runtime\n    # timing then made physical-item resolution nondeterministic across fixtures.\n    if not hasattr(service, "_physical_item_scope_cache"):\n        service._physical_item_scope_cache = OrderedDict()\n    if getattr(physical_items_module, "_PERFORMANCE_ITEM_INDEX_INSTALLED", False):\n        return\n\n    def clone(item):\n'''

old_existing = '''    def existing_items(service_obj, context: MemoryQueryContext):\n        revision = _scope_revision(service_obj, context)\n        key = (*_context_key(context), revision)\n        cached = scope_cache.get(key)\n'''
new_existing = '''    def existing_items(service_obj, context: MemoryQueryContext):\n        scope_cache = getattr(service_obj, "_physical_item_scope_cache", None)\n        if scope_cache is None:\n            scope_cache = OrderedDict()\n            service_obj._physical_item_scope_cache = scope_cache\n        revision = _scope_revision(service_obj, context)\n        key = (*_context_key(context), revision)\n        cached = scope_cache.get(key)\n'''

text = PATH.read_text(encoding="utf-8")
if new not in text:
    if old not in text:
        raise SystemExit("physical-item cache installer anchor missing")
    text = text.replace(old, new, 1)
if new_existing not in text:
    if old_existing not in text:
        raise SystemExit("physical-item cache lookup anchor missing")
    text = text.replace(old_existing, new_existing, 1)
PATH.write_text(text, encoding="utf-8")
