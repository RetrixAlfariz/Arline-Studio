from pathlib import Path

path = Path("tools/complete_v120_foundation.py")
text = path.read_text(encoding="utf-8")
old = '''if normal_memory not in app:\n    app = replace_once(app, normal_session_anchor, normal_memory, label="normal generation memory")\n'''
new = '''if normal_memory not in app:\n    generate_marker = '    @app.post("/api/generate")\\n'\n    prefix, marker, generate_tail = app.partition(generate_marker)\n    if not marker:\n        raise RuntimeError("normal generation memory: generate endpoint marker not found")\n    if normal_session_anchor not in generate_tail:\n        raise RuntimeError("normal generation memory: session context anchor not found inside generate endpoint")\n    generate_tail = generate_tail.replace(normal_session_anchor, normal_memory, 1)\n    app = prefix + marker + generate_tail\n'''
if old not in text:
    raise RuntimeError("normal generation patcher block not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
