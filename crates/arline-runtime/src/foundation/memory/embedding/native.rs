//! FastEmbed pooling/tokenization follows Verithen's qualified native adapter.
//! Only CPU execution is compiled; no Hugging Face hub/download feature exists.
use super::{artifacts, BekkoConfig, EmbeddingError, ErrorKind, ModelIdentity, Result, DIMENSIONS};
use fastembed::{
    InitOptionsUserDefined, Pooling, TextEmbedding, TokenizerFiles, UserDefinedEmbeddingModel,
};
use std::{
    ffi::CStr,
    path::PathBuf,
    sync::{Mutex, OnceLock},
};

pub(super) const RUNTIME_VERSION: &str = "1.27.0";
pub(super) struct NativeModel {
    embedding: TextEmbedding,
    _residency: tokio::sync::OwnedSemaphorePermit,
}
// A residency limit, not merely an inference limit: an idle AppState must not
// let another workspace allocate a second >650-MiB initialization peak.
static RESIDENCY: OnceLock<std::sync::Arc<tokio::sync::Semaphore>> = OnceLock::new();
struct RuntimeBinding {
    path: PathBuf,
    sha256: String,
    environment: Option<ort::environment::Environment>,
    // Keep the securely preloaded library resident. ORT itself also retains its
    // binding for the life of the process; model eviction cannot replace it.
    _library: libloading::Library,
}
static RUNTIME: OnceLock<Mutex<Option<RuntimeBinding>>> = OnceLock::new();
fn runtime_error(message: impl Into<String>) -> EmbeddingError {
    EmbeddingError::new(ErrorKind::Runtime, message)
}

pub(super) fn check_binding(
    bound_path: &std::path::Path,
    bound_digest: &str,
    path: &std::path::Path,
    digest: &str,
) -> Result<()> {
    if bound_path != path || bound_digest != digest {
        return Err(runtime_error("ONNX Runtime path/content changed after binding; restart Arline to replace the runtime"));
    }
    Ok(())
}

pub(super) fn environment(config: &BekkoConfig) -> Result<ort::environment::Environment> {
    let path = config.runtime_library.canonicalize().map_err(|_| {
        runtime_error("ONNX Runtime unavailable at configured/executable-adjacent path")
    })?;
    let (_, digest) = artifacts::digest_file(&path, 128 * 1024 * 1024)
        .map_err(|_| runtime_error("invalid ONNX Runtime library file"))?;
    let mut slot = RUNTIME
        .get_or_init(|| Mutex::new(None))
        .lock()
        .map_err(|_| runtime_error("ONNX Runtime lock poisoned; restart required"))?;
    if let Some(bound) = slot.as_ref() {
        check_binding(&bound.path, &bound.sha256, &path, &digest)?;
    } else {
        // SAFETY: Only explicitly provisioned, trusted native code is loaded.
        // Windows restricts dependency resolution to the DLL directory and
        // default trusted system/application directories, excluding the CWD.
        #[cfg(windows)]
        let library: libloading::Library =
            unsafe { libloading::os::windows::Library::load_with_flags(&path, 0x100 | 0x1000) }
                .map_err(|_| runtime_error("cannot load ONNX Runtime CPU dependencies"))?
                .into();
        #[cfg(not(windows))]
        let library = unsafe { libloading::Library::new(&path) }
            .map_err(|_| runtime_error("cannot load ONNX Runtime CPU dependencies"))?;
        // SAFETY: OrtGetApiBase is ONNX Runtime's stable C entrypoint. Check
        // pointers and exact version before passing control to the ort wrapper.
        let version = unsafe {
            let getter: libloading::Symbol<unsafe extern "C" fn() -> *const ort::sys::OrtApiBase> =
                library
                    .get(b"OrtGetApiBase")
                    .map_err(|_| runtime_error("library does not export OrtGetApiBase"))?;
            let base = getter();
            if base.is_null() {
                return Err(runtime_error("ONNX Runtime returned null API base"));
            }
            let raw = ((*base).GetVersionString)();
            if raw.is_null() {
                return Err(runtime_error("ONNX Runtime returned null version"));
            }
            CStr::from_ptr(raw)
                .to_str()
                .map_err(|_| runtime_error("invalid ONNX Runtime version"))?
                .to_owned()
        };
        if version != RUNTIME_VERSION {
            return Err(runtime_error(format!(
                "requires ONNX Runtime CPU {RUNTIME_VERSION}; got {version}"
            )));
        }
        *slot = Some(RuntimeBinding {
            path: path.clone(),
            sha256: digest,
            environment: None,
            _library: library,
        });
    }
    let bound = slot.as_mut().expect("runtime bound");
    if bound.environment.is_none() {
        bound.environment = Some(
            ort::init_from(&path)
                .map_err(|_| runtime_error("ONNX Runtime API initialization failed"))?
                .with_telemetry(false)
                .build()
                .map_err(|_| runtime_error("ONNX Runtime environment initialization failed"))?,
        );
    }
    Ok(bound
        .environment
        .as_ref()
        .expect("environment initialized")
        .clone())
}

pub(super) fn load(config: &BekkoConfig, identity: &ModelIdentity) -> Result<NativeModel> {
    let residency=RESIDENCY.get_or_init(||std::sync::Arc::new(tokio::sync::Semaphore::new(1))).clone().try_acquire_owned()
        .map_err(|_|EmbeddingError::new(ErrorKind::ResourceBusy,"another AppState owns the native model residency slot; unload it or retry after eviction"))?;
    let environment = environment(config)?;
    let mut files = artifacts::snapshot(config, identity)?;
    let tokenizer = TokenizerFiles {
        tokenizer_file: std::mem::take(&mut files[1]),
        config_file: std::mem::take(&mut files[2]),
        tokenizer_config_file: std::mem::take(&mut files[3]),
        special_tokens_map_file: std::mem::take(&mut files[4]),
    };
    let model = UserDefinedEmbeddingModel::new(std::mem::take(&mut files[0]), tokenizer)
        .with_pooling(Pooling::Mean);
    let options = InitOptionsUserDefined::new()
        .with_environment(environment)
        .with_max_length(config.max_tokens)
        .with_intra_threads(config.threads)
        .with_session_config("session.intra_op.allow_spinning", "0")
        .with_session_config("session.inter_op.allow_spinning", "0");
    let embedding = TextEmbedding::try_new_from_user_defined(model, options).map_err(|_| {
        EmbeddingError::new(
            ErrorKind::Inference,
            "Bekko tokenizer/session initialization failed",
        )
    })?;
    Ok(NativeModel {
        embedding,
        _residency: residency,
    })
}
pub(super) fn infer(model: &mut NativeModel, texts: &[String]) -> Result<Vec<Vec<f32>>> {
    let mut vectors = model
        .embedding
        .embed(texts, Some(16))
        .map_err(|_| EmbeddingError::new(ErrorKind::Inference, "Bekko CPU inference failed"))?;
    if vectors.len() != texts.len() {
        return Err(EmbeddingError::new(
            ErrorKind::Inference,
            "embedding result count mismatch",
        ));
    }
    for vector in &mut vectors {
        if vector.len() != DIMENSIONS || vector.iter().any(|v| !v.is_finite()) {
            return Err(EmbeddingError::new(
                ErrorKind::Inference,
                "invalid embedding dimensions/values",
            ));
        }
        let norm = vector
            .iter()
            .map(|v| f64::from(*v).powi(2))
            .sum::<f64>()
            .sqrt();
        if !norm.is_finite() || norm <= f64::EPSILON {
            return Err(EmbeddingError::new(
                ErrorKind::Inference,
                "embedding has zero/nonfinite norm",
            ));
        }
        for value in vector {
            *value = (f64::from(*value) / norm) as f32;
        }
    }
    Ok(vectors)
}
