//! Native, revisioned memory projections and discovery review persistence.
pub mod chunking;
pub mod contracts;
pub mod discovery;
pub mod indexing;
pub mod settings;
pub mod spatial;
pub mod temporal;
use crate::{store::Store, ApiError, ApiResult, AppState};
use axum::{
    response::{IntoResponse, Response},
    Json,
};
use rusqlite::{params, types::Value as SqlValue, ToSql};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{collections::HashMap, time::Instant};

const DDL: &str = r#"
CREATE TABLE IF NOT EXISTS memory_chunks(id TEXT PRIMARY KEY,source_type TEXT NOT NULL,source_id TEXT NOT NULL,source_revision TEXT,project_id TEXT,world_id TEXT,branch_id TEXT,session_id TEXT,source_start_id TEXT,source_end_id TEXT,source_recorded_at TEXT,world_time_json TEXT,story_order REAL,scope_kind TEXT NOT NULL DEFAULT 'project',semantic_class TEXT NOT NULL DEFAULT 'evidence',authority TEXT NOT NULL DEFAULT 'project_manuscript',trust_level TEXT NOT NULL DEFAULT 'trusted_local',text TEXT NOT NULL,retrieval_text TEXT,display_excerpt TEXT,token_count INTEGER NOT NULL DEFAULT 0,importance REAL NOT NULL DEFAULT 0.5,extraction_confidence REAL NOT NULL DEFAULT 1.0,identity_confidence REAL NOT NULL DEFAULT 1.0,semantic_status TEXT NOT NULL DEFAULT 'active',index_state TEXT NOT NULL DEFAULT 'pending',checksum TEXT NOT NULL,chunker_version INTEGER NOT NULL DEFAULT 1,index_generation INTEGER,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_native_memory_scope ON memory_chunks(project_id,world_id,branch_id,session_id,semantic_status);
CREATE TABLE IF NOT EXISTS memory_links(memory_chunk_id TEXT NOT NULL,resource_type TEXT NOT NULL,resource_id TEXT NOT NULL,relation TEXT NOT NULL DEFAULT 'mentions',confidence REAL NOT NULL DEFAULT 1.0,resolution_method TEXT NOT NULL DEFAULT 'exact',PRIMARY KEY(memory_chunk_id,resource_type,resource_id,relation),FOREIGN KEY(memory_chunk_id) REFERENCES memory_chunks(id) ON DELETE CASCADE);
CREATE VIRTUAL TABLE IF NOT EXISTS memory_chunks_fts USING fts5(text,content='memory_chunks',content_rowid='rowid');
CREATE TRIGGER IF NOT EXISTS native_memory_insert AFTER INSERT ON memory_chunks BEGIN INSERT INTO memory_chunks_fts(rowid,text) VALUES(new.rowid,new.text); END;
CREATE TRIGGER IF NOT EXISTS native_memory_delete AFTER DELETE ON memory_chunks BEGIN INSERT INTO memory_chunks_fts(memory_chunks_fts,rowid,text) VALUES('delete',old.rowid,old.text); END;
CREATE TRIGGER IF NOT EXISTS native_memory_update AFTER UPDATE OF text ON memory_chunks BEGIN INSERT INTO memory_chunks_fts(memory_chunks_fts,rowid,text) VALUES('delete',old.rowid,old.text); INSERT INTO memory_chunks_fts(rowid,text) VALUES(new.rowid,new.text); END;
CREATE TABLE IF NOT EXISTS memory_index_generations(generation_id INTEGER PRIMARY KEY AUTOINCREMENT,provider TEXT NOT NULL,embedding_model TEXT,embedding_dimension INTEGER,chunker_version INTEGER NOT NULL DEFAULT 1,status TEXT NOT NULL DEFAULT 'building',created_at TEXT NOT NULL,activated_at TEXT,detail_json TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS memory_retrieval_runs(id TEXT PRIMARY KEY,query TEXT NOT NULL,context_json TEXT NOT NULL,result_json TEXT NOT NULL,generation INTEGER,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memory_chunk_embeddings(chunk_id TEXT NOT NULL,model TEXT NOT NULL,dimensions INTEGER NOT NULL,embedding_json TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(chunk_id,model));
CREATE TABLE IF NOT EXISTS memory_timeline_state(id TEXT PRIMARY KEY,world_id TEXT NOT NULL,branch_id TEXT,projection_json TEXT NOT NULL,source_revision TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(world_id,branch_id));
CREATE TABLE IF NOT EXISTS discovery_propositions(id TEXT PRIMARY KEY,proposition_key TEXT NOT NULL UNIQUE,project_id TEXT,world_id TEXT,subject_type TEXT NOT NULL,subject_key TEXT NOT NULL,subject_label TEXT NOT NULL,predicate TEXT NOT NULL,value_json TEXT,object_type TEXT,object_key TEXT,object_label TEXT,operation TEXT NOT NULL,authority_state TEXT NOT NULL DEFAULT 'observed',temporal_state TEXT NOT NULL DEFAULT 'current_or_unspecified',target_resource_type TEXT,target_resource_id TEXT,materialized_resource_type TEXT,materialized_resource_id TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,promoted_at TEXT);
CREATE TABLE IF NOT EXISTS discovery_instances(id TEXT PRIMARY KEY,instance_key TEXT NOT NULL UNIQUE,proposition_id TEXT NOT NULL,source_kind TEXT NOT NULL,source_session_id TEXT,source_turn_id TEXT,origin_session_id TEXT,origin_turn_id TEXT,source_revision TEXT NOT NULL,project_id TEXT,world_id TEXT,branch_id TEXT,world_time_json TEXT,story_order REAL,source_segment TEXT,span_start INTEGER,span_end INTEGER,span_text TEXT NOT NULL DEFAULT '',extraction_confidence REAL NOT NULL DEFAULT 1.0,explicitness TEXT NOT NULL DEFAULT 'explicit',qualifies_review INTEGER NOT NULL DEFAULT 0,active INTEGER NOT NULL DEFAULT 1,invalidation_reason TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS discovery_decisions(id TEXT PRIMARY KEY,proposition_id TEXT NOT NULL,action TEXT NOT NULL,note TEXT NOT NULL DEFAULT '',actor TEXT NOT NULL DEFAULT 'user',created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS continuity_conflicts(id TEXT PRIMARY KEY,project_id TEXT,world_id TEXT,branch_id TEXT,session_id TEXT,subject_key TEXT NOT NULL,predicate TEXT NOT NULL,left_proposition_id TEXT NOT NULL,right_proposition_id TEXT NOT NULL,source_turn_id TEXT,reason TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open',created_at TEXT NOT NULL,resolved_at TEXT);
CREATE TABLE IF NOT EXISTS continuity_conflict_resolutions(id TEXT PRIMARY KEY,conflict_id TEXT NOT NULL,action TEXT NOT NULL,from_proposition_id TEXT,to_proposition_id TEXT,note TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS discovery_subject_links(project_id TEXT NOT NULL DEFAULT '',world_id TEXT NOT NULL DEFAULT '',subject_key TEXT NOT NULL,resource_type TEXT NOT NULL,resource_id TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(project_id,world_id,subject_key));
"#;
fn now() -> String {
    chrono::Utc::now().to_rfc3339()
}
fn newid(p: &str) -> String {
    format!("{}-{}", p, uuid::Uuid::new_v4())
}
fn sv(v: &Value, k: &str) -> Option<String> {
    v.get(k)
        .and_then(Value::as_str)
        .map(str::to_owned)
        .filter(|x| !x.is_empty())
}
fn sql(e: rusqlite::Error) -> ApiError {
    ApiError::internal(e.to_string())
}
fn temporal_allowed(row: &Value, requested: &Value, allow_future: bool) -> bool {
    let want = requested
        .as_str()
        .map(str::to_owned)
        .or_else(|| requested.as_i64().map(|x| x.to_string()));
    let Some(want) = want else {
        return true;
    };
    let have = row.get("world_time").or_else(|| row.get("world_time_json"));
    let Some(have) = have else {
        return true;
    };
    let have_num = have.as_f64().or_else(|| {
        have.as_str()
            .and_then(|x| x.trim_matches('"').parse::<f64>().ok())
    });
    let want_num = want.parse::<f64>().ok();
    allow_future
        || match (have_num, want_num) {
            (Some(a), Some(b)) => a <= b,
            _ => have.as_str().unwrap_or("").trim_matches('"') <= want.as_str(),
        }
}
fn explicitly_allowed(row: &Value, b: &Value) -> bool {
    b.get("explicit_cross_scope_sources")
        .and_then(Value::as_array)
        .map(|xs| {
            xs.iter().any(|x| {
                x.get("source_type").and_then(Value::as_str)
                    == row.get("source_type").and_then(Value::as_str)
                    && x.get("source_id").and_then(Value::as_str)
                        == row.get("source_id").and_then(Value::as_str)
            })
        })
        .unwrap_or(false)
}
fn guarded(row: &Value, b: &Value) -> bool {
    let explicit = explicitly_allowed(row, b);
    for k in ["project_id", "world_id"] {
        if let Some(w) = b.get(k).and_then(Value::as_str) {
            if let Some(v) = row.get(k).and_then(Value::as_str) {
                if v != w && !explicit {
                    return false;
                }
            }
        }
    }
    let trust = row
        .get("trust_level")
        .and_then(Value::as_str)
        .unwrap_or("trusted_local");
    let text = row
        .get("text")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_ascii_lowercase();
    let scratch_allowed = b
        .get("allow_scratch")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    explicit
        || (!matches!(trust, "quarantined")
            && (scratch_allowed || row.get("authority").and_then(Value::as_str) != Some("scratch"))
            && ![
                "ignore all previous instructions",
                "system prompt",
                "developer message",
                "execute this command",
                "call the tool",
            ]
            .iter()
            .any(|x| text.contains(x)))
}

/// Apply the database-backed part of Python's ScopeGate.  Memory chunks are
/// projections, so branch/session lineage must be resolved from the history
/// tables rather than inferred from the chunk's immediate ids.
pub(crate) fn scope_allowed(st: &AppState, row: &Value, b: &Value) -> bool {
    let mut row = row.clone();
    let kind = row["source_type"].as_str().unwrap_or("").to_owned();
    let table = match kind.as_str() {
        "document" => Some("workspace_documents"),
        "entity_variant" => Some("entity_variants"),
        "canon_fact" => Some("canon_facts"),
        "relationship" => Some("relationships"),
        "timeline_event" => Some("timeline_events"),
        "turn" | "chat_window" => Some("turns"),
        _ => None,
    };
    if let Some(table) = table {
        let Some(mut source) = st
            .store
            .get(table, row["source_id"].as_str().unwrap_or_default())
            .ok()
            .flatten()
        else {
            return false;
        };
        if matches!(kind.as_str(), "turn" | "chat_window") {
            if let Some(session) = source["session_id"]
                .as_str()
                .and_then(|id| st.store.get("sessions", id).ok().flatten())
            {
                for key in ["project_id", "world_id", "branch_id"] {
                    source[key] = session[key].clone();
                }
            }
        }
        for key in ["project_id", "world_id", "branch_id", "session_id"] {
            if let Some(value) = source.get(key) {
                row[key] = value.clone();
            }
        }
        if kind == "entity_variant" {
            if let Some(family) = source["family_id"]
                .as_str()
                .and_then(|id| st.store.get("entity_families", id).ok().flatten())
            {
                source["folder_id"] = family["folder_id"].clone();
                row["metadata"]["family_id"] = family["id"].clone();
            }
        }
        row["folder_id"] = source["folder_id"].clone();
    }
    let mut owners = vec![(
        if kind == "canon_fact" {
            "fact".into()
        } else {
            kind
        },
        row["source_id"].as_str().unwrap_or_default().to_owned(),
    )];
    if let Some(family) = row["metadata"]["family_id"].as_str() {
        owners.push(("entity_family".into(), family.into()));
    }
    let mut folder = sv(&row, "folder_id");
    let mut visited = std::collections::HashSet::new();
    while let Some(id) = folder {
        if !visited.insert(id.clone()) {
            return false;
        }
        owners.push(("folder".into(), id.clone()));
        folder = st
            .store
            .get("workspace_folders", &id)
            .ok()
            .flatten()
            .and_then(|folder| sv(&folder, "parent_id"));
    }
    for (kind, key) in [
        ("project", "project_id"),
        ("world", "world_id"),
        ("branch", "branch_id"),
        ("session", "session_id"),
    ] {
        if let Some(id) = row[key].as_str() {
            owners.push((kind.into(), id.into()));
        }
    }
    if let (Some(kind), Some(id)) = (
        row["metadata"]["owner_type"].as_str(),
        row["metadata"]["owner_id"].as_str(),
    ) {
        owners.push((kind.into(), id.into()));
    }
    for (kind, id) in owners {
        if st.store.query("SELECT 1 AS hidden FROM resource_lifecycle WHERE resource_type=? AND resource_id=? AND (trashed_at IS NOT NULL OR archived_at IS NOT NULL) LIMIT 1",&[&kind,&id]).map_or(true,|rows|!rows.is_empty()){return false;}
    }
    scope_allowed_inner(st, &row, b)
}
fn scope_allowed_inner(st: &AppState, row: &Value, b: &Value) -> bool {
    if explicitly_allowed(row, b) || !guarded(row, b) {
        return explicitly_allowed(row, b);
    }
    if let Some(want) = b.get("branch_id").and_then(Value::as_str) {
        let candidate = row.get("branch_id").and_then(Value::as_str);
        if candidate.is_some() {
            let mut visible = std::collections::HashMap::<String, Option<String>>::new();
            let mut current = Some(want.to_owned());
            let mut cutoff: Option<String> = None;
            for _ in 0..128 {
                let Some(id) = current.take() else {
                    break;
                };
                if visible.contains_key(&id) {
                    break;
                }
                visible.insert(id.clone(), cutoff.clone());
                let rowb = st
                    .store
                    .query(
                        "SELECT parent_branch_id,created_at FROM world_branches WHERE id=?",
                        &[&id],
                    )
                    .ok()
                    .and_then(|mut x| x.pop());
                let Some(rowb) = rowb else {
                    break;
                };
                cutoff = rowb
                    .get("created_at")
                    .and_then(Value::as_str)
                    .map(str::to_owned);
                current = rowb
                    .get("parent_branch_id")
                    .and_then(Value::as_str)
                    .map(str::to_owned);
            }
            let Some(cid) = candidate else {
                return true;
            };
            let Some(branch_cutoff) = visible.get(cid) else {
                return false;
            };
            if let Some(cutoff) = branch_cutoff {
                let recorded = row.get("source_recorded_at").and_then(Value::as_str);
                if recorded.is_none() {
                    return false;
                }
                let after = match (
                    chrono::DateTime::parse_from_rfc3339(recorded.unwrap_or("")),
                    chrono::DateTime::parse_from_rfc3339(cutoff),
                ) {
                    (Ok(left), Ok(right)) => left > right,
                    _ => recorded.unwrap_or("") > cutoff.as_str(),
                };
                if after {
                    return false;
                }
            }
        }
    } else if row.get("branch_id").and_then(Value::as_str).is_some() {
        return false;
    }
    if let Some(want) = b.get("session_id").and_then(Value::as_str) {
        let typ = row.get("source_type").and_then(Value::as_str).unwrap_or("");
        if matches!(typ, "turn" | "chat_window") {
            let candidate = row.get("session_id").and_then(Value::as_str);
            let mut visible = std::collections::HashMap::<String, Option<String>>::new();
            let mut current = Some(want.to_owned());
            let mut cutoff: Option<String> = None;
            for _ in 0..256 {
                let Some(id) = current.take() else {
                    break;
                };
                if visible.contains_key(&id) {
                    break;
                }
                visible.insert(id.clone(), cutoff.clone());
                let meta = st
                    .store
                    .query(
                        "SELECT parent_session_id,forked_from_turn_id FROM sessions WHERE id=?",
                        &[&id],
                    )
                    .ok()
                    .and_then(|mut x| x.pop());
                let Some(meta) = meta else {
                    break;
                };
                cutoff = meta
                    .get("forked_from_turn_id")
                    .and_then(Value::as_str)
                    .map(str::to_owned);
                current = meta
                    .get("parent_session_id")
                    .and_then(Value::as_str)
                    .map(str::to_owned);
            }
            let Some(cid) = candidate else {
                return false;
            };
            let Some(session_cutoff) = visible.get(cid) else {
                return false;
            };
            if let Some(stop) = session_cutoff {
                let source_id = row.get("source_id").and_then(Value::as_str).unwrap_or("");
                let ids = st
                    .store
                    .query(
                        "SELECT id FROM turns WHERE session_id=? ORDER BY created_at,id",
                        &[&cid],
                    )
                    .unwrap_or_default();
                let mut found = false;
                for t in ids {
                    if t.get("id").and_then(Value::as_str) == Some(source_id) {
                        found = true;
                    }
                    if t.get("id").and_then(Value::as_str) == Some(stop) {
                        break;
                    }
                }
                if !found {
                    return false;
                }
            }
        }
    } else if matches!(
        row.get("source_type").and_then(Value::as_str),
        Some("turn" | "chat_window")
    ) && row.get("session_id").and_then(Value::as_str).is_some()
    {
        return false;
    }
    if let Some(want) = b.get("world_time") {
        let allow = b
            .get("allow_future_author_knowledge")
            .and_then(Value::as_bool)
            .unwrap_or(false)
            && b.get("context_lens").and_then(Value::as_str) == Some("author");
        if !temporal_allowed(row, want, allow) {
            return false;
        }
    }
    if b.get("pov_variant_id").is_some()
        && (row.get("authority").and_then(Value::as_str) == Some("author_only")
            || row.get("semantic_class").and_then(Value::as_str) == Some("private"))
    {
        return false;
    }
    if let Some(order) = b.get("story_order").and_then(Value::as_f64) {
        if row
            .get("story_order")
            .and_then(Value::as_f64)
            .is_some_and(|value| value > order)
            && !(b.get("context_lens").and_then(Value::as_str) == Some("author")
                && b.get("allow_future_author_knowledge")
                    .and_then(Value::as_bool)
                    .unwrap_or(false))
        {
            return false;
        }
    }
    true
}

/// Read structured projections for query intents that cannot be represented by
/// FTS text alone. Rows are converted to the same provenance shape as memory
/// chunks so the common ScopeGate and packing path remains authoritative.
fn structured_candidates(st: &AppState, b: &Value, query: &str) -> ApiResult<Vec<Value>> {
    let lower = query.to_lowercase();
    let tokens = lower
        .split(|c: char| !c.is_alphanumeric())
        .filter(|word| {
            word.len() > 2
                && ![
                    "what",
                    "who",
                    "where",
                    "when",
                    "does",
                    "know",
                    "knows",
                    "believe",
                    "current",
                    "state",
                    "status",
                    "the",
                    "and",
                    "are",
                    "was",
                    "were",
                    "has",
                    "have",
                    "about",
                    "before",
                    "after",
                    "near",
                    "inside",
                    "located",
                    "thread",
                    "threads",
                    "unresolved",
                    "apa",
                    "siapa",
                    "dimana",
                    "kapan",
                    "yang",
                    "saat",
                    "ini",
                ]
                .contains(word)
        })
        .collect::<Vec<_>>();
    let world = b["world_id"].as_str();
    let variants=st.store.query("SELECT v.id,v.display_name,f.name FROM entity_variants v JOIN entity_families f ON f.id=v.family_id WHERE (? IS NULL OR v.world_id=?)",&[&world,&world])?;
    let names = variants
        .iter()
        .filter_map(|row| {
            row["id"].as_str().map(|id| {
                (
                    id.to_owned(),
                    format!(
                        "{} {}",
                        row["display_name"].as_str().unwrap_or(""),
                        row["name"].as_str().unwrap_or("")
                    )
                    .to_lowercase(),
                )
            })
        })
        .collect::<std::collections::HashMap<_, _>>();
    let mut lanes = vec![("structured_state", "current_state_projection")];
    if b.get("story_order").is_some_and(|v| !v.is_null())
        || [
            "before", "after", "when", "earlier", "past", "sebelum", "sesudah",
        ]
        .iter()
        .any(|word| lower.contains(word))
    {
        lanes.push(("temporal", "state_intervals"));
    }
    if ["know", "belie", "secret", "aware", "tahu", "percaya"]
        .iter()
        .any(|word| lower.contains(word))
    {
        lanes.push(("epistemic", "epistemic_intervals"));
    }
    if [
        "thread",
        "promise",
        "mystery",
        "unresolved",
        "plot",
        "misteri",
    ]
    .iter()
    .any(|word| lower.contains(word))
    {
        lanes.push(("thread", "story_threads"));
    }
    if [
        "where", "near", "inside", "located", "location", "dimana", "dekat", "lokasi",
    ]
    .iter()
    .any(|word| lower.contains(word))
    {
        lanes.push(("spatial", "spatial_edges"));
    }
    let mut out = Vec::new();
    for (lane, table) in lanes {
        let rows = st.store.query(
            &format!(
                "SELECT * FROM {table} WHERE (? IS NULL OR world_id=?) ORDER BY {} DESC LIMIT 400",
                if table == "state_intervals" || table == "epistemic_intervals" {
                    "created_at"
                } else {
                    "updated_at"
                }
            ),
            &[&world, &world],
        )?;
        for row in rows {
            if row
                .get("status")
                .and_then(Value::as_str)
                .is_some_and(|status| {
                    if lane == "thread" {
                        !["open", "developing"].contains(&status)
                    } else {
                        status != "accepted"
                    }
                })
            {
                continue;
            }
            if let Some(order) = b["story_order"].as_f64() {
                if row["story_order_from"]
                    .as_f64()
                    .is_some_and(|start| start > order)
                    || row["story_order_to"]
                        .as_f64()
                        .is_some_and(|end| order >= end)
                {
                    continue;
                }
            }
            if lane == "epistemic"
                && b["pov_variant_id"]
                    .as_str()
                    .is_some_and(|id| row["character_variant_id"] != id)
            {
                continue;
            }
            let mut searchable = row.to_string().to_lowercase();
            for key in [
                "owner_id",
                "character_variant_id",
                "subject_id",
                "object_id",
                "topic_id",
            ] {
                if let Some(label) = row[key].as_str().and_then(|id| names.get(id)) {
                    searchable.push(' ');
                    searchable.push_str(label);
                }
            }
            if !tokens.is_empty() && !tokens.iter().any(|token| searchable.contains(token)) {
                continue;
            }
            if let Some(project) = b["project_id"].as_str() {
                if let Some(owner) = row["project_id"].as_str() {
                    if owner != project {
                        continue;
                    }
                } else if let Some(world) = row["world_id"].as_str() {
                    let allowed: i64=st.store.connection()?.query_row("SELECT EXISTS(SELECT 1 FROM worlds WHERE id=? AND project_id=?) OR EXISTS(SELECT 1 FROM project_world_links WHERE project_id=? AND world_id=?)",rusqlite::params![world,project,project,world],|r|r.get(0))?;
                    if allowed == 0 {
                        continue;
                    }
                }
            }
            let id = row["id"].as_str().map(str::to_owned).unwrap_or_else(|| {
                format!(
                    "{}:{}:{}:{}",
                    row["world_id"], row["branch_id"], row["owner_id"], row["state_key"]
                )
            });
            let value = row
                .get("value")
                .cloned()
                .or_else(|| {
                    row["value_json"]
                        .as_str()
                        .and_then(|value| serde_json::from_str(value).ok())
                })
                .unwrap_or(Value::Null);
            let label = |key: &str| {
                row[key]
                    .as_str()
                    .map(|id| names.get(id).cloned().unwrap_or_else(|| id.to_owned()))
                    .unwrap_or_default()
            };
            let text = match lane {
                "structured_state" | "temporal" => format!(
                    "{} {} = {}",
                    label("owner_id"),
                    row["state_key"].as_str().unwrap_or("state"),
                    value
                ),
                "epistemic" => format!(
                    "{} {} {} = {}",
                    label("character_variant_id"),
                    row["state_type"].as_str().unwrap_or("knows"),
                    label("topic_id"),
                    value
                ),
                "spatial" => format!(
                    "{} {} {}",
                    label("subject_id"),
                    row["relation"].as_str().unwrap_or("near"),
                    label("object_id")
                ),
                _ => format!(
                    "{}: {}",
                    row["title"].as_str().unwrap_or("thread"),
                    row["description"].as_str().unwrap_or("")
                ),
            };
            let candidate = json!({"id":format!("{lane}:{id}"),"source_type":lane,"source_id":id,"project_id":row.get("project_id"),"world_id":row.get("world_id"),"branch_id":row.get("branch_id"),"source_recorded_at":row.get("updated_at").or_else(||row.get("created_at")),"text":text,"authority":row["authority"].as_str().unwrap_or("canon"),"trust_level":"trusted_local","semantic_status":"active","importance":0.9,"metadata":row});
            if scope_allowed(st, &candidate, b) {
                out.push(candidate);
            }
        }
    }
    Ok(out)
}
pub(crate) fn initialize(store: &Store) -> ApiResult<()> {
    temporal::ensure(store)?;
    spatial::ensure(store)?;
    let c = store.connection()?;
    c.execute_batch(DDL).map_err(sql)?;
    c.execute(
        "INSERT INTO memory_chunks_fts(memory_chunks_fts) VALUES('rebuild')",
        [],
    )
    .map_err(sql)?;
    Ok(())
}
fn retrieve(st: &AppState, b: &Value, q: &HashMap<String, String>) -> ApiResult<Value> {
    let query = sv(b, "query").unwrap_or_default();
    if query.trim().is_empty() {
        return Err(ApiError::bad_request("Memory query is empty"));
    }
    let terms = query
        .split(|c: char| !c.is_alphanumeric())
        .filter(|x| !x.is_empty())
        .take(32)
        .map(|x| format!("\"{}\"*", x.replace('"', "")))
        .collect::<Vec<_>>()
        .join(" OR ");
    let mut sqlq = "SELECT c.* FROM memory_chunks c WHERE c.semantic_status='active' AND c.rowid IN(SELECT rowid FROM memory_chunks_fts WHERE memory_chunks_fts MATCH ?) AND NOT EXISTS(SELECT 1 FROM resource_lifecycle l WHERE (l.trashed_at IS NOT NULL OR l.archived_at IS NOT NULL) AND ((l.resource_type=c.source_type AND l.resource_id=c.source_id) OR (l.resource_type='project' AND l.resource_id=c.project_id) OR (l.resource_type='world' AND l.resource_id=c.world_id) OR (l.resource_type='branch' AND l.resource_id=c.branch_id) OR (l.resource_type='session' AND l.resource_id=c.session_id))) AND ((c.source_type='document' AND EXISTS(SELECT 1 FROM workspace_documents d WHERE d.id=c.source_id)) OR (c.source_type='entity_variant' AND EXISTS(SELECT 1 FROM entity_variants v WHERE v.id=c.source_id)) OR c.source_type NOT IN ('document','entity_variant'))".to_owned();
    let mut vals = vec![SqlValue::Text(terms)];
    let explicit = b["explicit_cross_scope_sources"]
        .as_array()
        .is_some_and(|items| !items.is_empty());
    for k in ["project_id", "world_id", "trust_level", "semantic_class"] {
        if explicit && matches!(k, "project_id" | "world_id") {
            continue;
        }
        if let Some(x) = b
            .get(k)
            .and_then(Value::as_str)
            .or_else(|| q.get(k).map(String::as_str))
        {
            if matches!(k, "project_id" | "world_id") {
                sqlq.push_str(&format!(" AND (c.{k}=? OR c.{k} IS NULL)"));
            } else {
                sqlq.push_str(&format!(" AND c.{k}=?"));
            }
            vals.push(SqlValue::Text(x.into()));
        }
    }
    if let Some(x) = b
        .get("story_order")
        .and_then(Value::as_f64)
        .filter(|_| !(b["allow_future_author_knowledge"] == true && b["context_lens"] == "author"))
    {
        sqlq.push_str(" AND (c.story_order IS NULL OR c.story_order<=?)");
        vals.push(SqlValue::Real(x));
    }
    sqlq.push_str(" ORDER BY c.importance DESC,c.updated_at DESC,c.id LIMIT ?");
    vals.push(SqlValue::Integer(500));
    let refs: Vec<&dyn ToSql> = vals.iter().map(|x| x as &dyn ToSql).collect();
    let mut rows = if st.runtime_config()?.bool("memory.fts_enabled", true) {
        st.store.query(&sqlq, &refs)?
    } else {
        Vec::new()
    };
    rows.retain(|row| scope_allowed(st, row, b));
    let mut structured = structured_candidates(st, b, &query)?;
    rows.append(&mut structured);
    let mut seen = std::collections::HashSet::<String>::new();
    rows.retain(|row| {
        seen.insert(
            row.get("id")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_owned(),
        )
    });
    let run = newid("RET");
    let dense_enabled = st
        .runtime_config()
        .map(|cfg| {
            cfg.bool(
                "memory.embedding.enabled",
                cfg.bool("memory.dense_enabled", false),
            )
        })
        .unwrap_or(false);
    let mut selected = rows.clone();
    let mut excluded = Vec::new();
    if let Some(budget) = b.get("token_budget").and_then(Value::as_u64) {
        let limit = budget.saturating_mul(4) as usize;
        let mut used = 0usize;
        selected.retain(|row| {
            let cost = row.get("text").and_then(Value::as_str).map(|text| text.len()).unwrap_or(0);
            if used.saturating_add(cost) <= limit { used += cost; true } else {
                excluded.push(json!({"candidate":row,"decision":{"allowed":false,"rule":"token_budget","reason":"candidate exceeds packed context budget"}}));
                false
            }
        });
    }
    let packed = selected
        .iter()
        .filter_map(|r| r.get("text").and_then(Value::as_str))
        .collect::<Vec<_>>()
        .join("\n\n");
    let structured = selected
        .iter()
        .filter(|r| {
            matches!(
                r.get("source_type").and_then(Value::as_str),
                Some("entity_variant" | "structured_state" | "epistemic")
            )
        })
        .count();
    let thread = selected
        .iter()
        .filter(|r| {
            matches!(
                r.get("source_type").and_then(Value::as_str),
                Some("turn" | "chat_window" | "thread")
            )
        })
        .count();
    let temporal = selected
        .iter()
        .filter(|r| r.get("source_type").and_then(Value::as_str) == Some("timeline_event"))
        .count();
    let spatial = selected
        .iter()
        .filter(|r| r.get("source_type").and_then(Value::as_str) == Some("spatial"))
        .count();
    let lane_other = structured + thread + temporal + spatial;
    let out = json!({"results":rows,"provider":if dense_enabled {"fts5+lmstudio-fail-open"} else {"fts5"},"dense_embeddings":false,"reranked":false,"run_id":run,"plan":{"normalized_query":query,"scope":{"project_id":b.get("project_id"),"world_id":b.get("world_id"),"branch_id":b.get("branch_id"),"session_id":b.get("session_id"),"world_time":b.get("world_time"),"story_order":b.get("story_order"),"pov_variant_id":b.get("pov_variant_id")}},"selected":selected,"excluded":excluded,"packed_text":packed,"lane_counts":{"lexical":selected.len().saturating_sub(lane_other),"dense":0,"structured":structured,"temporal":temporal,"spatial":spatial,"thread":thread},"diagnostics":[],"abstain":false,"abstention_reason":Value::Null});
    st.store.connection()?.execute("INSERT INTO memory_retrieval_runs(id,query,context_json,result_json,created_at) VALUES(?,?,?,?,?)",params![run,query,serde_json::to_string(b).unwrap_or_default(),serde_json::to_string(&out).unwrap_or_default(),now()]).map_err(sql)?;
    Ok(out)
}

/// Async retrieval used by HTTP and generation integration. Lexical retrieval
/// is always authoritative; local model services only enrich/rerank it.
fn pack_retrieval(out: &mut Value, body: &Value) {
    let limit = body["limit"].as_u64().unwrap_or(20).clamp(1, 100) as usize;
    let budget = body["token_budget"].as_u64().unwrap_or(4096) as usize;
    let mut used = 0usize;
    let mut selected = Vec::new();
    let mut excluded = Vec::new();
    let mut seen = std::collections::HashSet::new();
    let mut per_source = HashMap::<String, usize>::new();
    let max_per_source = body["max_per_source"].as_u64().unwrap_or(2) as usize;
    let mut counts = serde_json::Map::new();
    for row in out["results"].as_array().into_iter().flatten() {
        let key = format!("{}:{}", row["source_type"], row["source_id"]);
        let chunk_key = row["id"].to_string();
        if !seen.insert(chunk_key) {
            continue;
        }
        let text = row["text"].as_str().unwrap_or("");
        let cost = text.chars().count().div_ceil(4).max(1);
        let reason = if per_source.get(&key).copied().unwrap_or(0) >= max_per_source {
            Some("source_diversity")
        } else if selected.len() >= limit {
            Some("result_limit")
        } else if used.saturating_add(cost) > budget {
            Some("token_budget")
        } else {
            None
        };
        if let Some(reason) = reason {
            excluded.push(json!({"candidate":row,"decision":{"allowed":false,"rule":reason}}));
            continue;
        }
        used += cost;
        *per_source.entry(key).or_default() += 1;
        let lane = if row.get("dense_score").is_some() {
            "dense"
        } else {
            match row["source_type"].as_str().unwrap_or("") {
                "structured_state" | "epistemic" => "structured",
                "temporal" => "temporal",
                "spatial" => "spatial",
                "thread" => "thread",
                _ => "lexical",
            }
        };
        let count = counts.get(lane).and_then(Value::as_u64).unwrap_or(0);
        counts.insert(lane.to_owned(), json!(count + 1));
        selected.push(row.clone());
    }
    for lane in [
        "lexical",
        "dense",
        "structured",
        "temporal",
        "spatial",
        "thread",
    ] {
        counts.entry(lane).or_insert(json!(0));
    }
    out["selected"] = json!(selected);
    out["packed_text"] = json!(selected
        .iter()
        .filter_map(|row| row["text"].as_str())
        .collect::<Vec<_>>()
        .join("\n\n"));
    out["excluded"] = json!(excluded);
    out["lane_counts"] = json!(counts);
    out["packed_tokens"] = json!(used);
    out["abstain"] = json!(selected.is_empty());
    out["abstention_reason"] = if selected.is_empty() {
        json!("No evidence survived scope and context packing")
    } else {
        Value::Null
    };
}

pub(crate) async fn retrieve_async(
    st: &AppState,
    b: &Value,
    q: &HashMap<String, String>,
) -> ApiResult<Value> {
    let cfg = st.runtime_config()?;
    let settings = settings::settings(&cfg);
    if settings["enabled"] == false {
        return Ok(
            json!({"run_id":"disabled","plan":{"normalized_query":b["query"],"scope":b},"results":[],"selected":[],"excluded":[],"packed_text":"","lane_counts":{},"abstain":true,"abstention_reason":"Memory retrieval is disabled."}),
        );
    }
    let mut body = b.clone();
    for (key, setting) in [
        ("limit", "final_k"),
        ("token_budget", "max_pack_tokens"),
        ("max_per_source", "max_per_source"),
    ] {
        if body.get(key).is_none_or(Value::is_null) {
            body[key] = settings[setting].clone();
        }
    }
    let b = &body;
    let mut out = retrieve(st, b, q)?;
    pack_retrieval(&mut out, b);
    if settings["dense_enabled"] != true {
        st.store.execute(
            "UPDATE memory_retrieval_runs SET result_json=? WHERE id=?",
            &[
                &out.to_string(),
                &out["run_id"].as_str().unwrap_or_default(),
            ],
        )?;
        return Ok(out);
    }
    let base = cfg
        .str("lmstudio.base_url", "http://127.0.0.1:1234")
        .trim_end_matches('/')
        .to_owned();
    let model = settings["embedding"]["model"]
        .as_str()
        .unwrap_or("")
        .to_owned();
    let payload = json!({"model":model,"input":format!("{}{}",settings["embedding"]["query_prefix"].as_str().unwrap_or(""),b.get("query").and_then(Value::as_str).unwrap_or(""))});
    let mut req = st
        .client
        .post(format!("{base}/v1/embeddings"))
        .json(&payload);
    let key = cfg.str("lmstudio.api_key", "");
    if !key.is_empty() {
        req = req.bearer_auth(&key);
    }
    let embedding = match req.send().await {
        Ok(r) => r.json::<Value>().await.ok(),
        Err(_) => None,
    };
    if let Some(e) = embedding {
        let query_vec = e
            .get("data")
            .and_then(Value::as_array)
            .and_then(|x| x.first())
            .and_then(|x| x.get("embedding"))
            .and_then(Value::as_array)
            .cloned()
            .unwrap_or_default();
        let dims = query_vec.len();
        if dims > 0 {
            let mut candidates=st.store.query("SELECT c.* FROM memory_chunks c WHERE c.semantic_status='active' AND NOT EXISTS(SELECT 1 FROM resource_lifecycle l WHERE (l.trashed_at IS NOT NULL OR l.archived_at IS NOT NULL) AND ((l.resource_type=c.source_type AND l.resource_id=c.source_id) OR (l.resource_type='project' AND l.resource_id=c.project_id) OR (l.resource_type='world' AND l.resource_id=c.world_id) OR (l.resource_type='branch' AND l.resource_id=c.branch_id) OR (l.resource_type='session' AND l.resource_id=c.session_id)) AND ((c.source_type='document' AND EXISTS(SELECT 1 FROM workspace_documents d WHERE d.id=c.source_id)) OR (c.source_type='entity_variant' AND EXISTS(SELECT 1 FROM entity_variants v WHERE v.id=c.source_id)) OR c.source_type NOT IN ('document','entity_variant'))) ORDER BY c.updated_at DESC LIMIT 500",&[])?;
            for key in ["project_id", "world_id"] {
                if let Some(want) = b.get(key).and_then(Value::as_str) {
                    candidates.retain(|r| {
                        r.get(key)
                            .and_then(Value::as_str)
                            .map(|x| x == want)
                            .unwrap_or(true)
                    });
                }
            }
            candidates.retain(|row| scope_allowed(st, row, b));
            let mut scored = Vec::new();
            for mut row in candidates.drain(..) {
                let cid = row.get("id").and_then(Value::as_str).unwrap_or("");
                let cached=st.store.query("SELECT embedding_json FROM memory_chunk_embeddings WHERE chunk_id=? AND model=?",&[&cid,&model])?.into_iter().next().and_then(|x|x.get("embedding_json").and_then(Value::as_str).map(str::to_owned));
                let vecv = if let Some(ref raw) = cached {
                    serde_json::from_str::<Value>(raw)
                        .ok()
                        .and_then(|x| x.as_array().cloned())
                } else {
                    let p = json!({"model":model,"input":format!("{}{}",settings["embedding"]["passage_prefix"].as_str().unwrap_or(""),row.get("retrieval_text").or_else(||row.get("text")).and_then(Value::as_str).unwrap_or(""))});
                    let mut request = st.client.post(format!("{base}/v1/embeddings")).json(&p);
                    if !key.is_empty() {
                        request = request.bearer_auth(&key);
                    }
                    match request.send().await {
                        Ok(resp) => resp.json::<Value>().await.ok().and_then(|x| {
                            x.get("data")
                                .and_then(Value::as_array)
                                .and_then(|a| a.first())
                                .and_then(|x| x.get("embedding"))
                                .and_then(Value::as_array)
                                .cloned()
                        }),
                        Err(_) => None,
                    }
                };
                if let Some(v) = vecv {
                    if v.len() == dims {
                        if cached.is_none() {
                            let _=st.store.connection()?.execute("INSERT OR REPLACE INTO memory_chunk_embeddings(chunk_id,model,dimensions,embedding_json,created_at) VALUES(?,?,?,?,?)",params![cid,model,dims,serde_json::to_string(&v).unwrap_or_default(),now()]);
                        }
                        let score = cosine(&query_vec, &v);
                        row["dense_score"] = json!(score);
                        scored.push((score, row));
                    }
                }
            }
            scored.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
            if !scored.is_empty() {
                let mut dense_rows = scored
                    .into_iter()
                    .take(
                        b.get("limit")
                            .and_then(Value::as_u64)
                            .unwrap_or(20)
                            .min(100) as usize,
                    )
                    .map(|(_, r)| r)
                    .collect::<Vec<_>>();
                dense_rows.extend(out["results"].as_array().into_iter().flatten().cloned());
                let mut seen = std::collections::HashSet::new();
                dense_rows.retain(|row| seen.insert(row["id"].to_string()));
                dense_rows.sort_by(|a, b| {
                    b["importance"]
                        .as_f64()
                        .unwrap_or(0.5)
                        .total_cmp(&a["importance"].as_f64().unwrap_or(0.5))
                });
                out["results"] = json!(dense_rows);
                out["selected"] = out["results"].clone();
                out["packed_text"] = json!(out["results"]
                    .as_array()
                    .into_iter()
                    .flatten()
                    .filter_map(|r| r.get("text").and_then(Value::as_str))
                    .collect::<Vec<_>>()
                    .join("\n\n"));
                out["dense_fusion"] = json!(true);
                let dense_count = out["results"].as_array().map(Vec::len).unwrap_or(0);
                if let Some(lanes) = out.get_mut("lane_counts").and_then(Value::as_object_mut) {
                    lanes.insert("dense".into(), json!(dense_count));
                }
            }
        }
        out["dense_embeddings"] = Value::Bool(dims > 0);
        out["embedding_dimensions"] = e
            .get("data")
            .and_then(Value::as_array)
            .and_then(|x| x.first())
            .and_then(|x| x.get("embedding"))
            .and_then(Value::as_array)
            .map(|x| json!(x.len()))
            .unwrap_or(Value::Null);
        if settings["reranker"]["enabled"] == true {
            let rerank_payload = json!({"model":cfg.str("memory.reranker.model", &model),"query":b.get("query"),"documents":out["results"].as_array().into_iter().flatten().map(|row|row["text"].clone()).collect::<Vec<_>>()});
            let mut request = st
                .client
                .post(format!("{base}/v1/rerank"))
                .json(&rerank_payload);
            if !key.is_empty() {
                request = request.bearer_auth(&key);
            }
            if let Ok(resp) = request.send().await {
                if let Ok(v) = resp.json::<Value>().await {
                    out["rerank_trace"] = v;
                    if let Some(items) =
                        out["rerank_trace"].get("results").and_then(Value::as_array)
                    {
                        let prior = out["results"].as_array().cloned().unwrap_or_default();
                        let mut reordered = Vec::new();
                        let mut seen = std::collections::HashSet::new();
                        for item in items {
                            if let Some(index) = item.get("index").and_then(Value::as_u64) {
                                if seen.insert(index) {
                                    if let Some(row) = prior.get(index as usize) {
                                        reordered.push(row.clone());
                                    }
                                }
                            }
                        }
                        if !reordered.is_empty() {
                            reordered.extend(
                                prior
                                    .iter()
                                    .enumerate()
                                    .filter(|(index, _)| !seen.contains(&(*index as u64)))
                                    .map(|(_, row)| row.clone()),
                            );
                            out["results"] = json!(reordered);
                            out["reranked"] = Value::Bool(true);
                        }
                    }
                    out["selected"] = out["results"].clone();
                    out["packed_text"] = json!(out["results"]
                        .as_array()
                        .into_iter()
                        .flatten()
                        .filter_map(|r| r.get("text").and_then(Value::as_str))
                        .collect::<Vec<_>>()
                        .join("\n\n"));
                }
            }
        }
    } else {
        out["dense_fallback_reason"] = Value::String("local embedding provider unavailable".into());
    }
    pack_retrieval(&mut out, b);
    st.store.execute(
        "UPDATE memory_retrieval_runs SET result_json=? WHERE id=?",
        &[
            &out.to_string(),
            &out["run_id"].as_str().unwrap_or_default(),
        ],
    )?;
    Ok(out)
}

fn cosine(a: &[Value], b: &[Value]) -> f64 {
    let mut dot = 0.0;
    let mut na = 0.0;
    let mut nb = 0.0;
    for (i, j) in a.iter().zip(b) {
        let x = i.as_f64().unwrap_or(0.0);
        let y = j.as_f64().unwrap_or(0.0);
        dot += x * y;
        na += x * x;
        nb += y * y;
    }
    if na == 0.0 || nb == 0.0 {
        0.0
    } else {
        dot / (na.sqrt() * nb.sqrt())
    }
}
fn source_project(st: &AppState, kind: &str, row: &Value) -> ApiResult<Option<String>> {
    if let Some(project) = sv(row, "project_id") {
        return Ok(Some(project));
    }
    let (table, id) = match kind {
        "entity_variant" => ("entity_families", sv(row, "family_id")),
        "turn" | "chat_window" => ("sessions", sv(row, "session_id")),
        _ => ("worlds", sv(row, "world_id")),
    };
    Ok(if let Some(id) = id {
        st.store
            .get(table, &id)?
            .and_then(|owner| sv(&owner, "project_id"))
    } else {
        None
    })
}
fn backfill(st: &AppState, project: Option<&str>) -> ApiResult<Value> {
    if !st.runtime_config()?.bool("memory.enabled", true) {
        return Ok(json!({"disabled":true,"documents":0,"turns":0,"chunks":0,"indexed":0}));
    }
    let timer = Instant::now();
    let generation = {
        let mut connection = st.store.connection()?;
        let tx = connection.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        tx.execute(
            "UPDATE memory_index_generations SET status='retired' WHERE status='active'",
            [],
        )?;
        tx.execute("INSERT INTO memory_index_generations(provider,embedding_model,embedding_dimension,chunker_version,status,created_at,activated_at,detail_json) VALUES('fts5',NULL,NULL,1,'active',?,?,?)",params![now(),now(),"{}"])?;
        let generation = tx.last_insert_rowid();
        tx.commit()?;
        generation
    };
    let mut indexed = 0usize;
    for (kind, table) in [
        ("document", "workspace_documents"),
        ("entity_variant", "entity_variants"),
        ("canon_fact", "canon_facts"),
        ("relationship", "relationships"),
        ("timeline_event", "timeline_events"),
        ("turn", "turns"),
    ] {
        for row in st.store.list(table, &[])? {
            if project.is_some_and(|wanted| {
                source_project(st, kind, &row).ok().flatten().as_deref() != Some(wanted)
            }) {
                continue;
            }
            let Some(id) = row["id"].as_str() else {
                continue;
            };
            refresh_source(st, kind, id)?;
            st.store.execute("UPDATE memory_chunks SET index_generation=? WHERE source_id=? AND semantic_status='active'",&[&generation,&id])?;
            indexed += 1;
        }
    }
    Ok(
        json!({"indexed":indexed,"generation":generation,"provider":"fts5","elapsed_ms":timer.elapsed().as_millis()}),
    )
}
fn refresh(st: &AppState, b: &Value) -> ApiResult<Value> {
    if let Some(id) = b.get("turn_id").and_then(Value::as_str) {
        return refresh_turn(st, id);
    }
    if let Some(id) = sv(b, "document_id") {
        let rows = st
            .store
            .query("SELECT * FROM workspace_documents WHERE id=?", &[&id])?;
        if rows.is_empty() {
            return Err(ApiError::not_found("Document not found"));
        }
        return refresh_source(st, "document", &id);
    }
    if let Some(world) = sv(b, "world_id") {
        return temporal::refresh_world(
            &st.store,
            &world,
            b.get("branch_id").and_then(Value::as_str),
        );
    }
    Err(ApiError::bad_request(
        "Provide document_id, turn_id, or world_id",
    ))
}

/// CRUD hooks use this stable API to refresh one document projection.
pub fn refresh_document(st: &AppState, document_id: &str) -> ApiResult<Value> {
    refresh(st, &json!({"document_id": document_id}))
}

/// Refresh any persisted source projection after a workspace mutation. Missing
/// sources are explicitly invalidated so deleted evidence cannot remain active.
pub fn refresh_source(st: &AppState, source_type: &str, source_id: &str) -> ApiResult<Value> {
    if !st.runtime_config()?.bool("memory.enabled", true) {
        return Ok(json!({"disabled":true}));
    }
    if matches!(source_type, "turn" | "chat_window") {
        return refresh_turn(st, source_id);
    }
    let table = match source_type {
        "document" => "workspace_documents",
        "entity_variant" => "entity_variants",
        "canon_fact" => "canon_facts",
        "relationship" => "relationships",
        "timeline_event" => "timeline_events",
        _ => return Err(ApiError::bad_request("Unsupported memory source")),
    };
    let Some(row) = st.store.get(table, source_id)? else {
        return indexing::replace_chunks(st, source_type, source_id, "", &json!({}));
    };
    let content = if source_type == "document" {
        format!(
            "{}\n{}",
            row["title"].as_str().unwrap_or(""),
            row["content"].as_str().unwrap_or("")
        )
    } else {
        let mut evidence = row.clone();
        if let Some(object) = evidence.as_object_mut() {
            for key in ["created_at", "updated_at", "slug"] {
                object.remove(key);
            }
        }
        evidence.to_string()
    };
    let metadata = json!({"project_id":source_project(st,source_type,&row)?,"world_id":row.get("world_id"),"branch_id":row.get("branch_id"),"source_recorded_at":row.get("updated_at").or_else(||row.get("created_at")),"world_time":row.get("world_time"),"story_order":row.get("story_order"),"authority":if source_type=="document"{"project_manuscript"}else{"user_accepted_world_canon"},"trust_level":"trusted_local","importance":if source_type=="document"{0.65}else{0.8}});
    indexing::replace_chunks(st, source_type, source_id, &content, &metadata)
}
pub fn refresh_turn(st: &AppState, turn_id: &str) -> ApiResult<Value> {
    if !st.runtime_config()?.bool("memory.enabled", true) {
        return Ok(json!({"disabled":true}));
    }
    let turn = st
        .store
        .get("turns", turn_id)?
        .ok_or_else(|| ApiError::not_found("Turn not found"))?;
    let session = st
        .store
        .get("sessions", turn["session_id"].as_str().unwrap_or_default())?
        .unwrap_or(json!({}));
    let scope = turn.get("workspace_scope").cloned().unwrap_or(json!({}));
    let scratch = session["scratch_mode"].as_bool().unwrap_or(false);
    let feedback = turn["feedback_status"].as_str().unwrap_or("unreviewed");
    let accepted = matches!(feedback, "accepted" | "edited_accept");
    let mut meta = json!({"project_id":session.get("project_id"),"world_id":session.get("world_id"),"branch_id":session.get("branch_id"),"session_id":session["id"],"source_recorded_at":turn.get("updated_at").or_else(||turn.get("created_at")),"world_time":scope.get("world_time"),"story_order":scope.get("story_order"),"authority":if scratch{"scratch"}else{"user_explicit_note"},"trust_level":"trusted_local","semantic_class":"evidence","importance":0.65});
    indexing::replace_chunks(
        st,
        "turn",
        turn_id,
        turn["user_prompt"].as_str().unwrap_or(""),
        &meta,
    )?;
    meta["authority"] = json!(if scratch {
        "scratch"
    } else if accepted {
        "accepted_generated_output"
    } else {
        "chat_exploration"
    });
    meta["semantic_class"] = json!(if accepted { "decision" } else { "exploratory" });
    meta["importance"] = json!(if accepted { 0.75 } else { 0.4 });
    let prose = if feedback == "edited_accept" {
        turn["edited_story"]
            .as_str()
            .filter(|text| !text.is_empty())
            .unwrap_or(turn["story"].as_str().unwrap_or(""))
    } else {
        turn["story"].as_str().unwrap_or("")
    };
    let result = indexing::replace_chunks(st, "chat_window", turn_id, prose, &meta)?;
    capture_turn(st, turn_id)?;
    Ok(json!({"turn_id":turn_id,"refreshed":true,"source_revision":result["source_revision"]}))
}
/// Extracts a persisted observation from a turn. It intentionally leaves the
/// proposition observed; canon requires an explicit decision route.
pub fn capture_turn(st: &AppState, turn_id: &str) -> ApiResult<Value> {
    discovery::capture(st, turn_id, "user_prompt")
}
fn dget(st: &AppState, id: &str) -> ApiResult<Value> {
    let mut r = st
        .store
        .query("SELECT * FROM discovery_propositions WHERE id=?", &[&id])?;
    let mut p = r
        .pop()
        .ok_or_else(|| ApiError::not_found("Discovery proposition not found"))?;
    p["instances"] = json!(st.store.query(
        "SELECT * FROM discovery_instances WHERE proposition_id=? ORDER BY created_at",
        &[&id]
    )?);
    Ok(p)
}
fn decision(st: &AppState, p: &str, a: &str, b: &Value) -> ApiResult<Value> {
    let c = st.store.connection()?;
    let ok: bool = c
        .query_row(
            "SELECT EXISTS(SELECT 1 FROM discovery_propositions WHERE id=?)",
            [p],
            |r| r.get(0),
        )
        .map_err(sql)?;
    if !ok {
        return Err(ApiError::not_found("Discovery proposition not found"));
    }
    let state = match a {
        "canon" => "canon",
        "dismiss" => "dismissed",
        "reset" => "observed",
        _ => return Err(ApiError::bad_request("unsupported discovery action")),
    };
    let n = now();
    c.execute(
        "UPDATE discovery_propositions SET authority_state=?,updated_at=? WHERE id=?",
        params![state, n, p],
    )
    .map_err(sql)?;
    c.execute("INSERT INTO discovery_decisions(id,proposition_id,action,note,created_at) VALUES(?,?,?,?,?)",params![newid("DEC"),p,a,sv(b,"note").unwrap_or_default(),n]).map_err(sql)?;
    dget(st, p)
}
fn status(st: &AppState) -> ApiResult<Value> {
    let cfg = st.runtime_config()?;
    let config = settings::settings(&cfg);
    let count = |table: &str, filter: &str| -> ApiResult<i64> {
        Ok(st.store.connection()?.query_row(
            &format!("SELECT COUNT(*) FROM {table} {filter}"),
            [],
            |row| row.get(0),
        )?)
    };
    let active=st.store.query("SELECT * FROM memory_index_generations WHERE status='active' ORDER BY generation_id DESC LIMIT 1",&[])?;
    let chunks = count("memory_chunks", "WHERE semantic_status='active'")?;
    let dense = config["dense_enabled"] == true;
    let reranker = config["reranker"]["enabled"] == true;
    let discovery = json!({"propositions":count("discovery_propositions","")?,"instances":count("discovery_instances","")?,"active_instances":count("discovery_instances","WHERE active=1")?,"canon":count("discovery_propositions","WHERE authority_state='canon'")?,"performance":{"pipeline":"native-rust","pipeline_revision":env!("CARGO_PKG_VERSION"),"persistent_cache":false}});
    Ok(
        json!({"available":true,"provider":"fts5","schema_version":2,"fts_available":true,"active_generation":active.first(),"chunks":chunks,"counts":{"active":chunks},"links":count("memory_links","")?,"threads":count("story_threads","WHERE status IN('open','developing')")?,"spatial_edges":count("spatial_edges","WHERE status='accepted'")?,"state_intervals":count("state_intervals","WHERE status='accepted'")?,"epistemic_intervals":count("epistemic_intervals","WHERE status='accepted'")?,"enabled":config["enabled"],"automatic_context":config["automatic_context"],"context_lens":config["default_lens"],"dense_embeddings":dense,"embedding":config["embedding"],"reranker":config["reranker"],"embedding_available":if dense{Value::Null}else{json!(false)},"fallback_active":if dense{Value::Null}else{json!(false)},"fallback":if config["fts_enabled"]==true{"structured indexes + SQLite FTS5"}else{"structured indexes"},"reranker_requested":reranker,"reranker_available":if reranker{Value::Null}else{json!(false)},"context_intelligence_version":"1.2.5a1","discovery":discovery,"config":config}),
    )
}
fn route(
    st: &AppState,
    m: &str,
    p: &[&str],
    q: &HashMap<String, String>,
    b: Value,
) -> ApiResult<Value> {
    match (m, p) {
        ("GET", ["memory", "status"]) => status(st),
        ("POST", ["memory", "query"]) => retrieve(st, &b, q),
        ("POST", ["memory", "backfill"]) => backfill(st, sv(&b, "project_id").as_deref()),
        ("POST", ["memory", "jobs"]) => {
            let job = newid("JOB");
            let n = now();
            st.store.connection()?.execute("INSERT INTO workspace_jobs(id,project_id,job_type,status,progress,message,payload_json,result_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)", params![job,sv(&b,"project_id"),"memory_backfill","running",0.05,"Indexing evidence",serde_json::to_string(&b).unwrap_or_default(),"{}",n,n]).map_err(sql)?;
            let result = backfill(st, sv(&b, "project_id").as_deref())?;
            let n2 = now();
            st.store.connection()?.execute("UPDATE workspace_jobs SET status='done',progress=1.0,message='Memory index ready',result_json=?,updated_at=? WHERE id=?",params![serde_json::to_string(&result).unwrap_or_default(),n2,job]).map_err(sql)?;
            Ok(
                json!({"job":st.store.query("SELECT * FROM workspace_jobs WHERE id=?",&[&job])?.into_iter().next(),"queued":true}),
            )
        }
        ("GET", ["memory", "retrieval", id]) => st
            .store
            .query("SELECT * FROM memory_retrieval_runs WHERE id=?", &[id])?
            .into_iter()
            .next()
            .ok_or_else(|| ApiError::not_found("Retrieval run not found")),
        ("GET", ["memory", "index-generations"]) => Ok(
            json!({"items":st.store.query("SELECT * FROM memory_index_generations ORDER BY generation_id DESC LIMIT ?",&[&q.get("limit").and_then(|value|value.parse::<i64>().ok()).unwrap_or(50).clamp(1,200)])?,"active":st.store.query("SELECT * FROM memory_index_generations WHERE status='active' ORDER BY generation_id DESC LIMIT 1",&[])?.first()}),
        ),
        ("GET", ["memory", "chunks"]) => {
            let mut statement =
                "SELECT c.* FROM memory_chunks c WHERE c.semantic_status='active'".to_owned();
            let mut values = Vec::<SqlValue>::new();
            for key in ["source_type", "source_id"] {
                if let Some(value) = q.get(key) {
                    statement.push_str(&format!(" AND c.{key}=?"));
                    values.push(SqlValue::Text(value.clone()));
                }
            }
            if let (Some(kind), Some(id)) = (q.get("resource_type"), q.get("resource_id")) {
                statement.push_str(" AND EXISTS(SELECT 1 FROM memory_links l WHERE l.memory_chunk_id=c.id AND l.resource_type=? AND l.resource_id=?)");
                values.push(SqlValue::Text(kind.clone()));
                values.push(SqlValue::Text(id.clone()));
            }
            statement.push_str(" ORDER BY c.updated_at DESC,c.id LIMIT ?");
            values.push(SqlValue::Integer(
                q.get("limit")
                    .and_then(|value| value.parse::<i64>().ok())
                    .unwrap_or(100)
                    .clamp(1, 1000),
            ));
            Ok(
                json!({"items":st.store.query(&statement,&values.iter().map(|v|v as &dyn ToSql).collect::<Vec<_>>())?}),
            )
        }
        ("GET", ["memory", "jobs", id]) => st
            .store
            .query("SELECT * FROM workspace_jobs WHERE id=?", &[id])?
            .into_iter()
            .next()
            .ok_or_else(|| ApiError::not_found("Memory job not found")),
        ("POST", ["memory", "refresh"]) => refresh(st, &b),
        ("GET", ["memory", "spatial", "neighborhood"]) => {
            let world = q
                .get("world_id")
                .ok_or_else(|| ApiError::bad_request("world_id is required"))?;
            let resource = q
                .get("resource_id")
                .ok_or_else(|| ApiError::bad_request("resource_id is required"))?;
            let kind = q
                .get("resource_type")
                .ok_or_else(|| ApiError::bad_request("resource_type is required"))?;
            spatial::neighborhood(
                &st.store,
                world,
                q.get("branch_id").map(String::as_str),
                kind,
                resource,
                q.get("depth").and_then(|x| x.parse().ok()).unwrap_or(2),
            )
        }
        ("GET", ["memory", "threads"]) => {
            let world = q
                .get("world_id")
                .ok_or_else(|| ApiError::bad_request("world_id is required"))?;
            temporal::threads(
                &st.store,
                world,
                q.get("branch_id").map(String::as_str),
                q.get("status").map(String::as_str),
                q.get("resource_type").map(String::as_str),
                q.get("resource_id").map(String::as_str),
            )
            .map(|items| json!({"items":items}))
        }
        ("GET", ["memory", "timeline"]) => {
            let world = q
                .get("world_id")
                .ok_or_else(|| ApiError::bad_request("world_id is required"))?;
            Ok(
                json!({"items":st.store.query("SELECT * FROM memory_timeline_state WHERE world_id=? ORDER BY updated_at DESC",&[world])?}),
            )
        }
        ("GET", ["memory", "profiles"]) => contracts::profiles(),
        ("GET", ["memory", "schemas"]) => contracts::schemas(),
        ("GET", ["memory", "schemas", id]) => contracts::schema(id),
        ("GET", ["memory", "discoveries", id]) => dget(st, id),
        ("POST", ["memory", "discoveries", id, "canon"]) => decision(st, id, "canon", &b),
        ("POST", ["memory", "discoveries", id, "dismiss"]) => decision(st, id, "dismiss", &b),
        ("POST", ["memory", "discoveries", id, "reset"]) => decision(st, id, "reset", &b),
        ("POST", ["memory", "discoveries", id, "edit"]) => {
            st.store
                .connection()?
                .execute(
                    "UPDATE discovery_propositions SET value_json=?,updated_at=? WHERE id=?",
                    params![
                        serde_json::to_string(b.get("value").unwrap_or(&Value::Null))
                            .unwrap_or_default(),
                        now(),
                        id
                    ],
                )
                .map_err(sql)?;
            dget(st, id)
        }
        ("GET", ["memory", "discoveries"]) => Ok(
            json!({"items":st.store.query("SELECT * FROM discovery_propositions WHERE authority_state<>'dismissed' ORDER BY updated_at DESC",&[])?}),
        ),
        ("GET", ["memory", "discoveries", "resource", typ, rid]) => Ok(
            json!({"resource_type":typ,"resource_id":rid,"items":st.store.query("SELECT p.* FROM discovery_propositions p JOIN discovery_subject_links l ON l.subject_key=p.subject_key WHERE l.resource_type=? AND l.resource_id=? ORDER BY p.updated_at DESC",&[typ,rid])?}),
        ),
        ("GET", ["memory", "discoveries", "turn", turn, "report"]) => Ok(
            json!({"turn_id":turn,"source_kind":q.get("source_kind").cloned().unwrap_or_else(||"user_prompt".into()),"propositions":st.store.query("SELECT DISTINCT proposition_id FROM discovery_instances WHERE source_turn_id=? AND active=1",&[turn])?.len(),"instances":st.store.query("SELECT id FROM discovery_instances WHERE source_turn_id=? AND active=1",&[turn])?.len(),"persisted":true}),
        ),
        ("POST", ["memory", "discoveries", "backfill"]) => {
            let turns = st.store.query("SELECT id,session_id,user_prompt FROM turns WHERE trim(user_prompt)<>'' ORDER BY created_at", &[]).unwrap_or_default();
            let c = st.store.connection()?;
            let mut created = 0i64;
            for turn in turns {
                let tid = turn["id"].as_str().unwrap_or("");
                let body = turn["user_prompt"].as_str().unwrap_or("");
                let rev = format!("{:x}", Sha256::digest(body.as_bytes()));
                let exists:bool=c.query_row("SELECT EXISTS(SELECT 1 FROM discovery_instances WHERE source_turn_id=? AND source_revision=?)",params![tid,rev],|r|r.get(0)).map_err(sql)?;
                if exists {
                    continue;
                }
                let prop = newid("PROP");
                let inst = newid("INST");
                let n = now();
                c.execute("INSERT INTO discovery_propositions(id,proposition_key,subject_type,subject_key,subject_label,predicate,value_json,operation,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",params![prop,prop,"observation",tid,tid,"text",serde_json::to_string(body).unwrap_or_default(),"assert",n,n]).map_err(sql)?;
                c.execute("INSERT INTO discovery_instances(id,instance_key,proposition_id,source_kind,source_session_id,source_turn_id,source_revision,span_text,qualifies_review,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",params![inst,inst,prop,"user_prompt",turn["session_id"].as_str(),tid,rev,body,1,n,n]).map_err(sql)?;
                created += 1;
            }
            Ok(
                json!({"sessions":0,"propositions":created,"instances":created,"materialization":{"persisted":true}}),
            )
        }
        ("POST", ["memory", "discoveries", "capture-turn", turn]) => {
            let text = sv(&b, "text").ok_or_else(|| ApiError::bad_request("text is required"))?;
            let n = now();
            let prop = newid("PROP");
            let inst = newid("INST");
            st.store.connection()?.execute("INSERT INTO discovery_propositions(id,proposition_key,project_id,world_id,subject_type,subject_key,subject_label,predicate,value_json,operation,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", params![prop,prop,sv(&b,"project_id"),sv(&b,"world_id"),"observation",turn,turn,"text",serde_json::to_string(&text).unwrap_or_default(),"assert",n,n]).map_err(sql)?;
            st.store.connection()?.execute("INSERT INTO discovery_instances(id,instance_key,proposition_id,source_kind,source_turn_id,source_revision,project_id,world_id,span_text,qualifies_review,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", params![inst,inst,prop,"user_prompt",turn,"capture",sv(&b,"project_id"),sv(&b,"world_id"),text,1,n,n]).map_err(sql)?;
            dget(st, &prop)
        }
        ("GET", ["memory", "discoveries", "continuity", "status"]) => Ok(
            json!({"items":st.store.query("SELECT * FROM continuity_conflicts WHERE status='open'",&[])?}),
        ),
        ("GET", ["memory", "discoveries", "continuity", "conflicts"]) => Ok(
            json!({"items":st.store.query("SELECT * FROM continuity_conflicts ORDER BY created_at DESC",&[])?}),
        ),
        ("POST", ["memory", "discoveries", "continuity", "conflicts", id, "resolve"]) => {
            st.store
                .connection()?
                .execute(
                    "UPDATE continuity_conflicts SET status='resolved',resolved_at=? WHERE id=?",
                    params![now(), id],
                )
                .map_err(sql)?;
            Ok(json!({"id":id,"status":"resolved"}))
        }
        _ => Err(ApiError::not_found("Native memory route unavailable")),
    }
}
pub async fn handle(
    st: AppState,
    m: &str,
    p: &[&str],
    q: &HashMap<String, String>,
    b: Value,
) -> Option<ApiResult<Response>> {
    if p.first() != Some(&"memory") {
        return None;
    }
    if let Some(result) = discovery::handle(&st, m, &p[1..], q, &b) {
        return Some(result.map(|value| Json(value).into_response()));
    }
    if m == "POST" && p == ["memory", "backfill"] && b["background"] != false {
        let foundation = crate::foundation::FoundationStore::from_store(st.store.clone());
        let job = match foundation.create_job(
            "memory_backfill",
            b["project_id"].as_str(),
            &b,
            "Queued memory indexing",
        ) {
            Ok(job) => job,
            Err(error) => return Some(Err(error)),
        };
        let job_id = job["id"].as_str().unwrap_or_default().to_owned();
        let project = sv(&b, "project_id");
        let worker = st.clone();
        tokio::spawn(async move {
            let _storage = worker.storage_gate.clone().read_owned().await;
            let _=tokio::task::spawn_blocking(move||{
                let _=worker.store.update("workspace_jobs",&job_id,json!({"status":"running","progress":0.05,"message":"Indexing evidence"}));
                let patch=match backfill(&worker,project.as_deref()){Ok(result)=>json!({"status":"done","progress":1.0,"message":"Memory index ready","result_json":result}),Err(error)=>json!({"status":"failed","message":error.message})};
                let _=worker.store.update("workspace_jobs",&job_id,patch);
            }).await;
        });
        return Some(Ok(Json(json!({"job":job,"queued":true})).into_response()));
    }
    if m == "POST" && p == ["memory", "refresh"] {
        let key = if b["document_id"].as_str().is_some() {
            "document"
        } else if b["turn_id"].as_str().is_some() {
            "turn"
        } else {
            "timeline_state"
        };
        return Some(refresh(&st, &b).map(|result| Json(json!({key:result})).into_response()));
    }
    if m == "POST" && p == ["memory", "query"] {
        return Some(
            retrieve_async(&st, &b, q)
                .await
                .map(|v| Json(v).into_response()),
        );
    }
    Some(route(&st, m, p, q, b).map(|v| Json(v).into_response()))
}

#[cfg(test)]
mod tests {
    use super::*;
    fn fixture() -> (tempfile::TempDir, AppState) {
        let temp = tempfile::tempdir().unwrap();
        let config = crate::config::RuntimeConfig::create_default(
            temp.path().join("config.toml"),
            temp.path(),
        )
        .unwrap();
        (temp, AppState::open(config).unwrap())
    }
    #[test]
    fn legacy_created_at_and_fts_replacement() {
        let (_temp, state) = fixture();
        let world = state.store.list("worlds", &[]).unwrap()[0]["id"]
            .as_str()
            .unwrap()
            .to_owned();
        let project = state.store.list("projects", &[]).unwrap()[0]["id"]
            .as_str()
            .unwrap()
            .to_owned();
        state.store.insert("workspace_documents",json!({"id":"legacy","project_id":project,"world_id":world,"title":"legacy","document_type":"scene","content":"lighthouse amber signal"})).unwrap();
        assert_eq!(backfill(&state, None).unwrap()["indexed"], 1);
        assert_eq!(
            retrieve(&state, &json!({"query":"amber"}), &HashMap::new()).unwrap()["results"]
                .as_array()
                .unwrap()
                .len(),
            1
        );
        state
            .store
            .update(
                "workspace_documents",
                "legacy",
                json!({"content":"violet beacon"}),
            )
            .unwrap();
        backfill(&state, None).unwrap();
        assert!(
            retrieve(&state, &json!({"query":"amber"}), &HashMap::new()).unwrap()["results"]
                .as_array()
                .unwrap()
                .is_empty()
        );
        assert_eq!(
            retrieve(&state, &json!({"query":"violet"}), &HashMap::new()).unwrap()["results"]
                .as_array()
                .unwrap()
                .len(),
            1
        );
    }
    #[test]
    fn scope_before_limit_and_hidden_deleted_owners() {
        let (_temp, state) = fixture();
        let world = state.store.list("worlds", &[]).unwrap()[0]["id"]
            .as_str()
            .unwrap()
            .to_owned();
        let project = state.store.list("projects", &[]).unwrap()[0]["id"]
            .as_str()
            .unwrap()
            .to_owned();
        state.store.insert("workspace_documents",json!({"id":"wanted","project_id":project,"world_id":world,"title":"wanted","document_type":"scene","content":"lighthouse amber signal"})).unwrap();
        backfill(&state, None).unwrap();
        state.store.connection().unwrap().execute("INSERT INTO memory_chunks(id,source_type,source_id,project_id,text,checksum,created_at,updated_at) SELECT 'foreign',source_type,source_id,project_id,text,checksum,created_at,'9999' FROM memory_chunks WHERE source_id='wanted'",[]).unwrap();
        let hit = retrieve(
            &state,
            &json!({"query":"amber","world_id":world,"limit":1}),
            &HashMap::new(),
        )
        .unwrap();
        assert_eq!(hit["results"][0]["source_id"], "wanted");
        crate::foundation::FoundationStore::from_store(state.store.clone())
            .archive("world", &world, true)
            .unwrap();
        assert!(retrieve(
            &state,
            &json!({"query":"amber","world_id":world}),
            &HashMap::new()
        )
        .unwrap()["results"]
            .as_array()
            .unwrap()
            .is_empty());
    }
}
