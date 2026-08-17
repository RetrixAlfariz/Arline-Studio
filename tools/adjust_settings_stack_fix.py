from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
js_path = ROOT / "src/interface/web/static/arline.js"
test_path = ROOT / "tests/test_settings_stack_layout.py"

js = js_path.read_text(encoding="utf-8")

old = '  data: () => setView("data"),'
new = '  data: () => { openInspector("review"); loadFeedbackLab(); },'
if old not in js:
    raise SystemExit("legacy command Feedback Lab route not found")
js = js.replace(old, new, 1)

old = 'data-home-view="data"'
if old not in js:
    raise SystemExit("Home Feedback Lab route not found")
js = js.replace(old, 'data-home-review="1"', 1)
js = js.replace('<small>Feedback Lab</small>', '<small>Review & Evals · Settings</small>', 1)

home_handler = '$$(\'[data-home-view]\',byId("homeView")).forEach((b)=>b.addEventListener("click",()=>setView(b.dataset.homeView)));'
review_handler = home_handler + '\n  $$(\'[data-home-review]\',byId("homeView")).forEach((b)=>b.addEventListener("click",()=>{openInspector("review");loadFeedbackLab();}));'
if home_handler not in js:
    raise SystemExit("Home view handler anchor not found")
js = js.replace(home_handler, review_handler, 1)

# Once the legacy route is remapped at function entry this branch can never run.
js = js.replace('  if (view === "data") loadFeedbackLab();\n', '', 1)
js_path.write_text(js, encoding="utf-8")

test = test_path.read_text(encoding="utf-8")
test = test.replace(
    "        self.assertNotIn('setView(\"data\")', js)\n",
    "        self.assertNotIn('data: () => setView(\"data\")', js)\n"
    "        self.assertNotIn('data-home-view=\"data\"', js)\n"
    "        self.assertIn('data-home-review=\"1\"', js)\n",
    1,
)
test_path.write_text(test, encoding="utf-8")

print("SETTINGS_STACK_ROUTE_CLEANUP_APPLIED")
