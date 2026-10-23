use crate::{ApiError, ApiResult};
use serde_json::{json, Value};
use std::{
    fs,
    path::{Path, PathBuf},
};

const DEFAULT_CONFIG: &str = r#"
[lmstudio]
base_url = "http://127.0.0.1:1234"
model = ""
api_key = ""
timeout_seconds = 600.0
auto_load = true
[model_load]
gpu_ratio = 1.0
context_length = 32768
flash_attention = true
[generation]
temperature = 0.8
top_p = 0.95
top_k = 40
min_p = 0.0
repeat_penalty = 1.05
reasoning = "off"
visible_output_tokens = 4096
reasoning_reserve_tokens = 4096
generation_mode = "single"
beat_count = 4
beat_tokens = 2048
total_story_target_tokens = 8192
[writer]
input_mode = "smart_hybrid"
system_prompt_file = "writer_system.txt"
[projection]
mode = "balanced"
[history]
database_path = "data/arline_history.db"
dataset_root = "data/datasets"
recent_limit = 100
continuity_turns = 2
continuity_chars = 12000
smart_hybrid_continuity = true
[workspace]
database_path = "data/arline_history.db"
context_enabled = true
mention_limit = 20
autosave_drafts = true
language_mode = "follow_prompt"
[ui]
host = "127.0.0.1"
port = 7860
[memory]
enabled = true
"#;

// Embedded at build time so the standalone app does not depend on repository files.
const DEFAULT_WRITER_PROMPT: &str = include_str!("../../../config/writer_system.txt");

#[derive(Clone, Debug)]
pub struct RuntimeConfig {
    pub raw: toml::Value,
    pub path: PathBuf,
    pub root: PathBuf,
    runtime_api_key: Option<String>,
}

impl RuntimeConfig {
    pub fn load(path: impl AsRef<Path>, root: impl AsRef<Path>) -> ApiResult<Self> {
        let root = root.as_ref().canonicalize()?;
        let path = absolute(&root, path.as_ref());
        let text = fs::read_to_string(&path)?;
        let raw: toml::Value = toml::from_str(&text)
            .map_err(|error| ApiError::bad_request(format!("Invalid runtime TOML: {error}")))?;
        let value = Self {
            raw,
            path,
            root,
            runtime_api_key: std::env::var("ARLINE_LMSTUDIO_API_KEY")
                .ok()
                .filter(|v| !v.is_empty()),
        };
        value.validate()?;
        Ok(value)
    }

    pub fn create_default(path: impl AsRef<Path>, root: impl AsRef<Path>) -> ApiResult<Self> {
        let path = path.as_ref();
        if !path.exists() {
            if let Some(parent) = path.parent() {
                fs::create_dir_all(parent)?;
            }
            // create_new prevents a concurrent launcher from replacing saved settings.
            use std::io::Write;
            let mut file = fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(path)?;
            file.write_all(DEFAULT_CONFIG.as_bytes())?;
            file.sync_all()?;
        }
        let prompt = path
            .parent()
            .unwrap_or(root.as_ref())
            .join("writer_system.txt");
        use std::io::Write;
        match fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&prompt)
        {
            Ok(mut file) => {
                file.write_all(DEFAULT_WRITER_PROMPT.as_bytes())?;
                file.sync_all()?;
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {}
            Err(error) => return Err(error.into()),
        }
        Self::load(path, root)
    }

    pub fn value(&self, key: &str) -> Option<&toml::Value> {
        key.split('.')
            .try_fold(&self.raw, |value, part| value.get(part))
    }
    pub fn str(&self, key: &str, default: &str) -> String {
        if key == "lmstudio.api_key" {
            if let Some(value) = &self.runtime_api_key {
                return value.clone();
            }
        }
        self.value(key)
            .and_then(toml::Value::as_str)
            .unwrap_or(default)
            .to_owned()
    }
    pub fn bool(&self, key: &str, default: bool) -> bool {
        self.value(key)
            .and_then(toml::Value::as_bool)
            .unwrap_or(default)
    }
    pub fn u64(&self, key: &str, default: u64) -> u64 {
        self.value(key)
            .and_then(toml::Value::as_integer)
            .and_then(|v| u64::try_from(v).ok())
            .unwrap_or(default)
    }
    pub fn f64(&self, key: &str, default: f64) -> f64 {
        self.value(key)
            .and_then(|value| {
                value
                    .as_float()
                    .or_else(|| value.as_integer().map(|v| v as f64))
            })
            .unwrap_or(default)
    }
    pub fn resolve(&self, value: &str) -> PathBuf {
        absolute(&self.root, &PathBuf::from(value.replace('\\', "/")))
    }
    pub fn database_path(&self) -> PathBuf {
        self.resolve(&self.str(
            "workspace.database_path",
            &self.str("history.database_path", "data/arline_history.db"),
        ))
    }
    pub fn prompt_path(&self) -> PathBuf {
        let value = PathBuf::from(self.str("writer.system_prompt_file", "writer_system.txt"));
        if value.is_absolute() {
            value
        } else {
            self.path.parent().unwrap_or(&self.root).join(value)
        }
    }
    pub fn set(&mut self, key: &str, value: toml::Value) -> ApiResult<()> {
        let parts: Vec<_> = key.split('.').collect();
        let mut current = &mut self.raw;
        for part in &parts[..parts.len() - 1] {
            let table = current
                .as_table_mut()
                .ok_or_else(|| ApiError::bad_request("Invalid configuration structure"))?;
            current = table
                .entry((*part).to_owned())
                .or_insert_with(|| toml::Value::Table(Default::default()));
        }
        current
            .as_table_mut()
            .ok_or_else(|| ApiError::bad_request("Invalid configuration table"))?
            .insert(parts[parts.len() - 1].to_owned(), value);
        Ok(())
    }
    fn validate(&self) -> ApiResult<()> {
        let url = url::Url::parse(&self.str("lmstudio.base_url", "http://127.0.0.1:1234"))
            .map_err(|_| ApiError::bad_request("LM Studio URL is invalid"))?;
        if !["http", "https"].contains(&url.scheme())
            || url.host_str().is_none()
            || !url.username().is_empty()
            || url.password().is_some()
        {
            return Err(ApiError::bad_request(
                "LM Studio must be an HTTP(S) URL without embedded credentials",
            ));
        }
        if !url.host_str().is_some_and(|host| {
            host.eq_ignore_ascii_case("localhost")
                || host
                    .trim_matches(['[', ']'])
                    .parse::<std::net::IpAddr>()
                    .is_ok_and(|ip| ip.is_loopback())
        }) {
            return Err(ApiError::bad_request(
                "This local runtime requires a loopback LM Studio URL",
            ));
        }
        if self.u64("generation.visible_output_tokens", 4096) == 0 {
            return Err(ApiError::bad_request("Response length must be positive"));
        }
        let gpu = self.f64("model_load.gpu_ratio", 1.0);
        if !gpu.is_finite() || !(0.0..=1.0).contains(&gpu) {
            return Err(ApiError::bad_request("gpu_ratio must be between 0 and 1"));
        }
        if self.u64("model_load.context_length", 32768) == 0 {
            return Err(ApiError::bad_request("context_length must be positive"));
        }
        if !["raw", "wcf", "wcf_raw", "smart_hybrid", "aif_core"]
            .contains(&self.str("writer.input_mode", "smart_hybrid").as_str())
        {
            return Err(ApiError::bad_request("Unsupported writer input mode"));
        }
        if !["off", "conservative", "balanced", "vivid"]
            .contains(&self.str("projection.mode", "balanced").as_str())
        {
            return Err(ApiError::bad_request("Unsupported projection mode"));
        }
        if !["single", "beats"].contains(&self.str("generation.generation_mode", "single").as_str())
        {
            return Err(ApiError::bad_request("Unsupported generation mode"));
        }
        if self.u64("generation.beat_count", 4) == 0
            || self.u64("generation.beat_tokens", 2048) == 0
        {
            return Err(ApiError::bad_request("Beat configuration must be positive"));
        }
        Ok(())
    }

    pub fn api_payload(&self) -> Value {
        json!({
            "studio_version":"1.2.5a1-rust", "runtime":"rust", "python_required":false,
            "server_url":self.str("lmstudio.base_url","http://127.0.0.1:1234"),
            "api_key_configured":!self.str("lmstudio.api_key","").is_empty(),
            "model":self.str("lmstudio.model",""), "auto_load":self.bool("lmstudio.auto_load",true), "gpu_ratio":self.f64("model_load.gpu_ratio",1.0), "flash_attention":self.bool("model_load.flash_attention",true),
            "context_length":self.u64("model_load.context_length",32768), "input_mode":self.str("writer.input_mode","smart_hybrid"),
            "reasoning":self.str("generation.reasoning","off"),"projection_mode":self.str("projection.mode","balanced"),
            "planning_enabled":self.bool("deliberation.enabled",false),
            "temperature":self.f64("generation.temperature",0.8),"top_p":self.f64("generation.top_p",0.95),"top_k":self.u64("generation.top_k",40),
            "min_p":self.f64("generation.min_p",0.0),"repeat_penalty":self.f64("generation.repeat_penalty",1.05),
            "visible_output_tokens":self.u64("generation.visible_output_tokens",4096),"reasoning_reserve_tokens":self.u64("generation.reasoning_reserve_tokens",4096),
            "api_max_output_tokens":self.u64("generation.visible_output_tokens",4096) + if self.str("generation.reasoning","off")=="off" {0} else {self.u64("generation.reasoning_reserve_tokens",4096)},
            "generation_mode":self.str("generation.generation_mode","single"),"beat_count":self.u64("generation.beat_count",4),"beat_tokens":self.u64("generation.beat_tokens",2048),"total_story_target_tokens":self.u64("generation.total_story_target_tokens",8192),
            "modes":{"smart_hybrid":"Smart Hybrid","raw":"Raw","wcf":"WCF","wcf_raw":"WCF + Raw","aif_core":"AIF Core"},
            "reasoning_modes":["off","on","low","medium","high"],"projection_modes":["off","conservative","balanced","vivid"],"generation_modes":["single","beats"],
            "workspace":self.raw.get("workspace").map(toml_json).unwrap_or(json!({})),
            "history":self.raw.get("history").map(toml_json).unwrap_or(json!({})),
            "memory":self.raw.get("memory").map(toml_json).unwrap_or(json!({"enabled":true})),
            "reasoning_guard":self.raw.get("reasoning_runtime").map(toml_json).unwrap_or(json!({})),
            "deliberation":self.raw.get("deliberation").map(toml_json).unwrap_or(json!({"enabled":false}))
        })
    }

    pub fn apply_settings(&mut self, payload: &Value) -> ApiResult<Value> {
        let object = payload
            .as_object()
            .ok_or_else(|| ApiError::bad_request("Settings must be an object"))?;
        let mut updated = self.clone();
        let fields = [
            ("server_url", "lmstudio.base_url"),
            ("model", "lmstudio.model"),
            ("auto_load", "lmstudio.auto_load"),
            ("gpu_ratio", "model_load.gpu_ratio"),
            ("context_length", "model_load.context_length"),
            ("flash_attention", "model_load.flash_attention"),
            ("input_mode", "writer.input_mode"),
            ("reasoning", "generation.reasoning"),
            ("projection_mode", "projection.mode"),
            ("temperature", "generation.temperature"),
            ("top_p", "generation.top_p"),
            ("top_k", "generation.top_k"),
            ("min_p", "generation.min_p"),
            ("repeat_penalty", "generation.repeat_penalty"),
            ("visible_output_tokens", "generation.visible_output_tokens"),
            (
                "reasoning_reserve_tokens",
                "generation.reasoning_reserve_tokens",
            ),
            ("generation_mode", "generation.generation_mode"),
            ("beat_count", "generation.beat_count"),
            ("beat_tokens", "generation.beat_tokens"),
            (
                "total_story_target_tokens",
                "generation.total_story_target_tokens",
            ),
            ("deliberation_enabled", "deliberation.enabled"),
            ("deliberation_max_tokens", "deliberation.max_tokens"),
            ("deliberation_temperature", "deliberation.temperature"),
            ("deliberation_alternatives", "deliberation.alternatives"),
        ];
        for (external, internal) in fields {
            if let Some(value) = object.get(external) {
                updated.set(internal, json_toml(value)?)?;
            }
        }
        if let Some(value) = object.get("api_key").and_then(Value::as_str) {
            updated.runtime_api_key = if value.is_empty() {
                None
            } else {
                Some(value.to_owned())
            };
        }
        for section in [
            "workspace",
            "history",
            "memory",
            "reasoning_runtime",
            "model_load",
            "projection",
            "context_budget",
            "deliberation",
        ] {
            if let Some(value) = object.get(section).and_then(Value::as_object) {
                for (key, value) in value {
                    if !value.is_null() {
                        updated.set(&format!("{section}.{key}"), json_toml(value)?)?;
                    }
                }
            }
        }
        updated.set("lmstudio.api_key", toml::Value::String(String::new()))?;
        updated.validate()?;
        let text = toml::to_string_pretty(&updated.raw)
            .map_err(|error| ApiError::internal(error.to_string()))?;
        if let Some(parent) = updated.path.parent() {
            fs::create_dir_all(parent)?;
        }
        let temp = updated
            .path
            .with_extension(format!("{}.tmp", uuid::Uuid::new_v4()));
        use std::io::Write;
        let mut file = fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temp)?;
        file.write_all(text.as_bytes())?;
        file.sync_all()?;
        drop(file);
        // Preserve a recoverable settings snapshot; never truncate the live config.
        let backup = updated.path.with_extension("toml.previous");
        if updated.path.is_file() {
            fs::copy(&updated.path, &backup)?;
        }
        #[cfg(windows)]
        if updated.path.exists() {
            fs::remove_file(&updated.path)?;
        }
        if let Err(error) = fs::rename(&temp, &updated.path) {
            if !updated.path.exists() && backup.is_file() {
                let _ = fs::copy(&backup, &updated.path);
            }
            return Err(error.into());
        }
        *self = updated;
        Ok(json!({"ok":true,"config":self.api_payload()}))
    }
}

fn absolute(root: &Path, value: &Path) -> PathBuf {
    if value.is_absolute() {
        value.to_owned()
    } else {
        root.join(value)
    }
}
fn toml_json(value: &toml::Value) -> Value {
    serde_json::to_value(value).unwrap_or(Value::Null)
}
fn json_toml(value: &Value) -> ApiResult<toml::Value> {
    toml::Value::try_from(value).map_err(|error| ApiError::bad_request(error.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn settings_retain_unknown_sections_and_keep_secrets_out_of_files() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("settings.toml");
        let mut config = RuntimeConfig::create_default(&path, temp.path()).unwrap();
        config
            .set("custom.keep_me", toml::Value::String("yes".into()))
            .unwrap();
        config.apply_settings(&json!({"model":"local-model","api_key":"private-test-key","visible_output_tokens":1024})).unwrap();
        assert_eq!(config.str("generation.visible_output_tokens", ""), "");
        assert_eq!(config.u64("generation.visible_output_tokens", 0), 1024);
        assert_eq!(config.str("custom.keep_me", ""), "yes");
        assert!(!fs::read_to_string(path)
            .unwrap()
            .contains("private-test-key"));
        assert_eq!(config.str("lmstudio.api_key", ""), "private-test-key");
        assert_eq!(config.api_payload()["api_key_configured"], true);
    }

    #[test]
    fn validation_rejects_unsupported_generation_and_context_values() {
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("settings.toml");
        let mut config = RuntimeConfig::create_default(&path, temp.path()).unwrap();
        config
            .set("writer.input_mode", toml::Value::String("bogus".into()))
            .unwrap();
        assert!(config.validate().is_err());
        config
            .set(
                "writer.input_mode",
                toml::Value::String("smart_hybrid".into()),
            )
            .unwrap();
        config
            .set("model_load.gpu_ratio", toml::Value::Float(1.5))
            .unwrap();
        assert!(config.validate().is_err());
    }

    #[test]
    fn public_planning_toggle_matches_saved_deliberation_setting() {
        let temp = tempfile::tempdir().unwrap();
        let mut config =
            RuntimeConfig::create_default(temp.path().join("settings.toml"), temp.path()).unwrap();
        assert_eq!(config.api_payload()["planning_enabled"], false);
        for enabled in [true, false] {
            config
                .set("deliberation.enabled", toml::Value::Boolean(enabled))
                .unwrap();
            assert_eq!(config.api_payload()["planning_enabled"], enabled);
        }
    }
}
