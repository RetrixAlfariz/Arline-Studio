from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from src.context.intelligence import NarrativeContextPlanner
from src.deliberation import NarrativeDeliberator
from src.directives import COMMAND_REGISTRY_VERSION, DirectiveEngine, DYNAMIC_REFERENCES, REFERENCE_SELECTORS
from src.runtime_config import RuntimeConfig


class _FakeChatResult:
    def __init__(self, text: str):
        self.text = text
        self.reasoning = ""
        self.stats = {}
        self.raw = {"output": []}


class _FakeClient:
    def __init__(self, text: str | None = None, failure: Exception | None = None):
        self.text = text
        self.failure = failure
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure:
            raise self.failure
        return _FakeChatResult(self.text or "{}")


class V124DirectiveDeliberationTests(unittest.TestCase):
    def test_registry_and_reference_contract(self):
        ids = {item["id"] for item in DirectiveEngine.catalog()}
        self.assertEqual(COMMAND_REGISTRY_VERSION, "1.2.4a1")
        self.assertTrue({"intuition", "alternatives", "describe", "pov", "pace", "dia"} <= ids)
        self.assertIn("voice", REFERENCE_SELECTORS)
        self.assertIn("pov", DYNAMIC_REFERENCES)

    def test_typed_dialogue_directive(self):
        refs = [
            {"type": "entity_variant", "id": "V-FILA", "label": "Fila", "mode": "context"},
            {"type": "entity_variant", "id": "V-MIRA", "label": "Mira", "mode": "context"},
        ]
        result = DirectiveEngine.parse('/dia @Fila @Mira slow curve=wave "awkward apology"', explicit_references=refs)
        self.assertEqual(result.command["id"], "dia")
        self.assertEqual(result.planner_intent, "dialogue")
        self.assertEqual(result.options["pacing"], "slow")
        self.assertEqual(result.options["curve"], "wave")
        self.assertEqual(result.semantic_prompt, "awkward apology")
        self.assertEqual({x["id"] for x in result.resolved_references}, {"V-FILA", "V-MIRA"})

    def test_dynamic_references_resolve_at_request_time(self):
        scene = {"document_id": "DOC-1", "pov_variant_id": "V-POV", "location_variant_id": "V-ROOM", "participants": ["V-POV", "V-GUEST"]}
        result = DirectiveEngine.parse('/continue @scene @pov @cast @location', active_scene=scene, project_id="P", world_id="W", branch_id="B")
        pairs = {(x["type"], x["id"]) for x in result.resolved_references}
        self.assertIn(("document", "DOC-1"), pairs)
        self.assertIn(("entity_variant", "V-POV"), pairs)
        self.assertIn(("entity_variant", "V-GUEST"), pairs)
        self.assertIn(("entity_variant", "V-ROOM"), pairs)

    def test_named_selector_stays_on_stable_reference(self):
        refs = [{"type": "entity_variant", "id": "V-FILA", "label": "Fila", "mode": "context"}]
        result = DirectiveEngine.parse('/describe @Fila.voice', explicit_references=refs)
        matched = next(x for x in result.resolved_references if x["id"] == "V-FILA" and x.get("selector"))
        self.assertEqual(matched["selector"], "voice")

    def test_unresolved_reference_abstains_without_fake_id(self):
        result = DirectiveEngine.parse('/continue @DefinitelyNotACharacter')
        self.assertIn("@DefinitelyNotACharacter", result.unresolved_references)
        self.assertFalse(result.resolved_references)

    def test_dynamic_suggestions_are_virtual(self):
        rows = DirectiveEngine.dynamic_reference_suggestions("po", active_scene={"pov_variant_id": "V1"}, world_id="W", branch_id="B")
        self.assertEqual(rows[0]["id"], "pov")
        self.assertTrue(rows[0]["dynamic"])
        self.assertTrue(rows[0]["available"])

    def test_planner_obeys_directive_intent_and_selector(self):
        class Scope:
            explicit_references = [{"type": "entity_variant", "id": "V1", "label": "Fila", "selector": "voice"}]
            pov_variant_id = None
            world_time = None
            story_order = None
            token_budget = 1500
            context_lens = "scene"
            allow_future_author_knowledge = False
        ws = SimpleNamespace(
            scope={"directive": {
                "planner_intent": "deliberate",
                "resolved_references": [{"type": "entity_variant", "id": "V1", "label": "Fila", "selector": "voice"}],
                "dynamic_scopes": [],
            }}, auto_selected=[], explicit_references=[],
        )
        plan = NarrativeContextPlanner().plan("next?", Scope(), workspace_context=ws, route="STORY_CONTINUE")
        self.assertEqual(plan.intent, "deliberate")
        self.assertGreaterEqual(plan.dimensions["relationships"], 0.8)
        self.assertTrue(any(x.get("selector") == "voice" for x in plan.focus_resources))

    def _config(self, root: Path) -> RuntimeConfig:
        cfg = root / "arline.toml"
        (root / "writer_system.txt").write_text("write", encoding="utf-8")
        (root / "reasoning_guard.txt").write_text("guard", encoding="utf-8")
        cfg.write_text("""[lmstudio]\nbase_url="http://127.0.0.1:1"\nmodel="fake-model"\napi_key=""\nauto_load=false\n[writer]\nsystem_prompt_file="writer_system.txt"\n[reasoning_runtime]\nguard_prompt_file="reasoning_guard.txt"\n[deliberation]\nenabled=true\nmax_tokens=500\ntemperature=0.2\nalternatives=3\ncontext_chars=8000\n""", encoding="utf-8")
        return RuntimeConfig.load(cfg)

    def test_pov_command_sets_request_scoped_epistemic_anchor(self):
        refs = [{"type": "entity_variant", "id": "V-FILA", "label": "Fila", "mode": "context"}]
        result = DirectiveEngine.parse('/pov @Fila "stay close to her internal perspective"', explicit_references=refs)
        self.assertEqual(result.options["pov_variant_id"], "V-FILA")
        self.assertEqual(result.command["id"], "pov")

    def test_dynamic_threads_and_recent_boost_their_dimensions(self):
        class Scope:
            explicit_references = []
            pov_variant_id = None
            world_time = None
            story_order = None
            token_budget = 1600
            context_lens = "scene"
            allow_future_author_knowledge = False
        ws = SimpleNamespace(
            scope={"directive": {"version": "1.2.4a1", "dynamic_scopes": ["threads", "recent"], "resolved_references": []}},
            auto_selected=[], explicit_references=[],
        )
        plan = NarrativeContextPlanner().plan("continue", Scope(), workspace_context=ws, route="STORY_CONTINUE")
        self.assertEqual(plan.dimensions["threads"], 1.0)
        self.assertEqual(plan.dimensions["source"], 1.0)
        self.assertIn("threads", plan.optional_lanes)
        self.assertIn("fts_manuscript", plan.optional_lanes)

    def test_alternatives_count_controls_deliberator_request_and_output(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = self._config(Path(td))
            payload = '{"scene_goal":"choose","likely_beats":[],"character_intentions":[],"emotional_trajectories":[],"opportunities":[],"alternatives":["a","b","c","d","e","f"],"uncertainties":[],"constraints":[]}'
            client = _FakeClient(payload)
            out = NarrativeDeliberator(cfg).deliberate(
                client=client, model="fake-model",
                directive={"planner_intent":"deliberate","output_mode":"author_alternatives","semantic_prompt":"options","options":{"count":"5"}},
                context_plan={"intent":"deliberate"}, workspace_text="trusted", wcf_text="LOCKED", narrative_brief="brief",
            )
            self.assertEqual(out.alternatives, ["a", "b", "c", "d", "e"])
            self.assertIn('"alternatives_requested": 5', client.calls[0]["input_text"])

    def test_model_deliberation_is_soft_noncanon(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = self._config(Path(td))
            client = _FakeClient('{"scene_goal":"defuse tension","likely_beats":["Fila hesitates"],"character_intentions":["Mira wants clarity"],"emotional_trajectories":["tension softens"],"opportunities":["use silence"],"alternatives":["Mira changes topic"],"uncertainties":["reason for anger is unknown"],"constraints":["do not reveal secret"]}')
            out = NarrativeDeliberator(cfg).deliberate(client=client, model="fake-model", directive={"planner_intent":"dialogue","output_mode":"fiction","semantic_prompt":"apology"}, context_plan={"intent":"dialogue"}, workspace_text="trusted", wcf_text="LOCKED", narrative_brief="brief")
            self.assertEqual(out.status, "model")
            self.assertIn("soft_non_canon", out.render())
            self.assertIn("canon_commit: forbidden", out.render())
            self.assertEqual(out.likely_beats, ["Fila hesitates"])

    def test_deliberation_failure_fails_soft(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = self._config(Path(td))
            out = NarrativeDeliberator(cfg).deliberate(client=_FakeClient(failure=RuntimeError("offline")), model="fake-model", directive={"planner_intent":"continue","output_mode":"fiction","semantic_prompt":"continue"}, context_plan={}, workspace_text="", wcf_text="", narrative_brief="")
            self.assertEqual(out.status, "fallback")
            self.assertTrue(out.uncertainties)

    def test_discovery_spatial_installer_repairs_stale_class_composition(self):
        from src.discovery.service import DiscoveryService
        from src.discovery.general import _capture_text_general, install_general_discovery
        from src.discovery.spatial import install_spatial_discovery

        original = DiscoveryService.capture_text
        try:
            DiscoveryService.capture_text = _capture_text_general
            install_general_discovery()
            install_spatial_discovery()
            repaired = DiscoveryService.capture_text
            self.assertTrue(getattr(repaired, "_arline_spatial_discovery", False))
            self.assertIs(getattr(repaired, "_arline_capture_base", None), _capture_text_general)
        finally:
            DiscoveryService.capture_text = original

    def test_source_integration_contracts(self):
        service = Path("src/service/arline_service.py").read_text(encoding="utf-8")
        streaming = Path("src/service/streaming.py").read_text(encoding="utf-8")
        rails = Path("src/service/v121_rails.py").read_text(encoding="utf-8")
        app = Path("src/interface/web/app.py").read_text(encoding="utf-8")
        self.assertIn("<NARRATIVE_DELIBERATION>", service)
        self.assertIn("self.deliberator.deliberate", service)
        self.assertIn("deliberation=deliberation", service)
        self.assertIn("deliberation=deliberation", rails)
        self.assertIn("deliberation = await asyncio.to_thread", streaming)
        self.assertIn('"command_registry_version"', app)
        self.assertIn('"reference_selectors"', app)
        self.assertIn('pov_variant_id=directive_pov or payload.pov_variant_id', app)

    def test_frontend_has_remote_commands_dynamic_refs_and_intuition_panel(self):
        js = Path("src/interface/web/static/arline.js").read_text(encoding="utf-8")
        html = Path("src/interface/web/static/index.html").read_text(encoding="utf-8")
        commands = Path("src/interface/web/static/js/commands.js").read_text(encoding="utf-8")
        self.assertIn("loadCommandRegistry", js)
        self.assertIn("referenceSelectors", js)
        self.assertIn("item.dynamic", js)
        self.assertIn("deliberationOutput", html)
        self.assertIn('/intuition', commands)
        self.assertIn('/alternatives', commands)
