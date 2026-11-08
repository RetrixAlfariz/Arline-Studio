//! Conversation and LM Studio generation runtime.
//!
//! The provider boundary deliberately lives here: the runtime never starts a
//! Python process and only speaks LM Studio's OpenAI compatible v1 stream.
use axum::{
    body::Body,
    http::{header, StatusCode},
    response::Response,
};
use futures_util::StreamExt;
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    convert::Infallible,
    time::{Duration, Instant},
};
use uuid::Uuid;

use crate::inference::{ProviderAppTimings, RunTelemetry};
use crate::{ApiError, ApiResult, AppState};

struct ProviderTimer {
    started: Instant,
    first_text: Option<std::time::Duration>,
}

impl ProviderTimer {
    fn new() -> Self {
        Self {
            started: Instant::now(),
            first_text: None,
        }
    }

    fn first_text(&mut self) {
        self.first_text
            .get_or_insert_with(|| self.started.elapsed());
    }

    fn finish(self, telemetry: &mut RunTelemetry, raw: &Value) {
        let total = self.started.elapsed();
        telemetry.record_provider_call_with_timings(
            raw,
            ProviderAppTimings {
                first_text: self.first_text,
                total: Some(total),
                text_stream: self.first_text.map(|first| total.saturating_sub(first)),
            },
        );
    }
}

fn inference_snapshot(telemetry: &mut RunTelemetry) -> Value {
    telemetry.freeze_total();
    telemetry.to_value()
}

fn profiled_error(error: ApiError, telemetry: &mut RunTelemetry) -> Response {
    profiled_error_with_partial(error,telemetry,true)
}
fn profiled_error_with_partial(error: ApiError, telemetry: &mut RunTelemetry, partial:bool) -> Response {
    let run_id = telemetry.run_id().to_owned();
    let mut response = json_response_value(json!({
        "detail":error.message,
        "run_id":run_id,
        "stats":{"run_status":"failed","partial":partial,"input_budget":error.diagnostic,"inference":inference_snapshot(telemetry)}
    }));
    *response.status_mut() = error.status;
    response
}

fn generation_telemetry(body: &Value, cfg: &crate::RuntimeConfig) -> RunTelemetry {
    let mut telemetry = RunTelemetry::new(format!("run-{}", Uuid::new_v4()));
    telemetry.record_metadata("backend", json!("lmstudio"));
    telemetry.record_metadata("provider_call_scope", json!("writer"));
    telemetry.record_metadata(
        "model_id",
        json!(payload_string(
            body,
            "model",
            &cfg.str("lmstudio.model", "")
        )),
    );
    telemetry.record_metadata(
        "reasoning_mode",
        json!(payload_string(
            body,
            "reasoning",
            &cfg.str("generation.reasoning", "off")
        )),
    );
    telemetry.record_metadata(
        "generation_mode",
        json!(payload_string(body, "generation_mode", "single")),
    );
    for (key, default) in [
        ("temperature", 0.8),
        ("top_p", 0.95),
        ("top_k", 40.0),
        ("min_p", 0.0),
        ("repeat_penalty", 1.05),
    ] {
        telemetry.record_metadata(
            key,
            body.get(key)
                .cloned()
                .unwrap_or_else(|| json!(cfg.f64(&format!("generation.{key}"), default))),
        );
    }
    telemetry
}

const CHAT_SCHEMA: &str = r#"
CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, pinned INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0, project TEXT, project_id TEXT, world_id TEXT, branch_id TEXT, folder_id TEXT, session_kind TEXT NOT NULL DEFAULT 'chat', tags_json TEXT NOT NULL DEFAULT '[]', workspace_refs_json TEXT NOT NULL DEFAULT '[]', parent_session_id TEXT, forked_from_turn_id TEXT, scratch_mode INTEGER NOT NULL DEFAULT 0, conversation_mode TEXT NOT NULL DEFAULT 'story_writer', conversation_profile_json TEXT NOT NULL DEFAULT '{}', mode_events_json TEXT NOT NULL DEFAULT '[]', world_fork_id TEXT, last_model TEXT, last_mode TEXT, last_reasoning TEXT);
CREATE TABLE IF NOT EXISTS turns (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, run_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, user_prompt TEXT NOT NULL, story TEXT NOT NULL, model TEXT, mode TEXT, reasoning TEXT, projection_mode TEXT, reasoning_text TEXT NOT NULL DEFAULT '', stats_json TEXT NOT NULL DEFAULT '{}', wcf TEXT NOT NULL DEFAULT '', aif_core TEXT NOT NULL DEFAULT '', session_context TEXT NOT NULL DEFAULT '', workspace_context TEXT NOT NULL DEFAULT '', workspace_scope_json TEXT NOT NULL DEFAULT '{}', workspace_refs_json TEXT NOT NULL DEFAULT '[]', lineage_json TEXT NOT NULL DEFAULT '{}', projections_json TEXT NOT NULL DEFAULT '[]', post_validation_json TEXT NOT NULL DEFAULT '{}', wcf_validation_json TEXT NOT NULL DEFAULT '{}', feedback_status TEXT NOT NULL DEFAULT 'unreviewed', feedback_issues_json TEXT NOT NULL DEFAULT '[]', feedback_note TEXT NOT NULL DEFAULT '', edited_story TEXT NOT NULL DEFAULT '', FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS generation_requests (idempotency_key TEXT PRIMARY KEY, endpoint TEXT NOT NULL, scope_hash TEXT NOT NULL, payload_hash TEXT NOT NULL, run_id TEXT NOT NULL, created_at TEXT NOT NULL);
"#;

fn now() -> String {
    chrono::Utc::now().to_rfc3339()
}
fn err(e: impl std::fmt::Display) -> ApiError {
    ApiError::internal(e.to_string())
}
fn preview(text: &str) -> String {
    text.chars().take(1000).collect()
}
fn strv(v: Option<&Value>) -> Option<String> {
    v.and_then(Value::as_str).map(ToOwned::to_owned)
}

struct CancellationGuard {
    store: crate::store::Store,
    turn_id: String,
    finished: bool,
    telemetry: RunTelemetry,
    provider_timer: Option<ProviderTimer>,
    output_budget: crate::inference::budget::OutputBudget,
    story: String,
    reasoning: String,
    last_checkpoint: Option<Instant>,
    checkpoint_writes: u64,
    checkpoint_failures: u64,
}

/// Partial-output checkpoints are throttled: cancel/failure paths write the full
/// in-memory text, so only a process crash can lose at most this window.
const CHECKPOINT_INTERVAL: Duration = Duration::from_millis(250);

impl CancellationGuard {
    fn checkpoint(&mut self) {
        if self
            .last_checkpoint
            .is_some_and(|at| at.elapsed() < CHECKPOINT_INTERVAL)
        {
            return;
        }
        let started = Instant::now();
        // Best effort: the final write is authoritative and startup recovery
        // marks a turn left "running" as interrupted.
        match self.store.update("turns", &self.turn_id, json!({"story":self.story,"reasoning":self.reasoning,"reasoning_text":self.reasoning,"stats_json":{"run_status":"running","partial":true}})) {
            Ok(_) => self.checkpoint_writes += 1,
            Err(_) => self.checkpoint_failures += 1,
        }
        self.last_checkpoint = Some(Instant::now());
        self.telemetry
            .accumulate_stage("persistence", started.elapsed());
    }

    /// Persist a failed run with whatever text arrived; returns whether it was saved.
    fn fail(&mut self, error: &Value) -> bool {
        self.finish_provider(&Value::Null);
        self.finished = true;
        let mut stats = self.status_stats("failed");
        stats["error"] = error.clone();
        self.store
            .update("turns", &self.turn_id, json!({"story":self.story,"reasoning":self.reasoning,"reasoning_text":self.reasoning,"stats_json":stats}))
            .is_ok()
    }

    fn finish_provider(&mut self, raw: &Value) {
        if let Some(timer) = self.provider_timer.take() {
            timer.finish(&mut self.telemetry, raw);
        }
    }

    fn status_stats(&mut self, status: &str) -> Value {
        let mut stats = crate::inference::budget::usage(&Value::Null, &self.output_budget);
        stats["run_status"] = json!(status);
        stats["partial"] = json!(status != "completed");
        stats["inference"] = inference_snapshot(&mut self.telemetry);
        stats
    }
}
impl Drop for CancellationGuard {
    fn drop(&mut self) {
        if self.finished {
            return;
        }
        let store = self.store.clone();
        let id = self.turn_id.clone();
        self.finish_provider(&Value::Null);
        let mut stats = self.status_stats("cancelled");
        stats["checkpoint_writes"] = json!(self.checkpoint_writes);
        let patch = json!({"story":std::mem::take(&mut self.story),"reasoning":self.reasoning,"reasoning_text":std::mem::take(&mut self.reasoning),"stats_json":stats});
        if let Ok(handle) = tokio::runtime::Handle::try_current() {
            handle.spawn_blocking(move || {
                // Nobody is listening anymore; if this fails the turn stays
                // "running" and startup recovery marks it interrupted.
                let _ = store.update("turns", &id, patch);
            });
        }
    }
}

pub fn initialize(store: &crate::store::Store) -> ApiResult<()> {
    store.connection()?.execute_batch(CHAT_SCHEMA).map_err(err)
}

/// Startup only: no run can be in flight yet, so any turn still marked
/// "running" was cut off by a crash or shutdown. Its checkpointed text is kept.
pub fn recover_interrupted(store: &crate::store::Store) -> ApiResult<usize> {
    store
        .connection()?
        .execute(
            "UPDATE turns SET stats_json=json_set(CASE WHEN json_valid(stats_json) THEN stats_json ELSE '{}' END,'$.run_status','interrupted','$.partial',json('true')) WHERE json_valid(stats_json) AND json_extract(stats_json,'$.run_status')='running'",
            [],
        )
        .map_err(err)
}

/// Commit a completed streaming run. `done` may only be sent after this
/// returns Ok: the final stats write is the point where the turn reads as completed.
fn finalize_stream_turn(
    state: &AppState,
    turn_id: &str,
    run_id: &str,
    analysis: &Value,
    bundle: &mut Value,
    stats: &mut Value,
    telemetry: &mut RunTelemetry,
) -> ApiResult<()> {
    let started = Instant::now();
    state.store.update("turns", turn_id, json!({"story":bundle["story"],"reasoning":bundle["reasoning"],"reasoning_text":bundle["reasoning"],"wcf":analysis["wcf"],"aif_core":analysis["aif_core"],"projections_json":analysis["projections"],"post_validation_json":bundle["post_validation"],"wcf_validation_json":analysis["wcf_validation"],"lineage_json":{"analysis_id":run_id}}))?;
    telemetry.accumulate_stage("persistence", started.elapsed());
    let memory_started = Instant::now();
    // The memory index is derived and rebuildable, so it must not fail the run.
    if let Err(error) = crate::foundation::memory::refresh_turn(state, turn_id) {
        stats["memory_index_error"] = json!(error.message);
    }
    telemetry.record_stage("memory_index", memory_started.elapsed());
    stats["inference"] = inference_snapshot(telemetry);
    bundle["stats"] = stats.clone();
    crate::analysis::cache_run(state, run_id, bundle)?;
    state
        .store
        .update("turns", turn_id, json!({"stats_json":stats}))?;
    Ok(())
}

/// INF-10: reserve `idempotency_key` for this run before any writer call.
/// Returns a 409 response for a duplicate; a key reused with another scope or
/// payload is rejected. Requests without a key keep the old behaviour.
fn context_rejection(state:&AppState,original:&Value,session:&str,run_id:&str,error:ApiError,telemetry:&mut RunTelemetry)->Response {
    if original.get("idempotency_key").is_some_and(|v|!v.is_null()) && matches!(error.status,StatusCode::PAYLOAD_TOO_LARGE|StatusCode::UNPROCESSABLE_ENTITY|StatusCode::SERVICE_UNAVAILABLE) {
        // A claimed request rejected before a writer call gets a terminal owner
        // record. A retry with the same key cannot become a second run.
        let persisted=state.store.insert("turns",json!({"session_id":session,"run_id":run_id,"user_prompt":original["prompt"],"story":"","reasoning":"","stats_json":{"run_status":"failed","failure_phase":"context_compilation","partial":false,"overflow_reason":error.message,"input_budget":error.diagnostic}})).is_ok();
        telemetry.record_metadata("context_rejection_persisted",json!(persisted));
    }
    let partial=error.diagnostic.is_none();
    profiled_error_with_partial(error,telemetry,partial)
}

fn claim_request(
    state: &AppState,
    original: &Value,
    endpoint: &str,
    run_id: &str,
) -> ApiResult<Option<Response>> {
    use sha2::{Digest, Sha256};
    let Some(key) = original.get("idempotency_key").filter(|v| !v.is_null()) else {
        return Ok(None);
    };
    let key = key
        .as_str()
        .map(str::trim)
        .filter(|k| !k.is_empty() && k.len() <= 200)
        .ok_or_else(|| {
            ApiError::bad_request(
                "idempotency_key must be a non-empty string of at most 200 characters",
            )
        })?;
    let digest = |value: &Value| format!("{:x}", Sha256::digest(value.to_string()));
    let scope = digest(&json!([
        endpoint,
        original["session_id"],
        original["project_id"],
        original["world_id"],
        original["branch_id"]
    ]));
    let mut payload = original.clone();
    if let Some(object) = payload.as_object_mut() {
        object.remove("idempotency_key");
    }
    let payload = digest(&payload);
    let connection = state.store.connection()?;
    // The primary key makes concurrent claims race-free: exactly one insert wins.
    let claimed = connection.execute(
        "INSERT OR IGNORE INTO generation_requests(idempotency_key,endpoint,scope_hash,payload_hash,run_id,created_at) VALUES(?,?,?,?,?,?)",
        rusqlite::params![key, endpoint, scope, payload, run_id, now()],
    )?;
    if claimed == 1 {
        return Ok(None);
    }
    let (owner_scope, owner_payload, owner_run): (String, String, String) = connection.query_row(
        "SELECT scope_hash,payload_hash,run_id FROM generation_requests WHERE idempotency_key=?",
        [key],
        |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
    )?;
    let mismatch = if owner_scope != scope {
        Some("a different endpoint or session/project/world/branch scope")
    } else if owner_payload != payload {
        Some("a different request payload")
    } else {
        None
    };
    if let Some(what) = mismatch {
        return Err(ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            format!(
                "idempotency_key was already used with {what}; use a new key for a new request"
            ),
        ));
    }
    let turn = connection
        .query_row(
            "SELECT id, json_extract(stats_json,'$.run_status') FROM turns WHERE run_id=? ORDER BY rowid DESC LIMIT 1",
            [&owner_run],
            |row| Ok((row.get::<_, String>(0)?, row.get::<_, Option<String>>(1)?)),
        )
        .ok();
    let body = json!({
        "detail":"Duplicate generation request: this idempotency_key already owns a run",
        "duplicate":true,"run_id":owner_run,
        "turn_id":turn.as_ref().map(|t| t.0.clone()),
        "run_status":turn.and_then(|t| t.1),
    });
    Response::builder()
        .status(StatusCode::CONFLICT)
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(body.to_string()))
        .map(Some)
        .map_err(err)
}

pub async fn ensure_schema(state: &AppState) -> ApiResult<()> {
    initialize(&state.store)
}
fn payload_string(body: &Value, key: &str, default: &str) -> String {
    strv(body.get(key)).unwrap_or_else(|| default.to_owned())
}
fn hydrate_session_scope(state: &AppState, body: &mut Value) -> ApiResult<()> {
    let Some(id) = body["session_id"].as_str() else {
        return Ok(());
    };
    let Some(session) = state.store.get("sessions", id)? else {
        return Ok(());
    };
    for key in [
        "project_id",
        "world_id",
        "branch_id",
        "folder_id",
        "conversation_mode",
        "conversation_profile",
    ] {
        if body.get(key).is_none_or(Value::is_null) {
            if let Some(value) = session.get(key) {
                body[key] = value.clone();
            }
        }
    }
    Ok(())
}
fn session_history(state: &AppState, id: &str) -> ApiResult<Vec<crate::inference::context::HistoryTurn>> {
    let limit = state
        .runtime_config()?
        .u64("history.continuity_turns", 2)
        .min(100) as i64;
    let rows=state.store.query("SELECT id,user_prompt,CASE WHEN feedback_status='edited_accept' AND edited_story<>'' THEN edited_story ELSE story END AS final_story FROM turns WHERE session_id=? AND story<>'' ORDER BY rowid DESC LIMIT ?",&[&id,&limit])?;
    Ok(rows.iter().rev().map(|turn|crate::inference::context::HistoryTurn{
        id:turn["id"].as_str().unwrap_or_default().into(),user:turn["user_prompt"].as_str().unwrap_or_default().into(),assistant:turn["final_story"].as_str().unwrap_or_default().into()
    }).collect())
}

pub(crate) fn delete_history(state: &AppState, kind: &str, id: &str) -> ApiResult<Response> {
    let table = if kind == "turn" { "turns" } else { "sessions" };
    let existing = state
        .store
        .get(table, id)?
        .ok_or_else(|| ApiError::not_found("History record not found"))?;
    let mut connection = state.store.connection()?;
    let transaction =
        connection.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    if kind == "turn" {
        let anchors: i64 = transaction.query_row(
            "SELECT COUNT(*) FROM sessions WHERE forked_from_turn_id=?",
            [id],
            |row| row.get(0),
        )?;
        if anchors > 0 {
            return Err(ApiError::new(
                StatusCode::CONFLICT,
                "Turn is a fork lineage anchor; delete or rebase those forks first",
            ));
        }
        transaction.execute("UPDATE memory_chunks SET semantic_status='deleted',index_state='stale' WHERE source_type IN('turn','chat_window') AND source_id=?",[id])?;
        transaction.execute("UPDATE discovery_instances SET active=0,invalidation_reason='source_deleted',updated_at=? WHERE source_turn_id=?",rusqlite::params![now(),id])?;
        transaction.execute("DELETE FROM turns WHERE id=?", [id])?;
        transaction.execute(
            "UPDATE sessions SET updated_at=? WHERE id=?",
            rusqlite::params![now(), existing["session_id"].as_str()],
        )?;
    } else {
        transaction.execute("UPDATE memory_chunks SET semantic_status='deleted',index_state='stale' WHERE session_id=? OR (source_type IN('turn','chat_window') AND source_id IN(SELECT id FROM turns WHERE session_id=?))",[id,id])?;
        transaction.execute("UPDATE discovery_instances SET active=0,invalidation_reason='source_deleted',updated_at=? WHERE source_session_id=?",rusqlite::params![now(),id])?;
        transaction.execute("DELETE FROM sessions WHERE id=?", [id])?;
    }
    transaction.commit()?;
    json_response(&if kind == "turn" {
        json!({"ok":true,"turn_id":id,"session_id":existing["session_id"]})
    } else {
        json!({"ok":true})
    })
}
fn validate_images(body: &Value) -> ApiResult<()> {
    let Some(images) = body.get("images").and_then(Value::as_array) else {
        return Ok(());
    };
    if images.len() > 8 {
        return Err(ApiError::bad_request("At most 8 images may be attached"));
    }
    for image in images {
        let Some(data) = image.as_str() else {
            return Err(ApiError::bad_request("Image attachment must be a data URL"));
        };
        let Some((head, payload)) = data.split_once(',') else {
            return Err(ApiError::bad_request("Invalid image data URL"));
        };
        let mime = head
            .strip_prefix("data:")
            .and_then(|v| v.split(';').next())
            .unwrap_or("");
        if !matches!(
            mime,
            "image/png" | "image/jpeg" | "image/webp" | "image/gif"
        ) {
            return Err(ApiError::bad_request("Unsupported image MIME type"));
        }
        if payload.len() > 14_000_000 {
            return Err(ApiError::bad_request("Image attachment exceeds 10 MiB"));
        }
    }
    Ok(())
}

fn sse(event: &str, data: &Value) -> String {
    format!(
        "event: {event}\ndata: {}\n\n",
        serde_json::to_string(data).unwrap_or_else(|_| "{}".into())
    )
}
fn take_sse_line(buffer: &mut Vec<u8>) -> Option<String> {
    let end = buffer.iter().position(|b| *b == b'\n')?;
    let line = std::str::from_utf8(&buffer[..end])
        .ok()?
        .trim_end_matches('\r')
        .to_owned();
    buffer.drain(..=end);
    Some(line)
}

/// Conservative token estimate: retrieval packs at 4 chars/token, but the final
/// input uses 3 because overflowing the provider window truncates or fails the run.
fn config_string(cfg: &crate::RuntimeConfig, key: &str, default: &str) -> String {
    cfg.str(key, default)
}
fn config_num(cfg: &crate::RuntimeConfig, key: &str, default: f64) -> f64 {
    let mut value = &cfg.raw;
    for part in key.split('.') {
        value = match value.get(part) {
            Some(v) => v,
            None => return default,
        };
    }
    value
        .as_float()
        .or_else(|| value.as_integer().map(|v| v as f64))
        .unwrap_or(default)
}

pub(crate) fn chat_payload(
    body: &Value,
    cfg: &crate::RuntimeConfig,
    context: &str,
    budget: &crate::inference::budget::OutputBudget,
) -> Value {
    let configured_reasoning = cfg.str("generation.reasoning", "off");
    let requested_reasoning = body
        .get("reasoning")
        .and_then(Value::as_str)
        .unwrap_or(configured_reasoning.as_str());
    let input_text = if context.contains("<REQUEST>") && body["generation_mode"] != "beats" {
        context.to_owned()
    } else if context.is_empty() {
        payload_string(body, "prompt", "")
    } else {
        format!("{context}\n\n{}", payload_string(body, "prompt", ""))
    };
    let mut p = json!({
        "model": payload_string(body, "model", &config_string(cfg, "lmstudio.model", "")),
        "input": input_text, "stream": true,
        "temperature": body.get("temperature").cloned().unwrap_or(json!(config_num(cfg, "generation.temperature", 0.8))),
        "top_p": body.get("top_p").cloned().unwrap_or(json!(config_num(cfg, "generation.top_p", 0.95))),
        "max_output_tokens": budget.api_max,
    });
    if let Some(images) = body.get("images").and_then(Value::as_array) {
        if !images.is_empty() {
            let mut input = vec![json!({"type":"message","content":p["input"]})];
            input.extend(
                images
                    .iter()
                    .map(|image| json!({"type":"image","data_url":image})),
            );
            p["input"] = json!(input);
        }
    }
    let system = body
        .get("system_prompt")
        .and_then(Value::as_str)
        .map(str::to_owned)
        .or_else(|| std::fs::read_to_string(cfg.prompt_path()).ok());
    {
        let mut system = system.unwrap_or_default();
        let mode = payload_string(body, "conversation_mode", "story_writer");
        let instruction = if mode == "story_lab" {
            "Discuss ideas with the author; do not write prose unless explicitly requested."
        } else if mode == "interactive" {
            "Preserve author agency and respond to the active conversational presence."
        } else {
            "Maintain continuity and obey the supplied narrative context."
        };
        system.push_str("\n\n");
        system.push_str(instruction);
        if let Some(profile) = body.get("conversation_profile") {
            system.push_str("\nConversation profile: ");
            system.push_str(&profile.to_string());
        }
        if body
            .get("scratch_mode")
            .and_then(Value::as_bool)
            .unwrap_or(false)
        {
            system.push_str(
                "\nScratch/non-canon exploration; alternatives do not modify accepted canon.",
            );
        }
        p["system_prompt"] = json!(system);
    }
    p["reasoning"] = json!(requested_reasoning);
    for (k, key, fallback) in [
        ("top_k", "generation.top_k", 40.0),
        ("min_p", "generation.min_p", 0.0),
        ("repeat_penalty", "generation.repeat_penalty", 1.05),
        ("context_length", "model_load.context_length", 32768.0),
    ] {
        p[k] = body
            .get(k)
            .cloned()
            .unwrap_or(json!(config_num(cfg, key, fallback)));
    }
    if let Some(v) = body.get("seed") {
        p["seed"] = v.clone();
    }
    p
}

async fn resolve_reasoning(
    state: &AppState,
    cfg: &crate::RuntimeConfig,
    model: &str,
    requested: &str,
) -> ApiResult<Option<String>> {
    let enforce = cfg.bool("reasoning_runtime.enforce_model_capabilities", true);
    if !enforce {
        return Ok(Some(requested.to_owned()));
    }
    let requested = requested.to_ascii_lowercase();
    let response = state
        .client
        .get(format!(
            "{}/api/v1/models",
            cfg.str("lmstudio.base_url", "http://127.0.0.1:1234")
                .trim_end_matches('/')
        ))
        .send()
        .await;
    let Ok(response) = response else {
        if requested == "off" {
            return Ok(Some("off".to_owned()));
        }
        return Err(ApiError::bad_request(
            "Unable to query model reasoning capabilities",
        ));
    };
    if !response.status().is_success() {
        if requested == "off" {
            return Ok(Some("off".to_owned()));
        }
        return Err(ApiError::bad_request(
            "Unable to query model reasoning capabilities",
        ));
    }
    let payload: Value = response
        .json()
        .await
        .map_err(|e| ApiError::bad_request(e.to_string()))?;
    let info = payload
        .get("models")
        .and_then(Value::as_array)
        .and_then(|models| {
            models.iter().find(|item| {
                item.get("key").and_then(Value::as_str) == Some(model)
                    || item.get("id").and_then(Value::as_str) == Some(model)
                    || item.get("loaded_instances").and_then(Value::as_array).is_some_and(|instances|instances.iter().any(|instance|instance["id"]==model))
            })
        });
    let config = info
        .and_then(|item| item.get("capabilities"))
        .and_then(|caps| caps.get("reasoning"))
        .or_else(|| info.and_then(|item| item.get("reasoning")));
    let allowed = config
        .and_then(|v| v.get("allowed_options"))
        .and_then(Value::as_array)
        .map(|xs| {
            xs.iter()
                .filter_map(Value::as_str)
                .map(|s| s.to_ascii_lowercase())
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    if requested == "off" && allowed.is_empty() {
        return Ok(None);
    }
    if allowed.is_empty() || !allowed.iter().any(|x| x == &requested) {
        return Err(ApiError::bad_request(format!(
            "Model {model:?} does not support reasoning={requested:?}"
        )));
    }
    Ok(Some(requested))
}

async fn model_stream(
    state: &AppState,
    body: &Value,
    context: &crate::inference::context::CompiledWriterContext,
    budget: &crate::inference::budget::OutputBudget,
    telemetry: &mut RunTelemetry,
) -> ApiResult<(String, String, Value, Value, crate::inference::context::CompiledWriterContext)> {
    let cfg = state.runtime_config()?;
    let model = payload_string(body, "model", &config_string(&cfg, "lmstudio.model", ""));
    let configured_reasoning = cfg.str("generation.reasoning", "off");
    let requested_reasoning = body
        .get("reasoning")
        .and_then(Value::as_str)
        .unwrap_or(&configured_reasoning)
        .to_owned();
    let capability_started = Instant::now();
    let effective_reasoning = resolve_reasoning(state, &cfg, &model, &requested_reasoning).await?;
    telemetry.accumulate_stage("provider_capabilities", capability_started.elapsed());
    let base = config_string(&cfg, "lmstudio.base_url", "http://127.0.0.1:1234")
        .trim_end_matches('/')
        .to_owned();
    let url = format!("{base}/api/v1/chat");
    let mut compiled = crate::inference::context::compile(state,&cfg,body,&context.selection,budget.api_max,|text|{
        let mut payload=chat_payload(body,&cfg,text,budget);
        if let Some(ref reasoning)=effective_reasoning {payload["reasoning"]=json!(reasoning);}else if let Some(object)=payload.as_object_mut(){object.remove("reasoning");}
        payload
    }).await?;
    let provider_body=compiled.payload.clone();
    telemetry.record_metadata(
        "effective_reasoning",
        provider_body
            .get("reasoning")
            .cloned()
            .unwrap_or(json!("omitted")),
    );
    let mut request = state.client.post(url.clone()).json(&provider_body);
    let api_key = cfg.str("lmstudio.api_key", "");
    if !api_key.is_empty() {
        request = request.bearer_auth(api_key);
    }
    let mut provider_timer = ProviderTimer::new();
    let result = async {
        let response = request
            .send()
            .await
            .map_err(|e| err(format!("LM Studio request failed at {url}: {e}")))?;
        let status = response.status();
        if !status.is_success() {
            let text = response.text().await.unwrap_or_default();
            return Err(ApiError::bad_request(format!(
                "LM Studio HTTP {status}: {}",
                preview(&text)
            )));
        }
        let mut bytes = response.bytes_stream();
        let mut story = String::new();
        let mut reasoning = String::new();
        let mut final_story = String::new();
        let mut final_reasoning = String::new();
        let mut saw_story_delta = false;
        let mut saw_reasoning_delta = false;
        let mut raw = Vec::new();
        let mut final_response = Value::Null;
        let mut pending = Vec::new();
        let mut current_event = String::from("message");
        while let Some(item) = bytes.next().await {
            let chunk = item.map_err(err)?;
            raw.extend_from_slice(&chunk);
            pending.extend_from_slice(&chunk);
            while let Some(line) = take_sse_line(&mut pending) {
                if let Some(event) = line.strip_prefix("event:") {
                    current_event = event.trim().to_owned();
                    continue;
                }
                let Some(data) = line.strip_prefix("data:").map(str::trim) else {
                    continue;
                };
                if data == "[DONE]" {
                    continue;
                }
                let Ok(v) = serde_json::from_str::<Value>(data) else {
                    continue;
                };
                let content = v.get("content").and_then(Value::as_str).unwrap_or_default();
                let typ = v
                    .get("type")
                    .and_then(Value::as_str)
                    .unwrap_or(&current_event);
                if typ.contains("error") || v.get("error").is_some() {
                    return Err(ApiError::internal(format!(
                        "LM Studio generation failed: {}",
                        preview(&v.to_string())
                    )));
                }
                if !content.is_empty() && typ.contains("reason") {
                    provider_timer.first_text();
                    reasoning.push_str(content);
                    saw_reasoning_delta = true;
                } else if !content.is_empty() && (typ.contains("message") || typ.ends_with("delta"))
                {
                    provider_timer.first_text();
                    story.push_str(content);
                    saw_story_delta = true;
                }
                if let Some(result) = v.get("result") {
                    final_response = result.clone();
                    if let Some(items) = result.get("output").and_then(Value::as_array) {
                        for x in items {
                            let c = x.get("content").and_then(Value::as_str).unwrap_or_default();
                            if x.get("type").and_then(Value::as_str) == Some("reasoning") {
                                final_reasoning.push_str(c)
                            } else {
                                final_story.push_str(c)
                            }
                        }
                    }
                }
            }
        }
        if !saw_story_delta {
            story.push_str(&final_story);
            if !final_story.is_empty() {
                provider_timer.first_text();
            }
        }
        if !saw_reasoning_delta {
            reasoning.push_str(&final_reasoning);
            if !final_reasoning.is_empty() {
                provider_timer.first_text();
            }
        }
        if story.trim().is_empty() {
            return Err(ApiError::internal(
                "LM Studio stream ended without message output",
            ));
        }
        let raw = if final_response.is_null() {
            serde_json::from_slice(&raw).unwrap_or_else(|_| json!({"raw_bytes": raw.len()}))
        } else {
            final_response
        };
        crate::inference::context::observe_usage(&mut compiled.report,&raw);
        Ok((story.trim().to_owned(), reasoning, raw, provider_body, compiled))
    }
    .await;
    provider_timer.finish(
        telemetry,
        result
            .as_ref()
            .map(|(_, _, raw, _, _)| raw)
            .unwrap_or(&Value::Null),
    );
    result
}

fn run_stats(
    raw: &Value,
    request: &Value,
    body: &Value,
    cfg: &crate::RuntimeConfig,
    status: &str,
    resolved: &crate::inference::budget::OutputBudget,
) -> Value {
    let mut stats = raw["stats"].as_object().cloned().unwrap_or_default();
    if let Some(usage) = crate::inference::budget::usage(raw, resolved).as_object() {
        stats.extend(usage.clone());
    }
    stats.insert(
        "requested_reasoning".into(),
        json!(payload_string(
            body,
            "reasoning",
            &cfg.str("generation.reasoning", "off")
        )),
    );
    stats.insert(
        "api_reasoning".into(),
        request
            .get("reasoning")
            .cloned()
            .unwrap_or(json!("omitted")),
    );
    stats.insert("run_status".into(), json!(status));
    stats.insert("partial".into(), json!(status != "completed"));
    Value::Object(stats)
}

async fn generate_stream_response(
    state: &AppState,
    mut body: Value,
    original: &Value,
) -> ApiResult<Response> {
    let mut telemetry = generation_telemetry(&body, &state.runtime_config()?);
    let run_id = telemetry.run_id().to_owned();
    ensure_schema(state).await?;
    validate_images(&body)?;
    hydrate_session_scope(state, &mut body)?;
    if payload_string(&body, "generation_mode", "single") != "single" {
        return Err(ApiError::bad_request(
            "Streaming generation supports single mode only",
        ));
    }
    let prompt = payload_string(&body, "prompt", "");
    if prompt.trim().is_empty() {
        return Err(ApiError::bad_request("Prompt is empty"));
    }
    let session_id = strv(body.get("session_id")).unwrap_or_else(|| Uuid::new_v4().to_string());
    if let Some(session) = state.store.get("sessions", &session_id)? {
        for key in ["project_id", "world_id", "branch_id"] {
            if let (Some(requested), Some(bound)) = (strv(body.get(key)), strv(session.get(key))) {
                if requested != bound {
                    return Err(ApiError::bad_request(format!(
                        "{key} does not match the active session scope"
                    )));
                }
            }
        }
    }
    if let Some(duplicate) = claim_request(state, original, "generate/stream", &run_id)? {
        return Ok(duplicate);
    }
    if state.store.get("sessions", &session_id)?.is_none() {
        state.store.insert("sessions", json!({"id":session_id,"title":prompt.chars().take(80).collect::<String>(),"project_id":body.get("project_id"),"world_id":body.get("world_id"),"branch_id":body.get("branch_id"),"conversation_mode":payload_string(&body,"conversation_mode","story_writer"),"conversation_profile_json":body.get("conversation_profile").cloned().unwrap_or(json!({})),"workspace_refs_json":body.get("references").cloned().unwrap_or(json!([])),"scratch_mode":body.get("scratch_mode").and_then(Value::as_bool).unwrap_or(false),"created_at":now(),"updated_at":now()}))?;
    }
    let history = session_history(state, &session_id)?;
    let (context, mut analytical, budgets) =
        match prepare_generation(state, &body, &history, &mut telemetry).await {
            Ok(value) => value,
            Err(error) => return Ok(context_rejection(state,original,&session_id,&run_id,error,&mut telemetry)),
        };
    let cfg = state.runtime_config()?;
    let base = cfg.str("lmstudio.base_url", "http://127.0.0.1:1234");
    let url = format!("{}/api/v1/chat", base.trim_end_matches('/'));
    let mut provider_body = chat_payload(&body, &cfg, &context, &budgets.writers[0]);
    let deliberation = analytical["deliberation"].clone();
    let model = payload_string(&body, "model", &cfg.str("lmstudio.model", ""));
    let configured_reasoning = cfg.str("generation.reasoning", "off");
    let requested_reasoning = body
        .get("reasoning")
        .and_then(Value::as_str)
        .unwrap_or(&configured_reasoning);
    let capability_started = Instant::now();
    let effective_reasoning = resolve_reasoning(state, &cfg, &model, requested_reasoning).await?;
    telemetry.record_stage("provider_capabilities", capability_started.elapsed());
    if let Some(reasoning) = effective_reasoning {
        provider_body["reasoning"] = json!(reasoning);
    } else if let Some(object) = provider_body.as_object_mut() {
        object.remove("reasoning");
    }
    let compiled=match crate::inference::context::compile(state,&cfg,&body,&context.selection,budgets.writers[0].api_max,|text|{
        let mut payload=chat_payload(&body,&cfg,text,&budgets.writers[0]);
        if let Some(value)=provider_body.get("reasoning"){payload["reasoning"]=value.clone();}else{payload.as_object_mut().unwrap().remove("reasoning");}payload
    }).await {Ok(value)=>value,Err(error)=>return Ok(context_rejection(state,original,&session_id,&run_id,error,&mut telemetry))};
    apply_compiled(&mut analytical,&compiled);
    let context=compiled;
    let provider_body=context.payload.clone();
    let model_input=provider_body["input"].clone();
    let mut request = state.client.post(url).json(&provider_body);
    let api_key = cfg.str("lmstudio.api_key", "");
    if !api_key.is_empty() {
        request = request.bearer_auth(api_key);
    }
    let turn_id = Uuid::new_v4().to_string();
    let write_started = Instant::now();
    state.store.insert("turns", json!({"id":turn_id,"session_id":session_id,"run_id":run_id,"user_prompt":prompt,"story":"","reasoning":"","reasoning_text":"","model":payload_string(&body,"model",""),"mode":payload_string(&body,"input_mode","smart_hybrid"),"stats_json":{"run_status":"running"},"session_context":context,"created_at":now(),"updated_at":now()}))?;
    telemetry.accumulate_stage("persistence", write_started.elapsed());
    telemetry.record_metadata(
        "effective_reasoning",
        provider_body
            .get("reasoning")
            .cloned()
            .unwrap_or(json!("omitted")),
    );
    let stream_state = state.clone();
    let stream = async_stream::stream! {
        let mut cancellation = CancellationGuard { store: stream_state.store.clone(), turn_id: turn_id.clone(), finished: false, telemetry, provider_timer: None, output_budget:budgets.writers[0].clone(), story: String::new(), reasoning: String::new(), last_checkpoint: None, checkpoint_writes: 0, checkpoint_failures: 0 };
        let mut pending=Vec::<u8>::new();
        let mut raw_response=json!({});
        yield Ok::<_,Infallible>(sse("run.start",&json!({"run_id":run_id,"session_id":session_id})));
        cancellation.provider_timer = Some(ProviderTimer::new());
        let response=match request.send().await{Ok(v)=>v,Err(e)=>{let persisted=cancellation.fail(&json!(e.to_string()));yield Ok(sse("error",&json!({"message":e.to_string(),"run_id":run_id,"persisted":persisted})));return;}};
        if !response.status().is_success(){let status=response.status();let text=response.text().await.unwrap_or_default();let persisted=cancellation.fail(&json!(format!("LM Studio HTTP {status}")));yield Ok(sse("error",&json!({"message":format!("LM Studio HTTP {status}: {}",preview(&text)),"run_id":run_id,"persisted":persisted})));return;}
        let mut bytes=response.bytes_stream(); let mut current_event=String::from("message"); let mut provider_failed=false; let mut provider_error=String::new();
        while let Some(item)=bytes.next().await {
            let chunk=match item{Ok(v)=>v,Err(e)=>{provider_failed=true;provider_error=e.to_string();break;}};
            pending.extend_from_slice(&chunk);
            while let Some(line)=take_sse_line(&mut pending){
                if let Some(ev)=line.strip_prefix("event:"){current_event=ev.trim().to_owned();continue}
                let Some(data)=line.strip_prefix("data:").map(str::trim)else{continue};
                if data=="[DONE]"{continue}
                let Ok(v)=serde_json::from_str::<Value>(data)else{continue};
                let content=v.get("content").and_then(Value::as_str).unwrap_or_default();
                let typ=v.get("type").and_then(Value::as_str).unwrap_or(&current_event);
                if typ.contains("error")||v.get("error").is_some(){provider_failed=true;provider_error=v.to_string();break;}
                if let Some(result)=v.get("result"){raw_response=result.clone();}
                if !content.is_empty()&&typ.contains("reason"){if let Some(timer)=cancellation.provider_timer.as_mut(){timer.first_text();} cancellation.reasoning.push_str(content);yield Ok(sse("reasoning.delta",&json!({"content":content})));}
                else if !content.is_empty()&&(typ.contains("message")||typ.ends_with("delta")){
                    if let Some(timer) = cancellation.provider_timer.as_mut() { timer.first_text(); }
                    cancellation.story.push_str(content);
                    cancellation.checkpoint();
                    cancellation.telemetry.record_server_first_visible_text(cancellation.telemetry.elapsed());
                    yield Ok(sse("answer.delta",&json!({"content":content})));
                }
            }
            if provider_failed{break;}
        }
        if let Some(output)=raw_response["output"].as_array(){
            let final_story=output.iter().filter(|item|item["type"]=="message").filter_map(|item|item["content"].as_str()).collect::<String>();
            let final_reasoning=output.iter().filter(|item|item["type"]=="reasoning").filter_map(|item|item["content"].as_str()).collect::<String>();
            if cancellation.story.is_empty()&&!final_story.is_empty(){if let Some(timer)=cancellation.provider_timer.as_mut(){timer.first_text();} cancellation.story=final_story;cancellation.telemetry.record_server_first_visible_text(cancellation.telemetry.elapsed());yield Ok(sse("answer.delta",&json!({"content":cancellation.story})));}
            if cancellation.reasoning.is_empty()&&!final_reasoning.is_empty(){if let Some(timer)=cancellation.provider_timer.as_mut(){timer.first_text();} cancellation.reasoning=final_reasoning;yield Ok(sse("reasoning.delta",&json!({"content":cancellation.reasoning})));}
        }
        let completed=!provider_failed&&!cancellation.story.trim().is_empty();
        cancellation.finish_provider(&raw_response);
        let mut stats=run_stats(&raw_response,&provider_body,&body,&cfg,if completed{"completed"}else{"failed"},&budgets.writers[0]);
        stats["checkpoint_writes"]=json!(cancellation.checkpoint_writes);
        stats["checkpoint_failures"]=json!(cancellation.checkpoint_failures);
        stats["input_budget"]=analytical["input_budget"].clone();
        crate::inference::context::observe_usage(&mut stats["input_budget"],&raw_response);
        if !completed {
            let message=if provider_error.is_empty(){"LM Studio returned no message output".to_owned()}else{provider_error};
            stats["inference"]=inference_snapshot(&mut cancellation.telemetry);
            stats["error"]=json!(message);
            cancellation.finished=true;
            let persisted=stream_state.store.update("turns",&turn_id,json!({"story":cancellation.story,"reasoning":cancellation.reasoning,"reasoning_text":cancellation.reasoning,"stats_json":stats})).is_ok();
            yield Ok(sse("error",&json!({"message":message,"run_id":run_id,"session_id":session_id,"turn_id":turn_id,"persisted":persisted})));
            return;
        }
        let story=cancellation.story.clone();
        let reasoning=cancellation.reasoning.clone();
        let validation_started=Instant::now();
        let quality=crate::analysis::quality_report_with_context(&story, analytical.get("writer_context"));
        cancellation.telemetry.record_stage("validation",validation_started.elapsed());
        let analysis=&analytical;
        let mut done_bundle = json!({"analysis_id":run_id,"run_id":run_id,"turn_id":turn_id,"input_mode":payload_string(&body,"input_mode","smart_hybrid"),"projection_mode":payload_string(&body,"projection_mode","balanced"),"wcf":analysis["wcf"],"aif_core":analysis["aif_core"],"narrative_brief":analysis["narrative_brief"],"deliberation":deliberation,"projections":analysis["projections"],"wcf_validation":analysis["wcf_validation"],"extracted_state":analysis["extracted_state"],"events":analysis["events"],"semantic_core":analysis["semantic_core"],"writer_context":analysis["writer_context"],"world_runtime":analysis["world_runtime"],"narrative_runtime":analysis["narrative_runtime"],"model_input":model_input,"trace_choices":analysis["trace_choices"],"story":story,"reasoning":reasoning,"stats":stats,"post_validation":{"quality_report":quality},"raw_response":raw_response});
        let finalized=finalize_stream_turn(&stream_state,&turn_id,&run_id,analysis,&mut done_bundle,&mut stats,&mut cancellation.telemetry);
        cancellation.finished=true;
        if let Err(error)=finalized {
            // The run produced output but could not be committed: never report done.
            stats["run_status"]=json!("failed");
            stats["error"]=json!(format!("persistence failed: {}",error.message));
            let persisted=stream_state.store.update("turns",&turn_id,json!({"stats_json":stats})).is_ok();
            yield Ok(sse("error",&json!({"message":format!("Generation output could not be saved: {}",error.message),"run_id":run_id,"session_id":session_id,"turn_id":turn_id,"persisted":persisted})));
            return;
        }
        done_bundle["session_id"]=json!(session_id);
        done_bundle["quality_report"]=done_bundle["post_validation"]["quality_report"].clone();
        done_bundle["summary"]=json!({"response_kind":if payload_string(&body,"conversation_mode","story_writer")=="story_lab"{"discussion"}else{"prose"}});
        yield Ok(sse("done",&done_bundle));
    };
    Response::builder()
        .status(StatusCode::OK)
        .header(header::CONTENT_TYPE, "text/event-stream")
        .header("cache-control", "no-cache")
        .body(Body::from_stream(stream))
        .map_err(err)
}

async fn generate(state: &AppState, mut body: Value, original: &Value) -> ApiResult<Response> {
    let mut telemetry = generation_telemetry(&body, &state.runtime_config()?);
    let run_id = telemetry.run_id().to_owned();
    ensure_schema(state).await?;
    hydrate_session_scope(state, &mut body)?;
    validate_images(&body)?;
    let prompt = payload_string(&body, "prompt", "");
    if prompt.trim().is_empty() {
        return Err(ApiError::bad_request("Prompt is empty"));
    }
    let session_id = strv(body.get("session_id")).unwrap_or_else(|| Uuid::new_v4().to_string());
    let existing = state.store.get("sessions", &session_id)?;
    if let Some(ref session) = existing {
        for key in ["project_id", "world_id", "branch_id"] {
            if let (Some(requested), Some(bound)) = (strv(body.get(key)), strv(session.get(key))) {
                if requested != bound {
                    return Err(ApiError::bad_request(format!(
                        "{key} does not match the active session scope"
                    )));
                }
            }
        }
    }
    if let Some(duplicate) = claim_request(state, original, "generate", &run_id)? {
        return Ok(duplicate);
    }
    if existing.is_none() {
        let title = prompt.chars().take(80).collect::<String>();
        state.store.insert("sessions", json!({"id":session_id,"title":title,"project_id":body.get("project_id"),"world_id":body.get("world_id"),"branch_id":body.get("branch_id"),"conversation_mode":payload_string(&body,"conversation_mode","story_writer"),"conversation_profile_json":body.get("conversation_profile").cloned().unwrap_or(json!({})),"workspace_refs_json":body.get("references").cloned().unwrap_or(json!([])),"scratch_mode":body.get("scratch_mode").and_then(Value::as_bool).unwrap_or(false),"created_at":now(),"updated_at":now()}))?;
    }
    let history = if existing.is_some() {
        session_history(state, &session_id)?
    } else {
        Vec::new()
    };
    let (mut context, mut analytical, budgets) =
        match prepare_generation(state, &body, &history, &mut telemetry).await {
            Ok(value) => value,
            Err(error) => return Ok(context_rejection(state,original,&session_id,&run_id,error,&mut telemetry)),
        };
    let generation_mode = payload_string(&body, "generation_mode", "single");
    let (story, reasoning, raw, provider_request, beat_stats) = if generation_mode == "beats" {
        let count = budgets.writers.len();
        let per_beat = budgets.writers[0].visible;
        let total_budget: u64 = budgets.writers.iter().map(|b| b.visible).sum();
        let mut stories = Vec::new();
        let mut thoughts = Vec::new();
        let mut raws = Vec::new();
        let mut requests = Vec::new();
        let mut beat_usage = Vec::new();
        for index in 1..=count {
            let mut beat_body = body.clone();
            let previous = stories.join("\n\n");
            let instruction = format!("{}\n\nBeat {index} of {count}; advance one coherent narrative unit. Do not recap earlier beats.\n{}", prompt, if previous.is_empty(){String::new()}else{format!("Previous surface:\n{}", previous)});
            beat_body["prompt"] = json!(instruction);
            let resolved = &budgets.writers[index - 1];
            beat_body["visible_output_tokens"] = json!(resolved.visible);
            let (part, thought, raw, request, compiled) =
                match model_stream(state, &beat_body, &context, resolved, &mut telemetry).await {
                    Ok(value) => value,
                    Err(mut error) => {
                        // A failed middle beat must remain visible to callers and to
                        // continuation/history queries.  Persist the completed prefix
                        // before returning the provider error; this mirrors the
                        // streaming cancellation path's durable partial turn.
                        if !stories.is_empty() {
                            let partial_story = stories.join("\n\n");
                            let partial_reasoning = thoughts.join("\n\n");
                            let mut partial_stats =
                                crate::inference::budget::aggregate(&beat_usage);
                            for (key, value) in [
                                ("run_status", json!("partial")),
                                ("partial", json!(true)),
                                ("failed_beat", json!(index)),
                                ("completed_beats", json!(stories.len())),
                                ("generation_mode", json!("beats")),
                                ("beat_count", json!(count)),
                                ("tokens_per_beat", json!(per_beat)),
                                ("total_budget", json!(total_budget)),
                                ("beats", json!(beat_usage)),
                                ("inference", inference_snapshot(&mut telemetry)),
                            ] {
                                partial_stats[key] = value;
                            }
                            let saved = state.store.insert("turns", json!({
                            "id": Uuid::new_v4().to_string(),
                            "session_id": session_id.clone(),
                            "run_id": run_id.clone(),
                            "user_prompt": prompt.clone(),
                            "story": partial_story,
                            "reasoning": partial_reasoning,
                            "reasoning_text": partial_reasoning,
                            "model": payload_string(&body, "model", ""),
                            "mode": payload_string(&body, "input_mode", "smart_hybrid"),
                            "session_context": context.clone(),
                            "stats_json": partial_stats,
                            "lineage_json": {"run_id": run_id.clone(), "failed_beat": index},
                            "created_at": now(),
                            "updated_at": now()
                        }));
                            if let Err(persist) = saved {
                                error.message = format!(
                                    "{}; completed beat prefix could not be saved: {}",
                                    error.message, persist.message
                                );
                            }
                        }
                        return Ok(profiled_error(error, &mut telemetry));
                    }
                };
            stories.push(part);
            apply_compiled(&mut analytical,&compiled);
            beat_usage.push(run_stats(
                &raw,
                &request,
                &beat_body,
                &state.runtime_config()?,
                "completed",
                resolved,
            ));
            if let Some(last)=beat_usage.last_mut(){last["input_budget"]=compiled.report.clone();}
            if !thought.trim().is_empty() {
                thoughts.push(format!("[Beat {index}]\n{thought}"));
            }
            raws.push(raw);
            requests.push(request);
            context=compiled;
        }
        let stats = json!({"generation_mode":"beats","beat_count":count,"tokens_per_beat":if budgets.writers.iter().all(|b|b.visible==per_beat){json!(per_beat)}else{Value::Null},"total_budget":total_budget,
            "aggregate":crate::inference::budget::aggregate(&beat_usage),"beats":beat_usage.iter().enumerate().map(|(i,stats)|json!({"beat":i+1,"tokens":budgets.writers[i].visible,"stats":stats})).collect::<Vec<_>>()});
        (
            stories.join("\n\n"),
            thoughts.join("\n\n"),
            json!({"beats":raws}),
            json!({"beats":requests}),
            stats,
        )
    } else {
        let (story, reasoning, raw, request, compiled) =
            match model_stream(state, &body, &context, &budgets.writers[0], &mut telemetry).await {
                Ok(value) => value,
                Err(error) => return Ok(context_rejection(state,original,&session_id,&run_id,error,&mut telemetry)),
            };
        apply_compiled(&mut analytical,&compiled);
        context=compiled;
        (
            story,
            reasoning,
            raw,
            request,
            json!({"generation_mode":"single"}),
        )
    };
    let validation_started = Instant::now();
    let quality =
        crate::analysis::quality_report_with_context(&story, analytical.get("writer_context"));
    telemetry.record_stage("validation", validation_started.elapsed());
    let analysis_id = run_id.clone();
    let projections = analytical
        .get("projections")
        .cloned()
        .unwrap_or_else(|| json!([]));
    let wcf_validation = analytical
        .get("wcf_validation")
        .cloned()
        .unwrap_or_else(|| json!({}));
    let mut stats = if generation_mode == "beats" {
        beat_stats["aggregate"].clone()
    } else {
        run_stats(
            &raw,
            &provider_request,
            &body,
            &state.runtime_config()?,
            "completed",
            &budgets.writers[0],
        )
    }
    .as_object()
    .cloned()
    .unwrap_or_default();
    stats.insert("continuity_context_used".into(), json!(!context.is_empty()));
    stats.insert("input_budget".into(), analytical["input_budget"].clone());
    stats.insert("run_status".into(), json!("completed"));
    stats.insert("partial".into(), json!(false));
    if let Some(calls) = beat_stats["beats"].as_array() {
        for key in ["requested_reasoning", "api_reasoning"] {
            let common = calls
                .first()
                .filter(|first| {
                    calls
                        .iter()
                        .all(|call| call["stats"][key] == first["stats"][key])
                })
                .map(|first| first["stats"][key].clone())
                .unwrap_or(Value::Null);
            stats.insert(key.into(), common);
        }
    }
    stats.insert("generation".into(), beat_stats.clone());
    let mut stats = Value::Object(stats);
    let persistence_started = Instant::now();
    let turn = state.store.insert("turns", json!({"id":Uuid::new_v4().to_string(),"session_id":session_id,"run_id":run_id,"user_prompt":prompt,"story":story,"reasoning":reasoning,"reasoning_text":reasoning,"model":payload_string(&body,"model",""),"mode":payload_string(&body,"input_mode","smart_hybrid"),"projection_mode":payload_string(&body,"projection_mode","balanced"),"stats_json":stats,"wcf":analytical["wcf"],"aif_core":analytical["aif_core"],"session_context":context,"projections_json":projections,"post_validation_json":{"quality_report":quality},"wcf_validation_json":wcf_validation,"lineage_json":{"analysis_id":analysis_id,"run_id":run_id},"created_at":now(),"updated_at":now()}))?;
    telemetry.record_stage("persistence", persistence_started.elapsed());
    let memory_started = Instant::now();
    // The memory index is derived and rebuildable, so it must not fail the run.
    if let Err(error) =
        crate::foundation::memory::refresh_turn(state, turn["id"].as_str().unwrap_or_default())
    {
        stats["memory_index_error"] = json!(error.message);
    }
    telemetry.record_stage("memory_index", memory_started.elapsed());
    // Snapshot before publishing telemetry itself: self-report writes are not
    // recursively included in their own elapsed time.
    stats["inference"] = inference_snapshot(&mut telemetry);
    state.store.update(
        "turns",
        turn["id"].as_str().unwrap_or_default(),
        json!({"stats_json":stats}),
    )?;
    let bundle = json!({"analysis_id":analysis_id,"run_id":run_id,"turn_id":turn["id"],"input_mode":payload_string(&body,"input_mode","smart_hybrid"),"projection_mode":payload_string(&body,"projection_mode","balanced"),"wcf":analytical["wcf"],"aif_core":analytical["aif_core"],"narrative_brief":analytical["narrative_brief"],"deliberation":analytical["deliberation"],"projections":projections,"wcf_validation":wcf_validation,"extracted_state":analytical["extracted_state"],"events":analytical["events"],"semantic_core":analytical["semantic_core"],"writer_context":analytical["writer_context"],"world_runtime":analytical.get("world_runtime").cloned().unwrap_or_else(||json!({})),"narrative_runtime":analytical.get("narrative_runtime").cloned().unwrap_or_else(||json!({})),"model_input":provider_request.get("input").cloned().unwrap_or_else(||json!(provider_request["beats"].as_array().into_iter().flatten().map(|r|r["input"].clone()).collect::<Vec<_>>())),"story":turn["story"],"reasoning":turn["reasoning"],"stats":stats,"post_validation":{"quality_report":quality},"raw_response":raw,"trace_choices":analytical["trace_choices"]});
    crate::analysis::cache_run(state, &analysis_id, &bundle)?;
    let result = json!({"run_id":run_id,"analysis_id":analysis_id,"session_id":turn.get("session_id").cloned().unwrap_or(Value::Null),"turn_id":turn.get("id"),"story":turn.get("story"),"reasoning":turn.get("reasoning"),"wcf":analytical["wcf"],"aif_core":analytical["aif_core"],"narrative_brief":analytical["narrative_brief"],"deliberation":analytical["deliberation"],"projections":projections,"trace_choices":analytical["trace_choices"],"stats":stats,"summary":{"response_kind":if payload_string(&body,"conversation_mode","story_writer")=="story_lab" {"discussion"} else {"prose"}},"quality_report":quality,"post_validation":{"quality_report":quality},"wcf_validation":wcf_validation,"context_breakdown":{"continuity_context_used":!context.is_empty()},"raw_response":raw});
    Response::builder()
        .status(StatusCode::OK)
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(serde_json::to_vec(&result).map_err(err)?))
        .map_err(err)
}

fn clone_history_row(
    tx: &rusqlite::Transaction<'_>,
    table: &str,
    source: &str,
    overrides: &Value,
) -> ApiResult<()> {
    let mut statement = tx.prepare(&format!("PRAGMA table_info({table})"))?;
    let columns = statement
        .query_map([], |row| row.get::<_, String>(1))?
        .collect::<Result<Vec<_>, _>>()?;
    let mut values = Vec::new();
    let quoted = |name: &str| format!("\"{}\"", name.replace('"', "\"\""));
    let expressions = columns
        .iter()
        .map(|column| {
            if let Some(value) = overrides.get(column) {
                values.push(crate::store::json_to_sql(value)?);
                Ok("?".to_owned())
            } else {
                Ok(quoted(column))
            }
        })
        .collect::<ApiResult<Vec<_>>>()?;
    values.push(rusqlite::types::Value::Text(source.to_owned()));
    tx.execute(
        &format!(
            "INSERT INTO {table}({}) SELECT {} FROM {table} WHERE id=?",
            columns
                .iter()
                .map(|name| quoted(name))
                .collect::<Vec<_>>()
                .join(","),
            expressions.join(",")
        ),
        rusqlite::params_from_iter(values),
    )?;
    Ok(())
}
fn fork_session(state: &AppState, id: &str, body: &Value) -> ApiResult<Response> {
    let source = state
        .store
        .get("sessions", id)?
        .ok_or_else(|| ApiError::not_found("Session not found"))?;
    let mut turns = state.store.query(
        "SELECT * FROM turns WHERE session_id=? ORDER BY created_at,rowid",
        &[&id],
    )?;
    if let Some(stop) = body["through_turn_id"].as_str() {
        let Some(index) = turns.iter().position(|turn| turn["id"] == stop) else {
            return Err(ApiError::not_found(
                "Fork point is not a turn in this session",
            ));
        };
        turns.truncate(index + 1);
    }
    let anchor = turns.last().and_then(|turn| turn["id"].as_str());
    let new_id = Uuid::new_v4().to_string();
    let title = body["title"]
        .as_str()
        .map(str::to_owned)
        .unwrap_or_else(|| {
            format!(
                "{} (fork)",
                source["title"].as_str().unwrap_or("Conversation")
            )
        });
    let timestamp = now();
    let mut connection = state.store.connection()?;
    let tx = connection.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    clone_history_row(
        &tx,
        "sessions",
        id,
        &json!({"id":new_id,"title":title,"parent_session_id":id,"forked_from_turn_id":anchor,"folder_id":null,"pinned":false,"archived":false,"created_at":timestamp,"updated_at":timestamp}),
    )?;
    let mut copied_ids = Vec::new();
    for (index, turn) in turns.iter().enumerate() {
        let copied_id = Uuid::new_v4().to_string();
        let mut lineage = turn["lineage"].as_object().cloned().unwrap_or_default();
        lineage.insert("forked_from_session_id".into(), json!(id));
        lineage.insert("forked_from_turn_id".into(), turn["id"].clone());
        lineage.insert("fork_copy_index".into(), json!(index + 1));
        clone_history_row(
            &tx,
            "turns",
            turn["id"].as_str().unwrap_or_default(),
            &json!({"id":copied_id,"session_id":new_id,"run_id":format!("FORK-{}-{:02}",turn["run_id"].as_str().unwrap_or("history"),index+1),"lineage_json":lineage,"created_at":timestamp,"updated_at":timestamp}),
        )?;
        copied_ids.push(copied_id);
    }
    tx.commit()?;
    for copied in copied_ids {
        let _ = crate::foundation::memory::refresh_turn(state, &copied);
    }
    let mut fork = state.store.get("sessions", &new_id)?.unwrap_or(Value::Null);
    fork["turns"] = json!(state.store.query(
        "SELECT * FROM turns WHERE session_id=? ORDER BY created_at,rowid",
        &[&new_id]
    )?);
    json_response(&fork)
}
fn session_forks(state: &AppState, id: &str) -> ApiResult<Response> {
    let source = state
        .store
        .get("sessions", id)?
        .ok_or_else(|| ApiError::not_found("Session not found"))?;
    let mut root = source;
    let mut seen = std::collections::HashSet::new();
    while let Some(parent) = root["parent_session_id"].as_str() {
        if !seen.insert(parent.to_owned()) {
            break;
        }
        let Some(row) = state.store.get("sessions", parent)? else {
            break;
        };
        root = row;
    }
    let mut family = vec![root.clone()];
    let mut index = 0;
    while index < family.len() {
        let parent = family[index]["id"].as_str().unwrap_or_default();
        let children = state.store.query(
            "SELECT * FROM sessions WHERE parent_session_id=? ORDER BY created_at,rowid",
            &[&parent],
        )?;
        for child in children {
            if !family.iter().any(|row| row["id"] == child["id"]) {
                family.push(child);
            }
        }
        index += 1;
    }
    json_response(&json!({"root":root,"sessions":family,"active_id":id}))
}
fn patch_session(state: &AppState, id: &str, body: &Value) -> ApiResult<Response> {
    let current = state
        .store
        .get("sessions", id)?
        .ok_or_else(|| ApiError::not_found("Session not found"))?;
    let previous = payload_string(&current, "conversation_mode", "story_writer");
    let next = body
        .get("conversation_mode")
        .and_then(Value::as_str)
        .unwrap_or(&previous)
        .to_owned();
    let mut patch = body.clone();
    if previous != next {
        let mut events = current.get("mode_events").cloned().unwrap_or(json!([]));
        if let Some(list) = events.as_array_mut() {
            list.push(json!({"from":previous,"to":next,"created_at":now()}));
        }
        patch["mode_events_json"] = events;
    }
    state
        .store
        .update("sessions", id, patch)
        .and_then(|v| json_response(&v))
}
fn list_sessions(state: &AppState, query: &HashMap<String, String>) -> ApiResult<Response> {
    let mut sql = String::from("SELECT s.* FROM sessions s WHERE s.archived=0 AND NOT EXISTS (SELECT 1 FROM resource_lifecycle l WHERE l.resource_type='session' AND l.resource_id=s.id AND (l.trashed_at IS NOT NULL OR l.archived_at IS NOT NULL))");
    let mut values = Vec::new();
    for key in ["project_id", "world_id", "branch_id"] {
        if let Some(value) = query.get(key).filter(|v| !v.is_empty()) {
            sql.push_str(&format!(" AND s.{key}=?"));
            values.push(value.clone());
        }
    }
    sql.push_str(" ORDER BY updated_at DESC, rowid DESC");
    let refs: Vec<&dyn rusqlite::ToSql> =
        values.iter().map(|v| v as &dyn rusqlite::ToSql).collect();
    let rows = state.store.query(&sql, &refs)?;
    json_response(&json!({"sessions":rows}))
}

pub async fn handle(
    state: AppState,
    method: &str,
    path: &[&str],
    query: &HashMap<String, String>,
    mut body: Value,
) -> Option<Result<Response, ApiError>> {
    // Idempotency compares what the client sent, not config defaults filled in below.
    let original = if matches!(path, ["generate"] | ["generate", "stream"]) {
        body.clone()
    } else {
        Value::Null
    };
    if matches!(
        path,
        ["generate"] | ["generate", "stream"] | ["analyze"] | ["ablation"]
    ) {
        let config = match state.runtime_config() {
            Ok(value) => value,
            Err(error) => return Some(Err(error)),
        };
        if let Err(error) = crate::inference::budget::validate_request(&body, &config) {
            return Some(Err(error));
        }
        for (key, setting) in [
            ("input_mode", "writer.input_mode"),
            ("projection_mode", "projection.mode"),
            ("reasoning", "generation.reasoning"),
            ("generation_mode", "generation.generation_mode"),
            ("output_budget_mode", "generation.output_budget_mode"),
        ] {
            if body.get(key).is_none_or(Value::is_null) {
                if let Some(value) = setting
                    .split('.')
                    .try_fold(&config.raw, |value, key| value.get(key))
                {
                    body[key] = serde_json::to_value(value).unwrap_or(Value::Null);
                }
            }
        }
        for key in [
            "model",
            "max_output_tokens",
            "temperature",
            "top_p",
            "top_k",
            "min_p",
            "repeat_penalty",
            "seed",
        ] {
            if body.get(key).is_some_and(Value::is_null) {
                if let Some(object) = body.as_object_mut() {
                    object.remove(key);
                }
            }
        }
    }
    let result = match (method, path) {
        ("POST", ["generate"]) => generate(&state, body, &original).await,
        ("POST", ["generate", "stream"]) => generate_stream_response(&state, body, &original).await,
        ("GET", ["sessions"]) => {
            if let Err(e) = ensure_schema(&state).await {
                Err(e)
            } else {
                list_sessions(&state, query)
            }
        }
        ("GET", ["sessions", id]) => state
            .store
            .get("sessions", id)
            .and_then(|v| v.ok_or_else(|| ApiError::not_found("Session not found")))
            .and_then(|mut v| {
                let turns = state.store.query(
                    "SELECT * FROM turns WHERE session_id=? ORDER BY created_at ASC, rowid ASC",
                    &[&id],
                )?;
                v["turns"] = json!(turns);
                json_response(&v)
            }),
        ("GET", ["sessions", id, "forks"]) => session_forks(&state, id),
        ("POST", ["sessions", id, "fork"]) => fork_session(&state, id, &body),
        ("PATCH", ["sessions", id]) => patch_session(&state, id, &body),
        ("DELETE", ["sessions", id]) => delete_history(&state, "session", id),
        ("GET", ["turns", id]) => state
            .store
            .get("turns", id)
            .and_then(|v| v.ok_or_else(|| ApiError::not_found("Turn not found")))
            .and_then(|v| json_response(&v)),
        ("DELETE", ["turns", id]) => delete_history(&state, "turn", id),
        ("POST", ["turns", id, "feedback"]) => {
            let issues: std::collections::BTreeSet<String> = body["issues"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(Value::as_str)
                .map(str::trim)
                .filter(|value| !value.is_empty())
                .map(str::to_owned)
                .collect();
            let issues = json!(issues);
            let note = payload_string(&body, "note", "").trim().to_owned();
            let edited = payload_string(&body, "edited_story", "").trim().to_owned();
            let status = payload_string(&body, "status", "unreviewed");
            if !["unreviewed", "accepted", "edited_accept", "rejected", ""]
                .contains(&status.as_str())
            {
                return Some(Err(ApiError::bad_request(
                    "feedback status must be unreviewed, accepted, edited_accept, or rejected",
                )));
            }
            if status == "edited_accept" && edited.trim().is_empty() {
                return Some(Err(ApiError::bad_request(
                    "edited_accept requires edited_story",
                )));
            }
            let resolved = if status.is_empty() {
                if body
                    .get("accepted")
                    .and_then(Value::as_bool)
                    .unwrap_or(false)
                {
                    "accepted"
                } else {
                    "rejected"
                }
            } else {
                status.as_str()
            };
            state.store.update("turns",id,json!({"feedback_status":resolved,"feedback_issues_json":issues,"feedback_note":note,"edited_story":edited})).and_then(|mut turn|{
                if let Some(session)=turn["session_id"].as_str(){state.store.update("sessions",session,json!({"updated_at":now()}))?;}
                if ["accepted","edited_accept","rejected"].contains(&resolved){
                    let replaced=if resolved=="accepted"{"user_edited_prose"}else if resolved=="edited_accept"{"accepted_generation"}else{""};
                    state.store.connection()?.execute("UPDATE discovery_instances SET active=0,invalidation_reason=?,updated_at=? WHERE source_turn_id=? AND (source_kind=? OR (?='' AND source_kind IN('accepted_generation','user_edited_prose')))",rusqlite::params![if resolved=="rejected"{"feedback_rejected"}else{"feedback_replaced"},now(),id,replaced,replaced])?;
                    if resolved!="rejected"{let _=crate::foundation::memory::discovery::capture(&state,id,if resolved=="accepted"{"accepted_generation"}else{"user_edited_prose"});}
                }
                let _=crate::foundation::memory::refresh_turn(&state,id);
                turn["final_story"]=if resolved=="edited_accept"{turn["edited_story"].clone()}else{turn["story"].clone()};
                json_response(&json!({"ok":true,"turn":turn,"dataset":crate::io_services::dataset_stats(&state)?}))
            })
        }
        ("POST", ["analyze"]) => crate::analysis::analyze_async(&state, &body)
            .await
            .and_then(|payload| {
                let analysis_id = crate::analysis::cache(&state, &payload)?;
                let mut result = payload;
                result["analysis_id"] = json!(analysis_id);
                json_response(&result)
            }),
        ("POST", ["ablation"]) => ablation(&state, &body).await,
        ("GET", ["trace", cache_id, trace_id]) => crate::analysis::cached(&state, cache_id)
            .and_then(|payload| {
                let payload = payload.ok_or_else(|| {
                    ApiError::not_found("Analysis/run is no longer in the in-memory cache")
                })?;
                payload["trace_choices"]
                    .as_array()
                    .and_then(|items| {
                        items.iter().find(|item| {
                            item["id"].as_str() == Some(trace_id)
                                || item["trace_id"].as_str() == Some(trace_id)
                        })
                    })
                    .cloned()
                    .ok_or_else(|| ApiError::not_found("Trace entry not found"))
                    .and_then(|item| json_response(&item))
            }),
        ("POST", ["directives", "parse"]) => parse_directives(&body),
        ("GET", ["contract"]) => {
            let path = state.runtime_config().map(|cfg| cfg.prompt_path());
            let path = match path {
                Ok(path) => path,
                Err(e) => return Some(Err(e)),
            };
            match std::fs::read_to_string(path) {
                Ok(content) => Ok(json_response_value(json!({"content":content}))),
                Err(_) => Err(ApiError::new(
                    StatusCode::NOT_IMPLEMENTED,
                    "Conversation contract is unavailable",
                )),
            }
        }
        ("POST", ["contract"]) => {
            let content = match body.get("content").and_then(Value::as_str) {
                Some(value) => value,
                None => return Some(Err(ApiError::bad_request("content is required"))),
            };
            let path = match state.runtime_config() {
                Ok(config) => config.prompt_path(),
                Err(error) => return Some(Err(error)),
            };
            let temporary = path.with_extension("tmp");
            match std::fs::write(&temporary, format!("{}\n", content.trim_end()))
                .and_then(|()| std::fs::rename(&temporary, &path))
            {
                Ok(()) => Ok(json_response_value(json!({"ok":true,"content":content}))),
                Err(error) => Err(ApiError::from(error)),
            }
        }
        ("GET", ["commands"]) => Ok(json_response_value(command_catalog())),
        _ => return None,
    };
    Some(result)
}

async fn ablation(state: &AppState, body: &Value) -> ApiResult<Response> {
    let prompt = payload_string(body, "prompt", "");
    if prompt.trim().is_empty() {
        return Err(ApiError::bad_request("Prompt is empty"));
    }
    let mut conditions = body
        .get("conditions")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_else(|| {
            vec![
                json!("raw:off"),
                json!("raw:on"),
                json!("wcf:off"),
                json!("wcf:on"),
                json!("smart_hybrid:off"),
                json!("smart_hybrid:on"),
            ]
        });
    conditions.retain(|item| {
        item.as_str()
            .and_then(|value| value.split_once(':'))
            .is_some_and(|(mode, reasoning)| {
                ["raw", "wcf", "wcf_raw", "smart_hybrid", "aif_core"].contains(&mode)
                    && ["off", "on", "low", "medium", "high"].contains(&reasoning)
            })
    });
    if conditions.is_empty() {
        conditions = [
            "raw:off",
            "raw:on",
            "wcf:off",
            "wcf:on",
            "smart_hybrid:off",
            "smart_hybrid:on",
        ]
        .into_iter()
        .map(|value| json!(value))
        .collect();
    }
    let mut outcomes = Vec::new();
    for condition in conditions {
        let value = condition.as_str().unwrap_or("smart_hybrid:off");
        let (mode, reasoning) = value.split_once(':').unwrap_or((value, "off"));
        let mut request = body.clone();
        request["prompt"] = json!(prompt);
        request["input_mode"] = json!(mode);
        request["reasoning"] = json!(reasoning);
        let mut telemetry = generation_telemetry(&request, &state.runtime_config()?);
        let (context, analysis, budgets) =
            prepare_generation(state, &request, &[], &mut telemetry).await?;
        match model_stream(state, &request, &context, &budgets.writers[0], &mut telemetry).await {
            Ok((story, thoughts, raw, provider_request, compiled)) => {
                let report=crate::analysis::quality_report_with_context(&story,analysis.get("writer_context"));
                let violations=report["violations"].as_array().map_or(0,Vec::len) as f64;
                let warnings=report["warnings"].as_array().map_or(0,Vec::len) as f64;
                let metric=|key:&str|report["metrics"][key].as_f64().unwrap_or(0.0);
                let score=(100.0-18.0*violations-5.0*warnings-3.0*metric("repetition_pairs")-3.0*metric("spec_recitations")-5.0*metric("unsupported_specificities")).clamp(0.0,100.0);
                let mut stats=run_stats(&raw,&provider_request,&request,&state.runtime_config()?,"completed",&budgets.writers[0]);
                stats["inference"]=inference_snapshot(&mut telemetry);
                stats["input_budget"]=compiled.report;
                outcomes.push(json!({"key":format!("{mode}__thinking_{reasoning}"),"mode":mode,"reasoning":reasoning,"story":story,"reasoning_text":thoughts,"stats":stats,"post_validation":{"quality_report":report},"diagnostic_score":score,"raw_response":raw}));
            },
            Err(error) => outcomes.push(json!({"mode":mode,"reasoning":reasoning,"story":"","post_validation":{},"stats":{},"diagnostic_score":0.0,"error":error.message})),
        }
    }
    json_response(&json!({"results":outcomes,"prompt":prompt}))
}

fn command_catalog() -> Value {
    let mut catalog: Value = serde_json::from_str(include_str!("commands.json"))
        .unwrap_or_else(|_| json!({"version":"1.2.4a1","commands":[]}));
    catalog["results"] = json!([
        {"type":"command","id":"new_chat","label":"New chat","subtitle":"Create a new writing chat"},
        {"type":"command","id":"new_project","label":"New project","subtitle":"Create a story workspace"},
        {"type":"command","id":"new_world","label":"New world","subtitle":"Create or fork a world"},
        {"type":"command","id":"new_character","label":"New character","subtitle":"Create a character family/variant"},
        {"type":"command","id":"new_draft","label":"New manuscript item","subtitle":"Create a scene, chapter, note, or research document"},
        {"type":"command","id":"sandbox","label":"Open sandbox","subtitle":"Create a non-canonical what-if branch"},
        {"type":"command","id":"snapshot","label":"Save world snapshot","subtitle":"Checkpoint current world state"},
        {"type":"command","id":"compare_worlds","label":"Compare worlds","subtitle":"Open canon diff"},
        {"type":"command","id":"dataset","label":"Open Feedback Lab","subtitle":"Review prose feedback, comparisons, and exports"},
        {"type":"command","id":"runtime","label":"Model runtime","subtitle":"Open LM Studio controls"}
    ]);
    catalog["command_registry_version"] = json!("1.2.4a1");
    catalog["reference_selectors"] = json!([
        "voice",
        "state",
        "appearance",
        "knowledge",
        "beliefs",
        "relationships",
        "timeline",
        "evidence",
        "conflicts"
    ]);
    catalog["dynamic_references"] =
        json!(["scene", "pov", "location", "cast", "world", "branch", "threads", "recent"]);
    catalog
}

fn parse_directives(body: &Value) -> ApiResult<Response> {
    Ok(json_response_value(directive_context(body)))
}

pub(crate) fn directive_context(body: &Value) -> Value {
    let prompt = payload_string(body, "prompt", "");
    let mut stack = Vec::new();
    let mut semantic = Vec::new();
    let mut references = Vec::new();
    let mut unresolved = Vec::new();
    let catalog = command_catalog();
    let catalog_rows = catalog["commands"].as_array().cloned().unwrap_or_default();
    let mut clean = Vec::new();
    for line in prompt.lines() {
        let trimmed = line.trim();
        if let Some(rest) = trimmed.strip_prefix('/') {
            let mut parts = rest.splitn(2, char::is_whitespace);
            let id = parts.next().unwrap_or_default().to_lowercase();
            if let Some(command) = catalog_rows.iter().find(|row| row["id"] == id) {
                let args = parts.next().unwrap_or("").trim();
                let mut options = serde_json::Map::new();
                let mut goal = Vec::new();
                for token in args.split_whitespace() {
                    if let Some((key, value)) = token.split_once('=') {
                        let key = if key == "pace" { "pacing" } else { key };
                        let parsed = value
                            .parse::<i64>()
                            .map(|number| json!(number))
                            .unwrap_or_else(|_| json!(value));
                        options.insert(key.to_owned(), parsed);
                    } else if let Some(reference) = token.strip_prefix('@') {
                        let (label, selector) =
                            reference.split_once('.').unwrap_or((reference, ""));
                        references
                            .push(json!({"expression":token,"label":label,"selector":selector}));
                    } else if !token.starts_with('"') {
                        goal.push(token);
                    }
                }
                let option_specs = command["options"].as_array().cloned().unwrap_or_default();
                for (key, value) in options.clone() {
                    if let Some(spec) = option_specs.iter().find(|spec| spec["name"] == key) {
                        if let Some(choices) = spec["choices"].as_array() {
                            if !choices
                                .iter()
                                .any(|choice| choice.as_str() == value.as_str())
                            {
                                unresolved.push(format!("invalid option {key}={value}"));
                            }
                        }
                    }
                }
                stack.push(json!({"id":id,"label":command["label"],"role":command["role"],"raw":trimmed,"options":options,"planner_intent":command["planner_intent"],"deliberation_mode":command["deliberation_mode"],"output_mode":command["output_mode"],"execution_contract":command["execution_contract"]}));
                if !goal.is_empty() {
                    semantic.push(goal.join(" "));
                }
                continue;
            }
        }
        if !trimmed.is_empty() {
            clean.push(trimmed)
        }
    }
    let clean_prompt = clean.join("\n");
    let primary = stack.last().cloned().unwrap_or(Value::Null);
    let semantic_prompt = if clean_prompt.is_empty() {
        semantic.join(" ")
    } else {
        clean_prompt.clone()
    };

    json!({"version":"1.2.4a1","runtime_version":"1.2.5a1","active":!stack.is_empty() || !references.is_empty(),"command":primary,"stack":stack,"options":primary["options"].clone(),"reference_expressions":references,"resolved_references":[],"dynamic_scopes":[],"unresolved_references":unresolved,"planner_intent":primary["planner_intent"].clone().as_str().unwrap_or("continue"),"deliberation_mode":primary["deliberation_mode"].clone().as_str().unwrap_or("auto"),"output_mode":primary["output_mode"].clone().as_str().unwrap_or("fiction"),"execution_contract":primary["execution_contract"].clone(),"semantic_prompt":semantic_prompt,"clean_prompt":clean_prompt,"diagnostics":unresolved})
}

fn apply_compiled(analysis:&mut Value,compiled:&crate::inference::context::CompiledWriterContext){
    analysis["input_budget"]=compiled.report.clone();analysis["model_input"]=json!(compiled.context);
    analysis["wcf"]=json!(crate::analysis::with_memory_block(&compiled.selection.wcf,&compiled.evidence));
    analysis["memory"]=json!(compiled.evidence);analysis["analysis"]["evidence"]=json!(compiled.evidence);analysis["summary"]["memory_items"]=json!(compiled.evidence.len());
}

async fn prepare_generation(
    state: &AppState,
    body: &Value,
    history: &[crate::inference::context::HistoryTurn],
    telemetry: &mut RunTelemetry,
) -> ApiResult<(crate::inference::context::CompiledWriterContext, Value, crate::inference::budget::BudgetPlan)> {
    let preparation_started = Instant::now();
    let config = state.runtime_config()?;
    crate::inference::deliberation::validate_mode(body, &config)?;
    crate::inference::budget::resolve(body, &config, "short_continue")?;
    let mut analytical =
        crate::analysis::analyze_writer_profiled(state, body, Some(telemetry)).await?;
    let decision = crate::inference::deliberation::route(
        body,
        &analytical,
        &directive_context(body),
        &config,
    )?;
    let routing = decision.to_value();
    let budgets = crate::inference::budget::resolve(
        body,
        &config,
        routing["task"].as_str().unwrap_or("short_continue"),
    )?;
    let mut preflight=crate::inference::context::ContextSelection::from_analysis(body,&analytical,Vec::new());
    preflight.evidence.clear();preflight.deliberation=json!({"status":"disabled"});
    let reserve=budgets.writers.iter().map(|b|b.api_max).max().unwrap_or(0);
    crate::inference::context::compile(state,&config,body,&preflight,reserve,|text|chat_payload(body,&config,text,&budgets.writers[0])).await?;
    let deliberation_started = Instant::now();
    analytical["deliberation"] = crate::analysis::deliberate_with_override(
        state,
        body,
        &analytical,
        Some(decision.planning_enabled),
        Some(&budgets.planner),
    )
    .await;
    let planner_usage = analytical["deliberation"]
        .as_object_mut()
        .and_then(|v| v.remove("_output_usage"));
    telemetry.record_stage("deliberation", deliberation_started.elapsed());
    telemetry.record_metadata(
        "deliberation_status",
        analytical["deliberation"]["status"].clone(),
    );
    for (key, field) in [
        ("deliberation_requested_mode", "requested_mode"),
        ("deliberation_effective_mode", "effective_mode"),
        ("deliberation_route_reason", "reason"),
        ("generation_task", "task"),
        ("preparation_fast_path", "preparation_fast_path"),
    ] {
        telemetry.record_metadata(key, routing[field].clone());
    }
    let context_started = Instant::now();
    let history=if config.bool("history.smart_hybrid_continuity",true){history.to_vec()}else{Vec::new()};
    let selection=crate::inference::context::ContextSelection::from_analysis(body,&analytical,history);
    let context=crate::inference::context::compile(state,&config,body,&selection,reserve,|text|chat_payload(body,&config,text,&budgets.writers[0])).await?;
    apply_compiled(&mut analytical,&context);
    // Routing diagnostics belong to the response/cache, not the writer prompt.
    analytical["deliberation"]["routing"] = routing;
    if decision.planning_enabled {
        analytical["deliberation"]["output_budget"] = planner_usage
            .unwrap_or_else(|| crate::inference::budget::usage(&Value::Null, &budgets.planner));
    }
    telemetry.record_metadata(
        "output_budget_mode",
        json!(crate::inference::budget::mode(body, &config)?),
    );
    telemetry.record_stage("context_assembly", context_started.elapsed());
    telemetry.record_stage("preparation", preparation_started.elapsed());
    Ok((context, analytical, budgets))
}

fn json_response(value: &Value) -> ApiResult<Response> {
    Ok(json_response_value(value.clone()))
}
fn json_response_value(value: Value) -> Response {
    Response::builder()
        .status(StatusCode::OK)
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(
            serde_json::to_vec(&value).unwrap_or_else(|_| b"{}".to_vec()),
        ))
        .unwrap()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn chat_payload(body: &Value, cfg: &crate::RuntimeConfig, context: &str) -> Value {
        let budgets = crate::inference::budget::resolve(body, cfg, "short_continue").unwrap();
        super::chat_payload(body, cfg, context, &budgets.writers[0])
    }

    #[test]
    fn sse_frames_are_consumable_by_browser_parser() {
        let frame = sse("answer.delta", &json!({"content":"hello\nworld"}));
        assert!(frame.starts_with("event: answer.delta\ndata: "));
        assert!(frame.ends_with("\n\n"));
        let payload = frame.split_once("data: ").unwrap().1.trim();
        assert_eq!(
            serde_json::from_str::<Value>(payload).unwrap()["content"],
            "hello\nworld"
        );
    }

    #[test]
    fn story_lab_response_kind_is_explicit() {
        let mode = "story_lab";
        let kind = if mode == "story_lab" {
            "discussion"
        } else {
            "prose"
        };
        assert_eq!(kind, "discussion");
    }

    #[test]
    fn reasoning_off_uses_visible_budget_and_omits_provider_reasoning() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("arline.toml");
        std::fs::write(&path, "[lmstudio]\nmodel='mock'\n[generation]\nvisible_output_tokens=4096\nreasoning_reserve_tokens=4096\n").unwrap();
        let cfg = crate::RuntimeConfig::load(&path, dir.path()).unwrap();
        let payload = chat_payload(
            &json!({"prompt":"x","visible_output_tokens":17,"reasoning":"off"}),
            &cfg,
            "",
        );
        assert_eq!(payload["max_output_tokens"], 17);
        assert_eq!(payload["reasoning"], "off");
    }

    #[test]
    fn reasoning_reserve_is_added_only_when_enabled() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("arline.toml");
        std::fs::write(&path, "[lmstudio]\nmodel='mock'\n[generation]\nvisible_output_tokens=4096\nreasoning_reserve_tokens=4096\n").unwrap();
        let cfg = crate::RuntimeConfig::load(&path, dir.path()).unwrap();
        let payload = chat_payload(
            &json!({"prompt":"x","visible_output_tokens":17,"reasoning_reserve_tokens":9,"reasoning":"on"}),
            &cfg,
            "",
        );
        assert_eq!(payload["max_output_tokens"], 26);
        assert_eq!(payload["reasoning"], "on");
    }

    #[test]
    fn scratch_mode_marks_output_non_canon() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("arline.toml");
        std::fs::write(&path, "[lmstudio]\nmodel='mock'\n").unwrap();
        let cfg = crate::RuntimeConfig::load(&path, dir.path()).unwrap();
        let payload = chat_payload(&json!({"prompt":"what if?","scratch_mode":true}), &cfg, "");
        assert!(payload["system_prompt"]
            .as_str()
            .unwrap()
            .contains("do not modify accepted canon"));
    }

    #[test]
    fn sse_line_waits_for_split_utf8_codepoint() {
        let bytes = format!("data: {}\n", json!({"content":"é"})).into_bytes();
        let split = bytes.iter().position(|b| *b == 0xc3).unwrap() + 1;
        let mut pending = bytes[..split].to_vec();
        assert!(take_sse_line(&mut pending).is_none());
        pending.extend_from_slice(&bytes[split..]);
        assert_eq!(
            take_sse_line(&mut pending).unwrap(),
            format!("data: {}", json!({"content":"é"}))
        );
    }

    #[test]
    fn command_catalog_matches_reference_registry_shape() {
        let catalog = command_catalog();
        assert_eq!(catalog["version"], "1.2.4a1");
        assert_eq!(catalog["command_registry_version"], "1.2.4a1");
        assert!(catalog["reference_selectors"]
            .as_array()
            .unwrap()
            .iter()
            .any(|x| x == "appearance"));
        assert!(catalog["dynamic_references"]
            .as_array()
            .unwrap()
            .iter()
            .any(|x| x == "pov"));
        assert!(catalog["commands"].as_array().unwrap().len() >= 10);
        let continue_cmd = catalog["commands"]
            .as_array()
            .unwrap()
            .iter()
            .find(|item| item["id"] == "continue")
            .unwrap();
        assert!(continue_cmd["execution_contract"]["retrieval_profile"] == "scene_continue");
        assert!(continue_cmd["options"]
            .as_array()
            .unwrap()
            .iter()
            .any(|x| x["name"] == "pace"));
    }
}
