//! Optional embedding capability. No retrieval, SQL, downloading or writer calls.
mod artifacts;
mod lifecycle;
#[cfg(feature = "native-bekko")]
mod native;

use crate::config::RuntimeConfig;
use serde::Serialize;
use std::{future::Future, path::PathBuf, sync::Arc, time::Instant};
use tokio::sync::Semaphore;

pub use artifacts::{ArtifactDigest, ModelIdentity, MODEL_ID};
pub use lifecycle::Diagnostics as RuntimeDiagnostics;
pub const DIMENSIONS: usize = 384;

#[derive(Clone, Copy, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ErrorKind {
    Disabled,
    FeatureUnavailable,
    InvalidSettings,
    InvalidInput,
    Artifact,
    Runtime,
    Inference,
    Shutdown,
    ResourceBusy,
}

#[derive(Clone, Debug, Serialize)]
pub struct EmbeddingError {
    pub kind: ErrorKind,
    pub message: String,
    pub fallback: &'static str,
}
impl EmbeddingError {
    pub(super) fn new(kind: ErrorKind, message: impl Into<String>) -> Self {
        Self {
            kind,
            message: message.into(),
            fallback: "fts5+structured",
        }
    }
}
impl std::fmt::Display for EmbeddingError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{:?}: {}", self.kind, self.message)
    }
}
impl std::error::Error for EmbeddingError {}
pub type Result<T> = std::result::Result<T, EmbeddingError>;

#[derive(Clone, Debug)]
pub struct BekkoConfig {
    pub enabled: bool,
    pub model_dir: PathBuf,
    pub runtime_library: PathBuf,
    pub max_tokens: usize,
    pub threads: usize,
    pub keep_warm_seconds: u64,
}

impl BekkoConfig {
    /// Relative model paths use RuntimeConfig.root (the native application data
    /// directory), never the process working directory. Runtime DLL paths must
    /// be absolute; absence means the trusted executable-adjacent location.
    pub fn from_runtime(config: &RuntimeConfig) -> Result<Self> {
        let settings = super::settings::settings(config);
        let e = &settings["embedding"];
        fn invalid(message: impl Into<String>) -> EmbeddingError {
            EmbeddingError::new(ErrorKind::InvalidSettings, message)
        }
        if e["backend"] != "native_bekko_onnx" {
            return Err(invalid("native_bekko_onnx must be explicitly selected"));
        }
        let key = |field: &str| {
            let nested = format!("memory.embedding.{field}");
            if config.value(&nested).is_some() {
                nested
            } else {
                format!("memory_embedding.{field}")
            }
        };
        for field in ["enabled"] {
            if config.value(&key(field)).is_some_and(|v| !v.is_bool()) {
                return Err(invalid("embedding.enabled must be boolean"));
            }
        }
        if config
            .value("memory.dense_enabled")
            .is_some_and(|v| !v.is_bool())
        {
            return Err(invalid("memory.dense_enabled must be boolean"));
        }
        for field in [
            "backend",
            "model",
            "model_dir",
            "runtime_library",
            "query_prefix",
            "passage_prefix",
        ] {
            if config.value(&key(field)).is_some_and(|v| !v.is_str()) {
                return Err(invalid(
                    "native embedding paths, identity and prefixes must be strings",
                ));
            }
        }
        for (field, min, max) in [
            ("dimension", 384, 384),
            ("max_tokens", 2, 512),
            ("threads", 1, 32),
            ("keep_warm_seconds", 0, 86400),
        ] {
            if let Some(value) = config.value(&key(field)) {
                if !value.as_integer().is_some_and(|n| (min..=max).contains(&n)) {
                    return Err(invalid(format!(
                        "embedding.{field} must be an integer in {min}..={max}"
                    )));
                }
            }
        }
        if e["model"] != MODEL_ID || e["dimension"] != DIMENSIONS {
            return Err(invalid("native Bekko requires the exact hotchpotch/bekko-embedding-v1-a8m model and 384 dimensions"));
        }
        if e["query_prefix"] != "" || e["passage_prefix"] != "" {
            return Err(invalid("Bekko uses empty query and passage prefixes"));
        }
        let model_path = e["model_dir"].as_str().unwrap_or_default();
        if model_path.is_empty() {
            return Err(invalid("embedding.model_dir must not be empty"));
        }
        let runtime_library = match e["runtime_library"].as_str().filter(|s| !s.is_empty()) {
            Some(path) => PathBuf::from(path),
            None => std::env::current_exe()
                .map_err(|_| invalid("cannot determine executable location"))?
                .with_file_name(if cfg!(windows) {
                    "onnxruntime.dll"
                } else {
                    "libonnxruntime.so"
                }),
        };
        if !runtime_library.is_absolute() {
            return Err(invalid("embedding.runtime_library must be absolute"));
        }
        let value = Self {
            enabled: e["enabled"].as_bool().unwrap_or(false),
            model_dir: config.resolve(model_path),
            runtime_library,
            max_tokens: e["max_tokens"].as_u64().unwrap_or(512) as usize,
            threads: e["threads"].as_u64().unwrap_or(2) as usize,
            keep_warm_seconds: e["keep_warm_seconds"].as_u64().unwrap_or(300),
        };
        value.validate()?;
        Ok(value)
    }
    fn validate(&self) -> Result<()> {
        if !(2..=512).contains(&self.max_tokens)
            || !(1..=32).contains(&self.threads)
            || self.keep_warm_seconds > 86400
            || !self.model_dir.is_absolute()
            || !self.runtime_library.is_absolute()
        {
            return Err(EmbeddingError::new(
                ErrorKind::InvalidSettings,
                "invalid native embedding bounds or non-absolute resolved paths",
            ));
        }
        Ok(())
    }
}

pub fn validate_config(config: &RuntimeConfig) -> crate::ApiResult<()> {
    let backend_key = if config.value("memory.embedding.backend").is_some() {
        "memory.embedding.backend"
    } else {
        "memory_embedding.backend"
    };
    if config
        .value(backend_key)
        .is_some_and(|value| !value.is_str())
    {
        return Err(crate::ApiError::bad_request(
            "memory.embedding.backend must be a string",
        ));
    }
    let settings = super::settings::settings(config);
    let backend = settings["embedding"]["backend"].as_str().unwrap_or("");
    if !["lmstudio", "native_bekko_onnx"].contains(&backend) {
        return Err(crate::ApiError::bad_request(
            "Unsupported memory.embedding.backend",
        ));
    }
    if backend == "native_bekko_onnx" {
        BekkoConfig::from_runtime(config).map_err(|e| crate::ApiError::bad_request(e.message))?;
    }
    Ok(())
}

#[derive(Debug, Serialize)]
pub struct EmbeddingBatch {
    pub identity: ModelIdentity,
    pub vectors: Vec<Vec<f32>>,
    pub timings: EmbeddingTimings,
}
#[derive(Debug, Serialize)]
pub struct EmbeddingTimings {
    pub artifact_validation_ms: f64,
    pub model_load_ms: f64,
    pub inference_ms: f64,
    pub total_ms: f64,
    pub reused_session: bool,
}

/// Static-dispatch interface for R2 batch indexing; errors explicitly preserve
/// lexical fallback. No provider implementation may modify narrative authority.
pub trait EmbeddingProvider: Send + Sync {
    fn embed_batch(
        &self,
        config: BekkoConfig,
        texts: Vec<String>,
    ) -> impl Future<Output = Result<EmbeddingBatch>> + Send;
    fn diagnostics(&self) -> RuntimeDiagnostics;
}

#[cfg(feature = "native-bekko")]
type Model = native::NativeModel;
#[cfg(not(feature = "native-bekko"))]
struct Model;

pub struct EmbeddingService {
    cache: Arc<lifecycle::ModelCache<Model>>,
    admission: Arc<Semaphore>,
}
impl Default for EmbeddingService {
    fn default() -> Self {
        Self {
            cache: lifecycle::ModelCache::new(),
            admission: Arc::new(Semaphore::new(1)),
        }
    }
}
impl Drop for EmbeddingService {
    fn drop(&mut self) {
        self.cache.shutdown();
    }
}
impl EmbeddingService {
    /// Explicit, local identity inspection for index generation creation. No
    /// ONNX session or runtime is loaded, and no database transaction is held.
    pub async fn inspect_identity(&self, config: BekkoConfig) -> Result<ModelIdentity> {
        if !config.enabled {
            return Err(EmbeddingError::new(
                ErrorKind::Disabled,
                "native embedding is disabled",
            ));
        }
        config.validate()?;
        #[cfg(not(feature = "native-bekko"))]
        {
            let _ = config;
            Err(EmbeddingError::new(
                ErrorKind::FeatureUnavailable,
                "build with native-bekko",
            ))
        }
        #[cfg(feature = "native-bekko")]
        tokio::task::spawn_blocking(move || artifacts::inspect(&config))
            .await
            .map_err(|_| EmbeddingError::new(ErrorKind::Artifact, "identity worker failed"))?
    }

    /// Release a resident session before an indexing job relinquishes the
    /// process-level work permit. Actual destruction happens off Tokio workers.
    pub async fn unload(&self) -> Result<()> {
        let permit =
            self.admission.clone().acquire_owned().await.map_err(|_| {
                EmbeddingError::new(ErrorKind::Shutdown, "embedding service closed")
            })?;
        let cache = self.cache.clone();
        tokio::task::spawn_blocking(move || {
            let _permit = permit;
            cache.clear();
        })
        .await
        .map_err(|_| EmbeddingError::new(ErrorKind::Inference, "unload worker failed"))
    }
}
impl EmbeddingProvider for EmbeddingService {
    async fn embed_batch(&self, config: BekkoConfig, texts: Vec<String>) -> Result<EmbeddingBatch> {
        let call_started = Instant::now();
        // One admitted blocking task per workspace, not an unbounded blocking
        // pool of tasks waiting on the session mutex.
        let permit =
            self.admission.clone().acquire_owned().await.map_err(|_| {
                EmbeddingError::new(ErrorKind::Shutdown, "embedding service closed")
            })?;
        let cache = self.cache.clone();
        let mut batch = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                embed_blocking(&cache, &config, &texts)
            }))
            .unwrap_or_else(|_| {
                Err(EmbeddingError::new(
                    ErrorKind::Inference,
                    "native embedding worker panicked; session discarded",
                ))
            });
            if let Err(error) = &result {
                cache.invalidate(error);
            }
            result
        })
        .await
        .map_err(|_| EmbeddingError::new(ErrorKind::Inference, "embedding worker failed"))??;
        batch.timings.total_ms = call_started.elapsed().as_secs_f64() * 1000.0;
        Ok(batch)
    }
    fn diagnostics(&self) -> RuntimeDiagnostics {
        self.cache.diagnostics()
    }
}

fn embed_blocking(
    cache: &Arc<lifecycle::ModelCache<Model>>,
    config: &BekkoConfig,
    texts: &[String],
) -> Result<EmbeddingBatch> {
    let started = Instant::now();
    if !config.enabled {
        return Err(EmbeddingError::new(
            ErrorKind::Disabled,
            "native embedding is disabled",
        ));
    }
    config.validate()?;
    if texts.is_empty()
        || texts.len() > 64
        || texts.iter().any(|s| s.len() > 65536)
        || texts.iter().map(String::len).sum::<usize>() > 1024 * 1024
    {
        return Err(EmbeddingError::new(
            ErrorKind::InvalidInput,
            "expected 1..=64 texts, at most 64 KiB each and 1 MiB total",
        ));
    }
    #[cfg(not(feature = "native-bekko"))]
    {
        let _ = (cache, started);
        Err(EmbeddingError::new(
            ErrorKind::FeatureUnavailable,
            "build with native-bekko to enable native inference",
        ))
    }
    #[cfg(feature = "native-bekko")]
    {
        let identity = artifacts::inspect(config)?;
        // Verify the binding even when reusing a session. A replaced runtime
        // must never silently continue under a newly reported file identity.
        let _runtime = native::environment(config)?;
        let artifact_validation_ms = started.elapsed().as_secs_f64() * 1000.0;
        let key = format!(
            "{}|threads={}|runtime={}",
            identity.fingerprint,
            config.threads,
            config.runtime_library.display()
        );
        let run = cache.with_model(
            &key,
            std::time::Duration::from_secs(config.keep_warm_seconds),
            || native::load(config, &identity),
            |model| native::infer(model, texts),
        )?;
        Ok(EmbeddingBatch {
            identity,
            vectors: run.value,
            timings: EmbeddingTimings {
                artifact_validation_ms,
                model_load_ms: run.load_ms,
                inference_ms: run.infer_ms,
                total_ms: started.elapsed().as_secs_f64() * 1000.0,
                reused_session: run.reused,
            },
        })
    }
}

#[cfg(test)]
mod tests;
