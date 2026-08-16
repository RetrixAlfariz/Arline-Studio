from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any


@dataclass(slots=True)
class PostWriteReport:
    valid: bool
    violations: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


class PostWriteValidator:
    VERSION = "0.2.0"
    INTERNAL = re.compile(
        r"\b(?:char|garment|item|family|relationship|loc):|"
        r"\bevt_\d+\b|\binf_\d+\b|\bseg_\d+\b|"
        r"(?<!\w)(?:g|x)\d+(?!\w)",
        re.I,
    )
    MATERIALS = (
        "rayon",
        "jersey",
        "sutra",
        "silk",
        "satin",
        "katun",
        "cotton",
        "linen",
        "polyester",
    )
    NUMBER_WORD = (
        r"(?:nol|satu|dua|tiga|empat|lima|enam|tujuh|delapan|sembilan|"
        r"sepuluh|sebelas|belas|puluh|ratus|seribu|ribu)"
    )

    def validate(self, story: str, writer_context) -> PostWriteReport:
        violations: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        leaks = self.INTERNAL.findall(story)
        if leaks:
            violations.append({"type": "internal_id_leak", "examples": leaks[:10]})

        # Meta/constraint leakage is especially common in native reasoning mode:
        # the model correctly reasons about a rule, then repeats the rule in prose.
        meta_patterns = (
            r"\baku\s+(?:tidak|nggak)\s+(?:ingin|akan)\s+menjelaskan\b",
            r"\b(?:saya|aku)\s+(?:tidak|nggak)\s+akan\s+(?:mengarang|menebak|menginvent)\b",
            r"\b(?:context|konteks|prompt|instruksi|aturan)\s+(?:mengatakan|menyebut|meminta|says|requires)\b",
            r"\b(?:akan|would)\s+membuat\s+(?:cerita|story).{0,45}(?:daftar\s+spesifikasi|specification\s+list)\b",
            r"\b(?:tidak|cannot|can't)\s+(?:disebutkan|menentukan|provide).{0,40}(?:karena|because).{0,40}(?:unknown|tidak\s+diketahui|unspecified)\b",
        )
        meta_hits: list[str] = []
        for pattern in meta_patterns:
            meta_hits.extend(re.findall(pattern, story, re.I | re.S))
        if meta_hits:
            violations.append(
                {"type": "instruction_or_constraint_leakage", "examples": meta_hits[:10]}
            )

        allowed = self._allowed_measurements(writer_context)
        measurements = re.findall(
            r"(?<!\w)(\d+(?:[.,]\d+)?)\s*(cm|mm|m²|m2|meter|meters|kg|gram|jam|pukul)\b",
            story,
            re.I,
        )
        unsupported: list[str] = []
        for num, unit in measurements:
            norm = f"{num.replace(',', '.')} {unit.lower()}"
            if not self._measurement_allowed(norm, allowed):
                unsupported.append(norm)
        if unsupported:
            violations.append(
                {
                    "type": "unsupported_numeric_specificity",
                    "examples": sorted(set(unsupported))[:20],
                }
            )

        # Native-thinking models sometimes corrupt canonical numbers into malformed
        # number-word sequences (for example "dua belas enam lima sentimeter").
        # Valid natural equivalents such as "satu meter" are not treated as hard
        # failures; only malformed Indonesian number phrases are rejected here.
        worded_measurements = re.findall(
            rf"\b({self.NUMBER_WORD}(?:\s+{self.NUMBER_WORD}){{0,7}})\s+"
            r"(sentimeter|centimeter|meter|meters|milimeter|millimeter)\b",
            story,
            re.I,
        )
        corrupted_worded = [
            item for item in worded_measurements
            if self._parse_indonesian_number_words(item[0]) is None
        ]
        if corrupted_worded and self._has_locked_numeric_measurement(writer_context):
            violations.append(
                {
                    "type": "worded_or_corrupted_canonical_measurement",
                    "examples": [" ".join(item) for item in corrupted_worded[:10]],
                    "rule": "preserve canonical numeric values without malformed number-word rewrites",
                }
            )

        clock_times = re.findall(
            r"(?<!\d)(?:pukul\s*)?(\d{1,2}[:.]\d{2})(?!\d)", story, re.I
        )
        allowed_text = self._allowed_context_text(writer_context).lower()
        unsupported_times = [t for t in clock_times if t.lower() not in allowed_text]
        if unsupported_times:
            violations.append(
                {
                    "type": "unsupported_clock_time",
                    "examples": sorted(set(unsupported_times))[:10],
                }
            )

        location_mentions = re.findall(
            r"\b(?:kawasan|daerah|jalan|district|neighborhood)\s+([A-Z][A-Za-zÀ-ÿ'-]{2,})",
            story,
        )
        location_locked = str(
            (writer_context.freedom or {}).get("persistent_location", "low")
        ) in {"low", "locked"}
        unsupported_locations = [
            name for name in location_mentions if name.lower() not in allowed_text
        ]
        if location_locked and unsupported_locations:
            violations.append(
                {
                    "type": "unsupported_location_specificity",
                    "examples": sorted(set(unsupported_locations))[:10],
                }
            )

        mechanism_unknown = any(
            "activation mechanism" in str(item).lower()
            or "technology beyond" in str(item).lower()
            for item in writer_context.unknown
        )
        if mechanism_unknown:
            mechanism_hits = re.findall(
                r"\b(?:tombol\s+aktivasi|activation\s+button|menyalakan\s+(?:alat|perangkat)(?:nya)?|"
                r"perangkat\s+medis|medical\s+device|sirkuit|circuit|mekanisme\s+aktivasi|"
                r"energi\s+(?:panas|listrik)|arus\s+listrik|\bbeep\b)\b",
                story,
                re.I,
            )
            if mechanism_hits:
                violations.append(
                    {
                        "type": "unsupported_mechanism_detail",
                        "examples": mechanism_hits[:10],
                    }
                )

        # Spatial endpoints are projection-aware. An exact endpoint may remain
        # UNKNOWN while a bounded PROJECTION supplies a safe mental-model range.
        unknown_text = " ".join(str(item).lower() for item in writer_context.unknown)
        endpoint_words = (
            r"(?:punggung\s+bawah|lower\s+back|pinggang|waist|pinggul|hip|"
            r"paha(?:\s+atas)?|upper\s+thigh|mid\s+thigh|lutut|knee|betis|calf|"
            r"pergelangan\s+kaki|mata\s+kaki|ankle|menyentuh\s+lantai|lantai|floor|ground)"
        )
        unsupported_spatial: list[str] = []
        projection_out_of_range: list[str] = []
        projection_exactness: list[str] = []
        projection_uses: list[str] = []
        sentences = [s for s in re.split(r"(?<=[.!?])\s+|\n+", story) if s.strip()]
        previous_low = ""
        hair_projection = self._domain_projection(writer_context, "hair")
        garment_projection = self._domain_projection(writer_context, "garment")

        for sentence in sentences:
            low = sentence.lower()
            garment_context = bool(
                re.search(r"\b(?:gaun|dress|gamis)\b", low)
                or (re.search(r"\b(?:gaun|dress|gamis)\b", previous_low) and re.search(r"\b(?:panjang|length|hem|ujung)\b", low))
            )
            hair_context = bool(
                re.search(r"\b(?:rambut\w*|hair|wig)\b", low)
                or (re.search(r"\b(?:rambut\w*|hair|wig)\b", previous_low) and re.search(r"\b(?:panjang|length|ujung)\b", low))
            )
            has_endpoint = bool(re.search(endpoint_words, low))

            if has_endpoint and garment_context and "measurement origin/basis" in unknown_text:
                # Current garment projection only classifies visual length when
                # the measurement basis is unknown; it does not license an exact
                # ankle/floor/body landmark.
                allowed = self._projection_allowed_region(garment_projection)
                if not allowed:
                    unsupported_spatial.append(sentence.strip())
                else:
                    verdict = self._check_projection_sentence(low, allowed)
                    if verdict == "out_of_range":
                        projection_out_of_range.append(sentence.strip())
                    elif verdict == "exact":
                        projection_exactness.append(sentence.strip())
                    elif verdict == "ok":
                        projection_uses.append(sentence.strip())

            if has_endpoint and hair_context and "body-relative endpoint" in unknown_text:
                allowed = self._projection_allowed_region(hair_projection)
                if not allowed:
                    unsupported_spatial.append(sentence.strip())
                else:
                    verdict = self._check_projection_sentence(low, allowed)
                    if verdict == "out_of_range":
                        projection_out_of_range.append(sentence.strip())
                    elif verdict == "exact":
                        projection_exactness.append(sentence.strip())
                    elif verdict == "ok":
                        projection_uses.append(sentence.strip())
            previous_low = low

        if unsupported_spatial:
            violations.append(
                {
                    "type": "unsupported_body_relative_endpoint_inference",
                    "examples": unsupported_spatial[:8],
                }
            )
        if projection_out_of_range:
            violations.append(
                {
                    "type": "projection_out_of_range",
                    "examples": projection_out_of_range[:8],
                    "rule": "projected visualization must stay inside the bounded probable region",
                }
            )
        if projection_exactness:
            violations.append(
                {
                    "type": "projection_promoted_to_exact_fact",
                    "examples": projection_exactness[:8],
                    "rule": "projection is approximate and may not become a guaranteed/exact landmark",
                }
            )

        locked_materials = self._locked_materials(writer_context)
        story_materials = {
            material.lower()
            for material in re.findall(
                r"\b(?:" + "|".join(self.MATERIALS) + r")\b", story, re.I
            )
        }
        if (
            locked_materials
            and story_materials
            and not story_materials.issubset(locked_materials)
        ):
            violations.append(
                {
                    "type": "garment_material_contradiction",
                    "canonical": sorted(locked_materials),
                    "generated": sorted(story_materials),
                }
            )

        preserve_paths = {
            path
            for transition in writer_context.transitions
            for path in transition.get("preserves", []) or []
        }
        patterns: list[tuple[str, str]] = []
        if any("height" in path for path in preserve_paths):
            patterns.append(
                (
                    "height",
                    r"(?:tinggi(?:nya)?|height).{0,30}(?:menjadi|berubah menjadi|became)\s*\d+",
                )
            )
        if any("chest" in path for path in preserve_paths):
            patterns.append(
                (
                    "chest",
                    r"(?:dada|payudara|chest).{0,40}(?:membesar|mengecil|grew|became larger)",
                )
            )
        if any("morphology" in path for path in preserve_paths):
            patterns.append(
                (
                    "morphology",
                    r"(?:pinggul|bahu|tulang rusuk|hips|shoulders|rib).{0,40}(?:melebar|mengecil|widened|narrowed)",
                )
            )
        for domain, pattern in patterns:
            if re.search(pattern, story, re.I | re.S):
                violations.append(
                    {
                        "type": "preserve_contract_violation",
                        "domain": domain,
                        "pattern": pattern,
                    }
                )

        paragraphs = [
            p.strip()
            for p in re.split(r"\n\s*\n", story)
            if len(p.split()) >= 18
        ]
        duplicate_pairs: list[dict[str, Any]] = []
        token_sets = [set(re.findall(r"\w+", p.lower())) for p in paragraphs]
        for i in range(len(token_sets)):
            for j in range(i + 1, len(token_sets)):
                a, b = token_sets[i], token_sets[j]
                if not a or not b:
                    continue
                similarity = len(a & b) / len(a | b)
                if similarity >= 0.72:
                    duplicate_pairs.append(
                        {"paragraphs": [i + 1, j + 1], "similarity": round(similarity, 3)}
                    )
        if duplicate_pairs:
            warnings.append(
                {
                    "type": "semantic_paragraph_repetition",
                    "pairs": duplicate_pairs[:10],
                }
            )

        recitations = []
        for item in writer_context.locked:
            value = str(item.value)
            if any(ch.isdigit() for ch in value):
                count = story.lower().count(value.lower())
                if count > 1:
                    recitations.append(
                        {"fact": item.label, "value": value, "count": count}
                    )
        if recitations:
            warnings.append(
                {"type": "specification_recitation", "facts": recitations}
            )

        # Language and voice realization checks. These are warnings rather
        # than hard world-state violations: they help the data flywheel learn
        # natural Indonesian without rejecting otherwise grounded prose.
        language_profile = (writer_context.style or {}).get("language_profile", {}) or {}
        target_language = str(language_profile.get("language") or "")
        narrator_pronoun = str(language_profile.get("narrator_pronoun") or "")
        translationese_phrases = (
            "memberikan kesan", "menciptakan siluet", "dengan presisi tinggi",
            "pada saat yang sama", "dalam sekejap", "seolah-olah",
            "merupakan sebuah", "dengan demikian", "oleh karena itu",
            "terasa begitu nyata dan mendalam", "siap untuk mengeksplorasi",
        )
        translationese_hits = [
            phrase for phrase in translationese_phrases
            if phrase in story.lower()
        ]
        if target_language.lower().startswith("id") and len(translationese_hits) >= 3:
            warnings.append({
                "type": "translationese_density_high",
                "examples": translationese_hits[:10],
                "guidance": "prefer contemporary Indonesian realization over English-like explanatory phrasing",
            })

        english_function_words = re.findall(
            r"\b(?:the|and|with|this|that|was|were|from|into|because|however|therefore|while)\b",
            story, re.I,
        )
        indonesian_function_words = re.findall(
            r"\b(?:yang|dan|dengan|ini|itu|adalah|dari|ke|karena|namun|saat|ketika)\b",
            story, re.I,
        )
        language_drift_ratio = len(english_function_words) / max(1, len(english_function_words) + len(indonesian_function_words))
        if target_language.lower().startswith("id") and language_drift_ratio >= 0.18:
            warnings.append({
                "type": "target_language_drift",
                "target": "id-ID",
                "ratio": round(language_drift_ratio, 4),
                "examples": english_function_words[:12],
            })

        pronoun_inconsistency = 0
        if target_language.lower().startswith("id") and narrator_pronoun == "aku":
            # Quoted dialogue may legitimately use saya; this remains a warning.
            pronoun_inconsistency = len(re.findall(r"\bsaya\b", story, re.I))
            if pronoun_inconsistency:
                warnings.append({
                    "type": "narrator_pronoun_drift",
                    "expected": "aku",
                    "observed_count": pronoun_inconsistency,
                })

        # Detect semantic echoes below the paragraph-level duplicate threshold.
        # This intentionally uses content-token overlap, not exact wording.
        stop = {
            "yang","dan","di","ke","dari","itu","ini","aku","saya","ia","dia",
            "dengan","untuk","pada","sebuah","karena","namun","saat","ketika",
            "the","and","with","from","this","that","was","were","into",
        }
        echo_units = [p.strip() for p in re.split(r"\n\s*\n", story) if len(p.split()) >= 24]
        echo_sets = [
            {w for w in re.findall(r"[\w'-]+", p.lower()) if len(w) > 2 and w not in stop}
            for p in echo_units
        ]
        semantic_echoes = []
        for i in range(len(echo_sets)):
            for j in range(i + 1, len(echo_sets)):
                a, b = echo_sets[i], echo_sets[j]
                if not a or not b:
                    continue
                overlap = len(a & b) / max(1, min(len(a), len(b)))
                if overlap >= 0.68:
                    semantic_echoes.append({"paragraphs": [i + 1, j + 1], "overlap": round(overlap, 3)})
        if semantic_echoes:
            warnings.append({"type": "semantic_echo", "pairs": semantic_echoes[:10]})

        total_specificities = (
            len(measurements)
            + len(corrupted_worded)
            + len(clock_times)
            + len(location_mentions)
        )
        unsupported_total = (
            len(set(unsupported))
            + len(corrupted_worded)
            + len(set(unsupported_times))
            + len(set(unsupported_locations))
            + len(unsupported_spatial)
            + len(projection_out_of_range)
            + len(projection_exactness)
        )
        metrics = {
            "validator_version": self.VERSION,
            "paragraph_count": len(paragraphs),
            "internal_id_leaks": len(leaks),
            "instruction_leaks": len(meta_hits),
            "unsupported_specificities": unsupported_total,
            "unsupported_specificity_rate": round(
                unsupported_total / max(1, total_specificities), 4
            ),
            "unsupported_body_relative_inferences": len(unsupported_spatial),
            "projection_visualizations": len(projection_uses),
            "projection_out_of_range": len(projection_out_of_range),
            "projection_exactness_violations": len(projection_exactness),
            "repetition_pairs": len(duplicate_pairs),
            "semantic_echo_pairs": len(semantic_echoes),
            "spec_recitations": len(recitations),
            "translationese_phrases": len(translationese_hits),
            "language_drift_ratio": round(language_drift_ratio, 4),
            "narrator_pronoun_drift": pronoun_inconsistency,
        }
        return PostWriteReport(
            valid=not violations,
            violations=violations,
            warnings=warnings,
            metrics=metrics,
        )

    @staticmethod
    def _allowed_measurements(ctx):
        out = []
        for item in list(ctx.locked) + list(ctx.current) + list(ctx.scene):
            value = item.value
            if isinstance(value, str) and re.search(r"\d", value):
                out.append(value.lower().replace(",", "."))
            elif isinstance(value, (int, float)):
                out.append(str(value))
        return out

    @staticmethod
    def _measurement_allowed(norm, allowed):
        number = re.search(r"\d+(?:\.\d+)?", norm)
        if not number:
            return True
        value = number.group(0)
        return any(value in item for item in allowed)

    @staticmethod
    def _allowed_context_text(ctx):
        parts = []
        for collection in (ctx.scene, ctx.current, ctx.world, ctx.locked):
            for item in collection:
                parts.extend([str(item.label), str(item.value)])
        for values in ctx.characters.values():
            for item in values:
                parts.extend([str(item.label), str(item.value)])
        parts.extend(ctx.relations)
        return " ".join(parts)

    @staticmethod
    def _has_locked_numeric_measurement(ctx) -> bool:
        return any(
            any(ch.isdigit() for ch in str(item.value))
            and re.search(r"(?:cm|meter|m²|m2|height|length|floor)", item.label, re.I)
            for item in ctx.locked
        )

    @classmethod
    def _parse_indonesian_number_words(cls, phrase: str) -> int | None:
        tokens = phrase.lower().split()
        units = {
            "nol": 0, "satu": 1, "dua": 2, "tiga": 3, "empat": 4,
            "lima": 5, "enam": 6, "tujuh": 7, "delapan": 8, "sembilan": 9,
        }

        def under_100(parts):
            if not parts:
                return 0
            if len(parts) == 1:
                if parts[0] in units:
                    return units[parts[0]]
                if parts[0] == "sepuluh":
                    return 10
                if parts[0] == "sebelas":
                    return 11
                return None
            if len(parts) == 2 and parts[0] in units and parts[1] == "belas" and units[parts[0]] >= 2:
                return 10 + units[parts[0]]
            if len(parts) in {2, 3} and parts[0] in units and parts[1] == "puluh" and units[parts[0]] >= 1:
                value = units[parts[0]] * 10
                if len(parts) == 3:
                    if parts[2] not in units:
                        return None
                    value += units[parts[2]]
                return value
            return None

        if not tokens:
            return None
        if "ratus" in tokens:
            idx = tokens.index("ratus")
            if idx != 1 or tokens[0] not in units or units[tokens[0]] == 0:
                return None
            remainder = under_100(tokens[2:])
            return None if remainder is None else units[tokens[0]] * 100 + remainder
        return under_100(tokens)

    @staticmethod
    def _domain_projection(ctx, domain: str):
        for projection in getattr(ctx, "projections", []) or []:
            metadata = projection.metadata or {}
            value = metadata.get("domain") or metadata.get("domain ")
            if str(value).lower() == domain:
                return projection
        return None

    @staticmethod
    def _projection_allowed_region(projection):
        if projection is None:
            return None
        metadata = projection.metadata or {}
        region = metadata.get("allowed_region") or metadata.get("allowed region")
        if not isinstance(region, dict):
            return None
        start = region.get("from")
        end = region.get("to")
        if not start or not end:
            return None
        return str(start), str(end)

    @classmethod
    def _check_projection_sentence(cls, low: str, allowed: tuple[str, str]) -> str:
        order = [
            "shoulder", "upper_back", "mid_back", "lower_back", "waist",
            "hip", "upper_thigh", "mid_thigh", "knee", "calf", "ankle", "floor",
        ]
        ranks = {name: i for i, name in enumerate(order)}
        start, end = allowed
        if start not in ranks or end not in ranks:
            return "unsupported"
        lo, hi = sorted((ranks[start], ranks[end]))
        patterns = [
            ("lower_back", r"punggung\s+bawah|lower\s+back"),
            ("waist", r"\bpinggang\b|\bwaist\b"),
            ("hip", r"\bpinggul\b|\bhip(?:s)?\b"),
            ("upper_thigh", r"\bpaha(?:\s+atas)?\b|upper\s+thigh"),
            ("mid_thigh", r"tengah\s+paha|mid\s+thigh"),
            ("knee", r"\blutut\b|\bknee\b"),
            ("calf", r"\bbetis\b|\bcalf\b"),
            ("ankle", r"pergelangan\s+kaki|mata\s+kaki|\bankle\b"),
            ("floor", r"menyentuh\s+lantai|\blantai\b|\bfloor\b|\bground\b"),
        ]
        mentioned = [name for name, pattern in patterns if re.search(pattern, low)]
        if not mentioned:
            return "unsupported"
        if any(ranks.get(name, 999) < lo or ranks.get(name, 999) > hi for name in mentioned):
            return "out_of_range"
        exact = bool(re.search(
            r"\b(?:tepat|persis|exactly|precisely|pasti|must|berakhir\s+tepat|ujungnya\s+tepat)\b",
            low, re.I,
        ))
        return "exact" if exact else "ok"

    def _locked_materials(self, ctx):
        out = set()
        for item in ctx.locked:
            if "material" in item.label.lower() and isinstance(item.value, str):
                out.add(item.value.lower())
        return out
