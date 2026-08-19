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
old_record = "            ambiguous_candidates=list(result.ambiguous_candidates),\\n            span_start=span_start, span_end=span_end,"
new_record = "            ambiguous_candidates=list(result.ambiguous_candidates),\\n            span_start=span_start, span_end=span_end, resolved_label=result.subject_label,"
if old_record not in text:
    raise SystemExit('mention resolved_label anchor not found')
text = text.replace(old_record, new_record, 1)
path.write_text(text, encoding='utf-8')
print('v1.2.2 applicator hotfix applied')
