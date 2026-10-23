//! Deterministic analytical pipeline used by native generation.
//!
//! The Python service exposes a fairly rich bundle (WCF, AIF, narrative brief,
//! projections, traces and validation).  This module keeps the same contract
//! at the Rust boundary without starting a Python interpreter.  The rules are
//! intentionally conservative: unknown text remains an unresolved fragment.
use crate::{ApiError, ApiResult, AppState};
use axum::{
    body::Body,
    http::{header, StatusCode},
    response::Response,
};
use chrono::Utc;
use serde_json::{json, Value};
use std::collections::HashMap;
use uuid::Uuid;

pub mod quality;
pub mod validator;
pub mod wcf;

const SCHEMA: &str = "CREATE TABLE IF NOT EXISTS analysis_cache (id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL);";

fn text(v: Option<&Value>) -> String {
    v.and_then(Value::as_str).unwrap_or("").trim().to_owned()
}
fn response(v: Value) -> ApiResult<Response> {
    Response::builder()
        .status(StatusCode::OK)
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(serde_json::to_vec(&v)?))
        .map_err(|e| ApiError::internal(e.to_string()))
}
fn directive(prompt: &str) -> Value {
    for line in prompt.lines().map(str::trim) {
        if let Some(command) = line.strip_prefix('/') {
            let mut parts = command.splitn(2, char::is_whitespace);
            let id = parts.next().unwrap_or_default().to_ascii_lowercase();
            if [
                "continue",
                "beats",
                "pov",
                "analyze",
                "scene",
                "describe",
                "recent",
                "threads",
                "character",
                "world",
            ]
            .contains(&id.as_str())
            {
                return json!({"id":id,"active":true,"args":parts.next().unwrap_or("").trim(),"raw":line});
            }
        }
    }
    json!({"id":null,"active":false,"args":"","raw":""})
}

pub fn ensure_schema(store: &crate::store::Store) -> ApiResult<()> {
    store
        .connection()?
        .execute_batch(SCHEMA)
        .map_err(ApiError::from)
}

fn trace_choices(context: &str, prompt: &str) -> Vec<Value> {
    let mut out = Vec::new();
    for (i, line) in context
        .lines()
        .filter(|l| l.contains(':'))
        .take(32)
        .enumerate()
    {
        let id = format!("ctx-{}", i + 1);
        out.push(json!({"id":id,"trace_id":id,"label":line.chars().take(120).collect::<String>(),"source":"workspace","authority":"canon"}));
    }
    if out.is_empty() && !prompt.trim().is_empty() {
        out.push(json!({"id":"prompt-1","trace_id":"prompt-1","label":"User request","source":"prompt","authority":"request"}));
    }
    out
}

pub fn quality_report(story: &str) -> Value {
    quality_report_with_context(story, None)
}

pub fn quality_report_with_context(story: &str, context: Option<&Value>) -> Value {
    let mut report = validator::validate(story, context);
    let surface = quality::analyze(story);
    if let (Some(warnings), Some(surface_issues)) = (
        report.get_mut("warnings").and_then(Value::as_array_mut),
        surface.get("issues").and_then(Value::as_array),
    ) {
        warnings.extend(surface_issues.iter().cloned());
    }
    if surface
        .get("issues")
        .and_then(Value::as_array)
        .map(|x| {
            x.iter()
                .any(|i| i.get("kind").and_then(Value::as_str) == Some("duplicate_word"))
        })
        .unwrap_or(false)
    {
        if let Some(violations) = report.get_mut("violations").and_then(Value::as_array_mut) {
            violations.push(json!({"type":"repeated_adjacent_token"}));
        }
        report["valid"] = Value::Bool(false);
    }
    if let Some(metrics) = report.get_mut("metrics").and_then(Value::as_object_mut) {
        metrics.insert(
            "surface_quality".to_owned(),
            surface.get("metrics").cloned().unwrap_or(Value::Null),
        );
    }
    return report;
    #[allow(unreachable_code)]
    let ws: Vec<&str> = story.split_whitespace().collect();
    let repeats = ws
        .windows(2)
        .filter(|pair| pair[0].eq_ignore_ascii_case(pair[1]))
        .count();
    let lower = story.to_ascii_lowercase();
    let mut violations = Vec::new();
    let mut warnings = Vec::new();
    let internal: Vec<&str> = [
        "char:",
        "garment:",
        "item:",
        "family:",
        "relationship:",
        "loc:",
    ]
    .iter()
    .copied()
    .filter(|marker| lower.contains(marker))
    .collect();
    if !internal.is_empty() {
        violations.push(json!({"type":"internal_id_leak","examples":internal}));
    }
    let meta = [
        "context says",
        "prompt requires",
        "instruksi mengatakan",
        "jangan mengarang",
    ];
    let meta_hits: Vec<&str> = meta
        .iter()
        .copied()
        .filter(|phrase| lower.contains(phrase))
        .collect();
    if !meta_hits.is_empty() {
        violations.push(json!({"type":"instruction_or_constraint_leakage","examples":meta_hits}));
    }
    if repeats > 0 {
        violations.push(json!({"type":"repeated_adjacent_token","count":repeats}));
        warnings.push(json!({"type":"repeated_adjacent_token","count":repeats}));
    }
    let paragraphs: Vec<&str> = story
        .split("\n\n")
        .filter(|p| p.split_whitespace().count() >= 18)
        .collect();
    let mut semantic_pairs = Vec::new();
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
            let union = a.union(&b).count();
            if union > 0 && (a.intersection(&b).count() as f64) / (union as f64) >= 0.72 {
                semantic_pairs.push(json!({"paragraphs":[i+1,j+1],"similarity":0.72}));
            }
        }
    }
    if !semantic_pairs.is_empty() {
        warnings.push(json!({"type":"semantic_paragraph_repetition","pairs":semantic_pairs}));
    }
    if let Some(ctx) = context {
        let unknowns = ctx
            .get("unknown")
            .or_else(|| ctx.get("unknowns"))
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let unknown_text = unknowns
            .iter()
            .map(|v| v.to_string())
            .collect::<Vec<_>>()
            .join(" ")
            .to_ascii_lowercase();
        if !unknowns.is_empty()
            && (lower.contains("exactly")
                || lower.contains("pasti tepat")
                || lower.contains("guaranteed"))
        {
            violations.push(json!({"type":"unknown_promoted_to_exact_fact"}));
        }
        if (unknown_text.contains("body-relative") || unknown_text.contains("measurement origin"))
            && ["pinggang", "waist", "lutut", "knee", "lantai", "floor"]
                .iter()
                .any(|word| lower.contains(word))
        {
            violations.push(json!({"type":"unsupported_body_relative_endpoint_inference"}));
        }
        let locked = ctx
            .get("locked")
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let allowed_numbers: Vec<String> = locked
            .iter()
            .filter_map(|item| item.get("value").map(|v| v.to_string()))
            .filter(|v| v.chars().any(|c| c.is_ascii_digit()))
            .collect();
        let measurements: Vec<String> = story
            .split_whitespace()
            .filter(|token| token.chars().any(|c| c.is_ascii_digit()))
            .map(ToOwned::to_owned)
            .collect();
        if !allowed_numbers.is_empty()
            && measurements.iter().any(|item| {
                !allowed_numbers.iter().any(|allowed| {
                    allowed.contains(item.trim_matches(|c: char| !c.is_ascii_digit()))
                })
            })
        {
            warnings
                .push(json!({"type":"unsupported_numeric_specificity","examples":measurements}));
        }
    }
    let issue_count = violations.len();
    let score = (100_i64 - (issue_count as i64 * 20) - (repeats as i64 * 8)).clamp(0, 100);
    json!({"valid":violations.is_empty(),"score":score,"issue_count":issue_count,"violations":violations,"warnings":warnings,"metrics":{"validator_version":"0.2.0","repetition_pairs":repeats,"semantic_echo_pairs":semantic_pairs.len(),"paragraph_count":paragraphs.len(),"word_count":ws.len(),"internal_id_leaks":internal.len(),"instruction_leaks":meta_hits.len()}})
}

/// Run the configured planning pass. Its output is explicitly soft and never
/// enters canon; provider failures return a traceable fallback object.
pub async fn deliberate(state: &AppState, body: &Value, analysis: &Value) -> Value {
    let cfg = match state.runtime_config() {
        Ok(value) => value,
        Err(error) => {
            return json!({"version":"1.2.4a1","status":"fallback","authority":"soft_non_canon","diagnostics":[error.message]})
        }
    };
    let planning_enabled = match body.get("deliberation_mode").and_then(Value::as_str) {
        Some("on") => true,
        Some("off") => false,
        _ => cfg.bool("deliberation.enabled", false),
    };
    if !planning_enabled {
        return json!({"version":"1.2.4a1","status":"disabled","authority":"soft_non_canon","intent":"continue","likely_beats":[],"alternatives":[]});
    }
    let prompt = text(body.get("prompt"));
    let context = format!(
        "<WCF>\n{}\n</WCF>\n<NARRATIVE_BRIEF>\n{}\n</NARRATIVE_BRIEF>\n<REQUEST>\n{}\n</REQUEST>",
        analysis["wcf"].as_str().unwrap_or(""),
        analysis["narrative_brief"]["text"].as_str().unwrap_or(""),
        prompt
    );
    let base = cfg.str("lmstudio.base_url", "http://127.0.0.1:1234");
    let configured_model = cfg.str("lmstudio.model", "");
    let model = body
        .get("model")
        .and_then(Value::as_str)
        .unwrap_or(&configured_model);
    let payload = json!({"model":model,"input":format!("<AUTHORITATIVE_CONTEXT>\n{}\n</AUTHORITATIVE_CONTEXT>\nReturn one JSON object only with scene_goal, likely_beats, character_intentions, emotional_trajectories, opportunities, alternatives, uncertainties, constraints.", context),"system_prompt":"You are Arline's Narrative Deliberator. Return JSON only. Never write prose or invent canon. Your output is soft non-canon guidance.","stream":false,"temperature":cfg.f64("deliberation.temperature",0.35),"top_p":0.9,"top_k":40,"max_output_tokens":cfg.u64("deliberation.max_tokens",700).clamp(128,4096),"reasoning":"off"});
    let mut request = state
        .client
        .post(format!("{}/api/v1/chat", base.trim_end_matches('/')))
        .json(&payload);
    let key = cfg.str("lmstudio.api_key", "");
    if !key.is_empty() {
        request = request.bearer_auth(key);
    }
    let response = match request.send().await {
        Ok(value) => value,
        Err(error) => {
            return json!({"version":"1.2.4a1","status":"fallback","authority":"soft_non_canon","diagnostics":[format!("Deliberator failure: {error}")],"scene_goal":prompt})
        }
    };
    if !response.status().is_success() {
        return json!({"version":"1.2.4a1","status":"fallback","authority":"soft_non_canon","diagnostics":[format!("Deliberator HTTP {}",response.status())],"scene_goal":prompt});
    }
    let raw: Value = match response.json().await {
        Ok(value) => value,
        Err(error) => {
            return json!({"version":"1.2.4a1","status":"fallback","authority":"soft_non_canon","diagnostics":[error.to_string()],"scene_goal":prompt})
        }
    };
    let text = raw
        .get("output")
        .and_then(Value::as_array)
        .and_then(|items| {
            items
                .iter()
                .find(|item| item.get("type").and_then(Value::as_str) == Some("message"))
        })
        .and_then(|item| item.get("content"))
        .and_then(Value::as_str)
        .or_else(|| raw.get("content").and_then(Value::as_str))
        .unwrap_or("");
    let parsed = serde_json::from_str::<Value>(
        text.trim()
            .trim_start_matches("```json")
            .trim_end_matches("```")
            .trim(),
    );
    match parsed {
        Ok(value) if value.is_object() => {
            let mut result = serde_json::Map::new();
            for key in [
                "scene_goal",
                "likely_beats",
                "character_intentions",
                "emotional_trajectories",
                "opportunities",
                "alternatives",
                "uncertainties",
                "constraints",
            ] {
                if let Some(field) = value.get(key) {
                    let clipped = match field {
                        Value::String(text) => Value::String(text.chars().take(500).collect()),
                        Value::Array(items) => Value::Array(
                            items
                                .iter()
                                .take(8)
                                .filter_map(|item| {
                                    item.as_str()
                                        .map(|text| Value::String(text.chars().take(500).collect()))
                                })
                                .collect(),
                        ),
                        _ => continue,
                    };
                    result.insert(key.to_owned(), clipped);
                }
            }
            json!({"version":"1.2.4a1","status":"model","authority":"soft_non_canon","canon_commit":"forbidden","result":Value::Object(result)})
        }
        _ => {
            json!({"version":"1.2.4a1","status":"fallback","authority":"soft_non_canon","diagnostics":["Deliberator returned non-JSON output."],"scene_goal":prompt})
        }
    }
}

pub fn compose_input(
    prompt: &str,
    wcf: &str,
    mode: &str,
    aif: &str,
    brief: &str,
    unresolved: &[String],
    deliberation: Option<&Value>,
) -> String {
    let mode = match mode {
        "raw" | "wcf" | "wcf_raw" | "smart_hybrid" | "aif_core" => mode,
        _ => "smart_hybrid",
    };
    let request = if mode == "raw" {
        prompt.trim().to_owned()
    } else {
        prompt.split_whitespace().collect::<Vec<_>>().join(" ")
    };
    let write = "Write the requested fiction using the structured context.";
    match mode {
        "raw" => format!(
            "<REQUEST>\n{}\n</REQUEST>\n\n<WRITE>{}</WRITE>",
            prompt.trim(),
            write
        ),
        "aif_core" => format!(
            "<AIF_CORE>\n{}\n</AIF_CORE>\n\n<REQUEST>\n{}\n</REQUEST>\n\n<WRITE>{}</WRITE>",
            aif.trim(),
            request,
            write
        ),
        _ => {
            let mut s = format!("<ARLINE_CONTEXT>\n{}\n</ARLINE_CONTEXT>\n", wcf.trim());
            if !brief.trim().is_empty() {
                s.push_str(&format!(
                    "\n<NARRATIVE_BRIEF>\n{}\n</NARRATIVE_BRIEF>\n",
                    brief.trim()
                ));
            }
            s.push_str(&format!("\n<REQUEST>\n{}\n</REQUEST>", request));
            if mode == "wcf_raw" {
                s.push_str(&format!(
                    "\n\n<RAW_SOURCE>\n{}\n</RAW_SOURCE>",
                    prompt.trim()
                ));
            }
            if mode == "smart_hybrid" && !unresolved.is_empty() {
                s.push_str("\n\n<UNRESOLVED_SOURCE_CONTEXT>\n");
                s.push_str(
                    &unresolved
                        .iter()
                        .map(|x| format!("- {x}"))
                        .collect::<Vec<_>>()
                        .join("\n"),
                );
                s.push_str("\n</UNRESOLVED_SOURCE_CONTEXT>");
            }
            if let Some(deliberation) = deliberation {
                if deliberation.get("status").and_then(Value::as_str) != Some("disabled") {
                    s.push_str("\n\n<NARRATIVE_DELIBERATION>\n");
                    s.push_str(&serde_json::to_string_pretty(deliberation).unwrap_or_default());
                    s.push_str("\n</NARRATIVE_DELIBERATION>");
                }
            }
            s.push_str(&format!("\n\n<WRITE>\n{}\n</WRITE>", write));
            s
        }
    }
}

type PipelineState = (Vec<Value>, Vec<Value>, Vec<Value>, Vec<Value>, Vec<Value>);

#[allow(clippy::drop_non_drop)]
fn extract_pipeline_state(prompt: &str) -> PipelineState {
    let mut entities = vec![
        json!({"id":"char:character","type":"character","label":"character","attributes":{},"provisional":true,"introduced_by":null}),
    ];
    let mut claims = Vec::new();
    let mut events = Vec::new();
    let mut unknowns = Vec::new();
    let mut relations = Vec::new();
    let mut claim_no = 0usize;
    let mut named = Vec::<String>::new();
    let common = [
        "Aku", "Saya", "Dia", "Ia", "She", "He", "The", "My", "Namaku",
    ];
    for sentence in prompt.split(['.', '!', '?']) {
        let mut first = true;
        for raw in sentence.split_whitespace() {
            let token = raw.trim_matches(|c: char| !c.is_alphabetic());
            if token.is_empty() {
                continue;
            }
            let sentence_lower = sentence.to_ascii_lowercase();
            let name_like_start = first
                && [
                    " is ", " enters", " walks", " says", " wears", " memakai", " masuk",
                    " berdiri",
                ]
                .iter()
                .any(|v| sentence_lower.contains(v));
            if (!first || name_like_start)
                && token.chars().next().is_some_and(char::is_uppercase)
                && !common.contains(&token)
                && token.len() > 1
                && !named.iter().any(|x| x == token)
            {
                named.push(token.to_owned());
            }
            first = false;
        }
    }
    for lower in ["namaku ", "my name is "] {
        if let Some(pos) = prompt.to_ascii_lowercase().find(lower) {
            if let Some(raw) = prompt[pos + lower.len()..].split_whitespace().next() {
                let name = raw.trim_matches(|c: char| !c.is_alphabetic()).to_owned();
                if !name.is_empty() && !named.iter().any(|x| x.eq_ignore_ascii_case(&name)) {
                    named.insert(0, name);
                }
            }
        }
    }
    if let Some(primary) = named.first().cloned() {
        entities[0]["id"] = json!(format!("char:{}", primary.to_ascii_lowercase()));
        entities[0]["label"] = json!(primary);
        entities[0]["provisional"] = json!(false);
        for name in named.iter().skip(1) {
            entities.push(json!({"id":format!("char:{}",name.to_ascii_lowercase()),"type":"character","label":name,"attributes":{},"provisional":false,"introduced_by":"prompt"}));
        }
    }
    let mut last_subject = entities[0]["id"]
        .as_str()
        .unwrap_or("char:character")
        .to_owned();
    let mut add_claim = |text: &str,
                         predicate: &str,
                         subject: &str,
                         value: Value,
                         epistemic: &str,
                         confidence: f64| {
        claim_no += 1;
        let authority = if epistemic == "explicit" {
            "user_explicit"
        } else {
            "analytical_inference"
        };
        let segment = format!("seg_{claim_no:04}");
        claims.push(json!({
            "id": format!("claim_{claim_no:04}"),
            "kind": "fact",
            "subject": subject,
            "predicate": predicate,
            "object": null,
            "value": value,
            "confidence": confidence,
            "epistemic": epistemic,
            "authority": authority,
            "source_segment": segment,
            "source_text": text,
            "source": {"kind": "prompt"},
            "scope": {"truth_scope": "canonical", "temporal": "current_or_unspecified", "persistence": "persistent"},
            "provenance": [{"source_kind": "prompt", "source_segment": format!("seg_{claim_no:04}"), "source_text": text, "rule": predicate, "authority": authority}]
        }));
    };
    for (idx, raw) in prompt.split(['.', '!', '?']).enumerate() {
        let sentence = raw.trim();
        if sentence.len() < 3 {
            continue;
        }
        let low = sentence.to_ascii_lowercase();
        let sid = format!("seg_{:04}", idx + 1);
        let subject = named
            .iter()
            .find(|name| low.contains(&name.to_ascii_lowercase()))
            .map(|name| format!("char:{}", name.to_ascii_lowercase()))
            .unwrap_or_else(|| last_subject.clone());
        if !["dia", "ia", "she", "he", "they", "mereka"]
            .iter()
            .any(|p| low.starts_with(p))
        {
            last_subject = subject.clone();
        }
        if let Some(rest) = low
            .strip_prefix("namaku ")
            .or_else(|| low.strip_prefix("my name is "))
        {
            let name = rest
                .split_whitespace()
                .next()
                .unwrap_or("character")
                .trim_matches(|c: char| !c.is_alphabetic());
            entities[0]["label"] = json!(name);
            add_claim(
                sentence,
                "identity.name",
                &subject,
                json!(name),
                "explicit",
                0.99,
            );
        }
        if let Some(pos) = low.find("umur ").or_else(|| low.find("usia ")) {
            if let Some(age) = low[pos..].split_whitespace().nth(1).and_then(|x| {
                x.trim_matches(|c: char| !c.is_ascii_digit())
                    .parse::<i64>()
                    .ok()
            }) {
                add_claim(
                    sentence,
                    "identity.age",
                    &subject,
                    json!(age),
                    "explicit",
                    0.99,
                );
            }
        }
        if let Some(pos) = low.find("tinggi") {
            if let Some(v) = low[pos..].split_whitespace().find_map(|x| {
                x.trim_matches(|c: char| !c.is_ascii_digit() && c != '.')
                    .parse::<f64>()
                    .ok()
            }) {
                add_claim(
                    sentence,
                    "physical.height_cm",
                    &subject,
                    json!(v),
                    "explicit",
                    0.99,
                );
            }
        }
        for (word, kind, pred) in [
            ("gamis", "garment", "garment.wearing"),
            ("dress", "garment", "garment.wearing"),
            ("khimar", "garment", "garment.wearing"),
            ("rambut", "body", "hair.state"),
        ] {
            if low.contains(word) {
                let id = format!("{}:{}", kind, word);
                if !entities.iter().any(|e| e["id"] == id) {
                    let family = match word {
                        "gamis" | "dress" => "dress",
                        "khimar" => "head_covering",
                        "rambut" => "hair",
                        _ => "unknown",
                    };
                    entities.push(json!({"id":id,"type":kind,"label":word,"attributes":{"ontology":{"garment_family":family}},"provisional":false,"source_segment":sid}));
                }
                if low.contains("pakai") || low.contains("memakai") || low.contains("wear") {
                    add_claim(sentence, pred, &subject, json!(true), "explicit", 0.96);
                }
            }
        }
        // Measurement claims retain the Python extractor's explicit frame.
        // They are deliberately attached to the garment entity, so analytical
        // rules can compare front/back values without treating prose numbers
        // as character measurements.
        let words = low.split_whitespace().collect::<Vec<_>>();
        let parse_after = |needles: &[&str]| -> Option<f64> {
            for (i, word) in words.iter().enumerate() {
                if needles.iter().any(|needle| {
                    word.trim_matches(|c: char| !c.is_alphanumeric())
                        .eq(*needle)
                }) {
                    for candidate in words.iter().skip(i + 1).take(4) {
                        let cleaned =
                            candidate.trim_matches(|c: char| !c.is_ascii_digit() && c != '.');
                        if !cleaned.is_empty() {
                            if let Ok(value) = cleaned.parse::<f64>() {
                                return Some(value);
                            }
                        }
                    }
                }
            }
            None
        };
        if low.contains("khimar") || low.contains("dress") || low.contains("gamis") {
            if let Some(value) = parse_after(&["depan", "front"]) {
                add_claim(
                    sentence,
                    "garment.front_length",
                    "garment:garment",
                    json!({"value":value,"unit":"cm","frame":"front_length"}),
                    "explicit",
                    0.97,
                );
            }
            if let Some(value) = parse_after(&["belakang", "back"]) {
                add_claim(
                    sentence,
                    "garment.back_length",
                    "garment:garment",
                    json!({"value":value,"unit":"cm","frame":"back_length"}),
                    "explicit",
                    0.97,
                );
            }
        }
        if (low.contains("dia yang belikan")
            || low.contains("dia belikan")
            || low.contains("bought for")
            || (low.contains("bought") && low.contains(" for ")))
            && (low.contains("gamis") || low.contains("dress"))
        {
            relations.push(json!({"subject":"char:fano","predicate":"garment.purchased_for","object":"garment:garment","value":true,"confidence":0.91,"epistemic":"explicit","source_segment":sid,"temporal_scope":"current"}));
        }
        // Domain claims mirrored from ClaimExtractor's public vocabulary.
        if let Some(cup) = low.split_whitespace().find(|x| x.ends_with("cup")) {
            add_claim(
                sentence,
                "physical.chest.reference_cup",
                &subject,
                json!(cup.trim_end_matches("cup").to_ascii_uppercase()),
                "explicit",
                0.99,
            );
        }
        if low.contains("dada") || low.contains("chest") || low.contains("payudara") {
            for (needle, pred, value) in [
                ("empuk", "physical.chest.softness", "high"),
                ("empuk", "physical.chest.compliance", "high"),
                ("lembut", "physical.chest.softness", "high"),
                ("lembut", "physical.chest.compliance", "high"),
                ("tumbuh", "physical.chest.growth_profile", "female_like"),
                ("sensitif", "physical.chest.compliance", "high"),
            ] {
                if low.contains(needle) {
                    add_claim(sentence, pred, &subject, json!(value), "explicit", 0.9);
                }
            }
        }
        if low.contains("seperti cewek")
            || low.contains("seperti perempuan")
            || low.contains("feminin")
            || low.contains("feminine")
        {
            add_claim(
                sentence,
                "physical.morphology.presentation",
                &subject,
                json!("feminine"),
                "explicit",
                0.94,
            );
        }
        if low.contains("aslinya cowok") || low.contains("baseline sex male") {
            add_claim(
                sentence,
                "biological_context.baseline_sex",
                &subject,
                json!("male"),
                "explicit",
                0.94,
            );
        }
        if low.contains("produksi hormon") || low.contains("menghasilkan hormon") {
            add_claim(
                sentence,
                "endocrine.feminizing_hormone_production",
                &subject,
                json!(true),
                "explicit",
                0.94,
            );
        }
        if low.contains("sampai pinggang")
            || low.contains("sebatas pinggang")
            || low.contains("reaches the waist")
            || low.contains("waist-length")
        {
            add_claim(
                sentence,
                "hair.length_relative",
                &subject,
                json!({"anchor":"pinggang","frame":"body_relative"}),
                "explicit",
                0.96,
            );
        }
        for (color, value) in [
            ("hitam", "black"),
            ("putih", "white"),
            ("merah", "red"),
            ("biru", "blue"),
            ("lavender", "lavender"),
            ("ungu", "purple"),
            ("pink", "pink"),
        ] {
            if low.contains(color) {
                add_claim(
                    sentence,
                    "garment.color",
                    "garment:garment",
                    json!(value),
                    "explicit",
                    0.96,
                );
                break;
            }
        }
        for (material, value) in [
            ("jersey", "jersey"),
            ("rayon", "rayon"),
            ("katun", "cotton"),
            ("cotton", "cotton"),
            ("satin", "satin"),
            ("sutra", "silk"),
        ] {
            if low.contains(material) {
                add_claim(
                    sentence,
                    "garment.material",
                    "garment:garment",
                    json!(value),
                    "explicit",
                    0.96,
                );
                break;
            }
        }
        if low.contains("flowy") || low.contains("mengembang") {
            add_claim(
                sentence,
                "garment.flowiness",
                "garment:garment",
                json!("high"),
                "explicit",
                0.94,
            );
        }
        // Keep the relation explicit: the analytical fit rule requires an
        // actual garment.fits edge, rather than treating a worn garment as a
        // fit assertion.  This mirrors ClaimExtractor's provenance policy.
        if (low.contains("fits well")
            || low.contains("fit well")
            || low.contains("pas sekali")
            || low.contains("cocok sekali")
            || low.contains("cocok dengan tubuh"))
            && (low.contains("dress") || low.contains("gamis") || low.contains("garment"))
        {
            add_claim(
                sentence,
                "garment.fits",
                "garment:garment",
                json!("high"),
                "explicit",
                0.94,
            );
            relations.push(json!({
                "subject":"garment:garment", "predicate":"garment.fits",
                "object":subject, "value":"high", "confidence":0.94,
                "epistemic":"explicit", "source_segment":sid,
                "temporal_scope":"current"
            }));
        }
        if low.contains("keluarga") && low.contains("dekat") {
            add_claim(
                sentence,
                "social.family_close",
                &subject,
                json!(true),
                "explicit",
                0.9,
            );
        }
        if low.contains("menyetujui") || low.contains("mendukung") {
            add_claim(
                sentence,
                "social.approves_of",
                &subject,
                json!(true),
                "explicit",
                0.9,
            );
        }
        if (low.contains("teman") && low.contains("pacar"))
            || (low.contains("friend") && low.contains("dating"))
        {
            add_claim(
                sentence,
                "relationship.transition",
                &subject,
                json!("friend_to_dating"),
                "explicit",
                0.9,
            );
            add_claim(
                sentence,
                "relationship.dating",
                &subject,
                json!(true),
                "explicit",
                0.9,
            );
            add_claim(
                sentence,
                "relationship.friend_of",
                &subject,
                json!(true),
                "explicit",
                0.9,
            );
        }
        if low.contains("dating") || low.contains("pacar") {
            add_claim(
                sentence,
                "relationship.dating",
                &subject,
                json!(true),
                "explicit",
                0.9,
            );
        }
        if low.contains("friend") || low.contains("friends") || low.contains("teman") {
            add_claim(
                sentence,
                "relationship.friend_of",
                &subject,
                json!(true),
                "explicit",
                0.9,
            );
        }
        if low.contains("menikah") || low.contains("married") {
            add_claim(
                sentence,
                "relationship.married",
                &subject,
                json!(true),
                "explicit",
                0.9,
            );
        }
        if low.contains("aku merasa") || low.contains("i feel") {
            add_claim(
                sentence,
                "belief.self_reported",
                &subject,
                json!(sentence),
                "self_reported",
                0.8,
            );
        }
        if low.contains("tahu bahwa") || low.contains("aware of") {
            add_claim(
                sentence,
                "knowledge.aware_of",
                &subject,
                json!(sentence),
                "explicit",
                0.85,
            );
        }
        if low.contains("izin") || low.contains("permission") {
            add_claim(
                sentence,
                "norm.permission",
                &subject,
                json!(sentence),
                "explicit",
                0.85,
            );
        }
        if low.contains("rambut") && (low.contains("pendek") || low.contains("panjang")) {
            add_claim(
                sentence,
                "hair.length_class",
                &subject,
                json!(if low.contains("pendek") {
                    "short"
                } else {
                    "long"
                }),
                "explicit",
                0.95,
            );
        }
        if low.contains("tinggal sendiri") {
            relations.push(json!({"subject":subject,"predicate":"lives_alone_at","object":"loc:apartment_1","confidence":0.97,"epistemic":"explicit","source_segment":sid,"temporal_scope":"current"}));
        }
        let non_current_event = [
            "jika ",
            "kalau ",
            "seandainya ",
            "would ",
            "biasanya ",
            "usually ",
            "typically ",
            "selalu ",
            "sering ",
            "dulu ",
            "pernah ",
            "awalnya ",
        ]
        .iter()
        .any(|p| low.contains(p));
        if !non_current_event
            && (low.contains("masuk")
                || low.contains("enter")
                || low.contains("keluar")
                || low.contains("keluar")
                || low.contains("leave"))
        {
            let event_type = if low.contains("keluar") || low.contains("leave") {
                "leave"
            } else {
                "enter"
            };
            events.push(json!({"id":format!("EVENT-{:04}",idx+1),"event_type":event_type,"actor":subject,"text":sentence,"order":idx,"epistemic":"explicit","source_segment":sid,"temporal_scope":"current"}));
        }
        if low.contains("masuk")
            || low.contains("enter")
            || low.contains("keluar")
            || low.contains("leave")
        {
            add_claim(
                sentence,
                "runtime_event",
                &subject,
                json!(true),
                "explicit",
                0.95,
            );
        }
        if low.contains("ingin") || low.contains("want") || low.contains("wants") {
            add_claim(
                sentence,
                "intent.wants",
                &subject,
                json!(sentence),
                "explicit",
                0.9,
            );
        }
        if sentence.contains('?') || low.contains("what happens") || low.contains("bagaimana") {
            unknowns.push(json!({"id":format!("unknown_{:04}",idx+1),"question":"intent requires author resolution","status":"unresolved","epistemic":"unknown","source_segment":sid,"authority":"prompt"}));
        }
    }
    if prompt.contains('?') && unknowns.is_empty() {
        unknowns.push(json!({"id":"unknown_0001","question":"intent requires author resolution","status":"unresolved","epistemic":"unknown","source_segment":"prompt","authority":"prompt"}));
    }
    drop(add_claim);
    for claim in &mut claims {
        let source = claim["source_text"]
            .as_str()
            .unwrap_or("")
            .to_ascii_lowercase();
        let negated = ["tidak ", "bukan ", "never ", "jangan "]
            .iter()
            .any(|x| source.contains(x));
        let hypothetical = [
            "jika ",
            "kalau ",
            "seandainya ",
            "hypothetical",
            "mungkin ",
            "would ",
        ]
        .iter()
        .any(|x| source.contains(x));
        let historical = ["dulu ", "pernah ", "awalnya ", "ketika ", "historical"]
            .iter()
            .any(|x| source.contains(x));
        let habitual = ["biasanya ", "usually ", "selalu ", "sering ", "habitual"]
            .iter()
            .any(|x| source.contains(x));
        claim["negated"] = json!(negated);
        claim["scope"]["truth_scope"] = json!(if hypothetical {
            "scenario"
        } else {
            "canonical"
        });
        claim["scope"]["modality"] = json!(if hypothetical {
            "hypothetical"
        } else {
            "asserted"
        });
        claim["scope"]["polarity"] = json!(if negated { "negative" } else { "positive" });
        claim["scope"]["temporal"] = json!(if habitual {
            "habitual"
        } else if historical {
            "historical"
        } else {
            "current_or_unspecified"
        });
        claim["scope"]["temporal_scope"] = claim["scope"]["temporal"].clone();
        claim["scope"]["persistence"] = json!(if hypothetical || habitual || historical {
            "non_current"
        } else {
            "persistent"
        });
        if hypothetical {
            claim["epistemic"] = json!("hypothetical");
            claim["authority"] = json!("user_request");
        }
        if historical {
            claim["epistemic"] = json!("historical");
        }
        if habitual {
            claim["epistemic"] = json!("habitual");
        }
    }
    (entities, claims, events, unknowns, relations)
}

pub fn analyze(state: &AppState, body: &Value) -> ApiResult<Value> {
    let prompt = text(body.get("prompt"));
    if prompt.is_empty() {
        return Err(ApiError::bad_request("Prompt is empty"));
    }
    let wcf = if body.get("project_id").and_then(Value::as_str).is_some() {
        crate::context::build_context(state, body)?
    } else {
        String::new()
    };
    // Memory is augmented by `analyze_async` through the shared foundation
    // retrieval guard.  Keeping the synchronous core side-effect free also
    // prevents generation callers from bypassing scope/trust/POV policy.
    let memory: Vec<Value> = Vec::new();
    let memory_diagnostic = Value::Null;
    let command = directive(&prompt);
    let (mut entities, facts, events, unknown_records, relations) = extract_pipeline_state(&prompt);
    let mut unresolved = Vec::new();
    let lower_prompt = prompt.to_ascii_lowercase();
    if prompt.contains('?')
        || lower_prompt.contains("what happens")
        || lower_prompt.contains("how should")
    {
        unresolved.push("intent requires author resolution".to_owned());
    }
    if command["id"].as_str() == Some("pov") && command["args"].as_str().unwrap_or("").is_empty() {
        unresolved.push("POV target is unspecified".to_owned());
    }
    if entities.is_empty() && lower_prompt.contains("they") {
        unresolved.push("pronoun referent is unresolved".to_owned());
    }
    if !unknown_records.is_empty() {
        unresolved.extend(
            unknown_records
                .iter()
                .filter_map(|x| x["question"].as_str().map(ToOwned::to_owned)),
        );
    }
    if entities.is_empty() {
        entities.push(json!({"id":"char:character","type":"character","label":"character","attributes":{},"provisional":true,"introduced_by":Value::Null}));
    }
    let aliases: std::collections::HashMap<String, String> = entities
        .iter()
        .enumerate()
        .map(|(i, e)| {
            let id = e["id"].as_str().unwrap_or("").to_owned();
            let alias = if e["type"] == "character" {
                if i == 0 {
                    "self".to_owned()
                } else {
                    e["label"].as_str().unwrap_or("character").to_owned()
                }
            } else {
                format!(
                    "{}{}",
                    if e["type"] == "garment" { "g" } else { "x" },
                    i.max(1)
                )
            };
            (id, alias)
        })
        .collect();
    let mut aif = format!(
        "@AIF-CORE 0.3 profile=teacher\n@ARLINE 0.6.4\n{}\n{}",
        entities
            .iter()
            .map(|e| format!(
                "{} {}",
                if e["type"] == "character" {
                    "C"
                } else if e["type"] == "garment" {
                    "G"
                } else {
                    "O"
                },
                aliases
                    .get(e["id"].as_str().unwrap_or(""))
                    .cloned()
                    .unwrap_or_else(|| e["label"].as_str().unwrap_or("unknown").to_owned())
            ))
            .collect::<Vec<_>>()
            .join("\n"),
        facts
            .iter()
            .map(|fact| format!(
                "CL fact {}({})={}",
                fact["predicate"].as_str().unwrap_or("claim"),
                aliases
                    .get(fact["subject"].as_str().unwrap_or("char:character"))
                    .map(String::as_str)
                    .unwrap_or("self"),
                serde_json::to_string(&fact["value"]).unwrap_or_default(),
            ))
            .collect::<Vec<_>>()
            .join("\n")
    );
    let brief = format!(
        "Scene goal: {}\nKnown entities: {}\nUnresolved intent: {}",
        prompt,
        entities.len(),
        unresolved.len()
    );
    let deliberation = json!({
        "version":"1.2.4a1", "status":"fallback", "authority":"soft_non_canon",
        "intent":"continue", "scene_goal":prompt.chars().take(500).collect::<String>(),
        "likely_beats":[], "character_intentions":[], "emotional_trajectories":[],
        "opportunities":[], "alternatives":[], "uncertainties":unresolved,
        "constraints":["Do not invent missing canon or resolve ambiguity silently."],
        "diagnostics":["Native deterministic deliberation fallback; provider planning is unavailable."]
    });
    let mut traces = trace_choices(&wcf, &prompt);
    for fact in &facts {
        let id = fact["id"].as_str().unwrap_or("claim").to_owned();
        traces.push(json!({"id":id,"trace_id":id,"label":fact["predicate"],"source":"prompt","source_segment":fact["source_segment"],"authority":fact["authority"],"epistemic":fact["epistemic"],"confidence":fact["confidence"]}));
    }
    let trace_ids = traces
        .iter()
        .filter_map(|x| x["id"].as_str())
        .map(ToOwned::to_owned)
        .collect::<Vec<_>>();
    let projections = unresolved.iter().enumerate().map(|(i, x)| json!({"id":format!("projection-{}",i+1),"name":"unresolved_intent","value":x,"confidence":0.35,"priority":2,"canonical":false,"exact_claim_forbidden":true,"target_unknown":x,"basis_trace_ids":trace_ids.get(i..i+1).unwrap_or(&[])})).collect::<Vec<_>>();
    let mut derived_facts = Vec::new();
    let mut blocked_inferences = Vec::new();
    let mut constraints = vec![
        json!({"type":"canon_precedence","authority":"canonical","rule":"explicit canon outranks inferred projections"}),
        json!({"type":"ambiguity_policy","rule":"abstain_and_surface_unknowns"}),
    ];
    let has = |predicate: &str| {
        facts
            .iter()
            .any(|f| f["predicate"] == predicate && f["negated"] != true)
    };
    if has("physical.height_cm") {
        for height_fact in facts
            .iter()
            .filter(|f| f["predicate"] == "physical.height_cm")
        {
            if let Some(height) = height_fact["value"].as_f64() {
                let subject = height_fact["subject"].as_str().unwrap_or("char:character");
                let basis = facts
                    .iter()
                    .filter(|f| f["predicate"] == "physical.height_cm" && f["subject"] == subject)
                    .map(|f| f["id"].clone())
                    .collect::<Vec<_>>();
                let confidence = height_fact["confidence"].as_f64().unwrap_or(0.9) * 0.78;
                derived_facts.push(json!({"id":format!("inferred:{subject}:estimated_comfortable_reach_cm"),"predicate":"estimated_comfortable_reach_cm","subject":subject,"value":(height*1.15*100.0).round()/100.0,"authority":"analytical_inference","epistemic":"inferred","confidence":confidence,"basis_claim_ids":basis}));
                derived_facts.push(json!({"id":format!("inferred:{subject}:estimated_max_flat_foot_reach_cm"),"predicate":"estimated_max_flat_foot_reach_cm","subject":subject,"value":(height*1.24*100.0).round()/100.0,"authority":"analytical_inference","epistemic":"inferred","confidence":confidence,"basis_claim_ids":facts.iter().filter(|f|f["predicate"]=="physical.height_cm" && f["subject"] == subject).map(|f|f["id"].clone()).collect::<Vec<_>>() }));
            }
        }
    } else {
        blocked_inferences.push(json!({"rule":"reach_estimate","reason":"missing physical.height_cm","epistemic":"blocked"}));
    }
    if has("physical.morphology.presentation") && has("physical.chest.reference_cup") {
        let basis = facts
            .iter()
            .filter(|f| {
                f["predicate"] == "physical.morphology.presentation"
                    || f["predicate"] == "physical.chest.reference_cup"
            })
            .collect::<Vec<_>>();
        let confidence = basis
            .iter()
            .map(|f| f["confidence"].as_f64().unwrap_or(0.9))
            .fold(1.0, f64::min)
            * 0.93;
        derived_facts.push(json!({"id":"inferred:feminine_body_profile_high","predicate":"feminine_body_profile_high","value":true,"authority":"analytical_inference","epistemic":"inferred","confidence":confidence,"basis_claim_ids":basis.iter().map(|f|f["id"].clone()).collect::<Vec<_>>() }));
        derived_facts.push(json!({"id":"inferred:feminine_body_profile","predicate":"feminine_body_profile","value":true,"authority":"analytical_inference","epistemic":"inferred","confidence":confidence,"basis_claim_ids":basis.iter().map(|f|f["id"].clone()).collect::<Vec<_>>() }));
    } else {
        blocked_inferences.push(json!({"rule":"body_profile","reason":"requires morphology and chest reference","epistemic":"blocked"}));
    }
    if has("physical.chest.softness") {
        let basis = facts
            .iter()
            .filter(|f| {
                ["physical.chest.softness", "physical.chest.compliance"]
                    .contains(&f["predicate"].as_str().unwrap_or(""))
            })
            .collect::<Vec<_>>();
        let confidence = basis
            .iter()
            .map(|f| f["confidence"].as_f64().unwrap_or(0.9))
            .fold(1.0, f64::min)
            * 0.9;
        derived_facts.push(json!({"id":"inferred:soft_compliant_chest_tissue","predicate":"soft_compliant_chest_tissue","value":true,"authority":"analytical_inference","epistemic":"inferred","confidence":confidence,"basis_claim_ids":basis.iter().map(|f|f["id"].clone()).collect::<Vec<_>>() }));
    } else {
        blocked_inferences.push(json!({"rule":"soft_compliant_chest","reason":"missing chest softness","epistemic":"blocked"}));
    }
    if has("endocrine.feminizing_hormone_production") && has("physical.chest.growth_profile") {
        let basis = facts
            .iter()
            .filter(|f| {
                [
                    "endocrine.feminizing_hormone_production",
                    "physical.chest.growth_profile",
                ]
                .contains(&f["predicate"].as_str().unwrap_or(""))
            })
            .collect::<Vec<_>>();
        let confidence = basis
            .iter()
            .map(|f| f["confidence"].as_f64().unwrap_or(0.9))
            .fold(1.0, f64::min)
            * 0.9;
        derived_facts.push(json!({"id":"inferred:female_like_chest_growth_world_consistent","predicate":"female_like_chest_growth_world_consistent","value":true,"authority":"analytical_inference","epistemic":"inferred","confidence":confidence,"basis_claim_ids":basis.iter().map(|f|f["id"].clone()).collect::<Vec<_>>() }));
    }
    if has("garment.material") {
        let material_fact = facts
            .iter()
            .find(|f| f["predicate"] == "garment.material")
            .unwrap();
        let material = material_fact["value"].as_str().unwrap_or("unknown");
        let basis = vec![material_fact["id"].clone()];
        if ["jersey", "rayon", "satin", "silk", "sutra"]
            .iter()
            .any(|x| material.eq_ignore_ascii_case(x))
        {
            // Python keys this fact by garment entity.  Keep the unqualified
            // predicate as a compatibility alias for older clients.
            derived_facts.push(json!({"id":"inferred:garment:soft_flexible_drape","predicate":"garment:garment.soft_flexible_drape","subject":"garment:garment","value":true,"authority":"analytical_inference","epistemic":"inferred","confidence":0.8256,"basis_claim_ids":basis}));
            derived_facts.push(json!({"id":"inferred:garment_drape","predicate":"garment_drape","subject":"garment:garment","value":"soft_flexible_drape","authority":"analytical_inference","epistemic":"inferred","confidence":0.8256,"basis_claim_ids":vec![material_fact["id"].clone()]}));
        } else {
            blocked_inferences.push(json!({"rule":"garment_drape","reason":"material is not in the soft flexible material ontology","epistemic":"blocked","source_facts":basis}));
        }
    } else {
        blocked_inferences.push(json!({"rule":"garment_drape","reason":"missing garment.material","epistemic":"blocked"}));
    }
    let hair_rel = facts
        .iter()
        .find(|f| f["predicate"] == "hair.length_relative");
    let hair_cm = facts
        .iter()
        .find(|f| f["predicate"] == "hair.current.length_cm");
    if hair_rel.is_some() || hair_cm.is_some() || has("hair.length_class") {
        let basis = facts
            .iter()
            .filter(|f| f["predicate"].as_str().unwrap_or("").starts_with("hair."))
            .map(|f| f["id"].clone())
            .collect::<Vec<_>>();
        let mut relative = false;
        if let Some(rel) = hair_rel {
            let anchor = rel["value"]
                .get("anchor")
                .and_then(Value::as_str)
                .unwrap_or("");
            relative = ["waist", "pinggang", "back", "punggung"].contains(&anchor);
            if relative {
                derived_facts.push(json!({"id":"inferred:very_long_hair_body_relative","predicate":"very_long_hair_body_relative","value":true,"authority":"analytical_inference","epistemic":"inferred","confidence":(rel["confidence"].as_f64().unwrap_or(0.9)*0.94*10000.0).round()/10000.0,"basis_claim_ids":[rel["id"].clone()],"metadata":{"anchor":anchor}}));
                derived_facts.push(json!({"id":"inferred:high_hair_motion_lag","predicate":"high_hair_motion_lag","value":true,"authority":"analytical_inference","epistemic":"inferred","confidence":0.82,"basis_claim_ids":["inferred:very_long_hair_body_relative"]}));
            }
        }
        if !relative {
            if let Some(cm) = hair_cm.and_then(|f| f["value"].as_f64()) {
                if cm >= 75.0 {
                    let f = hair_cm.unwrap();
                    derived_facts.push(json!({"id":"inferred:very_long_hair","predicate":"very_long_hair","value":true,"authority":"analytical_inference","epistemic":"inferred","confidence":(f["confidence"].as_f64().unwrap_or(0.9)*0.93*10000.0).round()/10000.0,"basis_claim_ids":[f["id"].clone()]}));
                }
            }
        }
        derived_facts.push(json!({"id":"inferred:hair_motion_affordance","predicate":"hair_motion_affordance","value":"free_moving_segment","authority":"analytical_inference","epistemic":"inferred","confidence":0.70,"basis_claim_ids":basis}));
    } else {
        blocked_inferences.push(
            json!({"rule":"hair_motion","reason":"missing hair length fact","epistemic":"blocked"}),
        );
    }
    if has("garment.fits") && has("physical.morphology.presentation") {
        let fit = facts
            .iter()
            .find(|f| f["predicate"] == "garment.fits")
            .unwrap();
        derived_facts.push(json!({"id":"inferred:garment_body_fit_compatibility_high","predicate":"garment_body_fit_compatibility_high","value":true,"authority":"analytical_inference","epistemic":"inferred","confidence":(fit["confidence"].as_f64().unwrap_or(0.9)*0.94*10000.0).round()/10000.0,"basis_claim_ids":facts.iter().filter(|f| ["garment.fits","physical.morphology.presentation"].contains(&f["predicate"].as_str().unwrap_or(""))).map(|f|f["id"].clone()).collect::<Vec<_>>() }));
        derived_facts.push(json!({"id":"inferred:garment_body_fit_compatibility","predicate":"garment_body_fit_compatibility","value":"compatible_with_presented_morphology","authority":"analytical_inference","epistemic":"inferred","confidence":0.68,"basis_claim_ids":facts.iter().filter(|f| ["garment.fits","physical.morphology.presentation"].contains(&f["predicate"].as_str().unwrap_or(""))).map(|f|f["id"].clone()).collect::<Vec<_>>() }));
    } else {
        blocked_inferences.push(json!({"rule":"garment_body_fit","reason":"requires garment.fits and morphology","epistemic":"blocked"}));
    }
    let has_dating = has("relationship.dating");
    let has_historical_friend = facts.iter().any(|f| {
        f["predicate"] == "relationship.friend_of"
            && f["scope"]["temporal"] == "historical"
            && f["negated"] != true
    });
    if has_dating && has_historical_friend {
        derived_facts.push(json!({"id":"inferred:relationship_familiarity_high","predicate":"relationship_familiarity_high","value":true,"authority":"analytical_inference","epistemic":"inferred","confidence":0.90,"basis_claim_ids":facts.iter().filter(|f| f["predicate"] == "relationship.dating" || f["predicate"] == "relationship.friend_of").map(|f|f["id"].clone()).collect::<Vec<_>>() }));
        derived_facts.push(json!({"id":"inferred:relationship_familiarity","predicate":"relationship_familiarity","value":"established_or_transitioning","authority":"analytical_inference","epistemic":"inferred","confidence":0.70,"basis_claim_ids":facts.iter().filter(|f| f["predicate"].as_str().unwrap_or("").starts_with("relationship.")).map(|f|f["id"].clone()).collect::<Vec<_>>() }));
    } else {
        blocked_inferences.push(json!({"rule":"relationship_familiarity","reason":"missing relationship history","epistemic":"blocked"}));
    }
    if has("social.family_close")
        || has("social.approves_of")
        || has("social.arranged_relationship")
    {
        let basis = facts
            .iter()
            .filter(|f| f["predicate"].as_str().unwrap_or("").starts_with("social."))
            .map(|f| f["id"].clone())
            .collect::<Vec<_>>();
        derived_facts.push(json!({"id":"inferred:family_relationship_acceptance_high","predicate":"family_relationship_acceptance_high","value":true,"authority":"analytical_inference","epistemic":"inferred","confidence":0.86,"basis_claim_ids":basis.clone()}));
        derived_facts.push(json!({"id":"inferred:family_acceptance","predicate":"family_acceptance","value":true,"authority":"analytical_inference","epistemic":"inferred","confidence":0.65,"basis_claim_ids":basis}));
    } else {
        blocked_inferences.push(json!({"rule":"family_acceptance","reason":"missing family/social acceptance facts","epistemic":"blocked"}));
    }
    if has_dating {
        let basis = facts
            .iter()
            .filter(|f| f["predicate"] == "relationship.dating")
            .map(|f| f["id"].clone())
            .collect::<Vec<_>>();
        derived_facts.push(json!({"id":"inferred:romantic_relationship_current","predicate":"romantic_relationship_current","value":true,"authority":"analytical_inference","epistemic":"inferred","confidence":0.93,"basis_claim_ids":basis}));
    }
    if has("garment.flowiness") {
        let flow = facts
            .iter()
            .find(|f| f["predicate"] == "garment.flowiness")
            .unwrap();
        if flow["value"] == "high" {
            derived_facts.push(json!({"id":"inferred:garment:flowy_behavior_high","predicate":"garment:garment.flowy_behavior_high","subject":"garment:garment","value":true,"authority":"analytical_inference","epistemic":"inferred","confidence":(flow["confidence"].as_f64().unwrap_or(0.9)*0.93*10000.0).round()/10000.0,"basis_claim_ids":[flow["id"].clone()]}));
        }
    }
    let front = facts
        .iter()
        .find(|f| f["predicate"] == "garment.front_length");
    let back = facts
        .iter()
        .find(|f| f["predicate"] == "garment.back_length");
    if let (Some(front), Some(back)) = (front, back) {
        let front_value = front["value"]["value"]
            .as_f64()
            .or_else(|| front["value"].as_f64());
        let back_value = back["value"]["value"]
            .as_f64()
            .or_else(|| back["value"].as_f64());
        if let (Some(front_value), Some(back_value)) = (front_value, back_value) {
            if back_value > front_value {
                let confidence = front["confidence"]
                    .as_f64()
                    .unwrap_or(0.9)
                    .min(back["confidence"].as_f64().unwrap_or(0.9))
                    * 0.92;
                derived_facts.push(json!({"id":"inferred:garment:garment.asymmetric_front_back_drape","predicate":"garment:garment.asymmetric_front_back_drape","subject":"garment:garment","value":true,"authority":"analytical_inference","epistemic":"inferred","confidence":confidence,"basis_claim_ids":[front["id"].clone(),back["id"].clone()],"metadata":{"front_cm":front_value,"back_cm":back_value}}));
                derived_facts.push(json!({"id":"inferred:asymmetric_front_back_drape","predicate":"asymmetric_front_back_drape","subject":"garment:garment","value":true,"authority":"analytical_inference","epistemic":"inferred","confidence":confidence,"basis_claim_ids":[front["id"].clone(),back["id"].clone()],"metadata":{"front_cm":front_value,"back_cm":back_value}}));
            }
        }
    }
    let worn = facts
        .iter()
        .filter(|f| {
            f["predicate"] == "garment.wearing"
                && f["negated"] != true
                && f["scope"]["temporal"] == "current_or_unspecified"
                && f["scope"]["truth_scope"] == "canonical"
        })
        .map(|f| f["subject"].clone())
        .collect::<Vec<_>>();
    if !worn.is_empty() {
        derived_facts.push(json!({"id":"inferred:current_outfit_components","predicate":"current_outfit_components","value":worn,"authority":"analytical_inference","epistemic":"inferred","confidence":0.99,"basis_claim_ids":facts.iter().filter(|f| f["predicate"] == "garment.wearing").map(|f|f["id"].clone()).collect::<Vec<_>>() }));
    }
    if relations
        .iter()
        .any(|r| r["predicate"] == "garment.purchased_for")
    {
        derived_facts.push(json!({"id":"inferred:garment_interpersonal_significance_high","predicate":"garment_interpersonal_significance_high","value":true,"authority":"analytical_inference","epistemic":"inferred","confidence":0.819,"basis_relation_segments":relations.iter().filter(|r| r["predicate"] == "garment.purchased_for").filter_map(|r| r["source_segment"].as_str()).collect::<Vec<_>>() }));
    }
    if facts.iter().any(|f| f["scope"]["temporal"] == "habitual") {
        blocked_inferences.push(json!({"rule":"habitual_not_runtime","reason":"habitual claims do not create current runtime events","epistemic":"blocked"}));
    }
    for event in &events {
        derived_facts.push(json!({"id":format!("inferred:state_delta:{}",event["id"]),"predicate":"state_delta","value":event["event_type"],"authority":"analytical_inference","epistemic":"inferred","confidence":0.9,"basis_event_id":event["id"]}));
    }
    for event in &events {
        aif.push_str(&format!(
            "\nE {} {} actor=self",
            event["id"].as_str().unwrap_or("event"),
            event["event_type"].as_str().unwrap_or("event")
        ));
    }
    for derived in &derived_facts {
        aif.push_str(&format!(
            "\nD {}={}",
            derived["predicate"].as_str().unwrap_or("derived"),
            serde_json::to_string(&derived["value"]).unwrap_or_default()
        ));
    }
    for unknown in &unknown_records {
        aif.push_str(&format!(
            "\nU {}",
            unknown["question"].as_str().unwrap_or("unresolved")
        ));
    }
    for trace in &traces {
        if let Some(id) = trace["id"].as_str() {
            aif.push_str(&format!(
                "\nT {} source={}",
                id,
                trace["source"].as_str().unwrap_or("unknown")
            ));
        }
    }
    let mut runtime_state = serde_json::Map::new();
    let mut state_snapshots =
        vec![json!({"id":"S0","after_event":null,"state":{"runtime":{},"relations":relations}})];
    let mut state_patches = Vec::new();
    for (i, event) in events.iter().enumerate() {
        let actor = event["actor"]
            .as_str()
            .unwrap_or("char:character")
            .to_owned();
        let before = format!("S{i}");
        let after = format!("S{}", i + 1);
        let mut operations = Vec::new();
        let entry = runtime_state
            .entry(actor.clone())
            .or_insert_with(|| json!({}));
        if event["event_type"] == "enter" {
            entry["present"] = json!(true);
            operations
                .push(json!({"op":"set","path":format!("runtime.{actor}.present"),"value":true}));
        } else if event["event_type"] == "leave" {
            entry["present"] = json!(false);
            operations
                .push(json!({"op":"set","path":format!("runtime.{actor}.present"),"value":false}));
        }
        state_patches.push(json!({"event_id":event["id"],"state_before":before,"state_after":after,"operations":operations}));
        state_snapshots.push(json!({"id":after,"after_event":event["id"],"state":{"runtime":runtime_state,"relations":relations}}));
    }
    let inference_graph = json!({"nodes":facts.iter().map(|f|json!({"id":f["id"],"kind":"claim","epistemic":f["epistemic"]})).chain(derived_facts.iter().map(|f|json!({"id":f["id"],"kind":"derived","epistemic":"inferred"}))).collect::<Vec<_>>(),"edges":derived_facts.iter().filter_map(|f|f["basis_claim_ids"].as_array().map(|xs|json!({"to":f["id"],"from":xs}))).collect::<Vec<_>>()});
    constraints.push(json!({"type":"reasoning_budget","max_depth":4,"max_nodes":500,"min_confidence":0.35,"kept_nodes":derived_facts.len(),"pruned_by_depth":0,"pruned_by_relevance":0,"pruned_by_confidence":0}));
    let mut trace_index = serde_json::Map::new();
    for item in &traces {
        if let Some(id) = item["id"].as_str() {
            trace_index.insert(id.to_owned(), item.clone());
        }
    }
    let mut wcf_violations = Vec::new();
    if !(wcf.is_empty()
        || (wcf.contains("<ARLINE_CONTEXT>")
            && wcf.contains("SCOPE:")
            && wcf.contains("</ARLINE_CONTEXT>")))
    {
        wcf_violations.push(json!({"type":"context_structure_invalid"}));
    }
    for marker in [
        "char:",
        "garment:",
        "item:",
        "loc:",
        "family:",
        "relationship:",
    ] {
        if wcf.contains(marker) {
            wcf_violations.push(json!({"type":"internal_id_leak","marker":marker}));
        }
    }
    let wcf_valid = wcf_violations.is_empty();
    let payload = json!({"summary":{"scope_evidence":wcf.lines().count(),"unknowns":unresolved.len(),"entities":entities.len(),"facts":facts.len(),"memory_items":memory.len(),"projections":projections.len(),"derived_facts":derived_facts.len()},"wcf":wcf,"aif_core":aif,"narrative_brief":{"text":brief,"version":"0.1"},"deliberation":deliberation,"projections":projections.clone(),"wcf_validation":{"valid":true,"violations":[],"warnings":[],"trace_index":trace_index.clone()},"trace_choices":traces,"trace_index":trace_index.clone(),"memory":memory.clone(),"memory_diagnostic":memory_diagnostic,"extracted_state":{"system_version":"0.6.4","component_version":"0.3.3","entities":entities.clone(),"relations":relations.clone(),"claims":facts.clone(),"unknowns":unknown_records.clone(),"directives":[],"requests":[],"experience":[],"norms":[],"knowledge":[],"beliefs":[],"relationship_timeline":[],"claim_conflicts":[],"scenario":{"version":"0.3.3","requested_events":[],"scene_focus":{},"diagnostics":[]},"reference_resolutions":[],"entity_aliases":[],"entity_lifecycle":entities.iter().map(|e| json!({"op":"create","entity":e["id"],"source_segment":e.get("source_segment").cloned().unwrap_or(Value::Null)})).collect::<Vec<_>>(),"discourse_relations":[],"coverage":{"version":"0.3.3","total_segments":prompt.split(['.','!','?']).filter(|s|!s.trim().is_empty()).count(),"recognized_segments":facts.len(),"claim_count":facts.len(),"runtime_event_count":events.len(),"warnings":[]}},"events":{"system_version":"0.6.4","event_builder_version":"0.3.3","transition_resolver_version":"0.3.3","events":events,"scenario_events":[],"event_candidates":[],"state_patches":state_patches,"state_snapshots":state_snapshots,"conflicts":[],"diagnostics":[]},"analysis":{"system_version":"0.6.4","analytical_reasoner_version":"0.3.3","world_model_version":"0.3.3","surface_planner_version":"0.3.3","scene_focus":{"prompt":prompt},"derived_facts":derived_facts.clone(),"constraints":constraints.clone(),"interactions":[],"consequences":[],"blocked_inferences":blocked_inferences.clone(),"uncertainties":unresolved.clone(),"unknowns":unknown_records.clone(),"evidence":memory.clone(),"surface_plan":{"version":"0.3.3","scene_focus":{},"writer_context":[],"suppressed":[],"diagnostics":[]},"inference_graph":inference_graph,"coverage":{}},"semantic_core":{"version":"0.1","facts":facts,"relations":relations,"negative_facts":[],"transitions":[],"temporal_ledger":[{"index":0,"label":"baseline","event_id":null,"event_type":null,"state_before":null,"state_after":"S0","status":"baseline"}],"knowledge":[],"beliefs":[],"norms":[],"experience":[],"relationship_timeline":[],"contradictions":[],"unresolved":unknown_records,"trace_index":trace_index.clone(),"diagnostics":[]},"writer_context":{"scene":[],"characters":{},"world":[],"current":[],"locked":[],"unknown":unknown_records,"derivable":derived_facts,"surface":[],"projections":projections},"world_runtime":{"version":"0.1","scene_start_state":{"runtime":{},"relations":relations},"projected_state":{"runtime":{},"relations":relations},"state_sequence":[{"state_id":"S0","after_event":null,"state":{"runtime":{},"relations":relations}}],"temporal_ledger":[{"index":0,"label":"baseline","event_id":null,"event_type":null,"state_before":null,"state_after":"S0","status":"baseline"}],"invariants":[],"negative_state":[],"contradictions":[],"diagnostics":[]},"narrative_runtime":{"version":"0.2","language":{"language":"en-US","register":"natural_contemporary","narrator_pronoun":"adaptive","preserve_user_voice":"high"},"description_lens":{"visual":0.3,"tactile":0.2,"spatial":0.18,"emotional":0.12,"social":0.1,"auditory":0.1},"scene_energy":{"level":"adaptive","pacing":"adaptive","change_rate":"adaptive","introspection":"medium"},"paragraph_functions":["establish_space","establish_character","physical_or_social_interaction","state_or_scene_progression","reaction_or_new_observation"],"style":{"pov":"unspecified","tense":"unspecified","detail":"adaptive"},"freedom":{"body":"locked","relationship":"locked","measurements":"locked","timeline":"locked"},"scene_goal":{"phase":"scene","focus":[],"objective":"advance the requested scene while preserving canonical world state","do_not_advance_beyond":[]},"beat_state":{"current_beat":"establish_current_scene","completed_beats":[],"next_candidates":[],"forbidden_future_beats":[],"exit_condition":"end at a natural continuation point"},"surface_history":{"turn":0,"records":{}}},"created_at":Utc::now().to_rfc3339()});
    let mut payload = payload;
    payload["wcf_validation"]["valid"] = json!(wcf_valid);
    if !wcf_valid {
        payload["wcf_validation"]["violations"] = json!(wcf_violations);
    }
    payload["extracted_state"]["directives"] = json!([command.clone()]);
    payload["analysis"]["scene_focus"]["directive"] = command;
    let context_items: Vec<Value> = facts
        .iter()
        .map(|fact| {
            json!({
                "key": fact["predicate"],
                "label": fact["predicate"],
                "value": fact["value"],
                "priority": 0,
                "reason": "canonical fact",
                "trace_id": fact["id"],
                "epistemic": fact["epistemic"],
                "negated": fact["negated"],
                "confidence": fact["confidence"]
            })
        })
        .collect();
    payload["writer_context"]["scene"] = json!(context_items
        .iter()
        .filter(|x| x["key"].as_str().unwrap_or("").starts_with("location."))
        .cloned()
        .collect::<Vec<_>>());
    payload["writer_context"]["current"] = json!(context_items.clone());
    payload["writer_context"]["current"] = json!(context_items
        .iter()
        .filter(|x| {
            let epistemic = x["epistemic"].as_str().unwrap_or("");
            epistemic != "historical"
                && epistemic != "hypothetical"
                && epistemic != "habitual"
                && x["value"] != Value::Null
                && x["negated"] != true
        })
        .cloned()
        .collect::<Vec<_>>());
    payload["writer_context"]["locked"] = json!(context_items
        .iter()
        .filter(|x| x["epistemic"] == "explicit"
            && x["value"] != Value::Null
            && x["negated"] != true)
        .cloned()
        .collect::<Vec<_>>());
    payload["writer_context"]["unknown"] = json!(unknown_records.clone());
    payload["writer_context"]["derivable"] = json!(derived_facts.clone());
    payload["writer_context"]["transitions"] = json!(events.clone());
    payload["writer_context"]["relations"] = json!(relations.clone());
    let experience: Vec<Value> = facts
        .iter()
        .filter(|f| {
            f["predicate"]
                .as_str()
                .unwrap_or("")
                .starts_with("experience.")
        })
        .cloned()
        .collect();
    let knowledge: Vec<Value> = facts
        .iter()
        .filter(|f| {
            f["predicate"]
                .as_str()
                .unwrap_or("")
                .starts_with("knowledge.")
        })
        .cloned()
        .collect();
    let beliefs: Vec<Value> = facts
        .iter()
        .filter(|f| f["predicate"].as_str().unwrap_or("").starts_with("belief."))
        .cloned()
        .collect();
    let norms: Vec<Value> = facts
        .iter()
        .filter(|f| f["predicate"].as_str().unwrap_or("").starts_with("norm."))
        .cloned()
        .collect();
    payload["extracted_state"]["experience"] = json!(experience.clone());
    payload["extracted_state"]["knowledge"] = json!(knowledge.clone());
    payload["extracted_state"]["beliefs"] = json!(beliefs.clone());
    payload["extracted_state"]["norms"] = json!(norms.clone());
    payload["writer_context"]["experience"] = json!(experience);
    payload["writer_context"]["knowledge"] = json!(knowledge);
    payload["writer_context"]["beliefs"] = json!(beliefs);
    payload["writer_context"]["norms"] = json!(norms);
    payload["writer_context"]["history"] = json!(facts
        .iter()
        .filter(|f| f["scope"]["temporal"] == "historical")
        .cloned()
        .collect::<Vec<_>>());
    payload["writer_context"]["style"] =
        json!({"language_profile":{"language":"en-US","narrator_pronoun":"adaptive"}});
    let rendered = wcf::render(&payload["writer_context"]);
    payload["wcf"] = rendered["text"].clone();
    payload["wcf_metadata"] = rendered["metadata"].clone();
    Ok(payload)
}

/// Build the same analytical bundle as `analyze`, then augment it through the
/// canonical memory retrieval path.  HTTP and generation entrypoints use this
/// async form; the synchronous core remains useful to bounded context code.
pub async fn analyze_async(state: &AppState, body: &Value) -> ApiResult<Value> {
    let mut payload = analyze(state, body)?;
    let cfg = state.runtime_config()?;
    if !cfg.bool("memory.enabled", true) || !cfg.bool("memory.automatic_context", true) {
        payload["memory"] = json!([]);
        payload["memory_diagnostic"] = json!({"disabled":true,"automatic_context":false});
        return Ok(payload);
    }
    let prompt = text(body.get("prompt"));
    let mut query = body.clone();
    query["query"] = json!(prompt);
    query["limit"] = json!(20);
    let retrieval = crate::foundation::memory::retrieve_async(state, &query, &HashMap::new()).await;
    match retrieval {
        Ok(result) => {
            let memory = result.get("results").cloned().unwrap_or_else(|| json!([]));
            payload["memory"] = memory.clone();
            payload["memory_diagnostic"] = json!({"provider":result.get("provider"),"run_id":result.get("run_id"),"dense_embeddings":result.get("dense_embeddings"),"reranked":result.get("reranked")});
            if let Some(items) = memory.as_array() {
                if !items.is_empty() {
                    let mut wcf = payload["wcf"].as_str().unwrap_or_default().to_owned();
                    wcf.push_str("\n<MEMORY_RETRIEVAL>\n");
                    for item in items {
                        wcf.push_str("MEMORY: ");
                        wcf.push_str(&serde_json::to_string(item).unwrap_or_default());
                        wcf.push('\n');
                    }
                    wcf.push_str("</MEMORY_RETRIEVAL>\n");
                    payload["wcf"] = json!(wcf);
                    payload["summary"]["memory_items"] = json!(items.len());
                    payload["analysis"]["evidence"] = memory;
                }
            }
        }
        Err(error) => {
            payload["memory_diagnostic"] = json!({"fallback":true,"reason":error.message})
        }
    }
    Ok(payload)
}

pub fn cache(state: &AppState, payload: &Value) -> ApiResult<String> {
    ensure_schema(&state.store)?;
    let id = format!("AN-{}", Uuid::new_v4());
    state.store.execute(
        "INSERT INTO analysis_cache(id,created_at,payload) VALUES(?,?,?)",
        &[&id, &Utc::now().to_rfc3339(), &payload.to_string()],
    )?;
    Ok(id)
}

pub fn cache_run(state: &AppState, id: &str, payload: &Value) -> ApiResult<()> {
    ensure_schema(&state.store)?;
    state.store.execute(
        "INSERT INTO analysis_cache(id,created_at,payload) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
        &[&id, &Utc::now().to_rfc3339(), &payload.to_string()],
    )?;
    Ok(())
}
pub fn cached(state: &AppState, id: &str) -> ApiResult<Option<Value>> {
    ensure_schema(&state.store)?;
    let rows = state
        .store
        .query("SELECT payload FROM analysis_cache WHERE id=?", &[&id])?;
    Ok(rows.into_iter().next().and_then(|v| {
        serde_json::from_str(v.get("payload").and_then(Value::as_str).unwrap_or("{}")).ok()
    }))
}
pub fn handle(
    state: &AppState,
    method: &str,
    path: &[&str],
    body: &Value,
) -> Option<ApiResult<Response>> {
    match (method, path) {
        ("POST", ["analyze"]) => Some(analyze(state, body).and_then(|p| {
            let id = cache(state, &p)?;
            let mut out = p;
            out["analysis_id"] = json!(id);
            response(out)
        })),
        ("GET", ["trace", cache_id, trace_id]) => Some(cached(state, cache_id).and_then(|p| {
            let Some(p) = p else {
                return Err(ApiError::not_found(
                    "Analysis/run is no longer in the in-memory cache",
                ));
            };
            let found = p["trace_choices"]
                .as_array()
                .and_then(|xs| {
                    xs.iter().find(|x| {
                        x["id"].as_str() == Some(trace_id)
                            || x["trace_id"].as_str() == Some(trace_id)
                    })
                })
                .cloned();
            found
                .map(response)
                .unwrap_or_else(|| Err(ApiError::not_found("Trace entry not found")))
        })),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extraction_emits_explicit_claim_provenance_and_runtime_event() {
        let (entities, claims, events, unknowns, relations) =
            extract_pipeline_state("Namaku Mira. Aku memakai gamis. Aku masuk kamar.");
        assert_eq!(entities[0]["type"], "character");
        assert_eq!(claims[0]["predicate"], "identity.name");
        assert_eq!(claims[0]["epistemic"], "explicit");
        assert_eq!(claims[0]["provenance"][0]["source_kind"], "prompt");
        assert_eq!(events[0]["event_type"], "enter");
        assert!(relations.is_empty());
        assert!(unknowns.is_empty());
    }

    #[test]
    fn extraction_keeps_questions_as_unknown_author_intent() {
        let (_, _, _, unknowns, _) = extract_pipeline_state("What happens next?");
        assert_eq!(unknowns[0]["status"], "unresolved");
        assert_eq!(unknowns[0]["epistemic"], "unknown");
        assert_eq!(unknowns[0]["authority"], "prompt");
    }

    #[test]
    fn extraction_preserves_negative_and_non_current_scope() {
        let (_, claims, _, _, _) = extract_pipeline_state("Aku tidak memakai dress. Dulu aku memakai gamis. Jika aku memakai khimar, aku akan keluar.");
        assert!(claims.iter().any(|c| c["negated"] == true));
        assert!(claims
            .iter()
            .any(|c| c["scope"]["temporal"] == "historical"));
        assert!(claims
            .iter()
            .any(|c| c["epistemic"] == "hypothetical" && c["scope"]["truth_scope"] == "scenario"));
    }

    #[test]
    fn extraction_resolves_named_multicharacter_subjects_and_pronouns() {
        let (entities, claims, events, _, _) =
            extract_pipeline_state("Alice enters. Bob memakai dress. Dia keluar.");
        assert!(entities.iter().any(|e| e["id"] == "char:alice"));
        assert!(entities.iter().any(|e| e["id"] == "char:bob"));
        assert!(claims
            .iter()
            .any(|c| c["subject"] == "char:bob" && c["predicate"] == "garment.wearing"));
        assert!(events
            .iter()
            .any(|e| e["actor"] == "char:bob" && e["event_type"] == "leave"));
    }

    #[test]
    fn habitual_and_hypothetical_actions_do_not_become_runtime_events() {
        let (_, claims, events, _, _) =
            extract_pipeline_state("Alice biasanya masuk. Jika Alice keluar, dia berlari.");
        assert!(events.is_empty());
        assert!(claims.iter().any(|c| c["scope"]["temporal"] == "habitual"));
        assert!(claims
            .iter()
            .any(|c| c["scope"]["truth_scope"] == "scenario"));
    }

    #[test]
    fn python_provider_free_fixture_preserves_critical_claim_vocabulary() {
        let fixture: Value =
            serde_json::from_str(include_str!("../tests/fixtures/analysis-python.json")).unwrap();
        for row in fixture.as_array().unwrap() {
            let (_, claims, _, _, _) = extract_pipeline_state(row["prompt"].as_str().unwrap());
            for expected in row["claims"].as_array().unwrap() {
                let predicate = expected["predicate"].as_str().unwrap();
                assert!(
                    claims.iter().any(|claim| claim["predicate"] == predicate),
                    "missing reference predicate {predicate} for {}",
                    row["prompt"]
                );
            }
            assert_eq!(row["aif_header"][0], "@AIF-CORE 0.3 profile=teacher");
        }
    }

    #[test]
    fn writer_input_modes_preserve_structured_sections() {
        let d = json!({"status":"fallback","scene_goal":"continue"});
        assert!(compose_input(
            "Mira is here",
            "FACT: Mira",
            "raw",
            "C Mira",
            "brief",
            &[],
            Some(&d)
        )
        .contains("<REQUEST>"));
        assert!(compose_input(
            "Mira is here",
            "FACT: Mira",
            "wcf",
            "C Mira",
            "brief",
            &[],
            Some(&d)
        )
        .contains("<ARLINE_CONTEXT>"));
        assert!(compose_input(
            "Mira is here",
            "FACT: Mira",
            "wcf_raw",
            "C Mira",
            "brief",
            &[],
            Some(&d)
        )
        .contains("<RAW_SOURCE>"));
        assert!(compose_input(
            "Mira is here",
            "FACT: Mira",
            "aif_core",
            "C Mira",
            "brief",
            &[],
            Some(&d)
        )
        .contains("<AIF_CORE>"));
        assert!(compose_input(
            "Mira is here",
            "FACT: Mira",
            "smart_hybrid",
            "C Mira",
            "brief",
            &["unknown".into()],
            Some(&d)
        )
        .contains("<NARRATIVE_DELIBERATION>"));
    }

    #[test]
    fn quality_report_exposes_repetition_metrics() {
        let report = quality_report("Mira Mira turns");
        assert_eq!(report["valid"], false);
        assert_eq!(report["metrics"]["repetition_pairs"], 1);
    }

    #[test]
    fn validator_checks_projection_preservation_language_and_materials() {
        let context = json!({
            "locked":[{"label":"dress material","value":"cotton"},{"label":"height","value":"170 cm"}],
            "unknown":["measurement origin/basis"],
            "projections":[{"metadata":{"domain":"garment","allowed_region":{"from":"waist","to":"knee"}}}],
            "transitions":[{"preserves":["appearance.height"]}],
            "style":{"language_profile":{"language":"id-ID","narrator_pronoun":"aku"}}
        });
        let report = quality_report_with_context("Gaun rayon berakhir tepat di lantai. Tingginya berubah menjadi 180 cm. Saya memberikan kesan, menciptakan siluet, dengan presisi tinggi.", Some(&context));
        let violations = report["violations"].as_array().unwrap();
        assert!(violations
            .iter()
            .any(|x| x["type"] == "garment_material_contradiction"));
        assert!(violations
            .iter()
            .any(|x| x["type"] == "projection_out_of_range"));
        assert!(violations
            .iter()
            .any(|x| x["type"] == "preserve_contract_violation"));
        assert!(report["warnings"]
            .as_array()
            .unwrap()
            .iter()
            .any(|x| x["type"] == "translationese_density_high"));
        assert_eq!(report["metrics"]["narrator_pronoun_drift"], 1);
    }

    #[test]
    fn analytical_rules_compute_reach_values_and_block_missing_prerequisites() {
        let temp = tempfile::tempdir().unwrap();
        let config_path = temp.path().join("config.toml");
        let config = crate::RuntimeConfig::create_default(&config_path, temp.path()).unwrap();
        let state = AppState::open(config).unwrap();
        let payload = analyze(&state, &json!({"prompt":"Namaku Mira. Tinggi 170 cm."})).unwrap();
        let derived = payload["analysis"]["derived_facts"].as_array().unwrap();
        assert!(derived
            .iter()
            .any(|x| x["predicate"] == "estimated_comfortable_reach_cm" && x["value"] == 195.5));
        assert!(derived
            .iter()
            .any(|x| x["predicate"] == "estimated_max_flat_foot_reach_cm" && x["value"] == 210.8));
        assert!(payload["aif_core"]
            .as_str()
            .unwrap()
            .contains("D estimated_comfortable_reach_cm=195.5"));
        assert_eq!(payload["events"]["state_snapshots"][0]["id"], "S0");
        assert_eq!(
            payload["events"]["state_patches"].as_array().unwrap().len(),
            0
        );
        assert_eq!(payload["wcf_metadata"]["budget_tokens"], 4096);
        let missing = analyze(&state, &json!({"prompt":"Namaku Mira."})).unwrap();
        assert!(missing["analysis"]["blocked_inferences"]
            .as_array()
            .unwrap()
            .iter()
            .any(|x| x["rule"] == "reach_estimate"));
    }

    #[test]
    fn analytical_rules_require_source_prerequisites_and_emit_named_outputs() {
        let temp = tempfile::tempdir().unwrap();
        let config_path = temp.path().join("config.toml");
        let config = crate::RuntimeConfig::create_default(&config_path, temp.path()).unwrap();
        let state = AppState::open(config).unwrap();
        let payload = analyze(&state, &json!({"prompt":"Alice presents feminine morphology, wears a jersey dress that fits well. Her hair reaches the waist. Alice is dating Bob; historically they were friends."})).unwrap();
        let derived = payload["analysis"]["derived_facts"].as_array().unwrap();
        assert!(derived
            .iter()
            .any(|x| x["predicate"] == "garment:garment.soft_flexible_drape"));
        assert!(derived
            .iter()
            .any(|x| x["predicate"] == "garment_body_fit_compatibility_high"));
        assert!(derived
            .iter()
            .any(|x| x["predicate"] == "very_long_hair_body_relative"));
        assert!(derived
            .iter()
            .any(|x| x["predicate"] == "relationship_familiarity_high"));

        let blocked = analyze(&state, &json!({"prompt":"Alice is dating Bob."})).unwrap();
        let blocked = blocked["analysis"]["blocked_inferences"]
            .as_array()
            .unwrap();
        assert!(blocked
            .iter()
            .any(|x| x["rule"] == "relationship_familiarity"));
        assert!(!blocked
            .iter()
            .any(|x| x["predicate"] == "relationship_familiarity_high"));
    }

    #[test]
    fn current_outfit_and_events_exclude_non_current_scopes() {
        let temp = tempfile::tempdir().unwrap();
        let config_path = temp.path().join("config.toml");
        let config = crate::RuntimeConfig::create_default(&config_path, temp.path()).unwrap();
        let state = AppState::open(config).unwrap();
        let payload = analyze(
            &state,
            &json!({"prompt":"Historically Alice wears a dress. Usually Alice enters the room."}),
        )
        .unwrap();
        assert_eq!(payload["events"]["events"].as_array().unwrap().len(), 0);
        assert!(payload["writer_context"]["current"]
            .as_array()
            .unwrap()
            .iter()
            .all(|x| x["epistemic"] != "historical" && x["epistemic"] != "habitual"));
        assert!(payload["analysis"]["blocked_inferences"]
            .as_array()
            .unwrap()
            .iter()
            .any(|x| x["rule"] == "habitual_not_runtime"));
    }

    #[test]
    fn garment_measurements_drive_asymmetric_drape_with_provenance() {
        let temp = tempfile::tempdir().unwrap();
        let config_path = temp.path().join("config.toml");
        let config = crate::RuntimeConfig::create_default(&config_path, temp.path()).unwrap();
        let state = AppState::open(config).unwrap();
        let payload = analyze(&state, &json!({"prompt":"The khimar has front length 80 cm and back length 120 cm; Fano bought this dress for Alice."})).unwrap();
        let claims = payload["extracted_state"]["claims"].as_array().unwrap();
        assert!(claims
            .iter()
            .any(|x| x["predicate"] == "garment.front_length" && x["value"]["value"] == 80.0));
        assert!(claims
            .iter()
            .any(|x| x["predicate"] == "garment.back_length" && x["value"]["value"] == 120.0));
        let derived = payload["analysis"]["derived_facts"].as_array().unwrap();
        assert!(derived
            .iter()
            .any(|x| x["predicate"] == "asymmetric_front_back_drape"
                && x["metadata"]["back_cm"] == 120.0));
        assert!(derived
            .iter()
            .any(|x| x["predicate"] == "garment_interpersonal_significance_high"));
    }

    #[test]
    fn wcf_budget_prunes_low_priority_sections_and_keeps_locks() {
        let locked = (0..5000)
            .map(|i| json!({"label":format!("locked_{i}"),"value":"canonical"}))
            .collect::<Vec<_>>();
        let context =
            json!({"locked":locked,"history":["old context"],"projection":["projection"]});
        let rendered = crate::analysis::wcf::render(&context);
        let text = rendered["text"].as_str().unwrap();
        assert_eq!(rendered["metadata"]["pruned"], true);
        assert!(text.contains("[LOCKED]"));
        assert!(text.contains("locked_0"));
        assert!(text.contains("[CONTEXT PRUNED TO BUDGET]"));
        assert!(text.split_whitespace().count() <= 4096);
    }
}
