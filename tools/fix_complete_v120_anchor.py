from pathlib import Path
import re


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Repair the one-shot completion patcher itself before it generates source.
# ---------------------------------------------------------------------------
path = Path("tools/complete_v120_foundation.py")
text = path.read_text(encoding="utf-8")
old = '''if normal_memory not in app:\n    app = replace_once(app, normal_session_anchor, normal_memory, label="normal generation memory")\n'''
new = '''if normal_memory not in app:\n    generate_marker = '    @app.post("/api/generate")\\n'\n    prefix, marker, generate_tail = app.partition(generate_marker)\n    if not marker:\n        raise RuntimeError("normal generation memory: generate endpoint marker not found")\n    if normal_session_anchor not in generate_tail:\n        raise RuntimeError("normal generation memory: session context anchor not found inside generate endpoint")\n    generate_tail = generate_tail.replace(normal_session_anchor, normal_memory, 1)\n    app = prefix + marker + generate_tail\n'''
if old in text:
    text = text.replace(old, new, 1)

# These blocks are inserted inside existing classes/functions. `dedent()` made
# them top-level and accidentally terminated MemoryStore/MemoryService/create_app.
for variable, next_marker in (
    ("helpers", 'if "def mark_source_status(" not in store:'),
    ("gen_helper", 'if "def list_generations(" not in store:'),
    ("methods", 'if "def refresh_document(" not in service:'),
    ("helper", 'if "def _augment_memory_context(" not in app:'),
):
    opening = f"{variable} = dedent('''"
    if opening in text:
        start = text.index(opening)
        marker = text.index(next_marker, start)
        closing = text.rfind("''')", start, marker)
        if closing < 0:
            raise RuntimeError(f"{variable}: closing delimiter not found")
        text = text[:start] + text[start:closing].replace(opening, f"{variable} = '''", 1) + "'''\n" + text[closing + 5:]

path.write_text(text, encoding="utf-8")

# ---------------------------------------------------------------------------
# Fix pre-existing memory-store/query correctness issues before canonicalizing.
# ---------------------------------------------------------------------------
store_path = Path("src/memory/store.py")
store = store_path.read_text(encoding="utf-8")
store = replace_once(
    store,
    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'active','ready',?,?,?,?,?,?)",
    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'active','ready',?,?,?,?,?)",
    "memory chunk SQL value count",
)
store_path.write_text(store, encoding="utf-8")

query_path = Path("src/memory/query.py")
query = query_path.read_text(encoding="utf-8")
old_patterns = '''    ROUTE_PATTERNS: list[tuple[QueryRoute, re.Pattern[str]]] = [\n        (QueryRoute.EPISTEMIC_STATE, re.compile(r"\\b(know|knew|believe|believed|suspect|aware|secret|tahu|percaya|curiga)\\b", re.I)),\n        (QueryRoute.SPATIAL_LOOKUP, re.compile(r"\\b(where|inside|contains?|room|stored|located|near|adjacent|di mana|ruang|berisi|tersimpan)\\b", re.I)),\n'''
new_patterns = '''    ROUTE_PATTERNS: list[tuple[QueryRoute, re.Pattern[str]]] = [\n        (QueryRoute.STORY_CONTINUE, re.compile(r"\\b(continue|write|scene|dialogue|lanjut|tulis|adegan)\\b", re.I)),\n        (QueryRoute.EPISTEMIC_STATE, re.compile(r"\\b(know|knew|believe|believed|suspect|aware|secret|tahu|percaya|curiga)\\b", re.I)),\n        (QueryRoute.TEMPORAL_STATE, re.compile(r"\\b(before|after|at the time|used to|previously|historical|sebelum|setelah|saat itu|dulu)\\b", re.I)),\n        (QueryRoute.SPATIAL_LOOKUP, re.compile(r"\\b(where|inside|contains?|room|stored|located|near|adjacent|di mana|ruang|berisi|tersimpan)\\b", re.I)),\n'''
query = replace_once(query, old_patterns, new_patterns, "query route priority")
# Remove the now-duplicated later temporal route tuple.
late_temporal = '        (QueryRoute.TEMPORAL_STATE, re.compile(r"\\b(before|after|at the time|used to|previously|historical|sebelum|setelah|saat itu|dulu)\\b", re.I)),\n'
# The first occurrence is the newly inserted priority route; remove the second.
first = query.find(late_temporal)
second = query.find(late_temporal, first + len(late_temporal))
if second >= 0:
    query = query[:second] + query[second + len(late_temporal):]
query_path.write_text(query, encoding="utf-8")

# Keep all frontend assets on the same cache generation.
html_path = Path("src/interface/web/static/index.html")
html = html_path.read_text(encoding="utf-8")
html = html.replace("arline.css?v=1.1.3-media", "arline.css?v=1.2.0-memory")
html = html.replace("Studio v1.1</small>", "Studio v1.2 α</small>")
html_path.write_text(html, encoding="utf-8")

# ---------------------------------------------------------------------------
# Evolve v1.1 regression assertions so they still test the invariant rather
# than freezing the old release number/cache key on the development branch.
# ---------------------------------------------------------------------------
hardening_path = Path("tests/test_v11_hardening.py")
hardening = hardening_path.read_text(encoding="utf-8")
hardening = hardening.replace('        self.assertEqual(version, "1.1.0")\n        self.assertEqual(match.group(1), version)\n', '        self.assertEqual(match.group(1), version)\n')
hardening_path.write_text(hardening, encoding="utf-8")

settings_path = Path("tests/test_settings_stack_layout.py")
settings = settings_path.read_text(encoding="utf-8")
old_assets = '''        self.assertIn("arline.css?v=1.1.3-media", html)\n        self.assertIn("stream.js?v=1.1.3-media", html)\n        self.assertIn("arline.js?v=1.1.3-media", html)\n'''
new_assets = '''        versions = re.findall(r'(?:arline\\.css|stream\\.js|arline\\.js)\\?v=([^"\\s]+)', html)\n        self.assertEqual(len(versions), 3)\n        self.assertEqual(len(set(versions)), 1, versions)\n'''
if old_assets in settings:
    settings = settings.replace(old_assets, new_assets, 1)
if "import re\n" not in settings:
    settings = settings.replace("from pathlib import Path\n", "from pathlib import Path\nimport re\n", 1)
settings_path.write_text(settings, encoding="utf-8")

memory_test_path = Path("tests/memory/test_store_and_spatial.py")
memory_test = memory_test_path.read_text(encoding="utf-8")
old_replace = '''            second = store.upsert_chunk(\n                source_type="document", source_id="DOC-1", source_revision="2",\n                text="Vian moved the black dress into the storage room.",\n                project_id="P", world_id="W", branch_id="B",\n            )\n'''
new_replace = '''            # Source-level lifecycle is explicit so multi-chunk revisions can be\n            # inserted atomically without each chunk invalidating its siblings.\n            store.mark_source_status("document", "DOC-1", "stale")\n            second = store.upsert_chunk(\n                source_type="document", source_id="DOC-1", source_revision="2",\n                text="Vian moved the black dress into the storage room.",\n                project_id="P", world_id="W", branch_id="B",\n            )\n'''
if old_replace in memory_test:
    memory_test = memory_test.replace(old_replace, new_replace, 1)
memory_test_path.write_text(memory_test, encoding="utf-8")
