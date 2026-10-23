//! Atomic memory source replacement built on the native structural chunker.

use super::{chunking, settings};
use crate::{ApiError, ApiResult, AppState};
use rusqlite::params;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

fn now() -> String {
    chrono::Utc::now().to_rfc3339()
}
fn digest_hex(bytes: impl AsRef<[u8]>) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
fn text(meta: &Value, key: &str) -> Option<String> {
    meta.get(key)
        .and_then(Value::as_str)
        .map(str::to_owned)
        .filter(|v| !v.is_empty())
}
fn sql(error: rusqlite::Error) -> ApiError {
    ApiError::internal(error.to_string())
}

/// Replace all derived chunks for one source in a single transaction.
/// Existing chunks remain visible if preparation/insertion fails; a matching
/// active revision is returned unchanged for idempotent refreshes.
pub fn replace_chunks(
    state: &AppState,
    source_type: &str,
    source_id: &str,
    content: &str,
    metadata: &Value,
) -> ApiResult<Value> {
    let config = state
        .config
        .read()
        .map_err(|_| ApiError::internal("runtime config lock poisoned"))?;
    let cfg = settings::settings(&config);
    let max_chars = cfg["chunk_chars"].as_u64().unwrap_or(1800) as usize;
    let overlap = cfg["chunk_overlap_chars"].as_u64().unwrap_or(180) as usize;
    let revision = format!("base_sha256:{}", digest_hex(content.as_bytes()));
    let chunks = chunking::chunk(content, source_id, max_chars, overlap);
    if chunks.is_empty() {
        let con = state.store.connection()?;
        con.execute("UPDATE memory_chunks SET semantic_status='stale',index_state='stale',updated_at=? WHERE source_type=? AND source_id=? AND semantic_status='active'", params![now(),source_type,source_id]).map_err(sql)?;
        return Ok(
            json!({"source_type":source_type,"source_id":source_id,"source_revision":revision,"chunks":[],"replaced":true,"cleared":true}),
        );
    }
    let mut con = state.store.connection()?;
    con.execute_batch("CREATE TABLE IF NOT EXISTS memory_links(memory_chunk_id TEXT NOT NULL,resource_type TEXT NOT NULL,resource_id TEXT NOT NULL,relation TEXT NOT NULL DEFAULT 'mentions',confidence REAL NOT NULL DEFAULT 1.0,resolution_method TEXT NOT NULL DEFAULT 'exact',PRIMARY KEY(memory_chunk_id,resource_type,resource_id,relation)); CREATE INDEX IF NOT EXISTS idx_memory_links_resource ON memory_links(resource_type,resource_id,relation);").map_err(sql)?;
    let tx = con.transaction().map_err(sql)?;
    let active: i64 = tx.query_row("SELECT COUNT(*) FROM memory_chunks WHERE source_type=? AND source_id=? AND source_revision=? AND semantic_status='active'", params![source_type,source_id,revision], |r| r.get(0)).unwrap_or(0);
    if active as usize == chunks.len() {
        tx.execute("UPDATE memory_chunks SET project_id=?,world_id=?,branch_id=?,session_id=?,authority=COALESCE(?,authority),trust_level=COALESCE(?,trust_level),source_recorded_at=?,world_time_json=?,story_order=?,semantic_class=COALESCE(?,semantic_class),importance=COALESCE(?,importance),updated_at=? WHERE source_type=? AND source_id=? AND source_revision=? AND semantic_status='active'", params![text(metadata,"project_id"),text(metadata,"world_id"),text(metadata,"branch_id"),text(metadata,"session_id"),text(metadata,"authority"),text(metadata,"trust_level"),text(metadata,"source_recorded_at"),metadata.get("world_time").map(Value::to_string),metadata["story_order"].as_f64(),text(metadata,"semantic_class"),metadata["importance"].as_f64(),now(),source_type,source_id,revision]).map_err(sql)?;
        let rows = tx.query_row("SELECT COALESCE(json_group_array(json_object('id',id,'text',text)),json('[]')) FROM memory_chunks WHERE source_type=? AND source_id=? AND source_revision=? AND semantic_status='active'", params![source_type,source_id,revision], |r| r.get::<_,String>(0)).unwrap_or_else(|_| "[]".into());
        tx.commit().map_err(sql)?;
        return Ok(
            json!({"source_type":source_type,"source_id":source_id,"source_revision":revision,"chunks":serde_json::from_str::<Value>(&rows).unwrap_or(json!([])),"replaced":false,"idempotent":true}),
        );
    }
    let timestamp = now();
    let project = text(metadata, "project_id");
    let world = text(metadata, "world_id");
    let branch = text(metadata, "branch_id");
    let session = text(metadata, "session_id");
    let scope_kind = text(metadata, "scope_kind").unwrap_or_else(|| "project".into());
    let semantic = text(metadata, "semantic_class").unwrap_or_else(|| "evidence".into());
    let authority = text(metadata, "authority").unwrap_or_else(|| "project_manuscript".into());
    let trust = text(metadata, "trust_level").unwrap_or_else(|| "trusted_local".into());
    let source_recorded = text(metadata, "source_recorded_at");
    let world_time = metadata
        .get("world_time")
        .or_else(|| metadata.get("world_time_json"))
        .cloned();
    let story_order = metadata.get("story_order").and_then(Value::as_f64);
    let mut result = Vec::new();
    for chunk in &chunks {
        let clean = chunk.text.trim();
        if clean.is_empty() {
            continue;
        }
        let revision_tag = revision.strip_prefix("base_sha256:").unwrap_or(&revision);
        let chunk_id = format!(
            "MEM-{}-{}-{}-{}",
            source_type,
            source_id,
            &revision_tag[..revision_tag.len().min(16)],
            chunk.ordinal
        );
        let display = clean.chars().take(500).collect::<String>();
        tx.execute("INSERT INTO memory_chunks(id,source_type,source_id,source_revision,project_id,world_id,branch_id,session_id,source_start_id,source_end_id,source_recorded_at,world_time_json,story_order,scope_kind,semantic_class,authority,trust_level,text,retrieval_text,display_excerpt,token_count,importance,extraction_confidence,identity_confidence,semantic_status,index_state,checksum,chunker_version,index_generation,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'active','indexed',?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET source_revision=excluded.source_revision,project_id=excluded.project_id,world_id=excluded.world_id,branch_id=excluded.branch_id,session_id=excluded.session_id,text=excluded.text,retrieval_text=excluded.retrieval_text,display_excerpt=excluded.display_excerpt,authority=excluded.authority,trust_level=excluded.trust_level,semantic_status='active',index_state='indexed',checksum=excluded.checksum,updated_at=excluded.updated_at", params![chunk_id,source_type,source_id,revision,project,world,branch,session,chunk.start_id,chunk.end_id,source_recorded,world_time.as_ref().map(|v| serde_json::to_string(v).unwrap_or_else(|_| "null".into())),story_order,scope_kind,semantic,authority,trust,clean,clean,display,(clean.chars().count()/4).max(1),metadata.get("importance").and_then(Value::as_f64).unwrap_or(0.5),metadata.get("extraction_confidence").and_then(Value::as_f64).unwrap_or(1.0),metadata.get("identity_confidence").and_then(Value::as_f64).unwrap_or(1.0),digest_hex(clean.as_bytes()),1,Option::<i64>::None,timestamp,timestamp]).map_err(sql)?;
        tx.execute("INSERT OR IGNORE INTO memory_links(memory_chunk_id,resource_type,resource_id,relation,confidence,resolution_method) VALUES(?,?,?,?,?,?)",params![chunk_id,source_type,source_id,"source",1.0,"source"] ).map_err(sql)?;
        let lower = clean.to_ascii_lowercase();
        let families = tx
            .prepare(
                "SELECT id,project_id,name FROM entity_families WHERE (? IS NULL OR project_id=?)",
            )
            .map_err(sql)?
            .query_map(params![project, project], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                ))
            })
            .map_err(sql)?
            .filter_map(Result::ok)
            .collect::<Vec<_>>();
        for (family_id, _, name) in families {
            if name.len() >= 2 && lower.contains(&name.to_ascii_lowercase()) {
                tx.execute("INSERT OR IGNORE INTO memory_links(memory_chunk_id,resource_type,resource_id,relation,confidence,resolution_method) VALUES(?,?,?,?,?,?)",params![chunk_id,"entity_family",family_id,"mentions",0.95,"name_or_alias"] ).map_err(sql)?;
            }
            let aliases = tx.prepare("SELECT alias FROM resource_aliases WHERE resource_type='entity_family' AND resource_id=?").map_err(sql)?.query_map([&family_id], |r| r.get::<_,String>(0)).map_err(sql)?.filter_map(Result::ok).collect::<Vec<_>>();
            for alias in aliases {
                if alias.len() >= 2 && lower.contains(&alias.to_ascii_lowercase()) {
                    tx.execute("INSERT OR IGNORE INTO memory_links(memory_chunk_id,resource_type,resource_id,relation,confidence,resolution_method) VALUES(?,?,?,?,?,?)",params![chunk_id,"entity_family",family_id,"mentions",0.9,"name_or_alias"] ).map_err(sql)?;
                }
            }
        }
        let variants=tx.prepare("SELECT v.id,v.display_name FROM entity_variants v JOIN entity_families f ON f.id=v.family_id WHERE (? IS NULL OR v.world_id=?) AND (v.branch_id IS NULL OR v.branch_id IS ?) AND (? IS NULL OR f.project_id=? OR EXISTS(SELECT 1 FROM project_world_links p WHERE p.project_id=? AND p.world_id=v.world_id))")?.query_map(params![world,world,branch,project,project,project],|row|Ok((row.get::<_,String>(0)?,row.get::<_,String>(1)?)))?.collect::<Result<Vec<_>,_>>()?;
        for (variant, label) in variants {
            if label.chars().count() >= 2 && lower.contains(&label.to_lowercase()) {
                tx.execute("INSERT OR IGNORE INTO memory_links(memory_chunk_id,resource_type,resource_id,relation,confidence,resolution_method) VALUES(?,'entity_variant',?,'mentions',0.95,'display_name')",params![chunk_id,variant])?;
            }
        }
        result.push(
            json!({"id":chunk_id,"ordinal":chunk.ordinal,"text":clean,"source_revision":revision}),
        );
    }
    tx.execute("UPDATE memory_chunks SET semantic_status='stale',index_state='stale',updated_at=? WHERE source_type=? AND source_id=? AND source_revision<>? AND semantic_status='active'", params![timestamp,source_type,source_id,revision]).map_err(sql)?;
    tx.commit().map_err(sql)?;
    Ok(
        json!({"source_type":source_type,"source_id":source_id,"source_revision":revision,"chunks":result,"replaced":true,"idempotent":false}),
    )
}

#[cfg(test)]
mod tests {
    use super::replace_chunks;
    use crate::{config::RuntimeConfig, AppState};
    use serde_json::json;

    #[test]
    fn revision_replace_and_source_link_are_atomic_and_idempotent() {
        let dir = tempfile::tempdir().unwrap();
        let config =
            RuntimeConfig::create_default(dir.path().join("runtime.toml"), dir.path()).unwrap();
        let state = AppState::open(config).unwrap();
        let meta = json!({"project_id":"P1","authority":"user_explicit_note","trust_level":"trusted_local"});
        let first =
            replace_chunks(&state, "turn", "T1", "A long enough memory source.", &meta).unwrap();
        assert!(!first["chunks"].as_array().unwrap().is_empty());
        let second =
            replace_chunks(&state, "turn", "T1", "A long enough memory source.", &meta).unwrap();
        assert_eq!(second["idempotent"], true);
        let stale =
            replace_chunks(&state, "turn", "T1", "Changed source revision.", &meta).unwrap();
        assert_eq!(stale["replaced"], true);
        let rows = state.store.query("SELECT semantic_status,authority FROM memory_chunks WHERE source_type='turn' AND source_id='T1' ORDER BY created_at", &[]).unwrap();
        assert!(rows.iter().any(|r| r["semantic_status"] == "stale"));
        assert!(rows
            .iter()
            .any(|r| r["semantic_status"] == "active" && r["authority"] == "user_explicit_note"));
        assert_eq!(
            state
                .store
                .query(
                    "SELECT * FROM memory_links WHERE resource_type='turn' AND resource_id='T1'",
                    &[]
                )
                .unwrap()
                .len(),
            2
        );
    }

    #[test]
    fn source_type_scope_clear_and_aba_are_safe() {
        let dir = tempfile::tempdir().unwrap();
        let config =
            RuntimeConfig::create_default(dir.path().join("runtime.toml"), dir.path()).unwrap();
        let state = AppState::open(config).unwrap();
        let mut meta = json!({"project_id":"P1"});
        let turn = replace_chunks(&state, "turn", "same", "shared source", &meta).unwrap();
        let chat = replace_chunks(&state, "chat_window", "same", "shared source", &meta).unwrap();
        assert_ne!(turn["chunks"][0]["id"], chat["chunks"][0]["id"]);
        meta["project_id"] = json!("P2");
        replace_chunks(&state, "turn", "same", "shared source", &meta).unwrap();
        let scoped = state.store.query("SELECT project_id FROM memory_chunks WHERE source_type='turn' AND source_id='same' AND semantic_status='active'", &[]).unwrap();
        assert_eq!(scoped[0]["project_id"], "P2");
        replace_chunks(&state, "turn", "same", "", &meta).unwrap();
        assert_eq!(state.store.query("SELECT * FROM memory_chunks WHERE source_type='turn' AND source_id='same' AND semantic_status='active'", &[]).unwrap().len(), 0);
        replace_chunks(&state, "turn", "aba", "alpha", &meta).unwrap();
        replace_chunks(&state, "turn", "aba", "beta", &meta).unwrap();
        replace_chunks(&state, "turn", "aba", "alpha", &meta).unwrap();
        let active = state.store.query("SELECT text FROM memory_chunks WHERE source_type='turn' AND source_id='aba' AND semantic_status='active'", &[]).unwrap();
        assert_eq!(active.len(), 1);
        assert_eq!(active[0]["text"], "alpha");
    }
}
