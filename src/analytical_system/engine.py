from __future__ import annotations

from .inference_graph import Graph


class AnalyticalReasoner:
    VERSION = "0.3.3"

    @classmethod
    def default(cls):
        return cls()

    def analyze(self, state, events, transitions, world, scenario=None):
        scenario = scenario or {"requested_events": [], "scene_focus": {}}
        graph = Graph()
        derived, constraints, interactions, consequences = [], [], [], []
        blocked, uncertainties = [], []
        entities = {e["id"]: e for e in world.get("entities", [])}
        char = next(
            (
                e["id"] for e in world.get("entities", [])
                if e.get("type") == "character" and e.get("label") not in {"fano", "self_mother", "fano_mother"}
            ),
            "char:self",
        )
        A = entities.get(char, {}).get("attributes", {})
        focus = scenario.get("scene_focus", {}) or {}

        def fact(path, label=None):
            cur = A
            for p in path.split("."):
                if not isinstance(cur, dict) or p not in cur:
                    return None
                cur = cur[p]
            if not isinstance(cur, dict) or "value" not in cur:
                return None
            node = graph.add(
                "fact",
                label or path.replace(".", "_"),
                cur.get("confidence", .9),
                source_facts=[f"{char}.{path}"],
                metadata={"value": cur.get("value"), "epistemic": cur.get("epistemic", "explicit")},
            )
            return cur, node

        def add_derived(name, value, confidence, parents, *, tags=None, writer_relevant=False, metadata=None):
            node = graph.add("derived_fact", name, confidence, parents, metadata=metadata or {})
            derived.append({
                "name": name,
                "value": value,
                "confidence": round(confidence, 4),
                "focus_tags": tags or [],
                "writer_relevant": writer_relevant,
                "graph_node": node,
            })
            return node

        def add_consequence(event_id, effect, domain, confidence, salience, parents, *, policy="imply", tags=None, why=None, avoid=None, novelty=1.0):
            node = graph.add("consequence", effect, confidence, parents)
            consequences.append({
                "event_id": event_id,
                "effect": effect,
                "domain": domain,
                "confidence": round(confidence, 4),
                "salience": salience,
                "surface_policy": policy,
                "focus_tags": tags or [],
                "why_relevant": why or [],
                "avoid": avoid or [],
                "novelty": novelty,
                "graph_node": node,
            })
            return node

        # ------------------------------------------------------------------
        # Physical static derivation.
        # ------------------------------------------------------------------
        h = fact("physical.height_cm", "character_height")
        if h:
            hf, hn = h
            conf = hf["confidence"] * .78
            add_derived(
                "estimated_comfortable_reach_cm", round(hf["value"] * 1.15, 2), conf, [hn],
                tags=["reach", "spatial"], writer_relevant=False,
            )
            add_derived(
                "estimated_max_flat_foot_reach_cm", round(hf["value"] * 1.24, 2), conf, [hn],
                tags=["reach", "spatial"], writer_relevant=False,
            )

        fem = fact("physical.morphology.presentation", "feminine_body_morphology")
        cup = fact("physical.chest.reference_cup", "chest_size_reference")
        fem_profile = None
        if fem and cup:
            conf = min(fem[0]["confidence"], cup[0]["confidence"]) * .93
            fem_profile = add_derived(
                "feminine_body_profile_high", True, conf, [fem[1], cup[1]],
                tags=["appearance", "physical_detail", "clothing_fit"], writer_relevant=True,
            )

        # Story-world endocrine consistency: this is internal fictional consistency,
        # not a real-world medical claim.
        endocrine = fact("endocrine.feminizing_hormone_production", "feminizing_hormone_production_asserted")
        growth = fact("physical.chest.growth_profile", "female_like_chest_growth_asserted")
        if endocrine and growth:
            mech = graph.add(
                "mechanism", "feminizing_development_mechanism_available",
                endocrine[0]["confidence"] * .9, [endocrine[1]],
                metadata={"scope": "story_world_internal_consistency"},
            )
            add_derived(
                "female_like_chest_growth_world_consistent", True,
                min(endocrine[0]["confidence"], growth[0]["confidence"]) * .9,
                [mech, growth[1]], tags=["physical_detail", "character"], writer_relevant=False,
                metadata={"scope": "story_world_internal_consistency"},
            )

        soft = fact("physical.chest.softness", "chest_softness")
        compliance = fact("physical.chest.compliance", "chest_compliance")
        if soft:
            parents = [soft[1]] + ([compliance[1]] if compliance else [])
            add_derived(
                "soft_compliant_chest_tissue", True,
                min([soft[0]["confidence"]] + ([compliance[0]["confidence"]] if compliance else [])) * .9,
                parents,
                tags=["physical_detail", "clothing_fit", "bodily_sensation"],
                writer_relevant=bool(focus.get("physical_detail") or focus.get("clothing")),
            )

        hair_rel = fact("hair.current.length_relative", "hair_length_relative")
        hair_cm = fact("hair.current.length_cm", "hair_length_cm")
        hair_long_node = None
        if hair_rel:
            value = hair_rel[0]["value"]
            anchor = value.get("anchor") if isinstance(value, dict) else value
            if anchor in {"waist", "pinggang", "back", "punggung"}:
                hair_long_node = add_derived(
                    "very_long_hair_body_relative", True, hair_rel[0]["confidence"] * .94, [hair_rel[1]],
                    tags=["appearance", "hair", "physical_detail"], writer_relevant=True,
                    metadata={"anchor": anchor},
                )
                mech = graph.add("mechanism", "large_free_moving_hair_segment", .84, [hair_long_node])
                add_derived(
                    "high_hair_motion_lag", True, .82, [mech],
                    tags=["hair", "motion"], writer_relevant=False,
                )
        elif hair_cm and hair_cm[0]["value"] >= 75:
            hair_long_node = add_derived(
                "very_long_hair", True, hair_cm[0]["confidence"] * .93, [hair_cm[1]],
                tags=["appearance", "hair", "physical_detail"], writer_relevant=True,
            )

        # ------------------------------------------------------------------
        # Garment static properties.
        # ------------------------------------------------------------------
        garment_nodes = {}
        for eid, entity in entities.items():
            if entity.get("type") != "garment":
                continue
            attrs = entity.get("attributes", {})
            family = entity.get("attributes", {}).get("ontology", {}).get("garment_family")
            material = attrs.get("material")
            flow = attrs.get("flowiness")
            front = attrs.get("front_length")
            back = attrs.get("back_length")
            length = attrs.get("length") or attrs.get("length_cm")

            nodes = garment_nodes.setdefault(eid, {})
            if material and isinstance(material, dict) and "value" in material:
                mn = graph.add("fact", f"{eid}_material", material.get("confidence", .9), source_facts=[f"{eid}.material"], metadata={"value": material["value"]})
                nodes["material"] = mn
                mat = str(material["value"]).lower()
                if mat in {"jersey", "rayon", "satin", "silk", "sutra"}:
                    mech = graph.add("mechanism", f"{eid}_soft_drape_mechanism", material.get("confidence", .9) * .88, [mn], metadata={"material": mat})
                    nodes["drape"] = add_derived(
                        f"{eid}.soft_flexible_drape", True, material.get("confidence", .9) * .86, [mech],
                        tags=["clothing", "garment_motion", "physical_detail"], writer_relevant=True,
                    )
            if flow and isinstance(flow, dict) and flow.get("value") == "high":
                fn = graph.add("fact", f"{eid}_flowiness_high", flow.get("confidence", .9), source_facts=[f"{eid}.flowiness"])
                nodes["flow"] = add_derived(
                    f"{eid}.flowy_behavior_high", True, flow.get("confidence", .9) * .93, [fn],
                    tags=["clothing", "garment_motion", "atmosphere"], writer_relevant=True,
                )
            if front and back and isinstance(front, dict) and isinstance(back, dict):
                fv, bv = front.get("value"), back.get("value")
                try:
                    fnum = float(fv.get("value")) if isinstance(fv, dict) else float(fv)
                    bnum = float(bv.get("value")) if isinstance(bv, dict) else float(bv)
                except Exception:
                    fnum = bnum = 0
                if bnum > fnum:
                    p1 = graph.add("fact", f"{eid}_front_length", front.get("confidence", .9), metadata={"value": fv})
                    p2 = graph.add("fact", f"{eid}_back_length", back.get("confidence", .9), metadata={"value": bv})
                    add_derived(
                        f"{eid}.asymmetric_front_back_drape", True, min(front.get("confidence", .9), back.get("confidence", .9)) * .92, [p1, p2],
                        tags=["clothing", "appearance"], writer_relevant=True,
                    )
            if length and isinstance(length, dict):
                val = length.get("value")
                if isinstance(val, dict) and val.get("frame") == "garment_length":
                    # no floor clearance without measurement basis / body landmark reference
                    blocked.append({
                        "candidate": f"{eid}.hem_clearance_from_floor",
                        "status": "blocked",
                        "reason": "garment length exists but body-relative measurement basis is insufficient",
                        "source_facts": [f"{eid}.length"],
                    })

        # Explicit garment/body fit compatibility.
        fit_relations = [r for r in world.get("relations", []) if r.get("predicate") == "garment.fits" and r.get("object") == char]
        for r in fit_relations:
            rn = graph.add("relation", "garment_fits_character", r.get("confidence", .9), metadata={"garment": r.get("subject"), "level": r.get("value")})
            parents = [rn] + ([fem_profile] if fem_profile else [])
            fitn = add_derived(
                "garment_body_fit_compatibility_high", True, r.get("confidence", .9) * .94, parents,
                tags=["clothing_fit", "appearance"], writer_relevant=True,
                metadata={"garment": r.get("subject")},
            )
            add_consequence(
                "context", "clothing_fit_is_scene_salient", "fit", .9, .78, [fitn],
                tags=["clothing_fit", "appearance"],
                why=["the prompt explicitly states that the clothing fits very well"],
                avoid=["do not restate raw body specifications unless needed"], novelty=.8,
            )

        # ------------------------------------------------------------------
        # Experience / familiarity.
        # ------------------------------------------------------------------
        familiarity_node = None
        seen_familiarity = False
        for exp in world.get("experience", []):
            pred = exp.get("predicate")
            value = exp.get("value")
            en = graph.add("experience", pred.replace(".", "_"), exp.get("confidence", .9), metadata={"value": value})
            if pred in {"experience.feminine_presentation", "experience.current_presentation"}:
                familiar = False
                novelty = None
                if isinstance(value, dict):
                    familiar = value.get("familiarity") == "high" or value.get("prior_occurrence") is True or value.get("frequency") in {"repeated", "frequent"}
                    novelty = value.get("novelty")
                if familiar and not seen_familiarity:
                    seen_familiarity = True
                    familiarity_node = add_derived(
                        "feminine_presentation_familiarity_high", True, exp.get("confidence", .9) * .94, [en],
                        tags=["familiarity", "appearance", "clothing"], writer_relevant=True,
                    )
                    add_derived(
                        "feminine_presentation_novelty_low", True, exp.get("confidence", .9) * .91, [en],
                        tags=["familiarity", "novelty"], writer_relevant=True,
                    )
                    add_consequence(
                        "context", "feminine_presentation_is_familiar", "experience", .91, .82, [familiarity_node],
                        tags=["familiarity", "appearance"],
                        why=["prior feminine-presenting outings are established"],
                        avoid=["do not frame ordinary feminine presentation as a first-time shock"],
                        novelty=.65,
                    )

        # ------------------------------------------------------------------
        # Relationship and social reasoning.
        # ------------------------------------------------------------------
        rels = world.get("relations", [])
        dating = [r for r in rels if r.get("predicate") == "relationship.dating" and r.get("value") is not False]
        historical_friend = [r for r in rels if r.get("predicate") == "relationship.friend_of" and r.get("temporal_scope") in {"historical", "unspecified"}]
        if dating:
            dn = graph.add("relation", "dating_relationship_current", max(r.get("confidence", .9) for r in dating), metadata={"participants": [char, "char:fano"]})
            add_derived(
                "romantic_relationship_current", True, .93, [dn],
                tags=["relationship", "interpersonal"], writer_relevant=True,
            )
            if historical_friend:
                fn = graph.add("relation", "friendship_history", max(r.get("confidence", .85) for r in historical_friend))
                rn = add_derived(
                    "relationship_familiarity_high", True, .9, [dn, fn],
                    tags=["relationship", "interpersonal", "familiarity"], writer_relevant=True,
                )
                add_consequence(
                    "context", "relationship_has_established_familiarity", "relationship", .9, .78, [rn],
                    tags=["relationship", "interpersonal"],
                    why=["current dating relationship grew from earlier friendship"],
                    avoid=["do not repeatedly restate the entire relationship history"],
                    novelty=.7,
                )

        # Garment provenance / interpersonal significance.
        for r in rels:
            if r.get("predicate") == "garment.purchased_for" and r.get("subject") == "char:fano":
                rn = graph.add("relation", "garment_purchased_by_fano", r.get("confidence", .9), metadata={"garment": r.get("object")})
                sig = add_derived(
                    "garment_interpersonal_significance_high", True, r.get("confidence", .9) * .9, [rn],
                    tags=["relationship", "clothing", "interpersonal"], writer_relevant=True,
                    metadata={"garment": r.get("object")},
                )
                # Surface only if the garment is currently worn.
                runtime = world.get("current_runtime_state", {}).get(char, {})
                if runtime.get("wearing", {}).get(r.get("object")):
                    add_consequence(
                        "context", "worn_garment_has_fano_provenance", "relationship", .86, .68, [sig],
                        policy="mention_if_natural", tags=["relationship", "clothing"],
                        why=["Fano bought the garment currently being worn"],
                        avoid=["do not force this fact into prose if the relationship context is inactive"],
                        novelty=.65,
                    )

        family_close = any(r.get("predicate") == "social.family_close" for r in rels)
        approved = [r for r in rels if r.get("predicate") == "social.approves_of" and r.get("value") is not False]
        arranged = any(r.get("predicate") == "social.arranged_relationship" for r in rels)
        if family_close or approved or arranged:
            parents = []
            for label, cond in (("family_close", family_close), ("arranged", arranged)):
                if cond:
                    parents.append(graph.add("relation", label, .9))
            if approved:
                parents.append(graph.add("relation", "family_approval", max(r.get("confidence", .8) for r in approved)))
            fan = add_derived(
                "family_relationship_acceptance_high", True, .86, parents,
                tags=["relationship", "family", "social"], writer_relevant=True,
            )
            add_consequence(
                "context", "relationship_is_normalized_within_families", "social", .88, .84, [fan],
                policy="mention_if_natural", tags=["relationship", "family"],
                why=["family closeness/arrangement/approval lowers family-side secrecy pressure"],
                avoid=["do not restate family approval unless the scene activates family context"],
                novelty=.9,
            )

        # Normative rules stay latent unless boundary focus is active.
        for norm in world.get("norms", []):
            nn = graph.add("norm", norm.get("predicate", "norm"), norm.get("confidence", .85), metadata={"value": norm.get("value")})
            dn = add_derived(
                "conditional_relationship_boundary_rule_present", True, norm.get("confidence", .85) * .94, [nn],
                tags=["social_boundary", "relationship"], writer_relevant=bool(focus.get("social_boundary")),
            )
            if focus.get("social_boundary", 0) > .4:
                add_consequence(
                    "context", "conditional_boundary_rule_is_scene_relevant", "normative", .88, .84, [dn],
                    policy="mention_if_natural", tags=["social_boundary", "relationship"],
                    why=["the prompt establishes an explicit conditional family boundary rule"],
                    avoid=["do not treat the condition as if it has already happened"], novelty=.9,
                )

        # ------------------------------------------------------------------
        # Current outfit state.
        # ------------------------------------------------------------------
        runtime = world.get("current_runtime_state", {}).get(char, {})
        worn = [gid for gid, active in runtime.get("wearing", {}).items() if active]
        if worn:
            wn = graph.add("state", "current_outfit_state", .99, metadata={"wearing": worn})
            add_derived(
                "current_outfit_components", worn, .99, [wn],
                tags=["clothing", "appearance"], writer_relevant=False,
            )

        # ------------------------------------------------------------------
        # Dynamic event reasoning.
        # ------------------------------------------------------------------
        patch_by_event = {p["event_id"]: p for p in transitions.get("patches", [])}
        snapshots = {s["id"]: s["state"] for s in transitions.get("snapshots", [])}
        for event in events.get("events", []):
            en = graph.add("event", event["type"], .99, metadata={"event_id": event["id"]})
            patch = patch_by_event.get(event["id"], {})
            before = snapshots.get(patch.get("state_before"), {})
            after = snapshots.get(patch.get("state_after"), {})

            if event["type"] == "hair_transformation":
                bh = before.get("runtime", {}).get(char, {}).get("hair", {})
                ah = after.get("runtime", {}).get(char, {}).get("hair", {})
                if bh != ah:
                    tn = graph.add("state_transition", "hair_state_changed", .98, [en], metadata={"before": bh, "after": ah})
                    parents = [tn] + ([hair_long_node] if hair_long_node else [])
                    add_consequence(
                        event["id"], "major_silhouette_change", "appearance", .95, .96, parents,
                        tags=["appearance", "physical_detail", "hair"], why=["hair state changes substantially"],
                    )

            if event["type"] == "dress_change":
                add_consequence(
                    event["id"], "outfit_state_changed", "appearance", .94, .88, [en],
                    tags=["clothing", "appearance"], why=["explicit clothing change alters the current outfit"],
                )
                if event.get("cause") == "state:thermal_discomfort":
                    cn = graph.add("causal_relation", "thermal_discomfort_causes_clothing_change", .94, [en])
                    interactions.append({"type": "causal_relation", "cause": "thermal_discomfort", "effect_event": event["id"], "confidence": .94, "graph_node": cn})
                    add_consequence(
                        event["id"], "clothing_change_is_comfort_motivated", "comfort", .92, .76, [cn],
                        tags=["clothing", "bodily_sensation"], why=["the text explicitly links heat/discomfort to changing clothes"],
                    )

            if event["type"] == "anatomical_transformation":
                add_consequence(
                    event["id"], "downstream_body_interactions_use_transformed_state", "state_transition", .9, .83, [en],
                    policy="hidden", why=["subsequent reasoning must use the updated body state"],
                )

            if event["type"] == "appearance_observation":
                add_consequence(
                    event["id"], "presentation_shift_is_scene_salient", "appearance", .93, .92, [en],
                    tags=["appearance"], why=["moment-specific appearance observation"],
                )

            if event.get("cause") and event.get("cause") != "state:thermal_discomfort":
                interactions.append({
                    "type": "causal_relation",
                    "cause": event["cause"],
                    "effect_event": event["id"],
                    "confidence": .9,
                })

        # Scenario requested event reasoning.
        for requested in scenario.get("requested_events", []):
            en = graph.add("scenario_event", requested["type"], requested.get("confidence", .9), metadata={"id": requested["id"]})
            sid = "scenario:" + requested["id"]
            if requested.get("recurrence") == "first_time":
                add_consequence(
                    sid, "first_time_clothing_experience_high_novelty", "novelty", .96, .97, [en],
                    tags=["novelty", "appearance", "bodily_sensation"], why=["requested event is explicitly the first occurrence"],
                )
            add_consequence(
                sid, "interpersonal_guidance_scene_relevant", "interpersonal", .9, .84, [en],
                tags=["interpersonal", "relationship"], why=["another character causes or guides the requested action"],
            )

        consequences.sort(key=lambda x: (x["salience"], x["confidence"]), reverse=True)
        return {
            "version": self.VERSION,
            "derived_facts": derived,
            "constraints": constraints,
            "interactions": interactions,
            "consequences": consequences,
            "blocked_inferences": blocked,
            "uncertainties": uncertainties,
            "inference_graph": graph.dump(),
            "diagnostics": [],
        }
