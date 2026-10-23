use serde_json::Value;

fn value(v: &Value) -> String {
    match v {
        Value::Null => "unknown".into(),
        Value::Bool(b) => {
            if *b {
                "yes".into()
            } else {
                "no".into()
            }
        }
        Value::String(s) => s.clone(),
        Value::Array(a) => a.iter().map(value).collect::<Vec<_>>().join(", "),
        _ => v.to_string(),
    }
}
fn section(out: &mut String, name: &str, lines: &[String]) {
    if lines.is_empty() {
        return;
    }
    out.push_str(&format!("[{name}]\n"));
    for line in lines {
        out.push_str("- ");
        out.push_str(line);
        out.push('\n');
    }
    out.push('\n');
}

pub fn render(ctx: &Value) -> Value {
    let mut text = String::from("@ARLINE-WRITER-CONTEXT 0.2\n\n");
    let mut sections = Vec::new();
    let items = |key: &str| -> Vec<String> {
        ctx.get(key)
            .and_then(Value::as_array)
            .map(|a| {
                a.iter()
                    .map(|x| {
                        format!(
                            "{} = {}",
                            x.get("label").and_then(Value::as_str).unwrap_or("fact"),
                            value(x.get("value").unwrap_or(&Value::Null))
                        )
                    })
                    .collect()
            })
            .unwrap_or_default()
    };
    for (name, key) in [
        ("SCENE", "scene"),
        ("WORLD", "world"),
        ("CURRENT", "current"),
        ("LOCKED", "locked"),
        ("UNKNOWN", "unknown"),
        ("DERIVABLE", "derivable"),
        ("RELATIONS", "relations"),
        ("HISTORY", "history"),
        ("KNOWLEDGE", "knowledge"),
        ("BELIEFS", "beliefs"),
        ("NORMS", "norms"),
        ("NEGATIVE", "negative"),
        ("SURFACE", "surface"),
    ] {
        let lines = items(key);
        if !lines.is_empty() {
            sections.push(name);
            section(&mut text, name, &lines);
        }
    }
    if let Some(style) = ctx.get("style").and_then(Value::as_object) {
        let lines = style
            .iter()
            .map(|(k, v)| format!("{k} = {}", value(v)))
            .collect::<Vec<_>>();
        sections.push("STYLE");
        section(&mut text, "STYLE", &lines);
    }
    if let Some(transitions) = ctx.get("transitions").and_then(Value::as_array) {
        let lines = transitions
            .iter()
            .map(|x| value(x.get("event").unwrap_or(x)))
            .collect::<Vec<_>>();
        if !lines.is_empty() {
            sections.push("TRANSITIONS");
            section(&mut text, "TRANSITIONS", &lines);
        }
    }
    if let Some(projections) = ctx.get("projections").and_then(Value::as_array) {
        let lines = projections
            .iter()
            .map(|x| {
                format!(
                    "{} ≈ {} (non-canonical; exact claim forbidden)",
                    x.get("label")
                        .and_then(Value::as_str)
                        .unwrap_or("projection"),
                    value(x.get("value").unwrap_or(&Value::Null))
                )
            })
            .collect::<Vec<_>>();
        if !lines.is_empty() {
            sections.push("PROJECTION");
            section(&mut text, "PROJECTION", &lines);
        }
    }
    let estimated_tokens = text.split_whitespace().count();
    let (text, pruned) = if estimated_tokens > 4096 {
        let mut groups: Vec<(String, Vec<String>)> = Vec::new();
        for line in text.lines() {
            if line.starts_with('[') && line.ends_with(']') {
                groups.push((line.to_owned(), Vec::new()));
            } else if let Some((_, lines)) = groups.last_mut() {
                lines.push(line.to_owned());
            }
        }
        let priority = |header: &str| match header {
            "[LOCKED]" | "[UNKNOWN]" => 0u8,
            "[CURRENT]" | "[SCENE]" => 1u8,
            "[PROJECTION]" | "[HISTORY]" | "[SURFACE]" | "[DERIVABLE]" => 2u8,
            _ => 1u8,
        };
        groups.sort_by_key(|(header, _)| priority(header));
        let marker = "[CONTEXT PRUNED TO BUDGET]";
        let reserve = marker.split_whitespace().count();
        let mut used = 2usize;
        let mut kept = vec!["@ARLINE-WRITER-CONTEXT 0.2".to_owned(), String::new()];
        for (header, lines) in groups {
            let mut count = header.split_whitespace().count();
            let mut selected = Vec::new();
            for line in lines {
                let n = line.split_whitespace().count();
                if used + count + n + reserve > 4096 {
                    break;
                }
                selected.push(line);
                count += n;
            }
            if selected.is_empty() {
                continue;
            }
            used += count;
            kept.push(header);
            kept.extend(selected);
            kept.push(String::new());
        }
        kept.push(marker.to_owned());
        (kept.join("\n") + "\n", true)
    } else {
        (text, false)
    };
    let estimated_tokens = text.split_whitespace().count();
    let sections = text
        .lines()
        .filter_map(|line| {
            line.strip_prefix('[')
                .and_then(|line| line.strip_suffix(']'))
        })
        .filter(|line| *line != "CONTEXT PRUNED TO BUDGET")
        .collect::<Vec<_>>();
    serde_json::json!({"version":"0.2","text":text,"metadata":{"wcf_version":"0.2","sections":sections,"characters":text.len(),"lines":text.lines().count(),"estimated_tokens":estimated_tokens,"budget_tokens":4096,"pruned":pruned,"token_counter":"whitespace"}})
}
