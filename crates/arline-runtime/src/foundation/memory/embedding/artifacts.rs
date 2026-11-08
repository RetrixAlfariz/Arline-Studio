#![cfg_attr(not(feature = "native-bekko"), allow(dead_code))]
use super::{BekkoConfig, EmbeddingError, ErrorKind, Result, DIMENSIONS};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{fs::File, io::Read, path::Path};

pub const MODEL_ID: &str = "hotchpotch/bekko-embedding-v1-a8m";
pub const REVISION: &str = "c721113d59a1d91b447450324f51c4b3332c924a";
pub(super) const FILES: [&str; 6] = [
    "onnx/model.onnx",
    "tokenizer.json",
    "config.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "1_Pooling/config.json",
];
const MANIFEST: &str = include_str!("../../../../tests/fixtures/bekko-artifacts.json");

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct ArtifactDigest {
    pub path: String,
    pub size: u64,
    pub sha256: String,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct ModelIdentity {
    pub backend: String,
    pub model: String,
    pub revision: String,
    pub dimensions: usize,
    pub max_tokens: usize,
    pub pooling: String,
    pub fingerprint: String,
    pub artifacts: Vec<ArtifactDigest>,
    pub integrity_verified: bool,
    pub provenance_authenticated: bool,
}
fn invalid(message: impl Into<String>) -> EmbeddingError {
    EmbeddingError::new(ErrorKind::Artifact, message)
}

pub(super) fn read_file(dir: &Path, rel: &str) -> Result<Vec<u8>> {
    let file = File::open(dir.join(rel))
        .map_err(|_| invalid(format!("missing or unreadable model artifact: {rel}")))?;
    let size = file
        .metadata()
        .map_err(|_| invalid(format!("cannot inspect {rel}")))?;
    let limit = if rel == FILES[0] {
        512 * 1024 * 1024
    } else if rel == FILES[1] {
        64 * 1024 * 1024
    } else {
        1024 * 1024
    };
    if !size.is_file() || size.len() == 0 || size.len() > limit {
        return Err(invalid(format!(
            "empty, non-file or oversized artifact: {rel}"
        )));
    }
    let mut bytes = Vec::with_capacity(size.len() as usize);
    file.take(limit + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| invalid(format!("cannot read {rel}")))?;
    if bytes.len() as u64 != size.len() {
        return Err(invalid(format!("artifact changed while reading: {rel}")));
    }
    Ok(bytes)
}

/// Contents are hashed on every explicit native operation, never from lexical
/// retrieval or cheap runtime status. Size/mtime alone cannot identify a model.
pub(super) fn digest_file(path: &Path, max: u64) -> Result<(u64, String)> {
    let mut file =
        File::open(path).map_err(|_| invalid("missing or unreadable artifact/runtime file"))?;
    let meta = file
        .metadata()
        .map_err(|_| invalid("cannot inspect artifact/runtime file"))?;
    if !meta.is_file() || meta.len() == 0 || meta.len() > max {
        return Err(invalid(
            "empty, non-file or oversized artifact/runtime file",
        ));
    }
    let mut hash = Sha256::new();
    let mut buffer = vec![0; 1024 * 1024];
    let mut count = 0;
    loop {
        let n = file
            .read(&mut buffer)
            .map_err(|_| invalid("artifact/runtime read failed"))?;
        if n == 0 {
            break;
        }
        count += n as u64;
        if count > max || count > meta.len() {
            return Err(invalid("artifact changed during hashing"));
        }
        hash.update(&buffer[..n]);
    }
    if count != meta.len() {
        return Err(invalid("artifact changed during hashing"));
    }
    Ok((count, format!("{:x}", hash.finalize())))
}

pub(super) fn inspect(config: &BekkoConfig) -> Result<ModelIdentity> {
    let mut artifacts = Vec::new();
    for rel in FILES {
        let max = if rel == FILES[0] {
            512 * 1024 * 1024
        } else if rel == FILES[1] {
            64 * 1024 * 1024
        } else {
            1024 * 1024
        };
        let (size, sha256) = digest_file(&config.model_dir.join(rel), max)?;
        artifacts.push(ArtifactDigest {
            path: rel.into(),
            size,
            sha256,
        });
    }
    let pinned: serde_json::Value =
        serde_json::from_str(MANIFEST).map_err(|_| invalid("invalid built-in Bekko manifest"))?;
    for actual in &artifacts {
        let expected = pinned["files"]
            .as_array()
            .and_then(|files| files.iter().find(|f| f["path"] == actual.path))
            .ok_or_else(|| invalid("incomplete built-in Bekko manifest"))?;
        if expected["sha256"] != actual.sha256 || expected["size"] != actual.size {
            return Err(invalid(format!(
                "Bekko artifact differs from pinned official default: {}",
                actual.path
            )));
        }
    }
    validate_metadata(&config.model_dir)?;
    let contract = serde_json::json!({"backend":"native_bekko_onnx-v1","model":MODEL_ID,"dimensions":DIMENSIONS,"max_tokens":config.max_tokens,"pooling":"masked_mean_then_l2","prefixes":["",""],"implementation":"fastembed-7.5.0/tokenizers-0.23.2/ort-1.27.0","artifacts":artifacts});
    Ok(ModelIdentity {
        backend: "native_bekko_onnx".into(),
        model: MODEL_ID.into(),
        revision: REVISION.into(),
        dimensions: DIMENSIONS,
        max_tokens: config.max_tokens,
        pooling: "masked_mean_then_l2".into(),
        fingerprint: format!("sha256:{:x}", Sha256::digest(contract.to_string())),
        artifacts,
        integrity_verified: true,
        provenance_authenticated: false,
    })
}

pub(super) fn validate_metadata(dir: &Path) -> Result<()> {
    let json = |rel: &str| -> Result<serde_json::Value> {
        serde_json::from_slice(&read_file(dir, rel)?)
            .map_err(|_| invalid(format!("malformed model JSON: {rel}")))
    };
    let model = json("config.json")?;
    let pooling = json("1_Pooling/config.json")?;
    if model["hidden_size"] != DIMENSIONS
        || model["model_type"] != "modernbert"
        || model["pad_token_id"] != 0
    {
        return Err(invalid("incompatible Bekko model configuration"));
    }
    if pooling["word_embedding_dimension"] != DIMENSIONS
        || pooling["pooling_mode_mean_tokens"] != true
        || [
            "pooling_mode_cls_token",
            "pooling_mode_max_tokens",
            "pooling_mode_mean_sqrt_len_tokens",
            "pooling_mode_weightedmean_tokens",
            "pooling_mode_lasttoken",
        ]
        .iter()
        .any(|k| pooling[*k] != false)
    {
        return Err(invalid(
            "Bekko requires only masked mean pooling with 384 dimensions",
        ));
    }
    let tokenizer = json("tokenizer_config.json")?;
    if tokenizer["model_max_length"]
        .as_u64()
        .is_none_or(|n| n < 512)
        || !json("special_tokens_map.json")?.is_object()
    {
        return Err(invalid("incompatible tokenizer metadata"));
    }
    Ok(())
}

pub(super) fn snapshot(config: &BekkoConfig, identity: &ModelIdentity) -> Result<Vec<Vec<u8>>> {
    let mut files = Vec::new();
    for expected in &identity.artifacts {
        let bytes = read_file(&config.model_dir, &expected.path)?;
        if bytes.len() as u64 != expected.size
            || format!("{:x}", Sha256::digest(&bytes)) != expected.sha256
        {
            return Err(invalid(
                "model artifacts changed before session load; retry",
            ));
        }
        files.push(bytes);
    }
    Ok(files)
}
