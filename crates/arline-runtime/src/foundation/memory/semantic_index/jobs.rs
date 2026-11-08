use super::*;
use snapshot::{Eligibility, Snapshot};
use std::path::PathBuf;

const LEASE_SECONDS: i64 = 60;
static WORK: OnceLock<Arc<tokio::sync::Semaphore>> = OnceLock::new();
static REQUESTS: OnceLock<Arc<tokio::sync::Semaphore>> = OnceLock::new();
static ACTIVE: OnceLock<Mutex<HashSet<(PathBuf, String)>>> = OnceLock::new();
static OWNER: OnceLock<String> = OnceLock::new();
fn owner() -> &'static str {
    OWNER.get_or_init(|| format!("{}:{}", std::process::id(), uuid::Uuid::new_v4()))
}
struct Active {
    key: (PathBuf, String),
}
impl Drop for Active {
    fn drop(&mut self) {
        if let Ok(mut active) = ACTIVE.get_or_init(Default::default).lock() {
            active.remove(&self.key);
        }
    }
}
fn activate(store: &Store, id: &str) -> ApiResult<Active> {
    let key = (store.path.canonicalize()?, id.into());
    if !ACTIVE
        .get_or_init(Default::default)
        .lock()
        .map_err(|_| invalid("index registry poisoned"))?
        .insert(key.clone())
    {
        return Err(invalid("index job is already active"));
    }
    Ok(Active { key })
}
pub(super) fn recover_jobs(store: &Store) -> ApiResult<usize> {
    let connection = store.connection()?;
    let path = store.path.canonicalize()?;
    let mut count = 0;
    for job in query_connection(
        &connection,
        "SELECT id,owner,lease_until FROM semantic_index_jobs WHERE status='running'",
        &[],
    )? {
        let id = job["id"].as_str().unwrap_or_default();
        if ACTIVE
            .get_or_init(Default::default)
            .lock()
            .map_err(|_| invalid("index registry poisoned"))?
            .contains(&(path.clone(), id.into()))
        {
            continue;
        }
        if job["owner"] == owner()
            || job["lease_until"].as_i64().unwrap_or(0) <= chrono::Utc::now().timestamp()
        {
            count+=connection.execute("UPDATE semantic_index_jobs SET status=CASE WHEN cancel_requested=1 THEN 'cancelled' ELSE 'interrupted' END,owner=NULL,lease_until=0,last_error='Worker interrupted; resume from validated vectors',updated_at=? WHERE id=? AND status='running'",params![now(),id])?;
        }
    }
    Ok(count)
}

pub(crate) fn enqueue(
    state: &AppState,
    identity: &ModelIdentity,
    scope: &IndexScope,
) -> ApiResult<String> {
    scope.validate()?;
    let mut connection = state.store.connection()?;
    let tx = connection.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    register_generation(&tx, identity)?;
    let raw = serde_json::to_string(scope).map_err(|e| invalid(e.to_string()))?;
    let key = digest(&raw);
    if let Some(id)=tx.query_row("SELECT id FROM semantic_index_jobs WHERE model_fingerprint=? AND scope_key=? AND status IN('queued','running')",params![identity.fingerprint,key],|r|r.get::<_,String>(0)).optional()? {tx.commit()?;return Ok(id);}
    let queued: i64 = tx.query_row(
        "SELECT count(*) FROM semantic_index_jobs WHERE status IN('queued','running')",
        [],
        |r| r.get(0),
    )?;
    if queued >= 16 {
        return Err(ApiError::new(
            axum::http::StatusCode::TOO_MANY_REQUESTS,
            "semantic work queue is full (16 jobs)",
        ));
    }
    let id = uuid::Uuid::new_v4().to_string();
    tx.execute("INSERT INTO semantic_index_jobs(id,model_fingerprint,scope_json,scope_key,status,created_at,updated_at) VALUES(?,?,?,?,'queued',?,?)",params![id,identity.fingerprint,raw,key,now(),now()])?;
    tx.commit()?;
    Ok(id)
}

pub async fn index_pending(
    state: AppState,
    config: BekkoConfig,
    scope: IndexScope,
    batch_size: usize,
) -> ApiResult<Value> {
    validate_batch_size(batch_size)?;
    let _request = request_slot()?;
    let identity = state
        .embeddings
        .inspect_identity(config.clone())
        .await
        .map_err(|e| ApiError::new(axum::http::StatusCode::SERVICE_UNAVAILABLE, e.to_string()))?;
    let id = enqueue(&state, &identity, &scope)?;
    run_job(state, &id, config, batch_size).await
}
pub(super) fn request_slot() -> ApiResult<tokio::sync::OwnedSemaphorePermit> {
    REQUESTS
        .get_or_init(|| Arc::new(tokio::sync::Semaphore::new(4)))
        .clone()
        .try_acquire_owned()
        .map_err(|_| {
            ApiError::new(
                axum::http::StatusCode::TOO_MANY_REQUESTS,
                "semantic request admission is busy (four preflight slots); retry later",
            )
        })
}
pub async fn index_source(
    state: AppState,
    config: BekkoConfig,
    source_type: &str,
    source_id: &str,
    batch_size: usize,
) -> ApiResult<Value> {
    // Explicit maintenance operation: refresh only derived memory, never Canon.
    super::super::refresh_source(&state, source_type, source_id)?;
    let scope = IndexScope {
        source_type: Some(source_type.into()),
        source_id: Some(source_id.into()),
        ..Default::default()
    };
    index_pending(state, config, scope, batch_size).await
}
pub async fn resume_job(
    state: AppState,
    id: &str,
    config: BekkoConfig,
    batch_size: usize,
) -> ApiResult<Value> {
    prepare_resume(&state, id)?;
    run_job(state, id, config, batch_size).await
}

pub(super) fn prepare_resume(state: &AppState, id: &str) -> ApiResult<()> {
    recover_jobs(&state.store)?;
    // Reset scan cursor: valid prefix vectors are skipped, and newly inserted
    // IDs behind the previous cursor are not missed after a retry.
    state.store.execute("UPDATE semantic_index_jobs SET status='queued',cursor='',cancel_requested=0,last_error='',indexed=0,skipped=0,failed=0,discarded=0,batches=0,inference_ms=0,validation_ms=0,commit_ms=0,duration_ms=0,updated_at=? WHERE id=? AND status IN('failed','interrupted','partial','cancelled')",&[&now(),&id])?;
    Ok(())
}
pub fn cancel_index_job(state: &AppState, id: &str) -> ApiResult<bool> {
    Ok(state.store.execute("UPDATE semantic_index_jobs SET cancel_requested=1,status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END,updated_at=? WHERE id=? AND status IN('queued','running')",&[&now(),&id])?>0)
}
fn validate_batch_size(size: usize) -> ApiResult<()> {
    if !(1..=64).contains(&size) {
        Err(invalid("index batch size must be 1..=64"))
    } else {
        Ok(())
    }
}
pub async fn run_job(
    state: AppState,
    id: &str,
    config: BekkoConfig,
    batch_size: usize,
) -> ApiResult<Value> {
    validate_batch_size(batch_size)?;
    // Bounded process work queue: queued jobs remain durable; no unbounded
    // tasks or model sessions are spawned by repeated requests.
    let Ok(_work) = WORK
        .get_or_init(|| Arc::new(tokio::sync::Semaphore::new(1)))
        .clone()
        .try_acquire_owned()
    else {
        return job(&state, id);
    };
    // Match existing backfill ownership: ordinary narrative writes can proceed,
    // while destructive storage reset/import waits for this maintenance job.
    let _storage = state.storage_gate.clone().read_owned().await;
    let provider = state.embeddings.clone();
    let result = process_job(&state, id, provider.as_ref(), config, batch_size).await;
    let unloaded = provider.unload().await;
    if let Err(error) = unloaded {
        return Err(ApiError::internal(error.to_string()));
    }
    result
}
fn job(state: &AppState, id: &str) -> ApiResult<Value> {
    state
        .store
        .query("SELECT * FROM semantic_index_jobs WHERE id=?", &[&id])?
        .pop()
        .ok_or_else(|| ApiError::not_found("semantic job not found"))
}

pub(crate) async fn process_job<P: EmbeddingProvider>(
    state: &AppState,
    id: &str,
    provider: &P,
    config: BekkoConfig,
    batch_size: usize,
) -> ApiResult<Value> {
    validate_batch_size(batch_size)?;
    let _active = activate(&state.store, id)?;
    let started = Instant::now();
    let initial = job(state, id)?;
    if initial["status"] != "queued" {
        return Ok(initial);
    }
    let fingerprint = initial["model_fingerprint"]
        .as_str()
        .ok_or_else(|| invalid("job lacks fingerprint"))?
        .to_owned();
    let scope: IndexScope =
        serde_json::from_value(initial["scope"].clone()).map_err(|e| invalid(e.to_string()))?;
    let identity_raw: String = state.store.connection()?.query_row(
        "SELECT identity_json FROM semantic_model_generations WHERE model_fingerprint=?",
        [&fingerprint],
        |r| r.get(0),
    )?;
    let expected: ModelIdentity =
        serde_json::from_str(&identity_raw).map_err(|e| invalid(e.to_string()))?;
    let claimed=state.store.execute("UPDATE semantic_index_jobs SET status='running',owner=?,lease_until=?,updated_at=? WHERE id=? AND status='queued' AND cancel_requested=0",&[&owner(),&(chrono::Utc::now().timestamp()+LEASE_SECONDS),&now(),&id])?;
    if claimed == 0 {
        return job(state, id);
    }
    let work = process_batches(state, id, provider, &config, &expected, &scope, batch_size).await;
    if let Err(error) = work {
        // Drop the failed batch transaction before this independent, best-effort
        // error write. If even that fails, the lease remains recoverable.
        let _=state.store.execute("UPDATE semantic_index_jobs SET status=CASE WHEN cancel_requested=1 THEN 'cancelled' ELSE 'failed' END,failed=failed+1,last_error=?,owner=NULL,lease_until=0,duration_ms=duration_ms+?,updated_at=? WHERE id=? AND owner=? AND status='running'",&[&bounded(&error.message),&(started.elapsed().as_secs_f64()*1000.0),&now(),&id,&owner()]);
        return Err(error);
    }
    let mut finish = state.store.connection()?;
    let before: i64 = finish.pragma_query_value(None, "data_version", |r| r.get(0))?;
    let coverage = index_status(state, &fingerprint, &scope)?;
    let tx = finish.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    let after: i64 = tx.pragma_query_value(None, "data_version", |r| r.get(0))?;
    let latest = query_connection(&tx, "SELECT * FROM semantic_index_jobs WHERE id=?", &[&id])?
        .pop()
        .ok_or_else(|| invalid("job disappeared"))?;
    let status = if latest["cancel_requested"] == 1 {
        "cancelled"
    } else if coverage.complete && latest["discarded"] == 0 && before == after {
        "completed"
    } else {
        "partial"
    };
    tx.execute("UPDATE semantic_index_jobs SET status=?,owner=NULL,lease_until=0,duration_ms=duration_ms+?,updated_at=? WHERE id=? AND owner=? AND status='running'",params![status,started.elapsed().as_secs_f64()*1000.0,now(),id,owner()])?;
    tx.commit()?;
    let mut result = job(state, id)?;
    result["coverage"] = serde_json::to_value(coverage).map_err(|e| invalid(e.to_string()))?;
    Ok(result)
}

async fn process_batches<P: EmbeddingProvider>(
    state: &AppState,
    id: &str,
    provider: &P,
    config: &BekkoConfig,
    expected: &ModelIdentity,
    scope: &IndexScope,
    batch_size: usize,
) -> ApiResult<()> {
    let mut cursor = job(state, id)?["cursor"]
        .as_str()
        .unwrap_or_default()
        .to_owned();
    loop {
        let live = job(state, id)?;
        if live["cancel_requested"] == 1 {
            return Ok(());
        }
        if live["status"] != "running" || live["owner"] != owner() {
            return Err(invalid("index worker lost job ownership"));
        }
        let connection = state.store.connection()?;
        let rows = page(&connection, &expected.fingerprint, scope, &cursor)?;
        if rows.is_empty() {
            return Ok(());
        }
        let mut snapshots = Vec::new();
        let mut bytes = 0usize;
        let mut skipped = 0usize;
        for row in &rows {
            let text = row["text"].as_str().unwrap_or_default();
            let eligibility = snapshot::capture(&connection, row)?;
            if !matches!(eligibility, Eligibility::Current(_)) || vector_current(row) {
                cursor = row["id"].as_str().unwrap_or_default().into();
                skipped += 1;
                continue;
            }
            if text.len() > 65536 {
                state.store.execute("INSERT INTO semantic_index_items VALUES(?,?,'failed',?,?,?,'Chunk exceeds 64 KiB input limit',?) ON CONFLICT(chunk_id,model_fingerprint) DO UPDATE SET state='failed',last_error=excluded.last_error,updated_at=excluded.updated_at",&[&row["id"].as_str(),&expected.fingerprint,&row["source_revision"].as_str(),&row["checksum"].as_str(),&row["chunker_version"].as_i64(),&now()])?;
                cursor = row["id"].as_str().unwrap_or_default().into();
                continue;
            }
            if snapshots.len() >= batch_size || bytes + text.len() > 1024 * 1024 {
                break;
            }
            bytes += text.len();
            cursor = row["id"].as_str().unwrap_or_default().into();
            if let Eligibility::Current(snapshot) = eligibility {
                snapshots.push(snapshot);
            }
        }
        drop(connection); // No read/write transaction survives native inference.
        if snapshots.is_empty() {
            state.store.execute("UPDATE semantic_index_jobs SET cursor=?,skipped=skipped+?,lease_until=?,updated_at=? WHERE id=? AND owner=? AND status='running'",&[&cursor,&(skipped as i64),&(chrono::Utc::now().timestamp()+LEASE_SECONDS),&now(),&id,&owner()])?;
            continue;
        }
        let texts = snapshots
            .iter()
            .map(|s| s.chunk["text"].as_str().unwrap_or_default().to_owned())
            .collect();
        let batch = match provider.embed_batch(config.clone(), texts).await {
            Ok(batch) => batch,
            Err(error) => {
                mark_failed(state, &expected.fingerprint, &snapshots, &error.to_string())?;
                return Err(ApiError::new(
                    axum::http::StatusCode::SERVICE_UNAVAILABLE,
                    error.to_string(),
                ));
            }
        };
        if batch.identity != *expected || batch.vectors.len() != snapshots.len() {
            mark_failed(
                state,
                &expected.fingerprint,
                &snapshots,
                "model identity/count changed during indexing",
            )?;
            return Err(invalid(
                "model identity/count changed during indexing; create a new generation job",
            ));
        }
        let encoded = batch
            .vectors
            .iter()
            .map(|v| encode_vector(v))
            .collect::<ApiResult<Vec<_>>>();
        let encoded = match encoded {
            Ok(v) => v,
            Err(error) => {
                mark_failed(state, &expected.fingerprint, &snapshots, &error.message)?;
                return Err(error);
            }
        };
        let commit_start = Instant::now();
        let mut connection = state.store.connection()?;
        let tx = connection.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        let owned:i64=tx.query_row("SELECT count(*) FROM semantic_index_jobs WHERE id=? AND owner=? AND status='running' AND lease_until>? AND cancel_requested=0",params![id,owner(),chrono::Utc::now().timestamp()],|r|r.get(0))?;
        if owned == 0 {
            return Err(invalid(
                "index job cancelled, interrupted or lease expired before commit",
            ));
        }
        let mut indexed = 0i64;
        let mut discarded = 0i64;
        for (snapshot, blob) in snapshots.iter().zip(encoded) {
            let c = &snapshot.chunk;
            if !snapshot::unchanged(&tx, snapshot)? {
                discarded += 1;
                continue;
            }
            tx.execute("INSERT INTO semantic_vectors VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(chunk_id,model_fingerprint) DO UPDATE SET source_revision=excluded.source_revision,content_checksum=excluded.content_checksum,chunker_version=excluded.chunker_version,dimensions=excluded.dimensions,vector_blob=excluded.vector_blob,indexed_at=excluded.indexed_at",params![c["id"].as_str(),expected.fingerprint,c["source_revision"].as_str(),c["checksum"].as_str(),c["chunker_version"].as_i64(),DIMENSIONS,blob,now()])?;
            tx.execute("INSERT INTO semantic_index_items VALUES(?,?,'current',?,?,?,'',?) ON CONFLICT(chunk_id,model_fingerprint) DO UPDATE SET state='current',source_revision=excluded.source_revision,content_checksum=excluded.content_checksum,chunker_version=excluded.chunker_version,last_error='',updated_at=excluded.updated_at",params![c["id"].as_str(),expected.fingerprint,c["source_revision"].as_str(),c["checksum"].as_str(),c["chunker_version"].as_i64(),now()])?;
            indexed += 1;
        }
        tx.execute("UPDATE semantic_index_jobs SET cursor=?,indexed=indexed+?,skipped=skipped+?,discarded=discarded+?,batches=batches+1,inference_ms=inference_ms+?,validation_ms=validation_ms+?,lease_until=?,updated_at=? WHERE id=? AND owner=?",params![cursor,indexed,skipped,discarded,batch.timings.inference_ms,batch.timings.artifact_validation_ms,chrono::Utc::now().timestamp()+LEASE_SECONDS,now(),id,owner()])?;
        tx.commit()?;
        let _ = state.store.execute(
            "UPDATE semantic_index_jobs SET commit_ms=commit_ms+? WHERE id=? AND owner=?",
            &[
                &(commit_start.elapsed().as_secs_f64() * 1000.0),
                &id,
                &owner(),
            ],
        );
    }
}
fn mark_failed(
    state: &AppState,
    fingerprint: &str,
    snapshots: &[Snapshot],
    message: &str,
) -> ApiResult<()> {
    let mut connection = state.store.connection()?;
    let tx = connection.transaction()?;
    for s in snapshots {
        let c = &s.chunk;
        tx.execute("INSERT INTO semantic_index_items VALUES(?,?,'failed',?,?,?,?,?) ON CONFLICT(chunk_id,model_fingerprint) DO UPDATE SET state='failed',source_revision=excluded.source_revision,content_checksum=excluded.content_checksum,chunker_version=excluded.chunker_version,last_error=excluded.last_error,updated_at=excluded.updated_at",params![c["id"].as_str(),fingerprint,c["source_revision"].as_str(),c["checksum"].as_str(),c["chunker_version"].as_i64(),bounded(message),now()])?;
    }
    tx.commit()?;
    Ok(())
}

pub fn reconcile_index(
    state: &AppState,
    fingerprint: &str,
    scope: &IndexScope,
) -> ApiResult<IndexStatus> {
    recover_jobs(&state.store)?;
    scope.validate()?;
    let connection = state.store.connection()?;
    let exists: i64 = connection.query_row(
        "SELECT count(*) FROM semantic_model_generations WHERE model_fingerprint=?",
        [fingerprint],
        |r| r.get(0),
    )?;
    if exists == 0 {
        return Err(invalid("semantic model generation is unavailable"));
    }
    let mut cursor = String::new();
    loop {
        let rows = page(&connection, fingerprint, scope, &cursor)?;
        if rows.is_empty() {
            break;
        }
        for row in rows {
            cursor = row["id"].as_str().unwrap_or_default().into();
            let eligibility = snapshot::capture(&connection, &row)?;
            let state_name = match eligibility {
                Eligibility::Excluded => "stale",
                Eligibility::NeedsRefresh => "pending",
                Eligibility::Current(_) => {
                    if vector_current(&row) {
                        "current"
                    } else {
                        "pending"
                    }
                }
            };
            connection.execute("INSERT INTO semantic_index_items VALUES(?,?,?,?,?,?,'',?) ON CONFLICT(chunk_id,model_fingerprint) DO UPDATE SET state=CASE WHEN semantic_index_items.state='failed' AND semantic_index_items.source_revision=excluded.source_revision AND semantic_index_items.content_checksum=excluded.content_checksum AND semantic_index_items.chunker_version=excluded.chunker_version AND excluded.state='pending' THEN 'failed' ELSE excluded.state END,source_revision=excluded.source_revision,content_checksum=excluded.content_checksum,chunker_version=excluded.chunker_version,updated_at=excluded.updated_at",params![cursor,fingerprint,state_name,row["source_revision"].as_str(),row["checksum"].as_str(),row["chunker_version"].as_i64(),now()])?;
        }
    }
    index_status(state, fingerprint, scope)
}
