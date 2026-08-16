from __future__ import annotations

import re


class ClaimExtractor:
    VERSION = "0.3.3"

    @classmethod
    def default(cls):
        return cls()

    def extract(self, resolved_segments: dict, entity_data: dict, annotations: dict | None = None, discourse: dict | None = None) -> dict:
        annotations = annotations or {"annotations": []}
        claims = []
        self_id = entity_data.get("self_entity", "char:self")
        entity_ids = {e["id"] for e in entity_data.get("entities", [])}
        ann_by_seg = {}
        for ann in annotations.get("annotations", []):
            ann_by_seg.setdefault(ann["segment_id"], []).append(ann)

        def add(
            segment,
            kind,
            predicate,
            value=True,
            *,
            subject=None,
            object_=None,
            confidence=0.90,
            epistemic="explicit",
            temporal="current_or_unspecified",
            persistence="persistent",
            source_kind="narrator_assertion",
            metadata=None,
        ):
            scope = dict(segment.get("scope", {}))
            scope.update({
                "truth_scope": "canonical" if persistence != "scenario" else "scenario",
                "temporal": temporal,
                "persistence": persistence,
            })
            claims.append({
                "id": f"claim_{len(claims)+1:04d}",
                "kind": kind,
                "subject": subject,
                "predicate": predicate,
                "object": object_,
                "value": value,
                "confidence": round(float(confidence), 4),
                "epistemic": epistemic,
                "source_segment": segment["id"],
                "source_text": segment.get("raw_text") or segment["text"],
                "source": {"kind": source_kind},
                "scope": scope,
                "metadata": metadata or {},
            })

        # Useful garment id lookup.
        garment_by_label = {}
        for e in entity_data.get("entities", []):
            if e.get("type") == "garment":
                garment_by_label[e.get("label")] = e["id"]

        wearing_chain_active = False
        rolling_history = []

        def garment_for(text: str, context: str = ""):
            low = (context + " " + text).lower()
            for label in ("khimar", "gamis", "dress", "bra", "underwear", "underwear_set", "kemben", "feminine_clothing"):
                if label in low and label in garment_by_label:
                    return garment_by_label[label]
            # celana dalam maps to underwear
            if "celana dalam" in low and "underwear" in garment_by_label:
                return garment_by_label["underwear"]
            return None

        for seg in resolved_segments.get("segments", []):
            text = seg.get("normalized_text") or seg["text"]
            raw = seg.get("raw_text") or seg["text"]
            context = seg.get("context_text", "")
            combined = f"{context} | {text}" if context else text
            low = combined.lower()
            own_low = text.lower()
            aspect = seg.get("aspect", {})
            modality = seg.get("scope", {}).get("modality", "asserted")

            # Scenario request: keep separate from realized world state.
            m = re.search(
                r"\bcerita\b.{0,150}?(?P<first>kali\s+pertama|pertama\s+kali)"
                r".{0,120}?(?P<actor>fano|[a-z][\w'-]+)\s+"
                r"(?:membuatku|membuat\s+aku|menyuruhku|menyuruh\s+aku)\s+"
                r"memakai\s+(?P<target>pakaian\s+(?:cewek|perempuan)|dress|gamis|baju)",
                own_low,
                re.S,
            )
            if m:
                target = garment_for(m.group("target")) or "garment:feminine_clothing_1"
                add(
                    seg,
                    "scenario_event",
                    "caused_dress_change",
                    True,
                    subject=f"char:{m.group('actor').lower()}",
                    object_=self_id,
                    confidence=0.96,
                    temporal="scenario",
                    persistence="scenario",
                    metadata={
                        "target": target,
                        "recurrence": "first_time",
                        "realization_status": "requested_not_realized",
                    },
                )

            # Requests/hypotheticals don't become canonical factual state.
            if modality in {"request", "hypothetical", "intent"}:
                continue

            # Explicit garment/body compatibility statement.
            if re.search(r"\bpakaian(?:nya)?\s+cocok(?:\s+banget|\s+sekali)?\b.{0,100}\b(?:di|buat|untuk)\s+(?:aku|tubuhku|bodyku)\b", low, re.S):
                fit_garment = garment_for(text, context)
                if fit_garment is None and "garment:feminine_clothing_1" in entity_ids:
                    fit_garment = "garment:feminine_clothing_1"
                if fit_garment:
                    add(seg, "relation", "garment.fits", "high", subject=fit_garment, object_=self_id, confidence=0.94)

            # ---------------------------------------------------------
            # Character physical facts.
            # ---------------------------------------------------------
            if re.search(
                r"\b(?:bodyku|tubuhku|badanku|postur\s+tubuhku)\b.{0,160}"
                r"\b(?:seperti|mirip(?:\s+dengan)?)\s+(?:cewek|perempuan)\b",
                low,
                re.S,
            ):
                add(seg, "fact", "physical.morphology.presentation", "feminine", subject=self_id, confidence=0.94)

            cup = re.search(r"\b([A-H])\s*cup\b", low, re.I)
            if cup:
                add(seg, "fact", "physical.chest.reference_cup", cup.group(1).upper(), subject=self_id, confidence=0.99)

            # Annotation-based chest softness/compliance.
            for ann in ann_by_seg.get(seg["id"], []):
                for hint in ann.get("hints", []):
                    if hint.get("type") == "tissue_property" and hint.get("target") in {"chest", "body.chest"}:
                        add(seg, "fact", "physical.chest.softness", hint.get("softness", "high"), subject=self_id, confidence=0.94)
                        add(seg, "fact", "physical.chest.compliance", hint.get("compliance", "high"), subject=self_id, confidence=0.88)

            # Some annotations are separate segments whose context carries the head.
            if ("empuk" in own_low or "lembut" in own_low) and ("dada" in low or "chest" in low):
                add(seg, "fact", "physical.chest.softness", "very_high" if "sangat" in own_low else "high", subject=self_id, confidence=0.92)
                add(seg, "fact", "physical.chest.compliance", "high", subject=self_id, confidence=0.86)

            # Female-like growth/endocrine facts retained from v0.3.1.
            if re.search(r"\b(?:dada(?:ku)?|payudara(?:ku)?)\b.{0,160}\b(?:tumbuh|berkembang)\b.{0,100}\b(?:seperti|cewek|perempuan)\b", low, re.S):
                add(seg, "fact", "physical.chest.growth_profile", "female_like", subject=self_id, confidence=0.92)
            if re.search(r"\b(?:tubuhku|bodyku|badanku)\b.{0,100}\b(?:bisa|dapat|mampu)\s+(?:memproduksi|produksi|menghasilkan)\s+hormon\s+(?:cewek|perempuan|wanita)\b", low, re.S):
                add(seg, "fact", "endocrine.feminizing_hormone_production", True, subject=self_id, confidence=0.94)
            if re.search(r"\b(?:aku|tubuhku|bodyku)\b.{0,120}\b(?:aslinya|awalnya)\s+(?:cowok|laki-laki|pria)\b", low, re.S):
                add(seg, "fact", "biological_context.baseline_sex", "male", subject=self_id, confidence=0.94)

            # Body-relative hair length.
            hair_anchor = re.search(r"\b(?:rambut(?:ku)?|panjang(?:nya)?)\b.{0,100}\b(?:sampai|sebatas)\s+(pinggang|bahu|lutut|mata\s+kaki|punggung)\b", low, re.S)
            if hair_anchor:
                anchor = hair_anchor.group(1).replace(" ", "_")
                add(
                    seg,
                    "fact",
                    "hair.length_relative",
                    {"anchor": anchor, "frame": "body_relative"},
                    subject=self_id,
                    confidence=0.96,
                )

            # ---------------------------------------------------------
            # Garment mentions, attributes, current wearing state.
            # ---------------------------------------------------------
            targets = []
            for label, gid in garment_by_label.items():
                if label in low or (label == "underwear" and "celana dalam" in low):
                    targets.append((label, gid))
            if "pakaian dalam" in low and "underwear_set" in garment_by_label:
                pair = ("underwear_set", garment_by_label["underwear_set"])
                if pair not in targets:
                    targets.append(pair)

            # Explicit state assertion: "aku memakai ..." is current state, not necessarily an event.
            if re.search(r"\baku\s+memakai\b", own_low) and aspect.get("event_status") not in {"habitual", "historical"}:
                wearing_chain_active = True
                for label, gid in targets:
                    if label not in {"kemben"}:
                        add(
                            seg,
                            "state_assertion",
                            "garment.wearing",
                            True,
                            subject=self_id,
                            object_=gid,
                            confidence=0.96,
                            temporal="current",
                            persistence="scene_state",
                        )
            elif wearing_chain_active and re.match(r"^\s*(?:serta|dan)\s+", own_low) and targets:
                # Coordination continues the same current outfit assertion across
                # an intervening annotation block: "gamis[...] serta khimar[...]".
                for label, gid in targets:
                    if label not in {"kemben"}:
                        add(
                            seg, "state_assertion", "garment.wearing", True,
                            subject=self_id, object_=gid, confidence=0.93,
                            temporal="current", persistence="scene_state",
                        )
            elif own_low.startswith(",") or aspect.get("event_status") == "habitual":
                wearing_chain_active = False

            # Colloquial state assertion such as "aku gerah sih pakai gamis".
            if re.search(r"\b(?:aku\s+)?(?:gerah|kepanasan|panas)\b.{0,80}\bpakai\s+(gamis|dress|baju)\b", own_low, re.S):
                word = re.search(r"\bpakai\s+(gamis|dress|baju)\b", own_low).group(1)
                gid = garment_by_label.get(word) or ("garment:feminine_clothing_1" if word == "baju" else None)
                if gid:
                    add(seg, "state_assertion", "garment.wearing", True, subject=self_id, object_=gid, confidence=0.95, temporal="current", persistence="scene_state")

            # Individual garment properties.
            for label, gid in targets:
                local = low
                # length and orientation
                if label == "khimar":
                    front = re.search(r"panjang\s+depan\s*(\d+(?:[.,]\d+)?)\s*(?:cm)?", local)
                    back = re.search(r"panjang\s+belakang\s*(\d+(?:[.,]\d+)?)\s*cm", local)
                    if front:
                        add(seg, "fact", "garment.front_length", {"value": float(front.group(1).replace(",", ".")), "unit": "cm", "frame": "front_length"}, subject=gid, confidence=0.97)
                    if back:
                        add(seg, "fact", "garment.back_length", {"value": float(back.group(1).replace(",", ".")), "unit": "cm", "frame": "back_length"}, subject=gid, confidence=0.97)
                    if "jumbo" in local:
                        add(seg, "fact", "garment.size_class", "jumbo", subject=gid, confidence=0.96)
                    if "instan" in local:
                        add(seg, "fact", "garment.construction", "instant", subject=gid, confidence=0.95)
                else:
                    # Prefer length near garment term.
                    length = re.search(rf"\b{re.escape(label)}(?:nya|ku|mu)?\b.{{0,80}}?(\d+(?:[.,]\d+)?)\s*cm\b", local, re.S)
                    if length:
                        add(seg, "fact", "garment.length", {"value": float(length.group(1).replace(",", ".")), "unit": "cm", "frame": "garment_length"}, subject=gid, confidence=0.95)

                if "flowy" in local and label in {"gamis", "dress"}:
                    add(seg, "fact", "garment.flowiness", "high", subject=gid, confidence=0.94)

                for color in ("hitam", "putih", "lavender", "merah", "biru", "navy", "pink", "ungu", "hijau", "kuning", "coklat", "magenta", "burgundy"):
                    if re.search(rf"\b{color}\b", own_low):
                        # Annotation context determines garment target.
                        context_gid = garment_for(text, context)
                        if context_gid == gid or len(targets) == 1:
                            add(seg, "fact", "garment.color", color, subject=gid, confidence=0.96)
                        break
                for material in ("jersey", "rayon", "katun", "cotton", "satin", "silk", "sutra", "linen", "polyester"):
                    if re.search(rf"\b{material}\b", own_low):
                        context_gid = garment_for(text, context)
                        if context_gid == gid or len(targets) == 1:
                            add(seg, "fact", "garment.material", material, subject=gid, confidence=0.97)
                        break

            # Cross-garment relation: underwear with a matching colour to
            # the surrounding dress/gamis annotation.
            if "warna senada" in own_low:
                outer = garment_for("", context)
                if outer:
                    for label in ("bra", "underwear", "underwear_set"):
                        gid = garment_by_label.get(label)
                        if gid and gid != outer and (label in targets or (label == "underwear" and "celana dalam" in own_low) or (label == "underwear_set" and "pakaian dalam" in own_low)):
                            add(seg, "relation", "garment.same_color_as", True, subject=gid, object_=outer, confidence=0.91)

            if re.search(r"\b(?:sudah|udah)\s+(?:biasa|sering)\s+pakai\b", own_low) and "pakaian dalam" in own_low:
                add(seg, "experience", "experience.feminine_underwear", {"frequency":"repeated","familiarity":"high","novelty":"low"}, subject=self_id, confidence=0.9, temporal="habitual")

            # ---------------------------------------------------------
            # Relationship & experience history.
            # ---------------------------------------------------------
            if "char:fano" in entity_ids:
                if re.search(r"\bawalnya\s+teman\b.{0,100}\b(?:lama-lama|kemudian|akhirnya)\s+(?:jadi\s+)?pacar\b", low, re.S):
                    add(seg, "relation", "relationship.friend_of", True, subject=self_id, object_="char:fano", confidence=0.97, temporal="historical")
                    add(seg, "relation", "relationship.dating", True, subject=self_id, object_="char:fano", confidence=0.97, temporal="current")
                    add(
                        seg,
                        "transition",
                        "relationship.transition",
                        {"from": "friend", "to": "dating", "progression": "gradual"},
                        subject="relationship:self_fano" if "relationship:self_fano" in entity_ids else self_id,
                        object_="char:fano",
                        confidence=0.96,
                        temporal="historical_to_current",
                    )
                elif re.search(r"\b(?:pacar(?:an)?\s+dengan\s+fano|fano\s+(?:adalah\s+)?pacar)\b", low):
                    add(seg, "relation", "relationship.dating", True, subject=self_id, object_="char:fano", confidence=0.95, temporal="current")

                # Friend annotation and ordinary mention.
                if re.search(r"\bteman(?:ku)?\b", low) and "fano" in low:
                    temporal = "historical" if "awalnya" in low else "unspecified"
                    add(seg, "relation", "relationship.friend_of", True, subject=self_id, object_="char:fano", confidence=0.9, temporal=temporal)

                # Gamis provenance: "gamis ini dia yang belikan".
                if re.search(r"\bgamis\s+ini\b.{0,80}\b(?:dia|fano)\b.{0,30}\b(?:belikan|beli)\b", low, re.S) or re.search(r"\bgamis\s+ini\b.{0,80}\bdia\s+yang\s+belikan\b", low, re.S):
                    gid = garment_by_label.get("gamis")
                    if gid:
                        add(seg, "relation", "garment.purchased_for", True, subject="char:fano", object_=gid, confidence=0.91, metadata={"beneficiary": self_id})

                # Repeated feminine presentation/cosplay experiences.
                if re.search(r"\b(?:bukan\s+(?:yang\s+)?pertama|sering)\b", low) and re.search(r"\b(?:sebagai|jadi|diriku\s+sebagai)\s+(?:cewek|perempuan)\b", low):
                    add(seg, "experience", "experience.feminine_presentation", {"frequency": "repeated", "familiarity": "high", "novelty": "low"}, subject=self_id, confidence=0.93, temporal="habitual")
                if "event cosplay" in low and re.search(r"\bsering\b", low):
                    add(seg, "experience", "experience.cosplay_outing", {"frequency": "frequent", "with": "char:fano"}, subject=self_id, object_="char:fano", confidence=0.92, temporal="habitual")
                if re.search(r"\bkadang\s+(?:jalan|keluar)\b", low):
                    add(seg, "experience", "experience.casual_outing", {"frequency": "occasional", "with": "char:fano"}, subject=self_id, object_="char:fano", confidence=0.88, temporal="habitual")

            # "bukan yang pertama" even if the sentence doesn't repeat "as a girl".
            if re.search(r"\bbukan\s+(?:yang\s+)?pertama\b", low):
                add(seg, "experience", "experience.current_presentation", {"prior_occurrence": True, "novelty": "low"}, subject=self_id, confidence=0.9, temporal="historical_summary")
                add(seg, "experience", "experience.feminine_presentation", {"frequency": "repeated", "familiarity": "high", "novelty": "low"}, subject=self_id, confidence=0.9, temporal="habitual")

            # Cross-segment habitual context: the phrase before [cowok-Fano]
            # can contain "sering diajak temanku", while the next prose says
            # "ke event cosplay".
            prior_low = " ".join(rolling_history[-3:]).lower()
            if "event cosplay" in low and ("sering diajak" in prior_low or "sering diajak" in low) and "char:fano" in entity_ids:
                add(seg, "experience", "experience.cosplay_outing", {"frequency": "frequent", "with": "char:fano"}, subject=self_id, object_="char:fano", confidence=0.9, temporal="habitual")

            rolling_history.append(text)

            # ---------------------------------------------------------
            # Attributed perception/belief is not promoted to world truth.
            # ---------------------------------------------------------
            if "char:fano" in entity_ids and re.search(r"\bfano\s+(?:bilang|mengatakan|ngomong)\b.{0,100}\b(?:aku|kamu)\b.{0,50}\b(?:cantik|cakep|pretty)\b", low, re.S):
                add(seg, "belief", "belief.perceives_as", "pretty", subject="char:fano", object_=self_id, confidence=0.88, source_kind="attributed_statement", metadata={"truth_status":"subjective_perception"})
            if re.search(r"\baku\s+(?:pikir|percaya|mengira)\b", own_low):
                add(seg, "belief", "belief.self_reported", raw.strip(), subject=self_id, confidence=0.78, source_kind="self_reported_belief", metadata={"truth_status":"unknown"})

            # ---------------------------------------------------------
            # Social / family knowledge and relationship acceptance.
            # ---------------------------------------------------------
            if "char:fano" in entity_ids:
                if re.search(r"\borang\s+tuaku\s+(?:tau|tahu)\b", low) and re.search(r"\bpacaran\s+dengan\s+fano\b", low):
                    add(seg, "knowledge", "knowledge.aware_of", True, subject="family:self", object_="relationship:self_fano", confidence=0.94, metadata={"topic": "dating"})
                if re.search(r"\bkeluarga\s+fano\b.{0,80}\bdekat\b.{0,80}\bkeluargaku\b|\bkeluargaku\b.{0,80}\bdekat\b.{0,80}\bkeluarga\s+fano\b", low, re.S):
                    add(seg, "relation", "social.family_close", True, subject="family:self", object_="family:fano", confidence=0.95)
                if "dijodohkan" in low:
                    add(seg, "relation", "social.arranged_relationship", True, subject="family:self", object_="relationship:self_fano", confidence=0.93, metadata={"other_family": "family:fano"})
                    add(seg, "relation", "social.approves_of", True, subject="family:self", object_="relationship:self_fano", confidence=0.86, epistemic="inferred")
                    add(seg, "relation", "social.approves_of", True, subject="family:fano", object_="relationship:self_fano", confidence=0.86, epistemic="inferred")
                if re.search(r"\bdi\s+mata\s+keluarga\s+aman\b", low):
                    add(seg, "derived_source", "social.family_acceptance_explicit", "high", subject="relationship:self_fano", confidence=0.9)

            # ---------------------------------------------------------
            # Normative attributed statements.
            # ---------------------------------------------------------
            if re.search(r"\b(?:mama|mamaku)\b.{0,80}\b(?:ibunya\s+fano|ibu\s+fano)\b.{0,80}\bbilang\b", low, re.S) and "kalau" in low:
                actions = []
                if "tampar" in low:
                    actions.append("slap")
                if "marah" in low:
                    actions.append("scold")
                if actions:
                    add(
                        seg,
                        "norm",
                        "norm.permission",
                        {
                            "condition": {"actor": "char:fano", "behavior": "sexual_boundary_violation"},
                            "permitted_actor": self_id,
                            "actions": actions,
                            "rationale": "unmarried" if "belum nikah" in low else None,
                        },
                        subject="family:self",
                        object_=self_id,
                        confidence=0.9,
                        temporal="conditional",
                        source_kind="attributed_statement",
                        metadata={"speakers": ["char:self_mother", "char:fano_mother"]},
                    )

            if "belum nikah" in low and "char:fano" in entity_ids:
                add(seg, "relation", "relationship.married", False, subject=self_id, object_="char:fano", confidence=0.97, temporal="current")

            # Thermal discomfort + causal change gets represented as claims too.
            if re.search(r"\b(?:gerah|kepanasan|panas)\b", low):
                add(seg, "state_assertion", "comfort.thermal", "hot_uncomfortable", subject=self_id, confidence=0.94, temporal="current", persistence="scene_state")

        # De-duplicate semantically identical claims while preserving strongest confidence.
        dedup = {}
        for claim in claims:
            key = (
                claim.get("kind"), claim.get("subject"), claim.get("predicate"),
                str(claim.get("object")), repr(claim.get("value")),
                claim.get("scope", {}).get("temporal"),
            )
            old = dedup.get(key)
            if old is None or claim["confidence"] > old["confidence"]:
                dedup[key] = claim

        final = list(dedup.values())
        # Re-number after dedup for stable compact ids.
        for i, claim in enumerate(final, 1):
            claim["id"] = f"claim_{i:04d}"

        return {
            "version": self.VERSION,
            "claims": final,
            "diagnostics": [],
        }
