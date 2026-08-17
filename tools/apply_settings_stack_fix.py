from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing anchor: {label}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# HTML: Feedback Lab is a Settings surface, not a main workspace destination.
# ---------------------------------------------------------------------------
html_path = "src/interface/web/static/index.html"
html = read(html_path)

feedback_page = re.compile(
    r"\n\s*<!-- FEEDBACK LAB -->\n\s*<section id=\"dataView\" class=\"workspace-view\" data-view-panel=\"data\">.*?\n\s*</section>\n\s*</main>",
    re.S,
)
match = feedback_page.search(html)
if not match:
    raise SystemExit("Feedback Lab main-workspace section not found")
html = html[: match.start()] + "\n      </main>" + html[match.end() :]

old_review = '''      <div class="inspector-panel" data-inspector-panel="review">
        <span class="eyebrow">Developer</span><h3>Review & Evals</h3>
        <p class="settings-help">Output review, comparisons, SFT/preference exports, and evaluator artifacts live here instead of the primary writing navigation.</p>
        <div id="developerReviewSummary" class="info-card">Open Review & Evals to inspect generated candidates.</div>
        <button id="openFeedbackLabBtn" class="primary-btn wide">Open Review & Evals</button>
      </div>'''

new_review = '''      <div class="inspector-panel" data-inspector-panel="review">
        <div class="settings-panel-heading">
          <span class="eyebrow">Developer</span>
          <h3>Review & Evals</h3>
          <p class="settings-help">Feedback Lab lives here. Review generated prose, compare forks, and export evaluation data without leaving Settings.</p>
        </div>
        <div class="settings-review-lab feedback-lab">
          <div class="settings-review-head">
            <div><h4>Feedback Lab</h4><p>Generated output remains separate from accepted training data until you review it.</p></div>
            <button id="feedbackAdvancedToggle" class="secondary-btn">Data & evaluation</button>
          </div>
          <div id="datasetCards" class="metric-grid"></div>
          <nav class="feedback-tabs" aria-label="Feedback review views">
            <button class="active" data-feedback-tab="queue">Review queue</button>
            <button data-feedback-tab="comparisons">Comparisons</button>
            <button data-feedback-tab="reviewed">Reviewed</button>
          </nav>
          <section class="feedback-workbench">
            <div id="feedbackQueue" class="feedback-queue"></div>
            <div id="feedbackQueueEmpty" class="empty-state small"><b>Nothing waiting for review.</b><span>New generated prose appears here until you accept, edit, or reject it.</span></div>
          </section>
          <section id="feedbackAdvanced" class="feedback-advanced hidden">
            <div class="section-head"><div><h4>Data & evaluation</h4><p>Exports keep their generation lineage automatically.</p></div></div>
            <div class="export-grid">
              <button data-export="master"><b>Master records</b><span>Full lineage and artifacts</span></button>
              <button data-export="sft"><b>SFT</b><span>Accepted context → final prose</span></button>
              <button data-export="preference"><b>Preference</b><span>Chosen vs rejected candidates</span></button>
              <button data-export="eval"><b>Evaluator</b><span>Context + issue labels</span></button>
            </div>
            <div class="policy-card"><code>generated ≠ accepted</code><code>edited + accepted = gold</code><code>rejected = negative</code><code>chat forks = comparison opportunity</code></div>
          </section>
        </div>
      </div>'''
html = replace_once(html, old_review, new_review, "Review & Evals panel")
html = html.replace('title="Developer inspector"', 'title="Settings"')

# Force a coherent asset generation after updates so stale HTML/CSS/JS do not mix.
html = html.replace('href="/static/arline.css"', 'href="/static/arline.css?v=1.1.1-settings"')
html = html.replace('src="/static/js/stream.js"', 'src="/static/js/stream.js?v=1.1.1-settings"')
html = html.replace('src="/static/arline.js"', 'src="/static/arline.js?v=1.1.1-settings"')
write(html_path, html)


# ---------------------------------------------------------------------------
# CSS: one-column, top-to-down Settings. Generic selectors also repair stale
# pre-v1.1 Inspector markup instead of allowing its old horizontal tab strip.
# ---------------------------------------------------------------------------
css_path = "src/interface/web/static/arline.css"
css = read(css_path)
css += r'''

/* v1.1 settings stack hotfix: Settings flows top-to-down, never side-to-side. */
.inspector{
  width:min(760px,calc(100vw - 24px));
  display:flex!important;
  flex-direction:column!important;
  grid-template-columns:none!important;
  grid-template-rows:none!important;
  overflow:hidden!important;
}
.inspector .inspector-head{
  grid-column:auto!important;grid-row:auto!important;flex:0 0 auto;
}
.inspector .inspector-tabs,
.inspector .inspector-tabs.settings-nav{
  grid-column:auto!important;grid-row:auto!important;
  display:flex!important;flex:0 0 auto;flex-direction:column!important;
  align-items:stretch!important;gap:2px;
  width:100%;max-height:min(290px,34vh);overflow:auto;
  padding:10px 16px 12px;
  border-right:0!important;border-bottom:1px solid var(--border)!important;
  background:#202321;
}
.inspector .inspector-tabs button,
.inspector .inspector-tabs.settings-nav button{
  width:100%;min-height:32px;text-align:left;justify-content:flex-start;
  border:0!important;border-left:2px solid transparent!important;
  border-radius:8px!important;padding:7px 10px!important;
}
.inspector .inspector-tabs button:hover{background:rgba(255,255,255,.04)}
.inspector .inspector-tabs button.active,
.inspector .inspector-tabs.settings-nav button.active{
  background:var(--accent-soft)!important;color:#c9eee4!important;
  border-left-color:var(--accent)!important;
}
.inspector .settings-search{
  position:sticky;top:0;z-index:3;display:flex!important;
  background:#252825!important;box-shadow:0 5px 12px rgba(0,0,0,.12);
}
.inspector .settings-group-label{display:block!important;padding:10px 9px 4px}
.inspector .inspector-panel{
  grid-column:auto!important;grid-row:auto!important;
  flex:1 1 auto;min-height:0;overflow:auto;padding:18px 20px 28px;
}
.inspector .settings-panel-heading h3{font-size:15px;margin:4px 0 5px}
.inspector .settings-review-lab{margin-top:14px}
.inspector .settings-review-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:12px}
.inspector .settings-review-head h4,.inspector .feedback-advanced h4{font-size:12px;margin:0 0 4px;color:var(--text)}
.inspector .settings-review-head p,.inspector .feedback-advanced .section-head p{margin:0;color:var(--muted);font-size:9px;line-height:1.5}
.inspector .metric-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}
.inspector .metric-card{padding:10px;border-radius:11px}
.inspector .metric-card strong{font-size:16px}
.inspector .feedback-tabs{margin-top:13px}
.inspector .feedback-workbench{min-height:110px}
.inspector .feedback-queue{gap:8px}
.inspector .feedback-card{padding:10px;border-radius:12px}
.inspector .feedback-prose{max-height:220px;font-size:12px}
.inspector .feedback-advanced{margin-top:17px;padding-top:15px}
.inspector .export-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}
.inspector .export-grid button{padding:10px;border-radius:10px}
.inspector .empty-state.small{padding:24px 12px}

@media(max-width:760px){
  .inspector{width:100vw!important;max-width:100vw}
  .inspector .inspector-tabs,.inspector .inspector-tabs.settings-nav{
    flex-direction:column!important;max-height:240px;border-right:0!important;
  }
  .inspector .inspector-tabs.settings-nav .settings-search{display:flex!important}
  .inspector .inspector-tabs.settings-nav .settings-group-label{display:block!important}
  .inspector .inspector-panel{grid-column:auto!important;grid-row:auto!important;padding:15px 14px 24px}
  .inspector .metric-grid,.inspector .export-grid{grid-template-columns:1fr}
  .inspector .settings-review-head{flex-direction:column}
}
'''
write(css_path, css)


# ---------------------------------------------------------------------------
# JS: legacy Feedback Lab routes are redirected into Settings → Review & Evals.
# ---------------------------------------------------------------------------
js_path = "src/interface/web/static/arline.js"
js = read(js_path)

old_activate = '''function activateInspectorTab(tab) {
  $$("[data-inspector-tab]").forEach((node) => node.classList.toggle("active", node.dataset.inspectorTab === tab));
  $$("[data-inspector-panel]").forEach((node) => node.classList.toggle("active", node.dataset.inspectorPanel === tab));
}'''
new_activate = '''function activateInspectorTab(tab) {
  $$("[data-inspector-tab]").forEach((node) => node.classList.toggle("active", node.dataset.inspectorTab === tab));
  $$("[data-inspector-panel]").forEach((node) => node.classList.toggle("active", node.dataset.inspectorPanel === tab));
  if (tab === "review") loadFeedbackLab();
}'''
js = replace_once(js, old_activate, new_activate, "activateInspectorTab")

js = replace_once(
    js,
    'function setView(view, options = {}) {\n  state.activeView = view;',
    'function setView(view, options = {}) {\n  if (view === "data") {\n    view = "home";\n    queueMicrotask(() => { openInspector("review"); loadFeedbackLab(); });\n  }\n  state.activeView = view;',
    "legacy data route redirect",
)

js = replace_once(
    js,
    '  on("openDataBtn", "click", () => setView("data"));',
    '  on("openDataBtn", "click", () => { openInspector("review"); loadFeedbackLab(); });',
    "openDataBtn handler",
)
js = replace_once(
    js,
    '  on("openFeedbackLabBtn", "click", () => { closeInspector(); setView("data"); });',
    '  on("openFeedbackLabBtn", "click", () => { openInspector("review"); loadFeedbackLab(); });',
    "legacy Feedback Lab button handler",
)
write(js_path, js)


# ---------------------------------------------------------------------------
# Regression test: this is deliberately structural because the bug was caused
# by a DOM/CSS generation mismatch rather than business logic.
# ---------------------------------------------------------------------------
test_path = ROOT / "tests/test_settings_stack_layout.py"
test_path.write_text(
    '''from pathlib import Path\nimport unittest\n\nROOT = Path(__file__).resolve().parents[1]\n\n\nclass SettingsStackLayoutTests(unittest.TestCase):\n    def test_feedback_lab_is_not_a_main_workspace_view(self):\n        html = (ROOT / "src/interface/web/static/index.html").read_text(encoding="utf-8")\n        self.assertNotIn('data-view-panel="data"', html)\n        review_at = html.index('data-inspector-panel="review"')\n        self.assertGreater(html.index('id="datasetCards"'), review_at)\n        self.assertGreater(html.index('id="feedbackQueue"'), review_at)\n        self.assertGreater(html.index('id="feedbackAdvanced"'), review_at)\n\n    def test_settings_navigation_is_top_to_down(self):\n        css = (ROOT / "src/interface/web/static/arline.css").read_text(encoding="utf-8")\n        self.assertIn("v1.1 settings stack hotfix", css)\n        self.assertIn("flex-direction:column!important", css)\n        self.assertIn(".inspector .inspector-tabs", css)\n\n    def test_legacy_feedback_route_redirects_to_settings(self):\n        js = (ROOT / "src/interface/web/static/arline.js").read_text(encoding="utf-8")\n        self.assertIn('if (view === "data")', js)\n        self.assertIn('openInspector("review")', js)\n        self.assertNotIn('setView("data")', js)\n\n    def test_static_assets_are_versioned_together(self):\n        html = (ROOT / "src/interface/web/static/index.html").read_text(encoding="utf-8")\n        self.assertIn("arline.css?v=1.1.1-settings", html)\n        self.assertIn("stream.js?v=1.1.1-settings", html)\n        self.assertIn("arline.js?v=1.1.1-settings", html)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''',
    encoding="utf-8",
)

print("SETTINGS_STACK_FIX_APPLIED")
