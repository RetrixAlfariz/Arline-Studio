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

# Identity anchor and displayed mention are different concerns. Reuse the
# canonical anchor but preserve the exact alias/name seen in the source.
old_label = 'subject_key=canonical_key, subject_label=family.get("name") or label,'
new_label = 'subject_key=canonical_key, subject_label=label,'
if old_label not in text:
    raise SystemExit('alias surface-label anchor not found')
text = text.replace(old_label, new_label, 1)

# Schema v4 is the intentional owner of mention/event/causality derived state.
marker = 'print("v1.2.2 top-down source pass applied")'
if marker not in text:
    raise SystemExit('applicator completion marker not found')
extra = r'''replace_once(
    "tests/test_architecture_hardening.py",
    "            self.assertEqual(store.SCHEMA_VERSION, 3)\n",
    "            self.assertEqual(store.SCHEMA_VERSION, 4)\n",
)
replace_once(
    "tests/test_architecture_hardening.py",
    '''                    "continuity_forms",\n                    "discovery_changes",''',
    '''                    "continuity_forms",\n                    "discovery_mentions",\n                    "continuity_events",\n                    "continuity_event_effects",\n                    "continuity_causal_links",\n                    "continuity_conflict_resolutions",\n                    "discovery_changes",''',
)

'''
text = text.replace(marker, extra + marker, 1)
path.write_text(text, encoding='utf-8')
print('v1.2.2 applicator compatibility hotfix applied')
