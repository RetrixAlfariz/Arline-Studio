//! R2 persistent derived vectors. No writer, ranking or production search wiring.
mod jobs;
mod snapshot;
pub(super) mod retrieval;
#[cfg(test)]
mod tests;

use super::embedding::{BekkoConfig, EmbeddingProvider, ModelIdentity, DIMENSIONS, MODEL_ID};
use crate::{
    store::{query_connection, Store},
    ApiError, ApiResult, AppState,
};
use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
#[cfg(test)]
use serde_json::json;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    collections::HashSet,
    sync::{Arc, Mutex, OnceLock},
    time::Instant,
};

pub use jobs::{
    cancel_index_job, index_pending, index_source, reconcile_index, resume_job, run_job,
};
#[cfg(test)]
pub(crate) use jobs::{enqueue, process_job};
const MIGRATION: &str = include_str!("../../../migrations/semantic_index_v1.sql");
const CURRENT_SQL:&str="SELECT c.*,hex(v.vector_blob) AS vector_hex,v.source_revision AS vector_revision,v.content_checksum AS vector_checksum,v.chunker_version AS vector_chunker,v.dimensions AS vector_dimensions FROM memory_chunks c LEFT JOIN semantic_vectors v ON v.chunk_id=c.id AND v.model_fingerprint=? WHERE (? IS NULL OR c.project_id=?) AND (? IS NULL OR (c.source_type=? AND c.source_id=?)) AND c.id>? ORDER BY c.id LIMIT 64";

fn now() -> String {
    chrono::Utc::now().to_rfc3339()
}
fn digest(text: &str) -> String {
    format!("{:x}", Sha256::digest(text))
}
fn invalid(message: impl Into<String>) -> ApiError {
    ApiError::bad_request(message)
}
fn bounded(message: &str) -> String {
    message.chars().take(512).collect()
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, PartialEq)]
pub struct IndexScope {
    pub project_id: Option<String>,
    pub source_type: Option<String>,
    pub source_id: Option<String>,
}
impl IndexScope {
    fn validate(&self) -> ApiResult<()> {
        if self.source_type.is_some() != self.source_id.is_some() {
            return Err(invalid(
                "source_type and source_id must be supplied together",
            ));
        }
        if self
            .project_id
            .iter()
            .chain(self.source_type.iter())
            .chain(self.source_id.iter())
            .any(|s| s.is_empty() || s.len() > 256)
        {
            return Err(invalid(
                "index scope identifiers must contain 1..=256 bytes",
            ));
        }
        Ok(())
    }
}

pub(crate) fn register_functions(connection: &Connection) -> rusqlite::Result<()> {
    connection.create_scalar_function(
        "semantic_f32_valid_v1",
        2,
        rusqlite::functions::FunctionFlags::SQLITE_DETERMINISTIC
            | rusqlite::functions::FunctionFlags::SQLITE_UTF8,
        |ctx| {
            let valid = ctx
                .get::<Vec<u8>>(0)
                .ok()
                .zip(ctx.get::<i64>(1).ok())
                .is_some_and(|(blob, dims)| {
                    dims == DIMENSIONS as i64 && decode_vector(&blob).is_ok()
                });
            Ok(i64::from(valid))
        },
    )
}
pub fn encode_vector(values: &[f32]) -> ApiResult<Vec<u8>> {
    if values.len() != DIMENSIONS
        || values.iter().any(|v| !v.is_finite())
        || values.iter().all(|v| *v == 0.0)
    {
        return Err(invalid(
            "semantic vectors require 384 finite, nonzero-norm values",
        ));
    }
    Ok(values
        .iter()
        .flat_map(|value| value.to_le_bytes())
        .collect())
}
pub fn decode_vector(blob: &[u8]) -> ApiResult<Vec<f32>> {
    if blob.len() != DIMENSIONS * 4 {
        return Err(invalid("invalid semantic vector BLOB length"));
    }
    let values = blob
        .chunks_exact(4)
        .map(|b| f32::from_le_bytes(b.try_into().expect("four bytes")))
        .collect::<Vec<_>>();
    if values.iter().any(|v| !v.is_finite()) || values.iter().all(|v| *v == 0.0) {
        return Err(invalid(
            "semantic vector contains nonfinite/zero-norm values",
        ));
    }
    Ok(values)
}

pub(crate) fn initialize(store: &Store) -> ApiResult<()> {
    let connection = store.connection()?;
    let exists: i64 = connection.query_row(
        "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='semantic_index_meta'",
        [],
        |r| r.get(0),
    )?;
    if exists == 0 {
        {
            let backup_path = store
                .path
                .with_extension(format!("before-semantic-v1-{}.bak", uuid::Uuid::new_v4()));
            std::fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&backup_path)?;
            let mut destination = Connection::open(&backup_path)?;
            rusqlite::backup::Backup::new(&connection, &mut destination)?.run_to_completion(
                64,
                std::time::Duration::from_millis(10),
                None,
            )?;
        }
    } else {
        let version: i64 =
            connection.query_row("SELECT version FROM semantic_index_meta", [], |r| r.get(0))?;
        if version != 1 {
            return Err(invalid("unsupported semantic index schema version"));
        }
    }
    connection.execute_batch(MIGRATION)?;
    jobs::recover_jobs(store)?;
    Ok(())
}

pub(super) fn register_generation(connection: &Connection, identity: &ModelIdentity) -> ApiResult<()> {
    if identity.model != MODEL_ID
        || identity.backend != "native_bekko_onnx"
        || identity.dimensions != DIMENSIONS
        || identity.fingerprint.len() != 71
        || !identity.fingerprint.starts_with("sha256:")
        || !identity.fingerprint[7..]
            .bytes()
            .all(|b| b.is_ascii_hexdigit())
    {
        return Err(invalid("invalid native model identity"));
    }
    let raw = serde_json::to_string(identity).map_err(|e| invalid(e.to_string()))?;
    let existing = connection
        .query_row(
            "SELECT identity_json FROM semantic_model_generations WHERE model_fingerprint=?",
            [&identity.fingerprint],
            |r| r.get::<_, String>(0),
        )
        .optional()?;
    if existing.as_ref().is_some_and(|v| v != &raw) {
        return Err(invalid(
            "model fingerprint already names a different identity contract",
        ));
    }
    connection.execute(
        "INSERT OR IGNORE INTO semantic_model_generations VALUES(?,?,?,?,?,1,?)",
        params![
            identity.fingerprint,
            identity.model,
            identity.backend,
            identity.dimensions,
            raw,
            now()
        ],
    )?;
    Ok(())
}

#[derive(Debug, Default, Serialize)]
pub struct IndexStatus {
    pub model_fingerprint: String,
    pub generation_available: bool,
    pub schema_version: u32,
    pub total_indexable: usize,
    pub current: usize,
    pub pending: usize,
    pub failed: usize,
    pub stale_vectors: usize,
    pub awaiting_source_refresh: usize,
    pub excluded: usize,
    pub complete: bool,
    pub database_bytes: u64,
    pub vector_bytes: u64,
    pub model_availability: Value,
    pub jobs: Vec<Value>,
    pub last_failure_reason: Option<String>,
}

pub fn index_status(
    state: &AppState,
    fingerprint: &str,
    scope: &IndexScope,
) -> ApiResult<IndexStatus> {
    scope.validate()?;
    let connection = state.store.connection()?;
    let read = connection.unchecked_transaction()?;
    let connection: &Connection = &read;
    let mut status = IndexStatus {
        model_fingerprint: fingerprint.into(),
        schema_version: 1,
        ..Default::default()
    };
    status.generation_available = connection.query_row("SELECT count(*) FROM semantic_model_generations WHERE model_fingerprint=? AND model_id=? AND backend='native_bekko_onnx' AND dimensions=384 AND encoding_version=1",params![fingerprint,MODEL_ID],|r|r.get::<_,i64>(0))?>0;
    let mut cursor = String::new();
    loop {
        let rows = page(connection, fingerprint, scope, &cursor)?;
        if rows.is_empty() {
            break;
        }
        for chunk in rows {
            cursor = chunk["id"].as_str().unwrap_or_default().to_owned();
            match snapshot::capture(connection, &chunk)? {
                snapshot::Eligibility::Current(_) => {
                    status.total_indexable += 1;
                    if vector_current(&chunk) {
                        status.current += 1;
                    } else {
                        status.pending += 1;
                        let failed:i64=connection.query_row("SELECT count(*) FROM semantic_index_items WHERE chunk_id=? AND model_fingerprint=? AND state='failed' AND content_checksum=? AND source_revision=? AND chunker_version=?",params![cursor,fingerprint,chunk["checksum"].as_str(),chunk["source_revision"].as_str(),chunk["chunker_version"].as_i64()],|r|r.get(0))?;
                        status.failed += failed as usize;
                    }
                }
                snapshot::Eligibility::NeedsRefresh => {
                    status.awaiting_source_refresh += 1;
                }
                snapshot::Eligibility::Excluded => {
                    status.excluded += 1;
                }
            }
        }
    }
    let stored:i64=connection.query_row("SELECT count(*) FROM semantic_vectors v LEFT JOIN memory_chunks c ON c.id=v.chunk_id WHERE v.model_fingerprint=? AND (? IS NULL OR c.project_id=?) AND (? IS NULL OR (c.source_type=? AND c.source_id=?))",params![fingerprint,scope.project_id,scope.project_id,scope.source_type,scope.source_type,scope.source_id],|r|r.get(0))?;
    status.stale_vectors = (stored as usize).saturating_sub(status.current);
    status.complete =
        status.generation_available && status.pending == 0 && status.awaiting_source_refresh == 0;
    status.vector_bytes=connection.query_row("SELECT coalesce(sum(length(vector_blob)),0) FROM semantic_vectors WHERE model_fingerprint=?",[fingerprint],|r|r.get::<_,u64>(0))?;
    status.database_bytes = std::fs::metadata(&state.store.path)?.len()
        + std::fs::metadata(format!("{}-wal", state.store.path.display()))
            .map(|m| m.len())
            .unwrap_or(0);
    status.model_availability =
        serde_json::to_value(state.embeddings.diagnostics()).unwrap_or(Value::Null);
    status.jobs=query_connection(connection,"SELECT * FROM semantic_index_jobs WHERE model_fingerprint=? AND scope_key=? ORDER BY created_at DESC,id LIMIT 16",&[&fingerprint,&digest(&serde_json::to_string(scope).map_err(|e|invalid(e.to_string()))?)])?;
    status.last_failure_reason = status.jobs.iter().find_map(|job| {
        job["last_error"]
            .as_str()
            .filter(|s| !s.is_empty())
            .map(str::to_owned)
    });
    if status.last_failure_reason.is_none() && status.failed > 0 {
        status.last_failure_reason=connection.query_row("SELECT i.last_error FROM semantic_index_items i JOIN memory_chunks c ON c.id=i.chunk_id WHERE i.model_fingerprint=? AND i.state='failed' AND (? IS NULL OR c.project_id=?) AND (? IS NULL OR (c.source_type=? AND c.source_id=?)) ORDER BY i.updated_at DESC,i.chunk_id LIMIT 1",params![fingerprint,scope.project_id,scope.project_id,scope.source_type,scope.source_type,scope.source_id],|r|r.get(0)).optional()?;
    }
    Ok(status)
}

fn page(
    connection: &Connection,
    fingerprint: &str,
    scope: &IndexScope,
    cursor: &str,
) -> ApiResult<Vec<Value>> {
    query_connection(
        connection,
        CURRENT_SQL,
        &[
            &fingerprint,
            &scope.project_id,
            &scope.project_id,
            &scope.source_type,
            &scope.source_type,
            &scope.source_id,
            &cursor,
        ],
    )
}
fn vector_current(chunk: &Value) -> bool {
    chunk["vector_revision"] == chunk["source_revision"]
        && chunk["vector_checksum"] == chunk["checksum"]
        && chunk["vector_chunker"] == chunk["chunker_version"]
        && chunk["vector_dimensions"] == DIMENSIONS
        && row_vector(chunk).is_ok()
}
fn row_vector(row: &Value) -> ApiResult<Vec<f32>> {
    let hex = row["vector_hex"].as_str().unwrap_or_default();
    if hex.len() != DIMENSIONS * 8 || !hex.is_ascii() {
        return Err(invalid("invalid vector BLOB"));
    }
    let bytes = (0..hex.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&hex[i..i + 2], 16).map_err(|_| invalid("invalid vector hex")))
        .collect::<ApiResult<Vec<_>>>()?;
    decode_vector(&bytes)
}

/// Synthetic/legacy notes have no native projection contract. Native projected
/// sources must still match authoritative content on lexical as well as dense paths.
pub(super) fn source_current(connection: &Connection, row: &Value) -> ApiResult<bool> {
    if !row["source_revision"].as_str().is_some_and(|v| v.starts_with("base_sha256:")) {
        return Ok(true);
    }
    Ok(matches!(snapshot::capture(connection, row)?, snapshot::Eligibility::Current(_)))
}

// Diagnostic search is deliberately crate-internal: only controlled tests and
// qualification fixtures may call it until R3 defines authoritative prefilters.
#[cfg(test)]
fn diagnostic_search(
    state: &AppState,
    fingerprint: &str,
    project: &str,
    allowed: &HashSet<String>,
    query: &[f32],
    limit: usize,
) -> ApiResult<Value> {
    encode_vector(query)?;
    let scope = IndexScope {
        project_id: Some(project.into()),
        ..Default::default()
    };
    let connection = state.store.connection()?;
    let read = connection.unchecked_transaction()?;
    let connection: &Connection = &read;
    if !index_status(state, fingerprint, &scope)?.generation_available {
        return Err(ApiError::new(
            axum::http::StatusCode::SERVICE_UNAVAILABLE,
            "semantic model generation is unavailable",
        ));
    }
    let mut cursor = String::new();
    let mut hits = Vec::new();
    loop {
        let rows = page(connection, fingerprint, &scope, &cursor)?;
        if rows.is_empty() {
            break;
        }
        for row in rows {
            cursor = row["id"].as_str().unwrap_or_default().to_owned();
            if !allowed.contains(&cursor)
                || !vector_current(&row)
                || !matches!(
                    snapshot::capture(connection, &row)?,
                    snapshot::Eligibility::Current(_)
                )
            {
                continue;
            }
            let v = row_vector(&row)?;
            let norm = |v: &[f32]| v.iter().map(|x| f64::from(*x).powi(2)).sum::<f64>().sqrt();
            let cosine = query
                .iter()
                .zip(&v)
                .map(|(a, b)| f64::from(*a) * f64::from(*b))
                .sum::<f64>()
                / (norm(query) * norm(&v));
            hits.push(json!({"chunk_id":cursor,"score":cosine,"source_type":row["source_type"],"source_id":row["source_id"],"source_revision":row["source_revision"],"checksum":row["checksum"],"authority":row["authority"]}));
        }
    }
    hits.sort_by(|a, b| {
        b["score"]
            .as_f64()
            .unwrap()
            .total_cmp(&a["score"].as_f64().unwrap())
            .then_with(|| a["chunk_id"].as_str().cmp(&b["chunk_id"].as_str()))
    });
    hits.truncate(limit.min(100));
    Ok(
        json!({"hits":hits,"coverage":index_status(state,fingerprint,&scope)?,"scope":"controlled-fixture-only","production_recall":false}),
    )
}
