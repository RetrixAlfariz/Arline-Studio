from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import re
import unittest

from fastapi.testclient import TestClient

from src.history.store import HistoryStore
from src.interface.web.app import RuntimePayload, _apply_payload, _conversation_contract, _public_config, create_app
from src.conversation import extract_blueprint, recipe_for_mode, resolve_presence, story_lab_prose_intent_warnings, story_lab_requests_prose, validate_user_agency
from src.profile import build_personalization_context, extract_profile_draft, normalize_user_profile, resolve_preferred_name
from src.runtime_config import RuntimeConfig
from src.service.arline_service import ArlineService


ROOT = Path(__file__).resolve().parents[1]


class ConversationModeTests(unittest.TestCase):
    def test_runtime_payload_keeps_configured_model_when_override_is_blank(self):
        config = RuntimeConfig.load(ROOT / "config/arline.toml")
        configured_model = config.lmstudio.model
        applied = _apply_payload(config, RuntimePayload())
        self.assertEqual(applied.lmstudio.model, configured_model)

    def test_planning_override_is_independent_of_reasoning_and_preserves_auto(self):
        for saved, mode, reasoning, expected in [
            (False, "auto", "on", False),
            (True, "auto", "off", True),
            (False, "on", "off", True),
            (True, "off", "on", False),
        ]:
            with self.subTest(saved=saved, mode=mode, reasoning=reasoning):
                config = RuntimeConfig.load(ROOT / "config/arline.toml")
                config.deliberation.enabled = saved
                applied = _apply_payload(config, RuntimePayload(deliberation_mode=mode, reasoning=reasoning))
                self.assertEqual(applied.deliberation.enabled, expected)
                self.assertEqual(applied.generation.reasoning, reasoning)
                self.assertEqual(_public_config(applied)["planning_enabled"], expected)

    def test_invalid_planning_override_is_rejected(self):
        with self.assertRaises(ValueError):
            RuntimePayload(deliberation_mode="invalid")

    def test_preferred_name_rules_and_personal_memory_policy_migrate(self):
        legacy = normalize_user_profile({
            "display_name": "Vian",
            "personal_details": {
                "preferred_name": {"value": "Vian", "visibility": "collaboration"},
                "birth_date": {"value": "2007-07-24", "visibility": "private"},
                "skills": {"value": "Voice acting", "visibility": "collaboration"},
            },
            "memory_policy": {"creative_preferences": True, "reusable_personas": False},
        })
        self.assertEqual(legacy["preferred_names"][0]["value"], "Vian")
        self.assertTrue(legacy["memory_policy"]["categories"]["collaboration_preferences"]["enabled"])
        self.assertFalse(legacy["memory_policy"]["categories"]["story_presence"]["enabled"])

        legacy["preferred_names"] = [
            {"id": "primary", "value": "Vian", "context": "default", "primary": True},
            {"id": "formal", "value": "Revian", "context": "formal", "primary": False},
            {"id": "casual", "value": "Vi", "context": "casual", "primary": False},
        ]
        self.assertEqual(resolve_preferred_name(legacy, "formal"), "Revian")
        self.assertEqual(resolve_preferred_name(legacy, "casual"), "Vi")
        context = build_personalization_context(legacy, "story_lab")
        self.assertEqual(context["preferred_name"], "Vi")
        self.assertEqual(context["personal_details"]["skills"], "Voice acting")
        self.assertNotIn("birth_date", context["personal_details"])

        legacy["collaboration"]["partner_name"] = "  Opheline\nWriter  "
        context = build_personalization_context(legacy, "story_lab")
        self.assertEqual(context["partner_name"], "Opheline Writer")
        contract = _conversation_contract("story_lab", {"personalization_context": context})
        self.assertIn('Assistant alias: "Opheline Writer"', contract)
        self.assertIn("resolve it as addressing you", contract)
        self.assertIn("Do not treat it as a story entity", contract)

        legacy["memory_policy"]["behavior"]["forget_inactive_days"] = 0
        self.assertEqual(normalize_user_profile(legacy)["memory_policy"]["behavior"]["forget_inactive_days"], 0)

        legacy["memory_policy"]["enabled"] = False
        self.assertEqual(build_personalization_context(legacy, "story_lab"), {"memory_enabled": False, "learn_from_chat": False, "partner_name": "Opheline Writer"})

    def test_mode_profile_events_and_forks_persist(self):
        with TemporaryDirectory() as directory:
            store = HistoryStore(Path(directory) / "history.db", backup_before_migration=False)
            session = store.create_session(
                prompt="Explore this premise",
                conversation_mode="story_lab",
                conversation_profile={"exploration": "open", "presence": {"mode": "self"}},
            )
            changed = store.update_session(
                session["id"],
                conversation_mode="interactive",
                conversation_profile={
                    "presence": {"mode": "self", "display_name": "Vian"},
                    "perspective": {"style": "first"},
                },
            )
            fork = store.fork_session(session["id"])

            self.assertEqual(changed["conversation_mode"], "interactive")
            self.assertEqual(changed["mode_events"][0]["from"], "story_lab")
            self.assertEqual(changed["mode_events"][0]["to"], "interactive")
            self.assertEqual(fork["conversation_profile"]["presence"]["display_name"], "Vian")
            self.assertEqual(fork["conversation_mode"], "interactive")

    def test_interactive_contract_protects_user_agency_and_pronouns(self):
        contract = _conversation_contract(
            "interactive",
            {
                "presence": {"mode": "self", "display_name": "Vian"},
                "perspective": {"style": "first"},
            },
        )
        self.assertIn("Resolve first-person pronouns", contract)
        self.assertIn("Never invent major voluntary user actions", contract)
        self.assertIn('"display_name": "Vian"', contract)

    def test_story_lab_defaults_to_discussion_and_requires_explicit_prose_intent(self):
        self.assertFalse(story_lab_requests_prose("Why would the protagonist distrust her sister?"))
        self.assertFalse(story_lab_requests_prose("Help me design their relationship"))
        self.assertTrue(story_lab_requests_prose("Write a scene where the sisters confront each other"))
        self.assertTrue(story_lab_requests_prose("Tolong tuliskan adegan pertengkaran mereka"))
        self.assertTrue(story_lab_requests_prose("/continue @scene"))
        self.assertTrue(story_lab_prose_intent_warnings(
            "Write a short scene where Mira opens the door.",
            "Okay, so let's look at the scene you want.",
        ))
        self.assertFalse(story_lab_prose_intent_warnings(
            "Write a short scene where Mira opens the door.",
            "The latch gave beneath Mira's thumb. Cold air entered first.",
        ))

        service = object.__new__(ArlineService)
        bundle = SimpleNamespace(directive=None)
        discussion = service.compose_model_input(
            "Why would the protagonist distrust her sister?", bundle, "raw",
            conversation_mode="story_lab",
        )
        prose = service.compose_model_input(
            "Write a scene where the sisters confront each other", bundle, "raw",
            conversation_mode="story_lab",
        )
        self.assertIn("natural, collaborative story-development partner", discussion)
        self.assertIn("do not narrate a scene", discussion)
        self.assertIn("Do not expose internal context labels", discussion)
        self.assertIn("Do not produce headings", discussion)
        self.assertNotIn("Write the requested fiction", discussion)
        self.assertIn("Output only the fiction itself", prose)

    def test_user_profile_is_separate_from_library_entities(self):
        with TemporaryDirectory() as directory:
            store = HistoryStore(Path(directory) / "history.db", backup_before_migration=False)
            profile = store.save_user_profile({
                "display_name": "Vian",
                "about": "Technical storyteller",
                "creative_profile": {"tone": "mixed"},
                "collaboration": {"challenge_level": "balanced"},
                "presence_defaults": {"mode": "observer"},
                "story_lab": {"exploration": "open"},
                "boundaries": {"avoid": ["chosen-one framing"]},
                "memory_policy": {"reusable_personas": False},
            })
            self.assertEqual(store.get_user_profile()["display_name"], "Vian")
            self.assertNotIn("entity_id", profile)

    def test_profile_text_extracts_editable_identity_and_sensitive_fields(self):
        draft = extract_profile_draft(
            "Namaku **Revian Alfariz**, tapi biasanya aku cukup dipanggil **Vian**. "
            "Aku lahir pada **24 Juli 2007** dan memiliki tinggi sekitar **165 cm**. "
            "Secara fisik, bentuk tubuhku cenderung feminin dengan rambut pendek. "
            "Aku juga memiliki bentuk dada sekitar **E cup**. "
            "Di kampus aku memakai pakaian yang menyamarkan bentuk tubuhku. "
            "Aku berbakat dalam **voice acting** dan memiliki kontrol suara yang luas."
        )
        fields = {field["key"]: field for field in draft["fields"]}
        self.assertEqual(draft["display_name"], "Vian")
        self.assertEqual(fields["full_name"]["value"], "Revian Alfariz")
        self.assertEqual(fields["birth_date"]["value"], "2007-07-24")
        self.assertEqual(fields["height_cm"]["value"], "165")
        self.assertEqual(fields["sensitive_details"]["visibility"], "private")
        self.assertTrue(fields["sensitive_details"]["sensitive"])
        self.assertIn("voice acting", fields["skills"]["value"])

    def test_user_profile_can_explicitly_link_a_library_variant(self):
        with TemporaryDirectory() as directory:
            store = HistoryStore(Path(directory) / "history.db", backup_before_migration=False)
            saved = store.save_user_profile({
                "display_name": "Vian", "about": "Technical storyteller",
                "creative_profile": {}, "collaboration": {}, "story_lab": {},
                "boundaries": {}, "memory_policy": {},
                "presence_defaults": {
                    "mode": "linked_entity", "identity_source": "self_entity",
                    "entity_family_id": "FAM-SELF", "entity_variant_id": "VAR-SELF",
                },
            })
            self.assertEqual(saved["presence_defaults"]["entity_variant_id"], "VAR-SELF")
            self.assertEqual(store.get_user_profile()["presence_defaults"]["identity_source"], "self_entity")

    def test_presence_bindings_are_scoped_and_do_not_leak(self):
        with TemporaryDirectory() as directory:
            store = HistoryStore(Path(directory) / "history.db", backup_before_migration=False)
            store.save_presence_binding("world", "WORLD-1", {"presence": {"display_name": "World Vian"}})
            store.save_presence_binding("branch", "BRANCH-1", {"presence": {"display_name": "Branch Vian"}})
            self.assertEqual(store.get_presence_binding("world", "WORLD-1")["profile"]["presence"]["display_name"], "World Vian")
            self.assertEqual(store.get_presence_binding("branch", "BRANCH-1")["profile"]["presence"]["display_name"], "Branch Vian")
            self.assertEqual(store.get_presence_binding("branch", "BRANCH-2")["profile"], {})

    def test_blueprint_requires_explicit_language_for_wanted_and_avoid(self):
        blueprint = extract_blueprint("I want to be a cartographer; maybe know the prince; don't make me chosen royalty")
        self.assertIn("be a cartographer", blueprint["wanted"])
        self.assertIn("know the prince", blueprint["flexible"])
        self.assertIn("make me chosen royalty", blueprint["avoid"])

    def test_presence_resolver_and_agency_validator(self):
        profile = {"presence": {"mode": "self", "display_name": "Vian"}, "perspective": {"style": "first", "pov_entity_id": "VAR-1"}}
        resolved = resolve_presence(profile)
        self.assertEqual(resolved["first_person_refers_to"], "active_user_presence")
        self.assertEqual(resolved["pov_variant_id"], "VAR-1")
        warnings = validate_user_agency("You decide to accept, then you say yes.", profile)
        self.assertGreaterEqual(len(warnings), 2)
        self.assertEqual(recipe_for_mode("character_room"), "RECIPE-CHARACTER-ROOM")

    def test_personalization_can_create_and_sync_a_real_library_entity(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = (ROOT / "config/arline.toml").read_text(encoding="utf-8")
            source = source.replace("auto_load = true", "auto_load = false")
            source = re.sub(r'(?m)^database_path\s*=.*$', f'database_path = "{(root / "studio.db").as_posix()}"', source)
            source = re.sub(r'(?m)^dataset_root\s*=.*$', f'dataset_root = "{(root / "datasets").as_posix()}"', source)
            source = re.sub(r'(?m)^output_root\s*=.*$', f'output_root = "{(root / "output").as_posix()}"', source)
            source = re.sub(r'(?m)^saved_root\s*=.*$', f'saved_root = "{(root / "saved").as_posix()}"', source)
            config_path = root / "arline.toml"
            config_path.write_text(source, encoding="utf-8")
            client = TestClient(create_app(config_path))
            active = client.get("/api/workspace/bootstrap").json()["active"]
            project_id = active["project"]["id"]
            world_id = active["world"]["id"]

            saved_details = client.put("/api/user-profile", json={
                "display_name": "Vian", "about": "A technical storyteller",
                "personal_details": {"birth_date": {"value": "2007-07-24", "visibility": "private"}},
                "creative_profile": {}, "collaboration": {}, "presence_defaults": {},
                "story_lab": {}, "boundaries": {}, "memory_policy": {},
            })
            self.assertEqual(saved_details.status_code, 200, saved_details.text)
            self.assertEqual(saved_details.json()["personal_details"]["birth_date"]["visibility"], "private")

            created = client.post("/api/user-profile/entity", json={
                "project_id": project_id, "world_id": world_id,
                "name": "Vian", "about": "A technical storyteller",
                "creative_profile": {"genres": "fantasy"},
            })
            self.assertEqual(created.status_code, 200, created.text)
            variant_id = created.json()["variant"]["id"]
            profile = client.get("/api/user-profile").json()
            self.assertEqual(profile["presence_defaults"]["identity_source"], "self_entity")
            self.assertEqual(profile["presence_defaults"]["entity_variant_id"], variant_id)
            self.assertEqual(profile["personal_details"]["birth_date"]["visibility"], "private")

            synced = client.post("/api/user-profile/entity", json={
                "project_id": project_id, "world_id": world_id,
                "name": "Vian", "about": "Updated story identity",
                "creative_profile": {"genres": "fantasy"},
                "entity_variant_id": variant_id,
            })
            self.assertEqual(synced.status_code, 200, synced.text)
            self.assertEqual(synced.json()["variant"]["id"], variant_id)
            self.assertEqual(synced.json()["variant"]["summary"], "Updated story identity")

    def test_react_chat_exposes_contextual_mode_controls(self):
        chat = (ROOT / "frontend/src/views/ChatView.tsx").read_text(encoding="utf-8")
        settings = (ROOT / "frontend/src/components/SettingsDrawer.tsx").read_text(encoding="utf-8")
        for token in ("Story Writer", "Story Lab", "Interactive", "Analyst", "Character Room", "Design My Presence", "mode-transition-marker"):
            self.assertIn(token, chat)
        self.assertIn('aria-label="Context mode"', chat)
        self.assertIn("Personalization", settings)
        self.assertIn("Story Presence defaults", settings)
        for token in ("Story identity", "Use a Library entity", "Referenced character", "Create myself", "saveUserAsEntity"):
            self.assertIn(token, settings if token != "saveUserAsEntity" else (ROOT / "frontend/src/api.ts").read_text(encoding="utf-8"))
        self.assertIn('/api/user-profile/entity', (ROOT / "src/interface/web/app.py").read_text(encoding="utf-8"))
        self.assertIn('/api/user-profile/extract', (ROOT / "src/interface/web/app.py").read_text(encoding="utf-8"))
        for token in ("Import text", "Review extracted details", "Personal details", "Private physical details"):
            self.assertIn(token, settings)
        for token in ("Save as Library character", "POV entity", "Non-canon rehearsal", "Extract from prompt"):
            self.assertIn(token, chat)

    def test_story_lab_sheet_proposals_create_update_conflict_and_branch(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = (ROOT / "config/arline.toml").read_text(encoding="utf-8")
            source = source.replace("auto_load = true", "auto_load = false")
            source = re.sub(r'(?m)^database_path\s*=.*$', f'database_path = "{(root / "studio.db").as_posix()}"', source)
            source = re.sub(r'(?m)^dataset_root\s*=.*$', f'dataset_root = "{(root / "datasets").as_posix()}"', source)
            source = re.sub(r'(?m)^output_root\s*=.*$', f'output_root = "{(root / "output").as_posix()}"', source)
            source = re.sub(r'(?m)^saved_root\s*=.*$', f'saved_root = "{(root / "saved").as_posix()}"', source)
            config_path = root / "arline.toml"
            config_path.write_text(source, encoding="utf-8")
            client = TestClient(create_app(config_path))
            active = client.get("/api/workspace/bootstrap").json()["active"]
            project_id = active["project"]["id"]
            world_id = active["world"]["id"]
            branch_id = active["branch"]["id"]

            staged = client.post("/api/story-lab/sheet-proposals", json={
                "project_id": project_id, "world_id": world_id, "branch_id": branch_id,
                "kind": "character", "prompt_text": "Help me develop a character named Mira who hides fear behind humor.",
                "source_text": "Mira hides her fear behind precise humor.",
            })
            self.assertEqual(staged.status_code, 200, staged.text)
            self.assertEqual(staged.json()["proposal"]["operation"], "create")
            self.assertEqual(staged.json()["proposal"]["name"], "Mira")
            change_id = staged.json()["change"]["id"]
            accepted = client.post(f"/api/story-lab/sheet-proposals/{change_id}/apply", json={"action": "accept"})
            self.assertEqual(accepted.status_code, 200, accepted.text)
            variant = accepted.json()["resource"]
            self.assertEqual(variant["summary"], "Mira hides her fear behind precise humor.")
            self.assertEqual(accepted.json()["change"]["status"], "accepted")
            revisions = client.get(f"/api/revisions/entity_variant/{variant['id']}").json()["revisions"]
            self.assertTrue(revisions)

            alias = client.post("/api/aliases", json={
                "resource_type": "entity_family", "resource_id": variant["family_id"], "alias": "Mirabel",
            })
            self.assertEqual(alias.status_code, 200, alias.text)
            alias_match = client.post("/api/story-lab/sheet-proposals", json={
                "project_id": project_id, "world_id": world_id, "branch_id": branch_id,
                "kind": "character", "prompt_text": "Develop a character named Mirabel.",
                "source_text": "Her public confidence masks the same old fear.",
            })
            self.assertEqual(alias_match.status_code, 200, alias_match.text)
            self.assertEqual(alias_match.json()["proposal"]["operation"], "update")
            self.assertEqual(alias_match.json()["proposal"]["target_id"], variant["id"])
            rejected_alias = client.post(
                f"/api/story-lab/sheet-proposals/{alias_match.json()['change']['id']}/apply",
                json={"action": "reject"},
            )
            self.assertEqual(rejected_alias.status_code, 200, rejected_alias.text)

            update = client.post("/api/story-lab/sheet-proposals", json={
                "project_id": project_id, "world_id": world_id, "branch_id": branch_id,
                "kind": "character", "prompt_text": "Revisit the character named Mira.",
                "source_text": "Mira now uses humor to redirect suspicion.",
            })
            self.assertEqual(update.status_code, 200, update.text)
            self.assertEqual(update.json()["proposal"]["operation"], "update")
            client.patch(f"/api/entities/variants/{variant['id']}", json={"summary": "A concurrent edit", "note": "test conflict"})
            conflict = client.post(
                f"/api/story-lab/sheet-proposals/{update.json()['change']['id']}/apply",
                json={"action": "accept"},
            )
            self.assertEqual(conflict.status_code, 409, conflict.text)

            plot = client.post("/api/story-lab/sheet-proposals", json={
                "project_id": project_id, "world_id": world_id, "branch_id": branch_id,
                "kind": "plot", "prompt_text": "Outline a plot where a glass bargain reveals a hidden heir.",
                "source_text": "The bargain succeeds, but exposes the hidden heir.",
            })
            self.assertEqual(plot.json()["proposal"]["name"], "Glass Bargain Reveals a Hidden Heir")
            branched = client.post(
                f"/api/story-lab/sheet-proposals/{plot.json()['change']['id']}/apply",
                json={"action": "branch", "branch_name": "glass-bargain-experiment"},
            )
            self.assertEqual(branched.status_code, 200, branched.text)
            self.assertEqual(branched.json()["resource"]["branch_id"], branched.json()["branch"]["id"])
            self.assertNotEqual(branched.json()["resource"]["branch_id"], branch_id)

            unnamed = client.post("/api/story-lab/sheet-proposals", json={
                "project_id": project_id, "world_id": world_id, "branch_id": branch_id,
                "kind": "character", "prompt_text": "Explore a character named Fano and his sister.",
                "source_text": "Fano trusts his sister, but she remains deliberately undefined.",
            })
            self.assertEqual(unnamed.status_code, 200, unnamed.text)
            unnamed_items = unnamed.json()["items"]
            self.assertEqual([(item["proposal"]["kind"], item["proposal"]["name"]) for item in unnamed_items], [("character", "Fano")])
            create_fano = client.post("/api/story-lab/sheet-proposal-bundles/apply", json={
                "action": "accept",
                "items": [{"change_id": item["change"]["id"], "proposal": item["proposal"], "selected": True} for item in unnamed_items],
            })
            self.assertEqual(create_fano.status_code, 200, create_fano.text)

            named_later = client.post("/api/story-lab/sheet-proposals", json={
                "project_id": project_id, "world_id": world_id, "branch_id": branch_id,
                "kind": "character", "prompt_text": "His sister is named Fila.",
                "source_text": "Fano's sister Fila challenges his caution.",
            })
            self.assertEqual(named_later.status_code, 200, named_later.text)
            later_items = named_later.json()["items"]
            later_characters = {item["proposal"]["name"] for item in later_items if item["proposal"]["kind"] == "character"}
            self.assertEqual(later_characters, {"Fano", "Fila"})
            self.assertTrue(any(item["proposal"].get("relation_type") == "sibling" for item in later_items))
            reject_later = client.post("/api/story-lab/sheet-proposal-bundles/apply", json={
                "action": "reject",
                "items": [{"change_id": item["change"]["id"], "proposal": item["proposal"], "selected": True} for item in later_items],
            })
            self.assertEqual(reject_later.status_code, 200, reject_later.text)

            bundle = client.post("/api/story-lab/sheet-proposals", json={
                "project_id": project_id, "world_id": world_id, "branch_id": branch_id,
                "kind": "character",
                "prompt_text": "Develop a character named Fano and his sister named Fila. They live in a city named Aster Hollow.",
                "source_text": "Fano and Fila protect each other while Aster Hollow tests their loyalty.",
            })
            self.assertEqual(bundle.status_code, 200, bundle.text)
            items = bundle.json()["items"]
            entity_keys = {(item["proposal"]["kind"], item["proposal"]["name"]) for item in items}
            self.assertIn(("character", "Fano"), entity_keys)
            self.assertIn(("character", "Fila"), entity_keys)
            self.assertIn(("location", "Aster Hollow"), entity_keys)
            relationships = [item for item in items if item["proposal"]["kind"] == "relationship"]
            self.assertTrue(any(item["proposal"]["relation_type"] == "sibling" for item in relationships))
            self.assertTrue(any(item["proposal"]["relation_type"] == "lives_in" for item in relationships))
            applied = client.post("/api/story-lab/sheet-proposal-bundles/apply", json={
                "action": "accept",
                "items": [{"change_id": item["change"]["id"], "proposal": item["proposal"], "selected": True} for item in items],
            })
            self.assertEqual(applied.status_code, 200, applied.text)
            families = client.get("/api/entities/families").json()["families"]
            by_name = {item["name"]: item for item in families}
            self.assertNotEqual(by_name["Fano"]["id"], by_name["Fila"]["id"])
            self.assertEqual(by_name["Aster Hollow"]["entity_type"], "location")
            linked = client.get("/api/relationships", params={"world_id": world_id}).json()["relationships"]
            self.assertGreaterEqual(len(linked), 3)

        chat = (ROOT / "frontend/src/views/ChatView.tsx").read_text(encoding="utf-8")
        for token in ("Propose sheet", "Accept change", "Save to branch", "Current sheet", "Proposed content"):
            self.assertIn(token, chat)
        self.assertIn("Close and reject sheet proposal", chat)
        self.assertIn("Manuscript outline", chat)


if __name__ == "__main__":
    unittest.main()
