from pathlib import Path

path = Path('.github/v124_topdown_apply.py')
text = path.read_text(encoding='utf-8')
start = "cfg.write_text('''[lmstudio]"
end = "context_chars=8000\\n''', encoding=\"utf-8\")"
if start not in text or end not in text:
    raise SystemExit('v1.2.4 nested TOML fixture anchors not found')
text = text.replace(start, 'cfg.write_text("""[lmstudio]', 1)
text = text.replace(end, 'context_chars=8000\\n""", encoding="utf-8")', 1)
path.write_text(text, encoding='utf-8')
print('v1.2.4 applicator quoting repaired')
