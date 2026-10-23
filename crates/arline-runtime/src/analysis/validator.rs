use serde_json::{json, Value};

fn lower_words(s: &str) -> String {
    s.to_ascii_lowercase()
}
fn context_text(ctx: &Value) -> String {
    let mut out = String::new();
    fn walk(v: &Value, o: &mut String) {
        match v {
            Value::String(s) => {
                o.push(' ');
                o.push_str(s)
            }
            Value::Array(a) => {
                for x in a {
                    walk(x, o)
                }
            }
            Value::Object(m) => {
                for x in m.values() {
                    walk(x, o)
                }
            }
            _ => {}
        }
    }
    walk(ctx, &mut out);
    out
}
fn array(ctx: &Value, key: &str) -> Vec<Value> {
    ctx.get(key)
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default()
}

pub fn validate(story: &str, ctx: Option<&Value>) -> Value {
    let mut violations = Vec::new();
    let mut warnings = Vec::new();
    let lower = lower_words(story);
    let ids: [&str; 6] = [
        "char:",
        "garment:",
        "item:",
        "family:",
        "relationship:",
        "loc:",
    ];
    let leaks: Vec<&str> = ids.iter().copied().filter(|x| lower.contains(x)).collect();
    if !leaks.is_empty() {
        violations.push(json!({"type":"internal_id_leak","examples":leaks}));
    }
    let meta = [
        "context says",
        "prompt requires",
        "instruksi mengatakan",
        "jangan mengarang",
    ];
    let mh: Vec<&str> = meta.iter().copied().filter(|x| lower.contains(x)).collect();
    if !mh.is_empty() {
        violations.push(json!({"type":"instruction_or_constraint_leakage","examples":mh}));
    }
    let mut unsupported = Vec::new();
    let units = ["cm", "mm", "meter", "meters", "kg", "gram", "jam", "pukul"];
    let locked = array(ctx.unwrap_or(&Value::Null), "locked");
    let toks: Vec<&str> = story.split_whitespace().collect();
    let allowed = ctx
        .map(context_text)
        .unwrap_or_default()
        .to_ascii_lowercase();
    for (i, t) in toks.iter().enumerate() {
        let n = t.trim_matches(|c: char| !c.is_ascii_digit() && c != '.' && c != ',');
        if !n.is_empty() && n.chars().any(|c| c.is_ascii_digit()) {
            if let Some(u) = toks.get(i + 1) {
                let ul = u.to_ascii_lowercase();
                if units.iter().any(|x| ul.starts_with(x))
                    && !allowed.contains(n.replace(',', ".").as_str())
                {
                    unsupported.push(format!("{} {}", n, ul));
                }
            }
        }
    }
    if !unsupported.is_empty() {
        violations.push(json!({"type":"unsupported_numeric_specificity","examples":unsupported}));
    }
    let number_words = [
        "nol", "satu", "dua", "tiga", "empat", "lima", "enam", "tujuh", "delapan", "sembilan",
        "sepuluh", "sebelas", "belas", "puluh", "ratus", "seribu", "ribu",
    ];
    let locked_numeric = locked.iter().any(|x| {
        x.get("value")
            .map(|v| v.to_string())
            .unwrap_or_default()
            .chars()
            .any(|c| c.is_ascii_digit())
    });
    let mut corrupted = Vec::new();
    // A sequence containing multiple unit digits after a multiplier is the
    // malformed Indonesian number-word pattern rejected by Python validator.
    if locked_numeric {
        for i in 0..toks.len() {
            if number_words.contains(&toks[i]) {
                let mut j = i;
                let mut seq = Vec::new();
                while j < toks.len() && number_words.contains(&toks[j]) {
                    seq.push(toks[j]);
                    j += 1;
                }
                if j < toks.len()
                    && [
                        "sentimeter",
                        "centimeter",
                        "meter",
                        "meters",
                        "milimeter",
                        "millimeter",
                    ]
                    .iter()
                    .any(|u| toks[j].starts_with(u))
                    && seq.len() >= 3
                    && seq
                        .iter()
                        .filter(|x| {
                            [
                                "dua", "tiga", "empat", "lima", "enam", "tujuh", "delapan",
                                "sembilan",
                            ]
                            .contains(x)
                        })
                        .count()
                        >= 2
                {
                    corrupted.push(seq.join(" "));
                }
            }
        }
    }
    if !corrupted.is_empty() {
        violations.push(json!({"type":"worded_or_corrupted_canonical_measurement","examples":corrupted,"rule":"preserve canonical numeric values without malformed number-word rewrites"}));
    }
    let times: Vec<&str> = toks
        .iter()
        .copied()
        .filter(|x| x.contains(':') && x.chars().filter(|c| c.is_ascii_digit()).count() >= 3)
        .collect();
    if !times.is_empty() && !allowed.contains(times[0]) {
        violations.push(json!({"type":"unsupported_clock_time","examples":times}));
    }
    let unknown = ctx
        .map(|x| context_text(x).to_ascii_lowercase())
        .unwrap_or_default();
    if (unknown.contains("activation mechanism") || unknown.contains("technology beyond"))
        && [
            "sirkuit",
            "circuit",
            "tombol aktivasi",
            "activation button",
            "beep",
        ]
        .iter()
        .any(|x| lower.contains(x))
    {
        violations.push(json!({"type":"unsupported_mechanism_detail"}));
    }
    if unknown.contains("body-relative endpoint")
        && ["pinggang", "waist", "lutut", "knee", "lantai", "floor"]
            .iter()
            .any(|x| lower.contains(x))
    {
        violations.push(json!({"type":"unsupported_body_relative_endpoint_inference"}));
    }
    let materials = [
        "rayon",
        "jersey",
        "sutra",
        "silk",
        "satin",
        "katun",
        "cotton",
        "linen",
        "polyester",
    ];
    let canonical: Vec<String> = locked
        .iter()
        .filter_map(|x| x.get("value").and_then(Value::as_str))
        .filter(|x| materials.iter().any(|m| x.to_ascii_lowercase().contains(m)))
        .map(|x| x.to_ascii_lowercase())
        .collect();
    let generated: Vec<String> = materials
        .iter()
        .filter(|m| lower.contains(**m))
        .map(|m| m.to_string())
        .collect();
    if !canonical.is_empty()
        && !generated.is_empty()
        && !generated
            .iter()
            .all(|x| canonical.iter().any(|c| c.contains(x)))
    {
        violations.push(json!({"type":"garment_material_contradiction","canonical":canonical,"generated":generated}));
    }
    // Projection bounds are advisory regions, never exact landmarks.
    let projections = ctx
        .and_then(|x| x.get("projections"))
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let mut projection_uses = 0usize;
    let mut projection_out = Vec::new();
    let mut projection_exact = Vec::new();
    let rank = [
        "shoulder",
        "upper_back",
        "mid_back",
        "lower_back",
        "waist",
        "hip",
        "upper_thigh",
        "mid_thigh",
        "knee",
        "calf",
        "ankle",
        "floor",
    ];
    for p in projections {
        let metadata = p.get("metadata").unwrap_or(&Value::Null);
        let domain = metadata.get("domain").and_then(Value::as_str).unwrap_or("");
        let region = metadata
            .get("allowed_region")
            .or_else(|| metadata.get("allowed region"));
        let (Some(from), Some(to)) = (
            region.and_then(|x| x.get("from")).and_then(Value::as_str),
            region.and_then(|x| x.get("to")).and_then(Value::as_str),
        ) else {
            continue;
        };
        let Some(lo) = rank.iter().position(|x| *x == from) else {
            continue;
        };
        let Some(hi) = rank.iter().position(|x| *x == to) else {
            continue;
        };
        let (lo, hi) = (lo.min(hi), lo.max(hi));
        let relevant = if domain.eq_ignore_ascii_case("hair") {
            ["rambut", "hair", "wig", "ujung"]
                .iter()
                .any(|x| lower.contains(x))
        } else {
            ["gaun", "dress", "gamis", "panjang", "ujung", "hem"]
                .iter()
                .any(|x| lower.contains(x))
        };
        if !relevant {
            continue;
        }
        let endpoints = [
            ("pinggang", 3),
            ("waist", 3),
            ("pinggul", 5),
            ("hip", 5),
            ("paha", 6),
            ("thigh", 6),
            ("lutut", 8),
            ("knee", 8),
            ("betis", 9),
            ("calf", 9),
            ("pergelangan kaki", 10),
            ("ankle", 10),
            ("lantai", 11),
            ("floor", 11),
        ];
        for (word, pos) in endpoints {
            if lower.contains(word) {
                if pos < lo || pos > hi {
                    projection_out.push(word.to_owned())
                } else if ["tepat", "persis", "exactly", "precisely", "pasti"]
                    .iter()
                    .any(|x| lower.contains(x))
                {
                    projection_exact.push(word.to_owned())
                } else {
                    projection_uses += 1
                }
            }
        }
    }
    if !projection_out.is_empty() {
        violations.push(json!({"type":"projection_out_of_range","examples":projection_out}));
    }
    if !projection_exact.is_empty() {
        violations.push(json!({"type":"projection_promoted_to_exact_fact","examples":projection_exact,"rule":"projection is approximate and may not become an exact landmark"}));
    }
    // Preserve contracts are attached to transitions in writer_context.
    let transitions = ctx
        .and_then(|x| x.get("transitions"))
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    for t in transitions {
        for path in t
            .get("preserves")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(Value::as_str)
        {
            let hit = if path.contains("height") {
                lower.contains("tinggi")
                    && ["menjadi", "berubah", "became"]
                        .iter()
                        .any(|x| lower.contains(x))
            } else if path.contains("chest") {
                ["dada", "payudara", "chest"]
                    .iter()
                    .any(|x| lower.contains(x))
                    && ["membesar", "mengecil", "grew", "larger"]
                        .iter()
                        .any(|x| lower.contains(x))
            } else if path.contains("morphology") {
                ["pinggul", "bahu", "hips", "shoulders", "rib"]
                    .iter()
                    .any(|x| lower.contains(x))
                    && ["melebar", "mengecil", "widened", "narrowed"]
                        .iter()
                        .any(|x| lower.contains(x))
            } else {
                false
            };
            if hit {
                violations.push(json!({"type":"preserve_contract_violation","domain":path}));
            }
        }
    }
    // Writer language profile checks are warnings, matching Python quality policy.
    let lang = ctx
        .and_then(|x| x.get("style"))
        .and_then(|x| x.get("language_profile"))
        .unwrap_or(&Value::Null);
    let target = lang
        .get("language")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_ascii_lowercase();
    let pronoun = lang
        .get("narrator_pronoun")
        .and_then(Value::as_str)
        .unwrap_or("");
    let translationese = [
        "memberikan kesan",
        "menciptakan siluet",
        "dengan presisi tinggi",
        "pada saat yang sama",
        "dalam sekejap",
        "seolah-olah",
        "merupakan sebuah",
        "dengan demikian",
        "oleh karena itu",
        "terasa begitu nyata dan mendalam",
        "siap untuk mengeksplorasi",
    ];
    let translation_hits: Vec<&str> = translationese
        .iter()
        .copied()
        .filter(|x| lower.contains(x))
        .collect();
    if target.starts_with("id") && translation_hits.len() >= 3 {
        warnings.push(json!({"type":"translationese_density_high","examples":translation_hits}));
    }
    let english = [
        "the",
        "and",
        "with",
        "this",
        "that",
        "was",
        "were",
        "from",
        "into",
        "because",
        "however",
        "therefore",
        "while",
    ];
    let indonesian = [
        "yang", "dan", "dengan", "ini", "itu", "adalah", "dari", "ke", "karena", "namun", "saat",
        "ketika",
    ];
    let en = english
        .iter()
        .map(|x| {
            lower
                .split_whitespace()
                .filter(|w| w.trim_matches(|c: char| !c.is_alphabetic()) == *x)
                .count()
        })
        .sum::<usize>();
    let id = indonesian
        .iter()
        .map(|x| {
            lower
                .split_whitespace()
                .filter(|w| w.trim_matches(|c: char| !c.is_alphabetic()) == *x)
                .count()
        })
        .sum::<usize>();
    let drift = en as f64 / (1.max(en + id) as f64);
    if target.starts_with("id") && drift >= 0.18 {
        warnings.push(json!({"type":"target_language_drift","target":"id-ID","ratio":drift}));
    }
    let pronoun_drift = if target.starts_with("id") && pronoun == "aku" {
        lower
            .split_whitespace()
            .filter(|x| x.trim_matches(|c: char| !c.is_alphabetic()) == "saya")
            .count()
    } else {
        0
    };
    if pronoun_drift > 0 {
        warnings.push(json!({"type":"narrator_pronoun_drift","expected":"aku","observed_count":pronoun_drift}));
    }
    let mut recitations = Vec::new();
    for item in locked.iter() {
        let label = item.get("label").and_then(Value::as_str).unwrap_or("");
        let val = item.get("value").map(|x| x.to_string()).unwrap_or_default();
        if val.chars().any(|c| c.is_ascii_digit())
            && lower.matches(&val.to_ascii_lowercase()).count() > 1
        {
            recitations.push(json!({"fact":label,"value":val,"count":2}));
        }
    }
    if !recitations.is_empty() {
        warnings.push(json!({"type":"specification_recitation","facts":recitations}));
    }
    let repeats = toks
        .windows(2)
        .filter(|p| p[0].eq_ignore_ascii_case(p[1]))
        .count();
    if repeats > 0 {
        warnings.push(json!({"type":"repeated_adjacent_token","count":repeats}));
    }
    let paragraphs: Vec<&str> = story
        .split("\n\n")
        .filter(|p| p.split_whitespace().count() >= 18)
        .collect();
    let mut pairs = Vec::new();
    for i in 0..paragraphs.len() {
        for j in i + 1..paragraphs.len() {
            let a: std::collections::HashSet<_> = paragraphs[i]
                .split_whitespace()
                .map(|x| x.to_ascii_lowercase())
                .collect();
            let b: std::collections::HashSet<_> = paragraphs[j]
                .split_whitespace()
                .map(|x| x.to_ascii_lowercase())
                .collect();
            let u = a.union(&b).count();
            if u > 0 && (a.intersection(&b).count() as f64) / (u as f64) >= 0.72 {
                pairs.push(json!({"paragraphs":[i+1,j+1],"similarity":0.72}));
            }
        }
    }
    if !pairs.is_empty() {
        warnings.push(json!({"type":"semantic_paragraph_repetition","pairs":pairs}));
    }
    let total = unsupported.len() + times.len();
    let metric = json!({"validator_version":"0.2.0","paragraph_count":paragraphs.len(),"internal_id_leaks":leaks.len(),"instruction_leaks":mh.len(),"unsupported_specificities":total,"unsupported_specificity_rate":(total as f64)/(1.max(toks.len()) as f64),"unsupported_body_relative_inferences":if unknown.contains("body-relative endpoint")&&lower.contains("knee"){1}else{0},"projection_visualizations":projection_uses,"projection_out_of_range":projection_out.len(),"projection_exactness_violations":projection_exact.len(),"repetition_pairs":pairs.len()+repeats,"semantic_echo_pairs":0,"spec_recitations":recitations.len(),"translationese_phrases":translation_hits.len(),"language_drift_ratio":drift,"narrator_pronoun_drift":pronoun_drift});
    json!({"valid":violations.is_empty(),"violations":violations,"warnings":warnings,"metrics":metric})
}
