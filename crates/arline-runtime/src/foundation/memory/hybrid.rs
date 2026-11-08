//! Opt-in R3 orchestration; all writer paths continue to consume `selected`.
use super::{
    embedding::{BekkoConfig, EmbeddingProvider},
    scope::ScopeGate,
    *,
};
use std::{collections::BTreeMap, sync::OnceLock, time::Instant};

pub(super) fn intent(body: &Value) -> &'static str {
    let query = body["query"].as_str().unwrap_or_default().to_lowercase();
    if body["pov_variant_id"].as_str().is_some()
        || ["knows", "secret", "tahu", "percaya"]
            .iter()
            .any(|s| query.contains(s))
    {
        "pov_knowledge"
    } else if ["relationship", "friend", "enemy", "hubungan", "musuh"]
        .iter()
        .any(|s| query.contains(s))
    {
        "relationship"
    } else if body["story_order"].is_number()
        || ["before", "earlier", "histor", "sebelum", "dahulu"]
            .iter()
            .any(|s| query.contains(s))
    {
        "historical"
    } else if ["current", "state", "status", "sekarang", "kondisi"]
        .iter()
        .any(|s| query.contains(s))
    {
        "current_state"
    } else if body["session_id"].as_str().is_some()
        || ["continue", "lanjut"].iter().any(|s| query.contains(s))
    {
        "scene_continuation"
    } else {
        "manuscript_search"
    }
}
fn tier(row: &Value, intent: &str) -> u8 {
    if row["authority"]
        .as_str()
        .is_some_and(|s| matches!(s, "contradiction" | "provisional" | "exploratory"))
    {
        return 2;
    }
    if intent == "current_state"
        && matches!(
            row["source_type"].as_str(),
            Some("structured_state" | "canon_fact")
        )
    {
        0
    } else {
        1
    }
}
pub(super) fn fuse(lexical: &[Value], dense: &[Value], intent: &str, k: f64) -> Vec<Value> {
    let mut by_id = BTreeMap::<String, Value>::new();
    for (lane, rows) in [("lexical", lexical), ("semantic", dense)] {
        for (rank, row) in rows.iter().enumerate() {
            let Some(id) = row["id"].as_str() else {
                continue;
            };
            let item = by_id.entry(id.into()).or_insert_with(|| row.clone());
            let contribution = 1.0 / (k + rank as f64 + 1.0);
            item["fusion_score"] =
                json!(item["fusion_score"].as_f64().unwrap_or(0.0) + contribution);
            item[format!("{lane}_rank")] = json!(rank + 1);
            if lane == "semantic" {
                item["dense_score"] = row["dense_score"].clone();
            }
            item["selection_reason"]=json!("eligible; applicability tier then reciprocal rank fusion, deterministic source diversity and packing");
        }
    }
    let mut rows = by_id.into_values().collect::<Vec<_>>();
    sort(&mut rows, intent);
    rows
}
fn sort(rows: &mut [Value], intent: &str) {
    rows.sort_by(|a, b| {
        tier(a, intent)
            .cmp(&tier(b, intent))
            .then_with(|| {
                b["fusion_score"]
                    .as_f64()
                    .unwrap()
                    .total_cmp(&a["fusion_score"].as_f64().unwrap())
            })
            .then_with(|| a["id"].as_str().cmp(&b["id"].as_str()))
    });
}
fn recent(st: &AppState, b: &Value) -> ApiResult<Vec<Value>> {
    let connection = st.store.connection()?;
    let read = connection.unchecked_transaction()?;
    let gate = ScopeGate::new(&read, b)?;
    let (filter, values) = gate.prefilter("c");
    let mut offset = 0i64;
    let mut out = vec![];
    loop {
        let mut params = values.clone();
        params.push(rusqlite::types::Value::Integer(offset));
        let refs = params
            .iter()
            .map(|v| v as &dyn rusqlite::ToSql)
            .collect::<Vec<_>>();
        let rows=crate::store::query_connection(&read,&format!("SELECT c.* FROM memory_chunks c WHERE c.semantic_status='active' AND c.source_type IN ('turn','chat_window'){filter} ORDER BY c.updated_at DESC,c.id LIMIT 64 OFFSET ?"),&refs)?;
        if rows.is_empty() {
            break;
        }
        offset += rows.len() as i64;
        for row in rows {
            if let Ok(mut row) = gate.evaluate(&row)? {
                if semantic_index::source_current(&read, &row)? {
                    row["retrieval_lane"] = json!("recent");
                    out.push(row);
                }
            }
            if out.len() >= 8 {
                return Ok(out);
            }
        }
    }
    Ok(out)
}
fn ms(start: Instant) -> f64 {
    start.elapsed().as_secs_f64() * 1000.0
}

pub(super) async fn retrieve(
    st: &AppState,
    b: &Value,
    q: &HashMap<String, String>,
    settings: &Value,
) -> ApiResult<Value> {
    retrieve_with_provider(st, b, q, settings, st.embeddings.as_ref()).await
}

async fn retrieve_with_provider<P: EmbeddingProvider>(
    st: &AppState,
    b: &Value,
    q: &HashMap<String, String>,
    settings: &Value,
    provider: &P,
) -> ApiResult<Value> {
    let config = st.runtime_config()?;
    let mode = config.str("memory.engine_mode", "legacy");
    let total = Instant::now();
    let mut timings = serde_json::Map::new();
    let started = Instant::now();
    let query_intent = intent(b);
    {
        let connection = st.store.connection()?;
        let _gate = ScopeGate::new(&connection, b)?;
    }
    timings.insert("scope_planning_ms".into(), json!(ms(started)));
    let started = Instant::now();
    let mut out = super::lexical_retrieve(st, b, q, true)?;
    let mut lexical = out["results"].as_array().cloned().unwrap_or_default();
    if query_intent == "scene_continuation" {
        let mut seen = lexical
            .iter()
            .filter_map(|r| r["id"].as_str().map(str::to_owned))
            .collect::<std::collections::HashSet<_>>();
        lexical.extend(
            recent(st, b)?
                .into_iter()
                .filter(|row| seen.insert(row["id"].as_str().unwrap_or_default().into())),
        );
    }
    timings.insert("lexical_and_structured_ms".into(), json!(ms(started)));
    let started = Instant::now();
    let mut fallback = None;
    let mut batch = None;
    static REQUESTS: OnceLock<std::sync::Arc<tokio::sync::Semaphore>> = OnceLock::new();
    let permit = REQUESTS
        .get_or_init(|| std::sync::Arc::new(tokio::sync::Semaphore::new(4)))
        .clone()
        .try_acquire_owned();
    if settings["dense_enabled"] != true {
        fallback = Some("semantic_disabled");
    } else if settings["embedding"]["backend"] != "native_bekko_onnx" {
        fallback = Some("native_backend_not_selected");
    } else if permit.is_err() {
        fallback = Some("resource_busy");
    } else {
        match BekkoConfig::from_runtime(&st.runtime_config()?) {
            Ok(config) => match provider
                .embed_batch(
                    config,
                    vec![b["query"].as_str().unwrap_or_default().to_owned()],
                )
                .await
            {
                Ok(value) => batch = Some(value),
                Err(error) => {
                    fallback = Some(match error.kind {
                        super::embedding::ErrorKind::ResourceBusy => "resource_busy",
                        super::embedding::ErrorKind::FeatureUnavailable => {
                            "native_feature_unavailable"
                        }
                        super::embedding::ErrorKind::Artifact => "model_artifact_unavailable",
                        _ => "semantic_provider_unavailable",
                    })
                }
            },
            Err(_) => fallback = Some("native_settings_unavailable"),
        }
    }
    drop(permit);
    timings.insert("query_embedding_ms".into(), json!(ms(started)));
    let started = Instant::now();
    let limit = settings["max_candidates"]
        .as_u64()
        .unwrap_or(60)
        .clamp(8, 1000) as usize;
    let (dense, coverage) = semantic_index::retrieval::search(
        st,
        b,
        batch.as_ref(),
        limit,
        config.f64("memory.semantic_min_score", -1.0),
    )?;
    if batch.is_some() && coverage["generation_available"] != true {
        fallback = Some("active_generation_not_indexed");
    }
    timings.insert(
        "semantic_candidates_and_coverage_ms".into(),
        json!(ms(started)),
    );
    let started = Instant::now();
    let mut candidates = fuse(
        &lexical,
        &dense,
        query_intent,
        settings["rrf_k"].as_f64().unwrap_or(60.0),
    );
    timings.insert("fusion_ms".into(), json!(ms(started)));
    let started = Instant::now();
    {
        let connection = st.store.connection()?;
        let read = connection.unchecked_transaction()?;
        let gate = ScopeGate::new(&read, b)?;
        let mut current = Vec::with_capacity(candidates.len());
        for row in candidates {
            let mut row = if matches!(
                row["source_type"].as_str(),
                Some("structured_state" | "temporal" | "epistemic" | "spatial" | "thread")
            ) {
                row
            } else {
                let Some(mut fresh) = crate::store::query_connection(
                    &read,
                    "SELECT * FROM memory_chunks WHERE id=?",
                    &[&row["id"].as_str().unwrap_or_default()],
                )?
                .pop() else {
                    continue;
                };
                for key in [
                    "fusion_score",
                    "lexical_score",
                    "dense_score",
                    "lexical_rank",
                    "semantic_rank",
                    "selection_reason",
                    "retrieval_lane",
                ] {
                    if let Some(value) = row.get(key) {
                        fresh[key] = value.clone();
                    }
                }
                fresh
            };
            if let Ok(effective) = gate.evaluate(&row)? {
                row = effective;
            } else {
                continue;
            }
            if semantic_index::source_current(&read, &row)? {
                current.push(row);
            }
        }
        candidates = current;
        sort(&mut candidates, query_intent);
    }
    timings.insert("final_eligibility_ms".into(), json!(ms(started)));
    out["results"] = json!(candidates);
    let started = Instant::now();
    super::pack_retrieval(&mut out, b);
    timings.insert("packing_ms".into(), json!(ms(started)));
    let selected = out["selected"]
        .as_array()
        .into_iter()
        .flatten()
        .map(|r| r["id"].clone())
        .collect::<Vec<_>>();
    let trace = json!({"intent":query_intent,"effective_scope":out["plan"]["scope"],"eligible_candidates":candidates.len(),"lane_candidates":{"lexical_and_structured":lexical.len(),"semantic":dense.len()},"coverage":coverage,"fallback":fallback,"selected_ids":selected,"estimated_context_tokens":out["packed_tokens"],"timings":timings,"embedding_timings":batch.as_ref().map(|b|&b.timings),"model_identity":batch.as_ref().map(|b|&b.identity)});
    out["retrieval_trace"] = trace;
    out["engine_mode"] = json!(mode);
    out["provider"] = json!("scope-safe-fts5+structured+native-index");
    out["dense_embeddings"] = json!(!dense.is_empty());
    out["dense_fallback_reason"] = json!(fallback);
    out["semantic_result_state"] = json!(if batch.is_none() {
        "provider_unavailable"
    } else if coverage["generation_available"] != true {
        "generation_unavailable"
    } else if coverage["complete"] != true {
        "partial_coverage"
    } else if dense.is_empty() {
        "empty_matches"
    } else {
        "available"
    });
    if mode == "shadow" {
        // Real legacy input, independently packed; comparison carries IDs and
        // aggregate diagnostics only, never shadow candidate passages.
        let mut legacy = super::legacy_retrieve(st, b, q, settings).await?;
        legacy["engine_mode"] = json!("shadow");
        legacy["shadow_trace"] = out["retrieval_trace"].clone();
        legacy["shadow_trace"]["total_ms"] = json!(ms(total));
        save(st, &legacy)?;
        return Ok(legacy);
    }
    out["retrieval_trace"]["total_ms"] = json!(ms(total));
    save(st, &out)?;
    Ok(out)
}
fn save(st: &AppState, out: &Value) -> ApiResult<()> {
    st.store.execute(
        "UPDATE memory_retrieval_runs SET result_json=? WHERE id=?",
        &[
            &out.to_string(),
            &out["run_id"].as_str().unwrap_or_default(),
        ],
    )?;
    Ok(())
}

#[cfg(test)]
mod tests;
