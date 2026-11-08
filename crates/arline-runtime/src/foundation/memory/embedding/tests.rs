use super::*;
use std::{
    sync::{
        atomic::{AtomicUsize, Ordering},
        Barrier,
    },
    time::Duration,
};

fn native_config(dir: &std::path::Path) -> RuntimeConfig {
    let mut config = RuntimeConfig::create_default(dir.join("config.toml"), dir).unwrap();
    config
        .set(
            "memory.embedding.backend",
            toml::Value::String("native_bekko_onnx".into()),
        )
        .unwrap();
    config
}
fn wait(mut ready: impl FnMut() -> bool) {
    let start = Instant::now();
    while !ready() {
        assert!(
            start.elapsed() < Duration::from_secs(3),
            "lifecycle timed out"
        );
        std::thread::sleep(Duration::from_millis(5));
    }
}

fn cache_idle<M: Send + 'static>(cache: &lifecycle::ModelCache<M>) -> bool {
    let diagnostic = cache.diagnostics();
    !diagnostic.busy && !diagnostic.loaded && !diagnostic.eviction_worker_running
}

#[test]
fn busy_diagnostics_cannot_be_treated_as_an_evicted_zero_load_cache() {
    let cache = lifecycle::ModelCache::<()>::new();
    let worker = cache.clone();
    let (started_tx, started_rx) = std::sync::mpsc::channel();
    let (resume_tx, resume_rx) = std::sync::mpsc::channel();
    let thread = std::thread::spawn(move || {
        worker
            .with_model(
                "busy",
                Duration::ZERO,
                || Ok(()),
                |_| {
                    started_tx.send(()).unwrap();
                    resume_rx.recv_timeout(Duration::from_secs(3)).unwrap();
                    Ok(())
                },
            )
            .unwrap()
    });
    started_rx.recv_timeout(Duration::from_secs(3)).unwrap();
    assert!(cache.diagnostics().busy);
    assert!(
        !cache_idle(&cache),
        "busy diagnostic fields are unknown, not evidence of eviction"
    );
    resume_tx.send(()).unwrap();
    thread.join().unwrap();
    assert!(cache_idle(&cache));
    assert_eq!(cache.diagnostics().successful_loads, 1);
}

#[test]
fn settings_are_explicit_strict_and_resolve_against_workspace_root() {
    let temp = tempfile::tempdir().unwrap();
    let mut config = native_config(temp.path());
    let native = BekkoConfig::from_runtime(&config).unwrap();
    let mut invalid_backend = config.clone();
    invalid_backend
        .set("memory.embedding.backend", toml::Value::Integer(1))
        .unwrap();
    assert!(validate_config(&invalid_backend).is_err());
    assert!(!native.enabled);
    assert_eq!(native.max_tokens, 512);
    assert_eq!(native.threads, 2);
    assert_eq!(native.keep_warm_seconds, 300);
    assert_eq!(
        native.model_dir,
        config.root.join("models/bekko-embedding-v1-a8m")
    );
    for (field, value) in [
        ("dimension", toml::Value::Integer(768)),
        ("max_tokens", toml::Value::Integer(513)),
        ("threads", toml::Value::Integer(0)),
        ("keep_warm_seconds", toml::Value::Integer(-1)),
        ("enabled", toml::Value::String("true".into())),
        ("model", toml::Value::String("other".into())),
        ("query_prefix", toml::Value::String("query: ".into())),
        (
            "runtime_library",
            toml::Value::String("./onnxruntime.dll".into()),
        ),
    ] {
        let mut bad = config.clone();
        bad.set(&format!("memory.embedding.{field}"), value)
            .unwrap();
        assert_eq!(
            BekkoConfig::from_runtime(&bad).unwrap_err().kind,
            ErrorKind::InvalidSettings,
            "{field}"
        );
    }
    config
        .set("memory.dense_enabled", toml::Value::Boolean(true))
        .unwrap();
    assert!(BekkoConfig::from_runtime(&config).unwrap().enabled);
    config
        .set("memory.embedding.enabled", toml::Value::Boolean(false))
        .unwrap();
    assert!(!BekkoConfig::from_runtime(&config).unwrap().enabled);
    assert_eq!(
        super::super::settings::settings(&config)["dense_enabled"],
        false
    );
    config
        .set("memory.dense_enabled", toml::Value::Boolean(false))
        .unwrap();
    config
        .set("memory.embedding.enabled", toml::Value::Boolean(true))
        .unwrap();
    assert!(
        !BekkoConfig::from_runtime(&config).unwrap().enabled,
        "conflicting saved gates must not activate embeddings"
    );
}

#[tokio::test]
async fn disabled_and_invalid_inputs_do_not_load_or_touch_model_files() {
    let temp = tempfile::tempdir().unwrap();
    let runtime = native_config(temp.path());
    let service = EmbeddingService::default();
    let mut config = BekkoConfig::from_runtime(&runtime).unwrap();
    assert_eq!(
        service
            .embed_batch(config.clone(), vec!["hello".into()])
            .await
            .unwrap_err()
            .kind,
        ErrorKind::Disabled
    );
    config.enabled = true;
    for texts in [vec![], vec!["x".repeat(65537)], vec!["x".into(); 65]] {
        assert_eq!(
            service
                .embed_batch(config.clone(), texts)
                .await
                .unwrap_err()
                .kind,
            ErrorKind::InvalidInput
        );
    }
    assert_eq!(service.diagnostics().successful_loads, 0);
    assert!(!service.diagnostics().loaded);
    #[cfg(not(feature = "native-bekko"))]
    assert_eq!(
        service
            .embed_batch(config, vec!["hello".into()])
            .await
            .unwrap_err()
            .kind,
        ErrorKind::FeatureUnavailable
    );
    #[cfg(feature = "native-bekko")]
    assert_eq!(
        service
            .embed_batch(config, vec!["hello".into()])
            .await
            .unwrap_err()
            .kind,
        ErrorKind::Artifact
    );
}

#[test]
fn cache_serializes_first_load_and_inference_and_is_workspace_local() {
    let cache = lifecycle::ModelCache::new();
    let loads = Arc::new(AtomicUsize::new(0));
    let barrier = Arc::new(Barrier::new(8));
    let active = Arc::new(AtomicUsize::new(0));
    let handles = (0..8)
        .map(|_| {
            let (cache, loads, barrier, active) = (
                cache.clone(),
                loads.clone(),
                barrier.clone(),
                active.clone(),
            );
            std::thread::spawn(move || {
                barrier.wait();
                cache
                    .with_model(
                        "model",
                        Duration::from_secs(60),
                        || {
                            loads.fetch_add(1, Ordering::SeqCst);
                            Ok(())
                        },
                        |_| {
                            assert_eq!(active.fetch_add(1, Ordering::SeqCst), 0);
                            std::thread::sleep(Duration::from_millis(5));
                            active.fetch_sub(1, Ordering::SeqCst);
                            Ok(())
                        },
                    )
                    .unwrap();
            })
        })
        .collect::<Vec<_>>();
    for h in handles {
        h.join().unwrap();
    }
    assert_eq!(loads.load(Ordering::SeqCst), 1);
    assert!(cache.diagnostics().eviction_worker_running);
    let other = lifecycle::ModelCache::<()>::new();
    assert!(!other.diagnostics().loaded);
    cache.shutdown();
    wait(|| cache_idle(&cache));
}

#[test]
fn cache_reuses_evicts_reloads_and_stops_one_worker() {
    let cache = lifecycle::ModelCache::<()>::new();
    let ttl = Duration::from_secs(5);
    assert!(!cache.diagnostics().loaded);
    let first = cache.with_model("a", ttl, || Ok(()), |_| Ok(7)).unwrap();
    assert!(!first.reused);
    assert_eq!(first.value, 7);
    assert!(first.load_ms.is_finite() && first.infer_ms.is_finite());
    assert!(
        cache
            .with_model(
                "a",
                Duration::from_millis(40),
                || panic!("must reuse"),
                |_| Ok(())
            )
            .unwrap()
            .reused
    );
    wait(|| cache_idle(&cache));
    assert!(!cache.diagnostics().loaded);
    assert!(
        !cache
            .with_model("a", ttl, || Ok(()), |_| Ok(()))
            .unwrap()
            .reused
    );
    assert_eq!(cache.diagnostics().successful_loads, 2);
    cache.shutdown();
    wait(|| cache_idle(&cache));
}

#[test]
fn replacement_zero_retention_errors_and_panics_discard_sessions() {
    let cache = lifecycle::ModelCache::<()>::new();
    cache
        .with_model("a", Duration::from_secs(5), || Ok(()), |_| Ok(()))
        .unwrap();
    assert!(
        !cache
            .with_model("b", Duration::from_secs(5), || Ok(()), |_| Ok(()))
            .unwrap()
            .reused
    );
    assert!(cache
        .with_model(
            "b",
            Duration::from_secs(5),
            || Ok(()),
            |_| -> Result<()> { panic!("fake inference panic") }
        )
        .is_err());
    assert!(!cache.diagnostics().loaded);
    let fail = || EmbeddingError::new(ErrorKind::Inference, "fake failure");
    assert!(cache
        .with_model("c", Duration::ZERO, || Err(fail()), |_| Ok(()))
        .is_err());
    cache
        .with_model("c", Duration::ZERO, || Ok(()), |_| Ok(()))
        .unwrap();
    assert!(!cache.diagnostics().loaded);
    cache
        .with_model("d", Duration::from_secs(5), || Ok(()), |_| Ok(()))
        .unwrap();
    assert!(cache
        .with_model(
            "d",
            Duration::from_secs(5),
            || Ok(()),
            |_| Err::<(), _>(fail())
        )
        .is_err());
    assert!(!cache.diagnostics().loaded);
    cache.shutdown();
    wait(|| cache_idle(&cache));
}

#[test]
fn fingerprints_detect_same_size_timestamp_replacement_and_validate_limits() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("artifact");
    std::fs::write(&path, b"abcdef").unwrap();
    let mtime = std::fs::metadata(&path).unwrap().modified().unwrap();
    let first = artifacts::digest_file(&path, 6).unwrap();
    std::fs::write(&path, b"abcdeg").unwrap();
    std::fs::File::options()
        .write(true)
        .open(&path)
        .unwrap()
        .set_times(std::fs::FileTimes::new().set_modified(mtime))
        .unwrap();
    assert_ne!(first.1, artifacts::digest_file(&path, 6).unwrap().1);
    assert!(artifacts::digest_file(&path, 5).is_err());
    std::fs::write(&path, b"").unwrap();
    assert!(artifacts::digest_file(&path, 6).is_err());
    assert!(artifacts::digest_file(&temp.path().join("missing"), 6).is_err());
}

#[test]
fn malformed_and_incompatible_pooling_metadata_are_rejected() {
    let temp = tempfile::tempdir().unwrap();
    std::fs::create_dir(temp.path().join("1_Pooling")).unwrap();
    std::fs::write(temp.path().join("config.json"), "broken").unwrap();
    assert!(artifacts::validate_metadata(temp.path()).is_err());
    std::fs::write(
        temp.path().join("config.json"),
        r#"{"hidden_size":384,"model_type":"modernbert","pad_token_id":0}"#,
    )
    .unwrap();
    std::fs::write(
        temp.path().join("1_Pooling/config.json"),
        r#"{"word_embedding_dimension":384,"pooling_mode_mean_tokens":false}"#,
    )
    .unwrap();
    assert!(artifacts::validate_metadata(temp.path()).is_err());
}

#[cfg(feature = "native-bekko")]
#[tokio::test]
async fn missing_and_incompatible_runtime_libraries_are_recoverable() {
    let temp = tempfile::tempdir().unwrap();
    let runtime = native_config(temp.path());
    let mut config = BekkoConfig::from_runtime(&runtime).unwrap();
    config.runtime_library = temp.path().join("missing-runtime.dll");
    assert_eq!(
        native::environment(&config).unwrap_err().kind,
        ErrorKind::Runtime
    );
    assert!(native::check_binding(
        &config.runtime_library,
        "old",
        &config.runtime_library,
        "new"
    )
    .is_err());
    assert!(native::check_binding(
        &config.runtime_library,
        "old",
        &temp.path().join("other.dll"),
        "old"
    )
    .is_err());
    assert!(native::check_binding(
        &config.runtime_library,
        "old",
        &config.runtime_library,
        "old"
    )
    .is_ok());
    std::fs::write(&config.runtime_library, b"not an ONNX library").unwrap();
    assert_eq!(
        native::environment(&config).unwrap_err().kind,
        ErrorKind::Runtime
    );
}

#[cfg(feature = "native-bekko")]
#[tokio::test]
#[ignore = "requires explicitly provisioned local Bekko artifacts and ONNX Runtime CPU 1.27.0"]
async fn qualified_bekko_vectors_match_frozen_references_and_truncate() {
    let temp = tempfile::tempdir().unwrap();
    let mut runtime = native_config(temp.path());
    runtime
        .set("memory.embedding.enabled", toml::Value::Boolean(true))
        .unwrap();
    runtime
        .set(
            "memory.embedding.model_dir",
            toml::Value::String(std::env::var("ARLINE_BEKKO_MODEL_DIR").unwrap()),
        )
        .unwrap();
    runtime
        .set(
            "memory.embedding.runtime_library",
            toml::Value::String(std::env::var("ARLINE_ONNX_RUNTIME").unwrap()),
        )
        .unwrap();
    let config = BekkoConfig::from_runtime(&runtime).unwrap();
    let service = EmbeddingService::default();
    let reference: serde_json::Value = serde_json::from_str(include_str!(
        "../../../../tests/fixtures/bekko-reference.json"
    ))
    .unwrap();
    let cases = reference["cases"].as_array().unwrap();
    let texts = cases
        .iter()
        .map(|c| c["text"].as_str().unwrap().to_owned())
        .collect::<Vec<_>>();
    let first = service
        .embed_batch(config.clone(), texts.clone())
        .await
        .unwrap();
    assert_eq!(first.identity.model, MODEL_ID);
    assert_eq!(first.identity.dimensions, DIMENSIONS);
    assert!(!first.timings.reused_session);
    for (actual, case) in first.vectors.iter().zip(cases) {
        let expected = case["vector"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_f64().unwrap())
            .collect::<Vec<_>>();
        let norm = actual
            .iter()
            .map(|v| f64::from(*v).powi(2))
            .sum::<f64>()
            .sqrt();
        let expected_norm = expected.iter().map(|v| v * v).sum::<f64>().sqrt();
        assert_eq!(actual.len(), 384);
        assert!(actual.iter().all(|v| v.is_finite()));
        assert!((norm - 1.0).abs() < 1e-5);
        let cosine = actual
            .iter()
            .zip(&expected)
            .map(|(a, b)| f64::from(*a) * b)
            .sum::<f64>()
            / (norm * expected_norm);
        let error = actual
            .iter()
            .zip(&expected)
            .map(|(a, b)| (f64::from(*a) - b).abs())
            .fold(0.0, f64::max);
        assert!(
            cosine >= reference["cosine_min"].as_f64().unwrap(),
            "{}: cosine={cosine}",
            case["id"]
        );
        assert!(
            error <= reference["max_component_error"].as_f64().unwrap(),
            "component error={error}"
        );
    }
    let warm = service.embed_batch(config.clone(), texts).await.unwrap();
    assert!(warm.timings.reused_session);
    assert_eq!(warm.identity.fingerprint, first.identity.fingerprint);
    let extra = service
        .embed_batch(
            config.clone(),
            vec![
                "".into(),
                "a".into(),
                format!(
                    "{} late suffix A",
                    "Vian mencari evidence untuk cerita. ".repeat(1000)
                ),
                format!(
                    "{} different late suffix B",
                    "Vian mencari evidence untuk cerita. ".repeat(1000)
                ),
            ],
        )
        .await
        .unwrap();
    assert_eq!(extra.vectors.len(), 4);
    assert!(
        extra.vectors[2]
            .iter()
            .zip(&extra.vectors[3])
            .all(|(a, b)| (a - b).abs() < 1e-6),
        "suffixes beyond 512 tokens affected the embedding"
    );
    assert!(extra
        .vectors
        .iter()
        .all(|v| v.len() == 384 && v.iter().all(|x| x.is_finite())));
    let mut changed = config;
    changed.max_tokens = 256;
    let shorter = service
        .embed_batch(changed, vec!["short text".into()])
        .await
        .unwrap();
    assert!(!shorter.timings.reused_session);
    assert_ne!(shorter.identity.fingerprint, first.identity.fingerprint);
    // Explicit cleanup also releases the R2 process-wide residency slot before
    // another provisioned-model test starts in this process.
    service.unload().await.unwrap();
}
