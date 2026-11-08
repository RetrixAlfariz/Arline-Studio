//! Read-only narrative scan over R2 contracts. No maintenance or passage inference.
use super::super::scope::ScopeGate;
use super::*;
use serde_json::json;

pub(crate) fn search(
    state: &AppState,
    body: &Value,
    batch: Option<&super::super::embedding::EmbeddingBatch>,
    limit: usize,
    threshold: f64,
) -> ApiResult<(Vec<Value>, Value)> {
    let connection = state.store.connection()?;
    let read = connection.unchecked_transaction()?;
    let gate = ScopeGate::new(&read, body)?;
    let fingerprint = batch.map(|b| b.identity.fingerprint.as_str()).unwrap_or("");
    let identity = read.query_row("SELECT identity_json FROM semantic_model_generations WHERE model_fingerprint=? AND dimensions=384 AND encoding_version=1 AND backend='native_bekko_onnx'", [fingerprint], |r| r.get::<_,String>(0)).optional()?;
    let available = batch.is_some_and(|b| {
        identity.as_ref().is_some_and(|raw| {
            serde_json::to_string(&b.identity).is_ok_and(|expected| expected == *raw)
        })
    });
    let query = batch.and_then(|b| b.vectors.first());
    if let Some(batch) = batch {
        if batch.vectors.len() != 1 || batch.identity.dimensions != DIMENSIONS {
            return Err(invalid("query embedding contract mismatch"));
        }
        encode_vector(&batch.vectors[0])?;
    }
    let (filter, values) = gate.prefilter("c");
    let sql = format!("SELECT c.*,hex(v.vector_blob) AS vector_hex,v.source_revision AS vector_revision,v.content_checksum AS vector_checksum,v.chunker_version AS vector_chunker,v.dimensions AS vector_dimensions FROM memory_chunks c LEFT JOIN semantic_vectors v ON v.chunk_id=c.id AND v.model_fingerprint=? WHERE c.id>?{filter} ORDER BY c.id LIMIT 64");
    let mut cursor = String::new();
    let mut hits = vec![];
    let mut current = 0;
    let mut pending = 0;
    let mut unknown = 0;
    let mut refresh = 0;
    let mut invalid_vectors = 0;
    let mut exclusions = serde_json::Map::new();
    loop {
        let mut params = vec![
            rusqlite::types::Value::Text(fingerprint.into()),
            rusqlite::types::Value::Text(cursor.clone()),
        ];
        params.extend(values.clone());
        let refs = params
            .iter()
            .map(|v| v as &dyn rusqlite::ToSql)
            .collect::<Vec<_>>();
        let rows = query_connection(&read, &sql, &refs)?;
        if rows.is_empty() {
            break;
        }
        for row in rows {
            cursor = row["id"].as_str().unwrap_or_default().into();
            let row = match gate.evaluate(&row)? {
                Ok(row) => row,
                Err(reason) => {
                    let n = exclusions.get(reason).and_then(Value::as_u64).unwrap_or(0);
                    exclusions.insert(reason.into(), json!(n + 1));
                    continue;
                }
            };
            match snapshot::capture(&read, &row)? {
                snapshot::Eligibility::Current(_) => {}
                snapshot::Eligibility::NeedsRefresh => {
                    refresh += 1;
                    if row["vector_hex"].as_str().is_some_and(|v| !v.is_empty()) {
                        invalid_vectors += 1;
                    }
                    continue;
                }
                snapshot::Eligibility::Excluded => continue,
            }
            if !available || !vector_current(&row) {
                if batch.is_none() {
                    unknown += 1;
                } else {
                    pending += 1;
                }
                if row["vector_hex"].as_str().is_some_and(|v| !v.is_empty()) {
                    invalid_vectors += 1;
                }
                continue;
            }
            current += 1;
            let vector = row_vector(&row)?;
            let query = query.expect("available generation has a query");
            let norm = |v: &[f32]| v.iter().map(|v| f64::from(*v).powi(2)).sum::<f64>().sqrt();
            let score = query
                .iter()
                .zip(&vector)
                .map(|(a, b)| f64::from(*a) * f64::from(*b))
                .sum::<f64>()
                / (norm(query) * norm(&vector));
            if score >= threshold {
                let mut row = row;
                // Internal storage bytes and aliases are never retrieval diagnostics.
                if let Some(object) = row.as_object_mut() {
                    object.retain(|k, _| !k.starts_with("vector_"));
                }
                row["dense_score"] = json!(score);
                hits.push(row);
                hits.sort_by(|a, b| {
                    b["dense_score"]
                        .as_f64()
                        .unwrap()
                        .total_cmp(&a["dense_score"].as_f64().unwrap())
                        .then_with(|| a["id"].as_str().cmp(&b["id"].as_str()))
                });
                hits.truncate(limit);
            }
        }
    }
    // Count authoritative resources that have never been projected. This is
    // deliberately separate from projected chunk coverage and job completion.
    let mut unprojected = 0;
    let mut sources_requiring_refresh = 0;
    for (kind, table) in [
        ("document", "workspace_documents"),
        ("entity_variant", "entity_variants"),
        ("canon_fact", "canon_facts"),
        ("relationship", "relationships"),
        ("timeline_event", "timeline_events"),
        ("turn", "turns"),
    ] {
        let mut cursor = String::new();
        loop {
            let rows = query_connection(
                &read,
                &format!("SELECT s.* FROM {table} s WHERE s.id>? ORDER BY s.id LIMIT 64"),
                &[&cursor],
            )?;
            if rows.is_empty() {
                break;
            }
            for mut source in rows {
                cursor = source["id"].as_str().unwrap_or_default().into();
                source["source_id"] = source["id"].clone();
                source["source_type"] = json!(kind);
                source["text"] = json!(super::super::source_text(kind, &source));
                if gate.evaluate(&source)?.is_ok() {
                    let chunks=query_connection(&read,"SELECT * FROM memory_chunks WHERE (source_type=? OR (?='turn' AND source_type='chat_window')) AND source_id=? AND semantic_status='active'",&[&kind,&kind,&cursor])?;
                    if chunks.is_empty() {
                        unprojected += 1;
                        sources_requiring_refresh += 1;
                    } else {
                        for chunk in chunks {
                            let scope_changed = gate.evaluate(&chunk)?.is_ok_and(|effective| {
                                ["project_id", "world_id", "branch_id", "session_id"]
                                    .iter()
                                    .any(|key| effective[*key] != chunk[*key])
                            });
                            if scope_changed
                                || matches!(
                                    snapshot::capture(&read, &chunk)?,
                                    snapshot::Eligibility::NeedsRefresh
                                )
                            {
                                sources_requiring_refresh += 1;
                                break;
                            }
                        }
                    }
                }
            }
        }
    }
    Ok((
        hits,
        json!({"generation_available":available,"model_fingerprint":if fingerprint.is_empty(){Value::Null}else{json!(fingerprint)},"provider_available":batch.is_some(),"projected_current_indexed":current,"projected_awaiting_embedding":pending,"projected_embedding_readiness_unknown":unknown,"projected_awaiting_source_refresh":refresh,"authoritative_unprojected_sources":unprojected,"authoritative_sources_requiring_projection_refresh":sources_requiring_refresh,"stale_or_invalid_vectors":invalid_vectors,"complete":available && pending==0 && refresh==0 && sources_requiring_refresh==0,"scope_exclusions":exclusions,"exclusion_count_basis":"rows remaining after safe SQL scope/lifecycle prefilter","coverage_basis":"eligible authoritative sources and existing projections; never inferred from job completion"}),
    ))
}
