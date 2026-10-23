from __future__ import annotations

from collections import OrderedDict
from types import SimpleNamespace
import unittest

from src.discovery import performance
from src.discovery import physical_items


class V125DiscoveryCacheIsolationTests(unittest.TestCase):
    def test_physical_item_index_cache_is_owned_per_service(self):
        had_flag = hasattr(physical_items, "_PERFORMANCE_ITEM_INDEX_INSTALLED")
        old_flag = getattr(physical_items, "_PERFORMANCE_ITEM_INDEX_INSTALLED", None)
        old_existing = physical_items._existing_items
        try:
            if had_flag:
                delattr(physical_items, "_PERFORMANCE_ITEM_INDEX_INSTALLED")

            first = SimpleNamespace()
            second = SimpleNamespace()
            performance._install_physical_item_index(first, physical_items)
            performance._install_physical_item_index(second, physical_items)

            self.assertIsInstance(first._physical_item_scope_cache, OrderedDict)
            self.assertIsInstance(second._physical_item_scope_cache, OrderedDict)
            self.assertIsNot(first._physical_item_scope_cache, second._physical_item_scope_cache)

            first._physical_item_scope_cache[("fixture",)] = ["first"]
            self.assertEqual(second._physical_item_scope_cache, OrderedDict())
        finally:
            physical_items._existing_items = old_existing
            if had_flag:
                physical_items._PERFORMANCE_ITEM_INDEX_INSTALLED = old_flag
            elif hasattr(physical_items, "_PERFORMANCE_ITEM_INDEX_INSTALLED"):
                delattr(physical_items, "_PERFORMANCE_ITEM_INDEX_INSTALLED")


if __name__ == "__main__":
    unittest.main()
