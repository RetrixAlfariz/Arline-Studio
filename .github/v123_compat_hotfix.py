from pathlib import Path

# v1.2.1 rail/temporal wrapper must preserve the v1.2.3 plan argument.
path = Path('src/memory/v121.py')
text = path.read_text(encoding='utf-8')
old = '''def _compile_v121(self: QueryCompiler, query: str, scope):\n    plan = _ORIGINAL_COMPILE(self, query, scope)\n'''
new = '''def _compile_v121(self: QueryCompiler, query: str, scope, context_plan=None):\n    plan = _ORIGINAL_COMPILE(self, query, scope, context_plan=context_plan)\n'''
if old not in text:
    raise SystemExit('v1.2.1 compile compatibility anchor not found')
path.write_text(text.replace(old, new, 1), encoding='utf-8')

# Discovery adds non-Canon candidates after base ranking. It must delegate the
# exact plan so v1.2.3 lane weights are not lost at this compatibility boundary.
path = Path('src/discovery/memory.py')
text = path.read_text(encoding='utf-8')
old = '''def _rrf_with_discovery(self: MemoryQueryEngine, lane_results):\n    result = list(_ORIGINAL_RRF(self, lane_results))\n'''
new = '''def _rrf_with_discovery(self: MemoryQueryEngine, lane_results, plan):\n    result = list(_ORIGINAL_RRF(self, lane_results, plan))\n'''
if old not in text:
    raise SystemExit('Discovery RRF compatibility anchor not found')
text = text.replace(old, new, 1)
path.write_text(text, encoding='utf-8')

# A valid context plan is itself useful runtime metadata. Render its header and
# policy even when no scoped evidence candidates were selected, so zero-result
# retrieval remains distinguishable from "context intelligence did not run".
path = Path('src/memory/query.py')
text = path.read_text(encoding='utf-8')
old = '''    def _pack(plan: QueryPlan, selected: list[MemoryCandidate], excluded: list[dict[str, Any]]) -> str:\n        if not selected:\n            return ""\n'''
new = '''    def _pack(plan: QueryPlan, selected: list[MemoryCandidate], excluded: list[dict[str, Any]]) -> str:\n        if not selected and not plan.context_plan:\n            return ""\n'''
if old not in text:
    raise SystemExit('v1.2.3 empty-plan pack anchor not found')
path.write_text(text.replace(old, new, 1), encoding='utf-8')
print('v1.2.3 compatibility/observability patches applied')
