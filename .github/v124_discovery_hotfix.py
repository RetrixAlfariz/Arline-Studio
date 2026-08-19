from pathlib import Path

# Discovery's class-level capture adapters historically trusted module-global
# _INSTALLED booleans. In long test/application processes the actual class method
# can be recomposed while those booleans stay True, silently dropping spatial
# extraction. Make installation idempotent against the current method chain.

path = Path('src/discovery/general.py')
text = path.read_text(encoding='utf-8')
old = '''def install_general_discovery() -> None:\n    global _INSTALLED\n    if _INSTALLED:\n        return\n    DiscoveryService.capture_text = _capture_text_general\n    _INSTALLED = True\n'''
new = '''def install_general_discovery() -> None:\n    global _INSTALLED\n    current = DiscoveryService.capture_text\n    # A spatial wrapper is built on top of the general adapter, so seeing its\n    # marker means the complete chain is already present. The old boolean alone\n    # is insufficient because another test/runtime adapter may have replaced the\n    # class method after initial installation.\n    if current is _capture_text_general or getattr(current, "_arline_spatial_discovery", False):\n        _INSTALLED = True\n        return\n    DiscoveryService.capture_text = _capture_text_general\n    _capture_text_general._arline_general_discovery = True\n    _INSTALLED = True\n'''
if old not in text:
    raise SystemExit('general discovery installer anchor missing')
path.write_text(text.replace(old, new, 1), encoding='utf-8')

path = Path('src/discovery/spatial.py')
text = path.read_text(encoding='utf-8')
old = '''def install_spatial_discovery() -> None:\n    global _INSTALLED\n    if _INSTALLED:\n        return\n    original_capture_text = DiscoveryService.capture_text\n\n    def capture_text_with_spatial(\n'''
new = '''def install_spatial_discovery() -> None:\n    global _INSTALLED\n    current = DiscoveryService.capture_text\n    if getattr(current, "_arline_spatial_discovery", False):\n        _INSTALLED = True\n        return\n    original_capture_text = current\n\n    def capture_text_with_spatial(\n'''
if old not in text:
    raise SystemExit('spatial discovery installer opening anchor missing')
text = text.replace(old, new, 1)
old = '''    DiscoveryService.capture_text = capture_text_with_spatial\n    _INSTALLED = True\n'''
new = '''    capture_text_with_spatial._arline_spatial_discovery = True\n    capture_text_with_spatial._arline_capture_base = original_capture_text\n    DiscoveryService.capture_text = capture_text_with_spatial\n    _INSTALLED = True\n'''
if old not in text:
    raise SystemExit('spatial discovery installer closing anchor missing')
text = text.replace(old, new, 1)
path.write_text(text, encoding='utf-8')

# Add a direct regression proving a stale module boolean cannot suppress
# re-installation after the class-level method has been reset/recomposed.
path = Path('tests/test_v124_directives_deliberation.py')
text = path.read_text(encoding='utf-8')
anchor = '''    def test_source_integration_contracts(self):\n'''
test = '''    def test_discovery_spatial_installer_repairs_stale_class_composition(self):\n        from src.discovery.service import DiscoveryService\n        from src.discovery.general import _capture_text_general, install_general_discovery\n        from src.discovery.spatial import install_spatial_discovery\n\n        original = DiscoveryService.capture_text\n        try:\n            # Simulate a later adapter/test resetting the class capture method\n            # while spatial._INSTALLED remains True from an earlier attach.\n            DiscoveryService.capture_text = _capture_text_general\n            install_general_discovery()\n            install_spatial_discovery()\n            repaired = DiscoveryService.capture_text\n            self.assertTrue(getattr(repaired, "_arline_spatial_discovery", False))\n            self.assertIs(getattr(repaired, "_arline_capture_base", None), _capture_text_general)\n        finally:\n            DiscoveryService.capture_text = original\n\n'''
if test not in text:
    if anchor not in text:
        raise SystemExit('v1.2.4 discovery regression test anchor missing')
    text = text.replace(anchor, test + anchor, 1)
path.write_text(text, encoding='utf-8')
print('v1.2.4 Discovery capture composition hardening applied')
