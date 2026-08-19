from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"anchor missing in {path}: {old[:140]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# A FORM created from a transition is a transition form even when it is the
# first persisted form snapshot for this identity.
patch(
    "src/discovery/continuity.py",
    '                    parent["id"] if parent else None, "state_transition" if parent else "baseline_observed",\n',
    '                    parent["id"] if parent else None, "state_transition",\n',
)

# Every story-change event explicitly exposes both sides of the state delta.
patch(
    "src/discovery/continuity.py",
    '''                        if event is not None:\n                            link_id = "CAUSE-" + sha256(\n''',
    '''                        if event is not None:\n                            self.store.link_event_effect(\n                                event["id"], previous["id"], subject_key=previous["subject_key"],\n                                predicate=previous["predicate"], role="before",\n                            )\n                            self.store.link_event_effect(\n                                event["id"], current["id"], subject_key=current["subject_key"],\n                                predicate=current["predicate"], role="after",\n                            )\n                            link_id = "CAUSE-" + sha256(\n''',
)

# Explicit user classification of a conflict as a story-world change must
# produce the same derived event/effect/causality/form model as automatic
# transition recognition. Corrections intentionally remain record repair only.
patch(
    "src/discovery/continuity.py",
    '''            self._insert_edge(\n                previous=previous, current=current, kind=action, session=session,\n                turn_id=conflict.get("source_turn_id") or "user_resolution",\n                source_kind="user_continuity_resolution", story_order=None, world_time=None,\n            )\n            with self.store._lock, self.store.connection() as con:\n''',
    '''            target_instances = self.store.list_instances(current["id"], active=True)\n            target_instance = max(target_instances, key=self._instance_order) if target_instances else {}\n            resolved_turn_id = str(target_instance.get("source_turn_id") or conflict.get("source_turn_id") or "user_resolution")\n            resolved_story_order = target_instance.get("story_order")\n            resolved_world_time = target_instance.get("world_time")\n            self._insert_edge(\n                previous=previous, current=current, kind=action, session=session,\n                turn_id=resolved_turn_id, source_kind="user_continuity_resolution",\n                story_order=resolved_story_order, world_time=resolved_world_time,\n            )\n            if action == "story_change":\n                event = self.store.upsert_continuity_event(\n                    project_id=session.get("project_id"), world_id=session.get("world_id"),\n                    branch_id=session.get("branch_id"), session_id=session.get("id"),\n                    source_turn_id=resolved_turn_id, source_kind="user_continuity_resolution",\n                    event_type="user_story_change",\n                    summary=note.strip() or f"{current.get('subject_label') or current['subject_key']} changed {current['predicate']}",\n                    story_order=resolved_story_order, world_time=resolved_world_time,\n                    stable_seed=[conflict_id, previous["id"], current["id"], "user_story_change"],\n                )\n                self.store.link_event_effect(\n                    event["id"], previous["id"], subject_key=previous["subject_key"],\n                    predicate=previous["predicate"], role="before",\n                )\n                self.store.link_event_effect(\n                    event["id"], current["id"], subject_key=current["subject_key"],\n                    predicate=current["predicate"], role="after",\n                )\n                causal_id = "CAUSE-" + sha256(\n                    dumps([event["id"], previous["id"], current["id"], "user_story_change"]).encode("utf-8")\n                ).hexdigest()[:16].upper()\n                with self.store._lock, self.store.connection() as con:\n                    con.execute(\n                        "INSERT OR IGNORE INTO continuity_causal_links(id,event_id,subject_key,predicate,"\n                        "from_proposition_id,to_proposition_id,kind,created_at) VALUES(?,?,?,?,?,?,?,?)",\n                        (causal_id, event["id"], current["subject_key"], current["predicate"],\n                         previous["id"], current["id"], "user_story_change", utc_now()),\n                    )\n                if current.get("subject_type") == "character" and str(current.get("predicate") or "").startswith("state."):\n                    context = MemoryQueryContext(\n                        project_id=session.get("project_id"), world_id=session.get("world_id"),\n                        branch_id=session.get("branch_id"), session_id=session.get("id"),\n                        current_turn_id=resolved_turn_id, world_time=resolved_world_time,\n                        story_order=resolved_story_order, context_lens="scene", retrieval_mode="continuity",\n                    )\n                    self._build_form(\n                        subject_key=current["subject_key"],\n                        subject_label=current.get("subject_label") or current["subject_key"],\n                        anchor_prop_id=current["id"], context=context, session=session,\n                        turn_id=resolved_turn_id, source_kind="user_continuity_resolution",\n                        story_order=resolved_story_order, world_time=resolved_world_time,\n                    )\n            with self.store._lock, self.store.connection() as con:\n''',
)

# Automatic transitions must expose before/after effects, not only causal IDs.
patch(
    "tests/test_v122_topdown_completion.py",
    '''            self.assertEqual(events[0]["causal_links"][0]["from_proposition_id"], p1["id"])\n            self.assertEqual(events[0]["causal_links"][0]["to_proposition_id"], p2["id"])\n\n    def test_resource_view_contains_one_continuity_projection(self):\n''',
    '''            self.assertEqual(events[0]["causal_links"][0]["from_proposition_id"], p1["id"])\n            self.assertEqual(events[0]["causal_links"][0]["to_proposition_id"], p2["id"])\n            roles = {(item["role"], item["proposition_id"]) for item in events[0]["effects"]}\n            self.assertIn(("before", p1["id"]), roles)\n            self.assertIn(("after", p2["id"]), roles)\n\n    def test_manual_story_change_resolution_builds_same_causal_model(self):\n        with tempfile.TemporaryDirectory() as td:\n            fx = Fixture(td)\n            t1 = fx.turn("Alex's form is human.", "manual-1")\n            t2 = fx.turn("Alex's form is wolf.", "manual-2")\n\n            def state_claim(turn, value, rev):\n                prop = fx.discovery.store.upsert_proposition(\n                    project_id=fx.project["id"], world_id=fx.world_id, subject_type="character",\n                    subject_key="char:alex", subject_label="Alex", predicate="state.form",\n                    value=value, operation="update", temporal_state="current_or_unspecified",\n                )\n                fx.discovery.store.add_instance(\n                    prop["id"], source_kind="user_prompt", source_session_id=fx.session["id"],\n                    source_turn_id=turn["id"], origin_session_id=fx.session["id"], origin_turn_id=turn["id"],\n                    source_revision=rev, project_id=fx.project["id"], world_id=fx.world_id,\n                    branch_id=fx.branch["id"], span_text=turn["user_prompt"], extraction_confidence=1,\n                    explicitness="explicit", qualifies_review=True,\n                )\n                return prop\n\n            before = state_claim(t1, "human", "MAN-A")\n            after = state_claim(t2, "wolf", "MAN-B")\n            fx.discovery.continuity.resolve_turn(t2["id"])\n            conflict = next(\n                item for item in fx.discovery.continuity.list_conflicts(fx.context(), subject_key="char:alex")\n                if {item["left_proposition_id"], item["right_proposition_id"]} == {before["id"], after["id"]}\n            )\n            fx.discovery.continuity.resolve_conflict(\n                conflict["id"], action="story_change",\n                from_proposition_id=before["id"], to_proposition_id=after["id"],\n                note="Alex transformed into wolf form",\n            )\n            events = fx.discovery.continuity.list_events(fx.context(), subject_key="char:alex")\n            event = next(item for item in events if item["event_type"] == "user_story_change")\n            roles = {(item["role"], item["proposition_id"]) for item in event["effects"]}\n            self.assertEqual(roles, {("before", before["id"]), ("after", after["id"])})\n            self.assertEqual(event["causal_links"][0]["from_proposition_id"], before["id"])\n            self.assertEqual(event["causal_links"][0]["to_proposition_id"], after["id"])\n            forms = fx.discovery.continuity.list_forms(fx.context(), subject_key="char:alex")\n            self.assertTrue(any(item["anchor_proposition_id"] == after["id"] and item["reason"] == "state_transition" for item in forms))\n            self.assertEqual(fx.discovery.store.get_proposition(after["id"])["authority_state"], "observed")\n\n    def test_resource_view_contains_one_continuity_projection(self):\n''',
)

# Keep the milestone document precise about explicit before/after effects.
patch(
    "docs/V12_IMPLEMENTATION_STATUS.md",
    "- state transitions create or reuse `EVENT-*` records and connect visible before/after propositions through causal links;\n",
    "- state transitions create or reuse `EVENT-*` records, expose explicit before/after event effects, and connect the propositions through causal links;\n",
)
patch(
    "docs/V122_NARRATIVE_CONTINUITY.md",
    "`EVENT-*` records and effect links; continuity supersession then joins the\nvisible before/after propositions through `CAUSE-*` links. Deterministic\n",
    "`EVENT-*` records with explicit `before`/`after` effects; continuity supersession then joins the\nvisible propositions through `CAUSE-*` links. Explicit user conflict resolution as a story change uses the same causal model. Deterministic\n",
)

print("v1.2.2 causality symmetry patch applied")
