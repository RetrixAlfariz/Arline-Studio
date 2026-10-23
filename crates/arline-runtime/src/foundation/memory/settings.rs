//! Memory configuration projection matching `src.memory.config.MemoryConfig`.

use crate::config::RuntimeConfig;
use serde_json::{json, Value};

fn bool_value(config: &RuntimeConfig, key: &str, default: bool) -> bool {
    config.bool(key, default)
}
fn usize_value(config: &RuntimeConfig, key: &str, default: usize) -> usize {
    config.u64(key, default as u64) as usize
}
fn float_value(config: &RuntimeConfig, key: &str, default: f64) -> f64 {
    config.f64(key, default)
}
fn string_value(config: &RuntimeConfig, key: &str, default: &str) -> String {
    config.str(key, default)
}

/// Return the stable JSON settings shape consumed by memory status and gates.
/// Nested memory.embedding/reranker values take precedence over the legacy
/// `[memory_embedding]` and `[memory_reranker]` tables.
pub fn settings(config: &RuntimeConfig) -> Value {
    let embedding = |key: &str, legacy: &str| {
        if config.value(key).is_some() {
            key.to_owned()
        } else {
            legacy.to_owned()
        }
    };
    let e = |field: &str| {
        embedding(
            &format!("memory.embedding.{field}"),
            &format!("memory_embedding.{field}"),
        )
    };
    let r = |field: &str| {
        embedding(
            &format!("memory.reranker.{field}"),
            &format!("memory_reranker.{field}"),
        )
    };
    let dense = bool_value(
        config,
        "memory.dense_enabled",
        bool_value(config, &e("enabled"), false),
    );
    json!({
        "enabled": bool_value(config, "memory.enabled", true),
        "fts_enabled": bool_value(config, "memory.fts_enabled", true),
        "dense_enabled": dense,
        "automatic_context": bool_value(config, "memory.automatic_context", true),
        "default_lens": string_value(config, "memory.default_lens", "scene"),
        "chunk_chars": usize_value(config, "memory.chunk_chars", 1800).max(400),
        "chunk_overlap_chars": usize_value(config, "memory.chunk_overlap_chars", 180),
        "max_candidates": usize_value(config, "memory.max_candidates", 60).max(8),
        "final_k": usize_value(config, "memory.final_k", 12).max(1),
        "max_per_source": usize_value(config, "memory.max_per_source", 2).max(1),
        "rrf_k": usize_value(config, "memory.rrf_k", 60).max(1),
        "trace_enabled": bool_value(config, "memory.trace_enabled", true),
        "max_pack_tokens": usize_value(config, "memory.max_pack_tokens", 4096),
        "embedding": {
            "enabled": bool_value(config, &e("enabled"), dense),
            "provider": string_value(config, &e("provider"), "lmstudio"),
            "model": string_value(config, &e("model"), "text-embedding-bge-m3"),
            "dimension": usize_value(config, &e("dimension"), 1024).max(1),
            "query_prefix": string_value(config, &e("query_prefix"), ""),
            "passage_prefix": string_value(config, &e("passage_prefix"), ""),
            "batch_size": usize_value(config, &e("batch_size"), 32).max(1),
            "timeout_seconds": float_value(config, &e("timeout_seconds"), 120.0).max(1.0)
        },
        "reranker": {
            "enabled": bool_value(config, &r("enabled"), false),
            "provider": string_value(config, &r("provider"), "disabled"),
            "model": string_value(config, &r("model"), "Qwen/Qwen3-Reranker-0.6B"),
            "top_k_input": usize_value(config, &r("top_k_input"), 20).max(1),
            "top_k_output": usize_value(config, &r("top_k_output"), 8).max(1)
        }
    })
}

#[cfg(test)]
mod tests {
    use super::settings;
    use crate::config::RuntimeConfig;
    use std::fs;

    #[test]
    fn defaults_match_python_memory_config() {
        let dir = tempfile::tempdir().unwrap();
        let config =
            RuntimeConfig::create_default(dir.path().join("runtime.toml"), dir.path()).unwrap();
        let value = settings(&config);
        assert_eq!(value["chunk_chars"], 1800);
        assert_eq!(value["embedding"]["model"], "text-embedding-bge-m3");
        assert_eq!(value["reranker"]["top_k_output"], 8);
    }

    #[test]
    fn legacy_tables_are_used_when_nested_memory_values_are_absent() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("runtime.toml");
        fs::write(&path, "[memory]\nenabled=true\n[memory_embedding]\nenabled=true\nmodel='legacy-embed'\ndimension=768\n[memory_reranker]\nenabled=true\ntop_k_output=3\n").unwrap();
        let config = RuntimeConfig::load(&path, dir.path()).unwrap();
        let value = settings(&config);
        assert_eq!(value["embedding"]["model"], "legacy-embed");
        assert_eq!(value["embedding"]["dimension"], 768);
        assert_eq!(value["reranker"]["top_k_output"], 3);
    }
}
