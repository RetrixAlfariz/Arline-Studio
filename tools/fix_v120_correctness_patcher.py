from pathlib import Path

path = Path("tools/v120_correctness_hardening.py")
text = path.read_text(encoding="utf-8")

# Keep MemoryStore helpers inside the class. The first patcher accidentally
# dedented this generated method to module scope.
opening = "transactional_method = dedent('''\n    def replace_source_revision("
if opening in text:
    start = text.index(opening)
    marker = text.index('if "def replace_source_revision(" not in store:', start)
    closing = text.rfind("''')", start, marker)
    if closing < 0:
        raise RuntimeError("transactional helper closing delimiter not found")
    text = text[:start] + text[start:closing].replace(
        "transactional_method = dedent('''", "transactional_method = '''", 1
    ) + "'''" + text[closing + 4:]

# 31 memory_chunk columns = 24 bound values + 2 status literals + 5 bound
# tail values. Keep the atomic INSERT at exactly 29 bind placeholders.
text = text.replace(
    '"VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,\'active\',\'ready\',?,?,?,?,?)",',
    '"VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,\'active\',\'ready\',?,?,?,?,?)",',
    1,
)

# Specific informational routes run first, then an explicit continuation
# imperative, and only then the broad CURRENT_STATE fallback.
old_route = '''new_route = \'\'\'    @classmethod\\n    def route(cls, query: str) -> QueryRoute:\\n        stripped = query.strip()\\n        for route, pattern in cls.ROUTE_PATTERNS:\\n            if pattern.search(stripped):\\n                return route\\n        if cls.STORY_CONTINUE_PATTERN.search(stripped):\\n            return QueryRoute.STORY_CONTINUE\\n        return QueryRoute.TEXT_RECALL\\n\'\'\'\n'''
new_route = '''new_route = \'\'\'    @classmethod\\n    def route(cls, query: str) -> QueryRoute:\\n        stripped = query.strip()\\n        for route, pattern in cls.ROUTE_PATTERNS:\\n            if route == QueryRoute.CURRENT_STATE:\\n                continue\\n            if pattern.search(stripped):\\n                return route\\n        if cls.STORY_CONTINUE_PATTERN.search(stripped):\\n            return QueryRoute.STORY_CONTINUE\\n        for route, pattern in cls.ROUTE_PATTERNS:\\n            if route == QueryRoute.CURRENT_STATE and pattern.search(stripped):\\n                return route\\n        return QueryRoute.TEXT_RECALL\\n\'\'\'\n'''
if old_route not in text:
    raise RuntimeError("query route patch block not found")
text = text.replace(old_route, new_route, 1)

# Scene order changes are part of the indexed revision even if prose text did
# not change; otherwise reordering a scene would keep stale story_order data.
old_doc_revision = '''        source_id = document["id"]\n        revision = self._revision(document.get("updated_at"), document.get("title"), document.get("content"))\n        title = str(document.get("title") or "Untitled")\n        units = self.chunker.chunk(str(document.get("content") or ""), source_id=source_id)\n'''
new_doc_revision = '''        source_id = document["id"]\n        story_order, world_time = self._document_temporal(document)\n        revision = self._revision(document.get("updated_at"), document.get("title"), document.get("content"), story_order, world_time)\n        title = str(document.get("title") or "Untitled")\n        units = self.chunker.chunk(str(document.get("content") or ""), source_id=source_id)\n'''
if old_doc_revision not in text:
    raise RuntimeError("document revision generation block not found")
text = text.replace(old_doc_revision, new_doc_revision, 1)
text = text.replace(
    '''        catalog = catalog if catalog is not None else self._identity_catalog()\n        story_order, world_time = self._document_temporal(document)\n        prepared = []\n''',
    '''        catalog = catalog if catalog is not None else self._identity_catalog()\n        prepared = []\n''',
    1,
)

# If the active scene has no Scene Card, use the Manuscript object's explicit
# sort_order rather than giving the query an unknown cutoff.
old_enrich = '''        scene_card = scene_card or {}\n        if context.story_order is None and scene_card.get("sort_order") is not None:\n            context.story_order = float(scene_card["sort_order"])\n        if context.world_time is None:\n'''
new_enrich = '''        scene_card = scene_card or {}\n        active_document = {}\n        if active.get("document_id"):\n            try:\n                active_document = self.workspace.get_document(active["document_id"]) or {}\n            except Exception:\n                active_document = {}\n        if context.story_order is None:\n            order = scene_card.get("sort_order")\n            if order is None:\n                order = active_document.get("sort_order")\n            if order is not None:\n                context.story_order = float(order)\n        if context.world_time is None:\n'''
if old_enrich not in text:
    raise RuntimeError("service story-order enrichment block not found")
text = text.replace(old_enrich, new_enrich, 1)

# The JS bridge should follow the active scene's document before falling back to
# whichever Manuscript document happens to be selected in the editor.
text = text.replace(
    '''    const sceneCard = (current.sceneCards || []).find((item) => item.document_id === activeDocumentId) || null;\n    return {\n''',
    '''    const sceneCard = (current.sceneCards || []).find((item) => item.document_id === activeDocumentId) || null;\n    const sceneDocument = (current.documents || []).find((item) => item.id === activeDocumentId) || null;\n    return {\n''',
    1,
)
text = text.replace(
    '''      storyOrder: memoryState.storyOrder ?? sceneCard?.sort_order ?? current.activeDocument?.sort_order ?? null,\n''',
    '''      storyOrder: memoryState.storyOrder ?? sceneCard?.sort_order ?? sceneDocument?.sort_order ?? current.activeDocument?.sort_order ?? null,\n''',
    1,
)

# Test real document order through the production update API; create_document
# intentionally does not accept sort_order at creation time.
text = text.replace(
    '''            earlier = workspace.create_document(project["id"], "Earlier", content="shared clue early", world_id=world_id, branch_id=branch["id"], sort_order=1)\n            later = workspace.create_document(project["id"], "Later", content="shared clue spoiler", world_id=world_id, branch_id=branch["id"], sort_order=2)\n''',
    '''            earlier = workspace.create_document(project["id"], "Earlier", content="shared clue early", world_id=world_id, branch_id=branch["id"])\n            later = workspace.create_document(project["id"], "Later", content="shared clue spoiler", world_id=world_id, branch_id=branch["id"])\n            earlier = workspace.update_document(earlier["id"], sort_order=1, note="test order")\n            later = workspace.update_document(later["id"], sort_order=2, note="test order")\n''',
    1,
)

path.write_text(text, encoding="utf-8")
