//! Frozen legacy request contracts, evaluated natively. No Python is loaded at runtime.
use serde_json::{json, Value};
use std::sync::LazyLock;
static CONTRACT: LazyLock<Value> = LazyLock::new(|| {
    serde_json::from_str(include_str!("request_contracts.json"))
        .expect("compiled request contracts")
});
fn schema(node: &Value) -> &Value {
    if let Some(reference) = node["$ref"].as_str() {
        CONTRACT["schemas"]
            .get(reference.rsplit('/').next().unwrap_or(""))
            .unwrap_or(node)
    } else {
        node
    }
}
fn issue(loc: &[Value], kind: &str, message: &str, input: &Value) -> Value {
    json!({"type":kind,"loc":loc,"msg":message,"input":input})
}
fn check(node: &Value, input: &Value, loc: &[Value], errors: &mut Vec<Value>) {
    let node = schema(node);
    if let Some(choices) = node["anyOf"].as_array() {
        if choices.iter().any(|choice| {
            let mut attempt = Vec::new();
            check(choice, input, loc, &mut attempt);
            attempt.is_empty()
        }) {
            return;
        }
        errors.push(issue(
            loc,
            "value_error",
            "Input does not match an allowed type",
            input,
        ));
        return;
    }
    let valid = match node["type"].as_str() {
        Some("string") => input.is_string(),
        Some("integer") => input.is_i64() || input.is_u64(),
        Some("number") => input.is_number(),
        Some("boolean") => input.is_boolean(),
        Some("object") => input.is_object(),
        Some("array") => input.is_array(),
        Some("null") => input.is_null(),
        _ => true,
    };
    if !valid {
        errors.push(issue(loc, "type_error", "Input has an invalid type", input));
        return;
    }
    if let Some(allowed) = node["enum"].as_array() {
        if !allowed.contains(input) {
            errors.push(issue(
                loc,
                "enum",
                "Input must be one of the allowed values",
                input,
            ));
        }
    }
    if let Some(number) = input.as_f64() {
        for key in ["minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"] {
            if let Some(bound) = node[key].as_f64() {
                let good = match key {
                    "minimum" => number >= bound,
                    "maximum" => number <= bound,
                    "exclusiveMinimum" => number > bound,
                    _ => number < bound,
                };
                if !good {
                    errors.push(issue(
                        loc,
                        "value_error",
                        "Input is outside the allowed range",
                        input,
                    ));
                }
            }
        }
    }
    if let Some(object) = input.as_object() {
        if let Some(required) = node["required"].as_array() {
            for key in required.iter().filter_map(Value::as_str) {
                if !object.contains_key(key) {
                    let mut path = loc.to_vec();
                    path.push(json!(key));
                    errors.push(issue(&path, "missing", "Field required", input));
                }
            }
        }
        if let Some(properties) = node["properties"].as_object() {
            for (key, value) in object {
                if let Some(child) = properties.get(key) {
                    let mut path = loc.to_vec();
                    path.push(json!(key));
                    check(child, value, &path, errors);
                }
            }
        }
    }
    if let Some(items) = input.as_array() {
        if let Some(max) = node["maxItems"].as_u64() {
            if items.len() > max as usize {
                errors.push(issue(loc, "too_long", "List has too many items", input));
            }
        }
        for (index, value) in items.iter().enumerate() {
            let mut path = loc.to_vec();
            path.push(json!(index));
            check(&node["items"], value, &path, errors);
        }
    }
    if let Some(text) = input.as_str() {
        let size = text.chars().count();
        if node["minLength"]
            .as_u64()
            .is_some_and(|min| size < min as usize)
            || node["maxLength"]
                .as_u64()
                .is_some_and(|max| size > max as usize)
        {
            errors.push(issue(
                loc,
                "string_length",
                "String has an invalid length",
                input,
            ));
        }
    }
}
pub fn validate(method: &str, path: &[&str], body: &Value) -> Result<(), Vec<Value>> {
    let paths = CONTRACT["paths"].as_object().expect("route contracts");
    for (template, methods) in paths {
        let segments: Vec<_> = template.trim_matches('/').split('/').collect();
        if segments.len() != path.len()
            || !segments
                .iter()
                .zip(path)
                .all(|(pattern, value)| pattern.starts_with('{') || pattern == value)
        {
            continue;
        }
        if let Some(node) = methods.get(method) {
            let mut errors = Vec::new();
            check(node, body, &[json!("body")], &mut errors);
            if !errors.is_empty() {
                return Err(errors);
            }
            return Ok(());
        }
    }
    Ok(())
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn required_nested_and_bounds() {
        assert!(validate(
            "POST",
            &["api", "generate"],
            &json!({"prompt":"hello","temperature":3})
        )
        .is_err());
        assert!(validate(
            "POST",
            &["api", "import", "manuscript", "preview"],
            &json!({"text":"a"})
        )
        .is_err());
        assert!(validate(
            "POST",
            &["api", "generate"],
            &json!({"prompt":"hello","references":[{"type":"document"}]})
        )
        .is_err());
        assert!(validate("POST", &["api", "generate"], &json!({"prompt":"hello"})).is_ok());
    }
}
