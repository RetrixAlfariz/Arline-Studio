//! Embedded memory task profiles and structured output contracts.
use crate::{ApiError, ApiResult};
use serde_json::{json, Value};

fn document() -> ApiResult<Value> {
    serde_json::from_str(include_str!("static_contracts.json"))
        .map_err(|e| ApiError::internal(e.to_string()))
}

pub fn profiles() -> ApiResult<Value> {
    Ok(json!({"profiles": document()?["profiles"]}))
}

pub fn schemas() -> ApiResult<Value> {
    let value = document()?;
    let mut ids = value["schemas"]
        .as_object()
        .map(|o| o.keys().cloned().collect::<Vec<_>>())
        .unwrap_or_default();
    ids.sort();
    Ok(json!({"schemas": ids}))
}

pub fn schema(id: &str) -> ApiResult<Value> {
    let value = document()?;
    value["schemas"]
        .get(id)
        .cloned()
        .map(|schema| json!({"id":id,"schema":schema}))
        .ok_or_else(|| ApiError::not_found(format!("Unknown memory schema: {id}")))
}
