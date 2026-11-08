use super::super::embedding::{
    EmbeddingBatch, EmbeddingError, EmbeddingTimings, ErrorKind, RuntimeDiagnostics,
};
use super::*;
use std::sync::atomic::{AtomicUsize, Ordering};

#[cfg(feature = "native-bekko")]
mod benchmark;

fn fixture() -> (tempfile::TempDir, AppState, BekkoConfig) {
    let temp = tempfile::tempdir().unwrap();
    let mut cfg =
        crate::RuntimeConfig::create_default(temp.path().join("config.toml"), temp.path()).unwrap();
    cfg.set(
        "memory.embedding.backend",
        toml::Value::String("native_bekko_onnx".into()),
    )
    .unwrap();
    cfg.set("memory.embedding.enabled", toml::Value::Boolean(true))
        .unwrap();
    let native = BekkoConfig::from_runtime(&cfg).unwrap();
    let state = AppState::open(cfg).unwrap();
    state
        .store
        .insert("projects", json!({"id":"r2","name":"R2"}))
        .unwrap();
    (temp, state, native)
}
fn identity(tag: char) -> ModelIdentity {
    ModelIdentity {
        backend: "native_bekko_onnx".into(),
        model: MODEL_ID.into(),
        revision: "fixture-v1".into(),
        dimensions: DIMENSIONS,
        max_tokens: 512,
        pooling: "masked_mean_then_l2".into(),
        fingerprint: format!("sha256:{}", tag.to_string().repeat(64)),
        artifacts: vec![],
        integrity_verified: false,
        provenance_authenticated: false,
    }
}
fn scope() -> IndexScope {
    IndexScope {
        project_id: Some("r2".into()),
        ..Default::default()
    }
}
fn document(state: &AppState, id: &str, text: &str) {
    state
        .store
        .insert(
            "workspace_documents",
            json!({"id":id,"project_id":"r2","title":id,"content":text}),
        )
        .unwrap();
    super::super::refresh_document(state, id).unwrap();
}
struct Fake {
    identity: ModelIdentity,
    calls: AtomicUsize,
    fail_at: usize,
    hook: Option<Box<dyn Fn(usize) + Send + Sync>>,
}
impl Fake {
    fn new() -> Self {
        Self {
            identity: identity('a'),
            calls: AtomicUsize::new(0),
            fail_at: usize::MAX,
            hook: None,
        }
    }
}
impl EmbeddingProvider for Fake {
    async fn embed_batch(
        &self,
        _: BekkoConfig,
        texts: Vec<String>,
    ) -> std::result::Result<EmbeddingBatch, EmbeddingError> {
        let call = self.calls.fetch_add(1, Ordering::SeqCst) + 1;
        if let Some(hook) = &self.hook {
            hook(call);
        }
        if call == self.fail_at {
            return Err(EmbeddingError::new(
                ErrorKind::Runtime,
                "fixture provider unavailable",
            ));
        }
        assert!(
            texts.len() <= 64
                && texts.iter().all(|text| text.len() <= 65536)
                && texts.iter().map(String::len).sum::<usize>() <= 1024 * 1024,
            "indexer exceeded R1 batch input bounds"
        );
        let vectors = texts
            .iter()
            .map(|text| {
                let mut v = vec![0f32; DIMENSIONS];
                v[usize::from(Sha256::digest(text)[0])] = 1.;
                v
            })
            .collect();
        Ok(EmbeddingBatch {
            identity: self.identity.clone(),
            vectors,
            timings: EmbeddingTimings {
                artifact_validation_ms: 1.,
                model_load_ms: 0.,
                inference_ms: 1.,
                total_ms: 2.,
                reused_session: call > 1,
            },
        })
    }
    fn diagnostics(&self) -> RuntimeDiagnostics {
        super::super::embedding::EmbeddingService::default().diagnostics()
    }
}
async fn index(state: &AppState, config: &BekkoConfig, fake: &Fake, size: usize) -> Value {
    let id = enqueue(state, &fake.identity, &scope()).unwrap();
    process_job(state, &id, fake, config.clone(), size)
        .await
        .unwrap()
}

#[tokio::test]
async fn fresh_index_is_binary_idempotent_and_keeps_legacy_data() {
    let (_dir, state, config) = fixture();
    document(&state, "a", "The sealed amber letter.");
    document(&state, "b", "Nafila membeli obat.");
    let fake = Fake::new();
    let first = index(&state, &config, &fake, 64).await;
    assert_eq!(first["status"], "completed");
    assert_eq!(first["indexed"], 2);
    assert_eq!(fake.calls.load(Ordering::SeqCst), 1);
    let status = index_status(&state, &fake.identity.fingerprint, &scope()).unwrap();
    assert_eq!(status.current, 2);
    assert_eq!(status.vector_bytes, 3072);
    assert!(status.complete);
    let second = index(&state, &config, &fake, 64).await;
    assert_eq!(second["indexed"], 0);
    assert_eq!(fake.calls.load(Ordering::SeqCst), 1);
    let connection = state.store.connection().unwrap();
    let (kind, len): (String, usize) = connection
        .query_row(
            "SELECT typeof(vector_blob),length(vector_blob) FROM semantic_vectors LIMIT 1",
            [],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .unwrap();
    assert_eq!((kind.as_str(), len), ("blob", 1536));
    assert_eq!(
        connection
            .query_row(
                "SELECT count(*) FROM sqlite_master WHERE name='memory_chunk_embeddings'",
                [],
                |r| r.get::<_, i64>(0)
            )
            .unwrap(),
        1
    );
}

#[tokio::test]
async fn edits_without_refresh_and_deleted_archived_sources_are_not_current() {
    let (_dir, state, config) = fixture();
    document(&state, "a", "An old scene.");
    let fake = Fake::new();
    index(&state, &config, &fake, 64).await;
    state
        .store
        .update(
            "workspace_documents",
            "a",
            json!({"content":"A completely new scene."}),
        )
        .unwrap();
    let stale = index_status(&state, &fake.identity.fingerprint, &scope()).unwrap();
    assert_eq!(stale.current, 0);
    assert_eq!(stale.awaiting_source_refresh, 1);
    assert!(!stale.complete);
    super::super::refresh_document(&state, "a").unwrap();
    index(&state, &config, &fake, 64).await;
    assert_eq!(fake.calls.load(Ordering::SeqCst), 2);
    state.store.connection().unwrap().execute("INSERT INTO resource_lifecycle(resource_type,resource_id,archived_at,updated_at) VALUES('document','a','2026-11-06','2026-11-06')",[]).unwrap();
    assert_eq!(
        index_status(&state, &fake.identity.fingerprint, &scope())
            .unwrap()
            .current,
        0
    );
    state.store.delete("workspace_documents", "a").unwrap();
    let removed = index_status(&state, &fake.identity.fingerprint, &scope()).unwrap();
    assert_eq!(removed.current, 0);
    assert!(removed.stale_vectors >= 2);
}

#[tokio::test]
async fn source_change_during_inference_discards_results_without_holding_write_lock() {
    let (_dir, state, config) = fixture();
    document(&state, "a", "An old scene.");
    let mut fake = Fake::new();
    let editor = state.clone();
    fake.hook = Some(Box::new(move |call| {
        if call == 1 {
            // Keep updated_at unchanged: freshness must depend on content.
            editor.store.execute("UPDATE workspace_documents SET content='Changed while embedding.' WHERE id='a'",&[]).unwrap();
        }
    }));
    let result = index(&state, &config, &fake, 64).await;
    assert_eq!(result["indexed"], 0);
    assert_eq!(result["discarded"], 1);
    assert_eq!(result["status"], "partial");
    assert_eq!(
        index_status(&state, &fake.identity.fingerprint, &scope())
            .unwrap()
            .current,
        0
    );
}

#[tokio::test]
async fn corrupt_vectors_and_wrong_dimensions_are_rejected_and_repaired() {
    let (_dir, state, config) = fixture();
    document(&state, "a", "A scene.");
    let fake = Fake::new();
    index(&state, &config, &fake, 64).await;
    let connection = state.store.connection().unwrap();
    assert!(connection
        .execute("UPDATE semantic_vectors SET dimensions=2", [])
        .is_err());
    assert!(connection
        .execute(
            "UPDATE semantic_vectors SET vector_blob=?",
            [vec![0u8; 1536]]
        )
        .is_err());
    assert!(connection
        .execute(
            "UPDATE semantic_vectors SET model_fingerprint='missing'",
            []
        )
        .is_err());
    connection
        .execute_batch("PRAGMA ignore_check_constraints=ON;")
        .unwrap();
    let mut nan = vec![0u8; 1536];
    nan[..4].copy_from_slice(&f32::NAN.to_le_bytes());
    connection
        .execute("UPDATE semantic_vectors SET vector_blob=?", [nan])
        .unwrap();
    assert_eq!(
        index_status(&state, &fake.identity.fingerprint, &scope())
            .unwrap()
            .current,
        0
    );
    index(&state, &config, &fake, 64).await;
    assert_eq!(
        index_status(&state, &fake.identity.fingerprint, &scope())
            .unwrap()
            .current,
        1
    );
    let calls = fake.calls.load(Ordering::SeqCst);
    state.store.execute("UPDATE memory_chunks SET text='damaged projection' WHERE source_id='a' AND semantic_status='active'",&[]).unwrap();
    assert_eq!(
        index_status(&state, &fake.identity.fingerprint, &scope())
            .unwrap()
            .current,
        0
    );
    super::super::refresh_document(&state, "a").unwrap();
    index(&state, &config, &fake, 64).await;
    assert_eq!(
        index_status(&state, &fake.identity.fingerprint, &scope())
            .unwrap()
            .current,
        1
    );
    assert_eq!(
        fake.calls.load(Ordering::SeqCst),
        calls,
        "repair of identical source text should reuse its valid vector"
    );
}

#[test]
fn binary_vectors_have_explicit_little_endian_encoding_and_reject_invalid_values() {
    let mut values = vec![0f32; DIMENSIONS];
    values[0] = 1.;
    let blob = encode_vector(&values).unwrap();
    assert_eq!(&blob[..4], &[0, 0, 128, 63]);
    assert_eq!(decode_vector(&blob).unwrap(), values);
    values[1] = f32::INFINITY;
    assert!(encode_vector(&values).is_err());
    assert!(encode_vector(&[1., 2.]).is_err());
    assert!(decode_vector(&blob[..100]).is_err());
}

#[tokio::test]
async fn model_generations_are_retained_and_cannot_be_relabelled() {
    let (_dir, state, config) = fixture();
    document(&state, "a", "A scene.");
    let mut fake = Fake::new();
    index(&state, &config, &fake, 64).await;
    let old = fake.identity.fingerprint.clone();
    fake.identity = identity('b');
    index(&state, &config, &fake, 64).await;
    assert_eq!(index_status(&state, &old, &scope()).unwrap().current, 1);
    assert_eq!(
        state
            .store
            .query("SELECT * FROM semantic_model_generations", &[])
            .unwrap()
            .len(),
        2
    );
    let mut mismatch = fake.identity.clone();
    mismatch.max_tokens = 256;
    assert!(enqueue(&state, &mismatch, &scope()).is_err());
    mismatch.dimensions = 1024;
    assert!(enqueue(&state, &mismatch, &scope()).is_err());
}

#[tokio::test]
async fn rechunking_changes_layout_identity_and_supersedes_extra_same_revision_chunks() {
    let (_dir, state, config) = fixture();
    let prose = (0..150)
        .map(|i| format!("Sentence {i} describes the amber lighthouse. "))
        .collect::<String>();
    document(&state, "long", &prose);
    let fake = Fake::new();
    index(&state, &config, &fake, 64).await;
    let first=state.store.query("SELECT id,source_revision,chunker_version FROM memory_chunks WHERE source_id='long' AND semantic_status='active'",&[]).unwrap();
    state
        .config
        .write()
        .unwrap()
        .set("memory.chunk_chars", toml::Value::Integer(500))
        .unwrap();
    super::super::refresh_document(&state, "long").unwrap();
    let changed = index_status(&state, &fake.identity.fingerprint, &scope()).unwrap();
    assert_eq!(changed.current, 0);
    assert!(changed.pending > first.len());
    let next=state.store.query("SELECT id,source_revision,chunker_version FROM memory_chunks WHERE source_id='long' AND semantic_status='active'",&[]).unwrap();
    assert_eq!(first[0]["source_revision"], next[0]["source_revision"]);
    assert_ne!(first[0]["chunker_version"], next[0]["chunker_version"]);
    index(&state, &config, &fake, 64).await;
    state
        .config
        .write()
        .unwrap()
        .set("memory.chunk_chars", toml::Value::Integer(8000))
        .unwrap();
    super::super::refresh_document(&state, "long").unwrap();
    let active = state
        .store
        .query(
            "SELECT id FROM memory_chunks WHERE source_id='long' AND semantic_status='active'",
            &[],
        )
        .unwrap();
    assert_eq!(active.len(), 1);
}

#[tokio::test]
async fn failed_batch_rolls_back_and_retry_skips_durable_prefix() {
    let (_dir, state, config) = fixture();
    for id in ["a", "b", "c"] {
        document(&state, id, "A scene.");
    }
    let mut fake = Fake::new();
    fake.fail_at = 2;
    let id = enqueue(&state, &fake.identity, &scope()).unwrap();
    assert!(process_job(&state, &id, &fake, config.clone(), 1)
        .await
        .is_err());
    assert_eq!(
        state
            .store
            .query("SELECT * FROM semantic_vectors", &[])
            .unwrap()
            .len(),
        1
    );
    assert_eq!(
        index_status(&state, &fake.identity.fingerprint, &scope())
            .unwrap()
            .failed,
        1
    );
    jobs::prepare_resume(&state, &id).unwrap();
    let good = Fake::new();
    let result = process_job(&state, &id, &good, config.clone(), 64)
        .await
        .unwrap();
    assert_eq!(result["status"], "completed");
    assert_eq!(result["indexed"], 2);
    assert_eq!(good.calls.load(Ordering::SeqCst), 1);
    // A failed SQL batch stores neither its vectors nor its durable cursor.
    document(&state, "d", "A later scene.");
    state.store.connection().unwrap().execute_batch("CREATE TRIGGER r2_fault BEFORE INSERT ON semantic_vectors BEGIN SELECT RAISE(ABORT,'fixture disk write failure'); END;").unwrap();
    let bad_id = enqueue(&state, &good.identity, &scope()).unwrap();
    assert!(process_job(&state, &bad_id, &good, config.clone(), 64)
        .await
        .is_err());
    assert_eq!(
        state
            .store
            .query("SELECT * FROM semantic_vectors", &[])
            .unwrap()
            .len(),
        3
    );
    state
        .store
        .connection()
        .unwrap()
        .execute_batch("DROP TRIGGER r2_fault;")
        .unwrap();
    jobs::prepare_resume(&state, &bad_id).unwrap();
    assert_eq!(
        process_job(&state, &bad_id, &good, config, 64)
            .await
            .unwrap()["status"],
        "completed"
    );
}

#[tokio::test]
async fn cancellation_and_source_deletion_during_inference_never_publish_vectors() {
    for delete in [false, true] {
        let (_dir, state, config) = fixture();
        document(&state, "a", "A scene.");
        let mut fake = Fake::new();
        let id = enqueue(&state, &fake.identity, &scope()).unwrap();
        let editor = state.clone();
        let target = id.clone();
        fake.hook = Some(Box::new(move |_| {
            if delete {
                editor.store.delete("workspace_documents", "a").unwrap();
            } else {
                cancel_index_job(&editor, &target).unwrap();
            }
        }));
        let result = process_job(&state, &id, &fake, config, 64).await;
        assert!(state
            .store
            .query("SELECT * FROM semantic_vectors", &[])
            .unwrap()
            .is_empty());
        let job = state
            .store
            .query("SELECT status FROM semantic_index_jobs WHERE id=?", &[&id])
            .unwrap()
            .pop()
            .unwrap();
        if delete {
            assert!(result.is_ok());
            assert_eq!(job["status"], "partial");
        } else {
            assert!(result.is_err());
            assert_eq!(job["status"], "cancelled");
        }
    }
}

#[tokio::test]
async fn recovery_reopening_and_missing_jobs_preserve_vectors_and_source_data() {
    let (_dir, state, config) = fixture();
    document(&state, "a", "Persist this scene.");
    let fake = Fake::new();
    index(&state, &config, &fake, 64).await;
    let id = enqueue(&state, &fake.identity, &scope()).unwrap();
    state.store.execute("UPDATE semantic_index_jobs SET status='running',owner='dead-process',lease_until=0 WHERE id=?",&[&id]).unwrap();
    let reopened = AppState::open(state.runtime_config().unwrap()).unwrap();
    assert_eq!(
        reopened
            .store
            .query("SELECT status FROM semantic_index_jobs WHERE id=?", &[&id])
            .unwrap()[0]["status"],
        "interrupted"
    );
    assert_eq!(
        index_status(&reopened, &fake.identity.fingerprint, &scope())
            .unwrap()
            .current,
        1
    );
    assert_eq!(
        reopened
            .store
            .get("workspace_documents", "a")
            .unwrap()
            .unwrap()["content"],
        "Persist this scene."
    );
    jobs::prepare_resume(&reopened, &id).unwrap();
    process_job(&reopened, &id, &fake, config.clone(), 64)
        .await
        .unwrap();
    assert_eq!(fake.calls.load(Ordering::SeqCst), 1);
    reopened
        .store
        .connection()
        .unwrap()
        .execute("DELETE FROM semantic_index_jobs", [])
        .unwrap();
    reconcile_index(&reopened, &fake.identity.fingerprint, &scope()).unwrap();
    index(&reopened, &config, &fake, 64).await;
    assert_eq!(fake.calls.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn diagnostic_search_filters_before_top_k_and_reports_unavailable_generations() {
    let (_dir, state, config) = fixture();
    document(&state, "allowed", "A scene.");
    document(&state, "hidden", "A scene.");
    let fake = Fake::new();
    index(&state, &config, &fake, 64).await;
    let row = state
        .store
        .query(
            "SELECT id FROM memory_chunks WHERE source_id='allowed' AND semantic_status='active'",
            &[],
        )
        .unwrap()[0]
        .clone();
    let allowed = HashSet::from([row["id"].as_str().unwrap().to_owned()]);
    let mut query = vec![0.; DIMENSIONS];
    query[0] = 1.;
    let result = diagnostic_search(
        &state,
        &fake.identity.fingerprint,
        "r2",
        &allowed,
        &query,
        1,
    )
    .unwrap();
    assert_eq!(result["hits"].as_array().unwrap().len(), 1);
    assert_eq!(result["hits"][0]["source_id"], "allowed");
    let foreign = diagnostic_search(
        &state,
        &fake.identity.fingerprint,
        "other-project",
        &allowed,
        &query,
        1,
    )
    .unwrap();
    assert!(foreign["hits"].as_array().unwrap().is_empty());
    assert!(diagnostic_search(&state, "missing", "r2", &allowed, &query, 1).is_err());
}

#[tokio::test]
async fn missing_native_provider_is_optional_and_leaves_a_retryable_job() {
    let (_dir, state, config) = fixture();
    document(&state, "a", "A scene.");
    let id = enqueue(&state, &identity('a'), &scope()).unwrap();
    assert!(
        process_job(&state, &id, state.embeddings.as_ref(), config, 64)
            .await
            .is_err()
    );
    assert_eq!(
        state
            .store
            .query("SELECT status FROM semantic_index_jobs WHERE id=?", &[&id])
            .unwrap()[0]["status"],
        "failed"
    );
    assert!(state
        .store
        .get("workspace_documents", "a")
        .unwrap()
        .is_some());
}

#[tokio::test]
async fn model_replacement_during_a_job_cannot_publish_under_the_old_fingerprint() {
    let (_dir, state, config) = fixture();
    document(&state, "a", "A scene.");
    let expected = identity('a');
    let id = enqueue(&state, &expected, &scope()).unwrap();
    let mut replacement = Fake::new();
    replacement.identity = identity('b');
    assert!(process_job(&state, &id, &replacement, config, 64)
        .await
        .is_err());
    assert!(state
        .store
        .query("SELECT * FROM semantic_vectors", &[])
        .unwrap()
        .is_empty());
    assert_eq!(
        index_status(&state, &expected.fingerprint, &scope())
            .unwrap()
            .failed,
        1
    );
}

#[tokio::test]
async fn migration_backup_and_old_runtime_rollback_preserve_authoritative_and_legacy_rows() {
    let (dir, state, config) = fixture();
    document(&state, "a", "A scene for rollback.");
    let fake = Fake::new();
    index(&state, &config, &fake, 64).await;
    let connection = state.store.connection().unwrap();
    connection.execute("INSERT INTO memory_chunk_embeddings(chunk_id,model,dimensions,embedding_json,created_at) VALUES('legacy','legacy-model',2,'[1,0]','2026-11-06')",[]).unwrap();
    // Simulate a pre-R2 workspace by removing only additive derived objects.
    connection.execute_batch("DROP TRIGGER semantic_chunk_insert;DROP TRIGGER semantic_chunk_update;DROP TRIGGER semantic_chunk_delete;DROP TABLE semantic_index_items;DROP TABLE semantic_index_jobs;DROP TABLE semantic_vectors;DROP TABLE semantic_model_generations;DROP TABLE semantic_pending_sources;DROP TABLE semantic_index_meta;").unwrap();
    let reopened = AppState::open(state.runtime_config().unwrap()).unwrap();
    assert_eq!(
        reopened
            .store
            .get("workspace_documents", "a")
            .unwrap()
            .unwrap()["content"],
        "A scene for rollback."
    );
    assert_eq!(
        reopened
            .store
            .query(
                "SELECT * FROM memory_chunk_embeddings WHERE chunk_id='legacy'",
                &[]
            )
            .unwrap()
            .len(),
        1
    );
    let parent = state.store.path.parent().unwrap();
    let backups = std::fs::read_dir(parent)
        .unwrap()
        .filter_map(Result::ok)
        .filter(|e| {
            e.file_name()
                .to_string_lossy()
                .contains("before-semantic-v1")
        })
        .collect::<Vec<_>>();
    assert!(backups.len() >= 2);
    let snapshot = backups
        .iter()
        .find(|entry| {
            let db = Connection::open(entry.path()).unwrap();
            db.query_row(
                "SELECT count(*) FROM workspace_documents WHERE id='a'",
                [],
                |r| r.get::<_, i64>(0),
            )
            .unwrap_or(0)
                == 1
        })
        .unwrap();
    let restored = dir.path().join("restored.db");
    std::fs::copy(snapshot.path(), &restored).unwrap();
    let old = Connection::open(&restored).unwrap();
    assert_eq!(
        old.query_row("PRAGMA integrity_check", [], |r| r.get::<_, String>(0))
            .unwrap(),
        "ok"
    );
    assert_eq!(
        old.query_row(
            "SELECT content FROM workspace_documents WHERE id='a'",
            [],
            |r| r.get::<_, String>(0)
        )
        .unwrap(),
        "A scene for rollback."
    );
    // An old runtime without the custom vector SQL function can still mutate
    // narrative rows while retaining R2 tables and vectors untouched.
    let old_live = Connection::open(&state.store.path).unwrap();
    old_live
        .execute(
            "UPDATE workspace_documents SET content='Old runtime edit' WHERE id='a'",
            [],
        )
        .unwrap();
    assert_eq!(
        reopened
            .store
            .get("workspace_documents", "a")
            .unwrap()
            .unwrap()["content"],
        "Old runtime edit"
    );
}

struct Paused {
    fake: Fake,
    started: tokio::sync::Notify,
    resume: tokio::sync::Notify,
}
impl EmbeddingProvider for Paused {
    async fn embed_batch(
        &self,
        cfg: BekkoConfig,
        texts: Vec<String>,
    ) -> std::result::Result<EmbeddingBatch, EmbeddingError> {
        self.started.notify_one();
        self.resume.notified().await;
        self.fake.embed_batch(cfg, texts).await
    }
    fn diagnostics(&self) -> RuntimeDiagnostics {
        self.fake.diagnostics()
    }
}
#[tokio::test]
async fn reopening_does_not_steal_a_live_job_and_aborted_workers_are_recoverable() {
    let (_dir, state, config) = fixture();
    document(&state, "a", "A scene.");
    let paused = Arc::new(Paused {
        fake: Fake::new(),
        started: tokio::sync::Notify::new(),
        resume: tokio::sync::Notify::new(),
    });
    let id = enqueue(&state, &paused.fake.identity, &scope()).unwrap();
    let worker = state.clone();
    let provider = paused.clone();
    let work_id = id.clone();
    let task =
        tokio::spawn(
            async move { process_job(&worker, &work_id, provider.as_ref(), config, 64).await },
        );
    paused.started.notified().await;
    let reopened = AppState::open(state.runtime_config().unwrap()).unwrap();
    assert_eq!(
        reopened
            .store
            .query("SELECT status FROM semantic_index_jobs WHERE id=?", &[&id])
            .unwrap()[0]["status"],
        "running"
    );
    task.abort();
    let _ = task.await;
    jobs::recover_jobs(&state.store).unwrap();
    assert_eq!(
        state
            .store
            .query("SELECT status FROM semantic_index_jobs WHERE id=?", &[&id])
            .unwrap()[0]["status"],
        "interrupted"
    );
    assert!(state
        .store
        .query("SELECT * FROM semantic_vectors", &[])
        .unwrap()
        .is_empty());
}

#[tokio::test]
async fn byte_bounded_batches_and_late_insertions_report_coverage_honestly() {
    let (_dir, state, config) = fixture();
    state
        .config
        .write()
        .unwrap()
        .set("memory.chunk_chars", toml::Value::Integer(64000))
        .unwrap();
    for i in 0..20 {
        document(&state, &format!("large-{i:02}"), &"x".repeat(60000));
    }
    let fake = Fake::new();
    let result = index(&state, &config, &fake, 64).await;
    assert_eq!(result["indexed"], 20);
    assert_eq!(fake.calls.load(Ordering::SeqCst), 2);
    let (_dir, state, config) = fixture();
    document(&state, "zz-last", "A scene.");
    let mut fake = Fake::new();
    let editor = state.clone();
    fake.hook = Some(Box::new(move |call| {
        if call == 1 {
            document(
                &editor,
                "aa-inserted-behind-cursor",
                "A newly created scene.",
            );
        }
    }));
    let partial = index(&state, &config, &fake, 64).await;
    assert_eq!(partial["status"], "partial");
    assert_eq!(partial["coverage"]["pending"], 1);
    let resumed = index(&state, &config, &fake, 64).await;
    assert_eq!(resumed["status"], "completed");
    assert_eq!(resumed["indexed"], 1);
}

#[tokio::test]
async fn repeated_requests_share_jobs_and_the_durable_queue_is_bounded() {
    let (_dir, state, _config) = fixture();
    let expected = identity('a');
    let first = enqueue(&state, &expected, &scope()).unwrap();
    assert_eq!(first, enqueue(&state, &expected, &scope()).unwrap());
    for i in 0..15 {
        enqueue(
            &state,
            &expected,
            &IndexScope {
                project_id: Some(format!("project-{i}")),
                ..Default::default()
            },
        )
        .unwrap();
    }
    assert!(enqueue(
        &state,
        &expected,
        &IndexScope {
            project_id: Some("overflow".into()),
            ..Default::default()
        }
    )
    .is_err());
    assert!(cancel_index_job(&state, &first).unwrap());
    assert_ne!(first, enqueue(&state, &expected, &scope()).unwrap());
}

#[tokio::test]
async fn sqlite_writer_contention_is_bounded_and_completed_batches_remain_atomic() {
    let (_dir, state, config) = fixture();
    document(&state, "a", "A scene.");
    let mut fake = Fake::new();
    let editor = state.clone();
    fake.hook = Some(Box::new(move |call| {
        if call == 1 {
            let connection = editor.store.connection().unwrap();
            connection.execute_batch("BEGIN IMMEDIATE;").unwrap();
            std::thread::spawn(move || {
                std::thread::sleep(std::time::Duration::from_millis(120));
                connection.execute_batch("COMMIT;").unwrap();
            });
        }
    }));
    let result = index(&state, &config, &fake, 64).await;
    assert_eq!(result["status"], "completed");
    assert_eq!(result["indexed"], 1);
    assert!(
        result["commit_ms"].as_f64().unwrap() >= 80.,
        "write contention was not included in commit timing"
    );
}

#[test]
fn index_maintenance_open_does_not_interrupt_a_live_narrative_writer() {
    let (_dir, state, _config) = fixture();
    state
        .store
        .insert("sessions", json!({"id":"live-writer","title":"Live"}))
        .unwrap();
    state.store.insert("turns",json!({"id":"live-turn","session_id":"live-writer","user_prompt":"Continue","story":"partial prose","stats_json":{"run_status":"running","partial":true}})).unwrap();
    let maintenance = AppState::open_index_maintenance(state.runtime_config().unwrap()).unwrap();
    assert_eq!(
        maintenance
            .store
            .get("turns", "live-turn")
            .unwrap()
            .unwrap()["stats"]["run_status"],
        "running"
    );
}

#[tokio::test]
async fn preflight_is_bounded_before_artifact_hashing_or_model_loading() {
    let (_dir, state, config) = fixture();
    let permits = (0..4)
        .map(|_| jobs::request_slot().unwrap())
        .collect::<Vec<_>>();
    let error = index_pending(state.clone(), config, scope(), 32)
        .await
        .unwrap_err();
    assert_eq!(error.status, axum::http::StatusCode::TOO_MANY_REQUESTS);
    assert_eq!(state.embeddings.diagnostics().successful_loads, 0);
    assert!(state
        .store
        .query("SELECT * FROM semantic_model_generations", &[])
        .unwrap()
        .is_empty());
    drop(permits);
}
