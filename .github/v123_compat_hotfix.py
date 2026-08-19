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

path = Path('src/memory/query.py')
text = path.read_text(encoding='utf-8')

# A valid context plan is itself useful runtime metadata. Render its header and
# policy even when no scoped evidence candidates were selected.
old = '''    def _pack(plan: QueryPlan, selected: list[MemoryCandidate], excluded: list[dict[str, Any]]) -> str:\n        if not selected:\n            return ""\n'''
new = '''    def _pack(plan: QueryPlan, selected: list[MemoryCandidate], excluded: list[dict[str, Any]]) -> str:\n        if not selected and not plan.context_plan:\n            return ""\n'''
if old not in text:
    raise SystemExit('v1.2.3 empty-plan pack anchor not found')
text = text.replace(old, new, 1)

# Candidate budgets happen *before* ScopeGate. Text lanes keep a small audit
# overfetch floor so context planning cannot make cross-scope evidence disappear
# before ScopeGate has a chance to reject and trace it.
old = '''        candidate_budgets = {\n            lane.value: max(2, int(round(self.config.max_candidates * weights.get(lane.value, 1.0) / total_weight)))\n            for lane in lanes\n        }\n        return QueryPlan(\n'''
new = '''        candidate_budgets = {\n            lane.value: max(2, int(round(self.config.max_candidates * weights.get(lane.value, 1.0) / total_weight)))\n            for lane in lanes\n        }\n        for lane in lanes:\n            if lane in fts_lanes:\n                candidate_budgets[lane.value] = max(16, candidate_budgets[lane.value])\n        return QueryPlan(\n'''
if old not in text:
    raise SystemExit('v1.2.3 candidate budget anchor not found')
text = text.replace(old, new, 1)
path.write_text(text, encoding='utf-8')

# Architecture regression intentionally tracks the active development version.
path = Path('tests/test_architecture_hardening.py')
text = path.read_text(encoding='utf-8')
old = '        self.assertEqual(__version__, "1.2.2a1")\n'
new = '        self.assertEqual(__version__, "1.2.3a1")\n'
if old not in text:
    raise SystemExit('version contract test anchor not found')
path.write_text(text.replace(old, new, 1), encoding='utf-8')

print('v1.2.3 compatibility, audit-overfetch, and version patches applied')
