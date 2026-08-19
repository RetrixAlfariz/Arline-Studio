from pathlib import Path

path = Path('src/memory/v121.py')
text = path.read_text(encoding='utf-8')
old = '''def _compile_v121(self: QueryCompiler, query: str, scope):\n    plan = _ORIGINAL_COMPILE(self, query, scope)\n'''
new = '''def _compile_v121(self: QueryCompiler, query: str, scope, context_plan=None):\n    plan = _ORIGINAL_COMPILE(self, query, scope, context_plan=context_plan)\n'''
if old not in text:
    raise SystemExit('v1.2.1 compile compatibility anchor not found')
path.write_text(text.replace(old, new, 1), encoding='utf-8')
print('v1.2.3 query compatibility patch applied')
