use serde_json::{json, Value};
use std::collections::HashMap;

fn words(text: &str) -> Vec<String> {
    text.split(|c: char| !c.is_alphanumeric() && c != '\'')
        .filter(|s| !s.is_empty())
        .map(|s| s.to_ascii_lowercase())
        .collect()
}

pub fn analyze(text: &str) -> Value {
    let tokens = words(text);
    let mut issues = Vec::new();
    let duplicate = tokens.windows(2).filter(|p| p[0] == p[1]).count();
    if duplicate > 0 {
        issues.push(json!({"kind":"duplicate_word","severity":"warning","message":"Adjacent duplicate words were detected.","count":duplicate}));
    }
    let first = tokens
        .iter()
        .filter(|w| ["aku", "saya", "ku", "i", "me", "my", "kami", "kita"].contains(&w.as_str()))
        .count();
    let second = tokens
        .iter()
        .filter(|w| ["kamu", "kau", "anda", "you", "your", "mu"].contains(&w.as_str()))
        .count();
    if first >= 4 && second >= 2 {
        issues.push(json!({"kind":"possible_pov_shift","severity":"warning","message":"Repeated first and second person markers may indicate POV drift.","first_person_markers":first,"second_person_markers":second}));
    }
    let lower = text.to_ascii_lowercase();
    let afternoon = lower.contains("sore") || lower.contains("afternoon");
    let night = lower.contains("malam") || lower.contains("night");
    if afternoon
        && night
        && ![
            "kemudian",
            "setelah itu",
            "later",
            "afterward",
            "menjelang malam",
        ]
        .iter()
        .any(|x| lower.contains(x))
    {
        issues.push(json!({"kind":"possible_time_jump","severity":"info","message":"Afternoon and night appear without a transition."}));
    }
    let intensifiers = [
        "sangat",
        "benar-benar",
        "sepenuhnya",
        "sempurna",
        "memukau",
        "really",
        "very",
        "completely",
        "perfectly",
        "stunning",
    ];
    let intensifier_hits = intensifiers
        .iter()
        .map(|x| lower.matches(x).count())
        .sum::<usize>();
    if intensifier_hits >= 4 {
        issues.push(json!({"kind":"generic_intensifier_overuse","severity":"info","message":"Generic intensifiers are overused.","count":intensifier_hits}));
    }
    let mut counts = HashMap::<String, usize>::new();
    for word in tokens.iter().filter(|w| {
        w.len() > 2
            && ![
                "yang", "dan", "the", "and", "untuk", "dengan", "this", "that",
            ]
            .contains(&w.as_str())
    }) {
        *counts.entry(word.clone()).or_default() += 1;
    }
    let repeated: Vec<Value> = counts
        .iter()
        .filter(|(_, n)| **n >= 5)
        .map(|(w, n)| json!({"term":w,"count":n}))
        .collect();
    if !repeated.is_empty() {
        issues.push(json!({"kind":"lexical_repetition","severity":"warning","message":"Content words repeat frequently.","terms":repeated}));
    }
    let score = issues
        .iter()
        .map(|x| if x["severity"] == "warning" { 12 } else { 5 })
        .fold(100i64, |a, b| a - b)
        .max(0);
    json!({"version":"1.1-surface-1","score":score,"issue_count":issues.len(),"issues":issues,"metrics":{"word_count":tokens.len(),"sentence_count":text.split(['.','!','?','\n']).filter(|x|!x.trim().is_empty()).count(),"first_person_markers":first,"second_person_markers":second,"intensifier_hits":intensifier_hits},"policy":"flag_surface_and_narrative_suspicion_without_rewriting_story_facts"})
}
