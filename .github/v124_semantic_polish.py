from pathlib import Path


def patch(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding='utf-8')
    if old not in text:
        raise SystemExit(f'anchor missing in {path}: {old[:100]!r}')
    p.write_text(text.replace(old, new, 1), encoding='utf-8')


# /pov is a real request-scoped epistemic override, not just a prose hint.
patch(
    'src/directives/engine.py',
    '''        resolved = cls._dedupe(resolved)\n        kept_lines = [line for index, line in enumerate(lines) if index != command_line_index]\n''',
    '''        resolved = cls._dedupe(resolved)\n        if command_spec is not None and command_spec.id == "pov":\n            pov_ref = next((item for item in resolved if item.get("type") == "entity_variant"), None)\n            if pov_ref is not None:\n                options["pov_variant_id"] = str(pov_ref["id"])\n            else:\n                diagnostics.append("/pov requires one resolved character reference; the existing scene POV remains active.")\n        kept_lines = [line for index, line in enumerate(lines) if index != command_line_index]\n''',
)

# Dynamic scope references are semantic controls, so they must change lane priority.
patch(
    'src/context/intelligence.py',
    '''        if "conflicts" in selectors:\n            dimensions["continuity"] = 1.0\n\n        lane_weights: dict[str, float] = {}\n''',
    '''        if "conflicts" in selectors:\n            dimensions["continuity"] = 1.0\n\n        dynamic_scopes = {str(item).casefold() for item in (directive.get("dynamic_scopes") or [])}\n        if "threads" in dynamic_scopes:\n            dimensions["threads"] = 1.0\n        if "recent" in dynamic_scopes:\n            dimensions["source"] = 1.0\n            dimensions["events"] = max(dimensions["events"], .72)\n\n        lane_weights: dict[str, float] = {}\n''',
)

# /alternatives count=N should affect the actual bounded intuition request/output.
patch(
    'src/deliberation/engine.py',
    '''        context = "\\n\\n".join(filter(None, [\n''',
    '''        options = dict(directive.get("options") or {})\n        try:\n            requested_alternatives = int(options.get("count", cfg.alternatives))\n        except (TypeError, ValueError):\n            requested_alternatives = int(cfg.alternatives)\n        requested_alternatives = max(1, min(8, requested_alternatives))\n        context = "\\n\\n".join(filter(None, [\n''',
)
patch(
    'src/deliberation/engine.py',
    '''            "alternatives_requested": max(1, int(cfg.alternatives)),\n''',
    '''            "alternatives_requested": requested_alternatives,\n''',
)
patch(
    'src/deliberation/engine.py',
    '''                alternatives=self._clip_list(payload.get("alternatives"), max(1, int(cfg.alternatives))),\n''',
    '''                alternatives=self._clip_list(payload.get("alternatives"), requested_alternatives),\n''',
)

# Apply /pov to ScopeGate for this request only. It never mutates the active scene.
patch(
    'src/interface/web/app.py',
    '''        lens = str(payload.context_lens or memory_config.default_lens or "scene").lower()\n        if lens not in {"author", "scene", "pov"}:\n''',
    '''        lens = str(payload.context_lens or memory_config.default_lens or "scene").lower()\n        directive_pov = str(directive.options.get("pov_variant_id") or "").strip() or None\n        if (directive.command or {}).get("id") == "pov" and directive_pov:\n            lens = "pov"\n        if lens not in {"author", "scene", "pov"}:\n''',
)
patch(
    'src/interface/web/app.py',
    '''            pov_variant_id=payload.pov_variant_id or active_scene.get("pov_variant_id"),\n''',
    '''            pov_variant_id=directive_pov or payload.pov_variant_id or active_scene.get("pov_variant_id"),\n''',
)

# Regression coverage for semantics promised by v1.2.4.
p = Path('tests/test_v124_directives_deliberation.py')
text = p.read_text(encoding='utf-8')
anchor = '''    def test_model_deliberation_is_soft_noncanon(self):\n'''
extra = '''    def test_pov_command_sets_request_scoped_epistemic_anchor(self):\n        refs = [{"type": "entity_variant", "id": "V-FILA", "label": "Fila", "mode": "context"}]\n        result = DirectiveEngine.parse('/pov @Fila "stay close to her internal perspective"', explicit_references=refs)\n        self.assertEqual(result.options["pov_variant_id"], "V-FILA")\n        self.assertEqual(result.command["id"], "pov")\n\n    def test_dynamic_threads_and_recent_boost_their_dimensions(self):\n        class Scope:\n            explicit_references = []\n            pov_variant_id = None\n            world_time = None\n            story_order = None\n            token_budget = 1600\n            context_lens = "scene"\n            allow_future_author_knowledge = False\n        ws = SimpleNamespace(\n            scope={"directive": {"version": "1.2.4a1", "dynamic_scopes": ["threads", "recent"], "resolved_references": []}},\n            auto_selected=[], explicit_references=[],\n        )\n        plan = NarrativeContextPlanner().plan("continue", Scope(), workspace_context=ws, route="STORY_CONTINUE")\n        self.assertEqual(plan.dimensions["threads"], 1.0)\n        self.assertEqual(plan.dimensions["source"], 1.0)\n        self.assertIn("threads", plan.optional_lanes)\n        self.assertIn("fts_manuscript", plan.optional_lanes)\n\n    def test_alternatives_count_controls_deliberator_request_and_output(self):\n        with tempfile.TemporaryDirectory() as td:\n            cfg = self._config(Path(td))\n            payload = '{"scene_goal":"choose","likely_beats":[],"character_intentions":[],"emotional_trajectories":[],"opportunities":[],"alternatives":["a","b","c","d","e","f"],"uncertainties":[],"constraints":[]}'\n            client = _FakeClient(payload)\n            out = NarrativeDeliberator(cfg).deliberate(\n                client=client, model="fake-model",\n                directive={"planner_intent":"deliberate","output_mode":"author_alternatives","semantic_prompt":"options","options":{"count":"5"}},\n                context_plan={"intent":"deliberate"}, workspace_text="trusted", wcf_text="LOCKED", narrative_brief="brief",\n            )\n            self.assertEqual(out.alternatives, ["a", "b", "c", "d", "e"])\n            self.assertIn('"alternatives_requested": 5', client.calls[0]["input_text"])\n\n'''
if extra not in text:
    if anchor not in text:
        raise SystemExit('semantic polish test anchor missing')
    text = text.replace(anchor, extra + anchor, 1)
p.write_text(text, encoding='utf-8')

# Strengthen integration contract: /pov must reach the memory epistemic boundary.
p = Path('tests/test_v124_directives_deliberation.py')
text = p.read_text(encoding='utf-8')
old = '''        self.assertIn('\"reference_selectors\"', app)\n'''
new = '''        self.assertIn('\"reference_selectors\"', app)\n        self.assertIn('pov_variant_id=directive_pov or payload.pov_variant_id', app)\n'''
if old not in text:
    raise SystemExit('source contract POV anchor missing')
p.write_text(text.replace(old, new, 1), encoding='utf-8')

print('v1.2.4 semantic directive/reference polish applied')
