from pathlib import Path

path = Path('.github/v122_topdown_apply.py')
text = path.read_text(encoding='utf-8')

old = "    '''      section.querySelectorAll(\"[data-prov-claim]\").forEach((row) => {\\n''',"
new = "    '''      const claimMap = new Map((data.claims || []).map((item) => [item.id, item]));\\n''',"
if old not in text:
    raise SystemExit('primary UI anchor not found in applicator')
text = text.replace(old, new, 1)
old_tail = "      });\\n\\n      section.querySelectorAll(\"[data-prov-claim]\").forEach((row) => {\\n''',"
new_tail = "      });\\n\\n      const claimMap = new Map((data.claims || []).map((item) => [item.id, item]));\\n''',"
if old_tail not in text:
    raise SystemExit('UI replacement tail not found in applicator')
text = text.replace(old_tail, new_tail, 1)

# Stable identity unifies aliases, but proposition labels preserve the exact
# source surface so provenance/UI still show what the story actually called it.
old_label = 'subject_key=canonical_key, subject_label=family.get("name") or label,'
new_label = 'subject_key=canonical_key, subject_label=label,'
if old_label not in text:
    raise SystemExit('alias surface-label anchor not found')
text = text.replace(old_label, new_label, 1)

marker = 'print("v1.2.2 top-down source pass applied")'
if marker not in text:
    raise SystemExit('applicator completion marker not found')
extra = '''replace_once(\n    "tests/test_architecture_hardening.py",\n    "            self.assertEqual(store.SCHEMA_VERSION, 3)\\n",\n    "            self.assertEqual(store.SCHEMA_VERSION, 4)\\n",\n)\n\n'''
text = text.replace(marker, extra + marker, 1)
path.write_text(text, encoding='utf-8')
print('v1.2.2 applicator compatibility hotfix applied')
