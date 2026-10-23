//! Cross-cutting workspace services used by the native runtime.
//!
//! This module intentionally keeps the foundation tables independent from the
//! domain stores.  Resources can therefore be hidden, aliased, grouped and
//! inspected without changing the schema owned by the world/document store.

use crate::store::Store;
use crate::{ApiError, ApiResult};
use axum::{
    body::Body,
    http::{header, StatusCode},
    response::Response,
};
use rusqlite::params;
use serde_json::{json, Map, Value};
use std::{
    collections::HashMap,
    fs,
    path::{Path, PathBuf},
};
use uuid::Uuid;

pub mod memory;

const FOUNDATION_SCHEMA: &str = r#"
CREATE TABLE IF NOT EXISTS resource_lifecycle(resource_type TEXT NOT NULL,resource_id TEXT NOT NULL,archived_at TEXT,trashed_at TEXT,previous_state_json TEXT NOT NULL DEFAULT '{}',updated_at TEXT NOT NULL,PRIMARY KEY(resource_type,resource_id));
CREATE TABLE IF NOT EXISTS resource_aliases(id TEXT PRIMARY KEY,resource_type TEXT NOT NULL,resource_id TEXT NOT NULL,alias TEXT NOT NULL,normalized_alias TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(resource_type,resource_id,normalized_alias));
CREATE INDEX IF NOT EXISTS idx_alias_lookup ON resource_aliases(normalized_alias,resource_type);
CREATE TABLE IF NOT EXISTS resource_media(id TEXT PRIMARY KEY,resource_type TEXT NOT NULL,resource_id TEXT NOT NULL,media_type TEXT NOT NULL DEFAULT 'image',kind TEXT NOT NULL DEFAULT 'reference',mime_type TEXT NOT NULL,original_name TEXT NOT NULL DEFAULT '',storage_path TEXT NOT NULL,caption TEXT NOT NULL DEFAULT '',description TEXT NOT NULL DEFAULT '',description_source TEXT NOT NULL DEFAULT 'manual',is_cover INTEGER NOT NULL DEFAULT 0,sort_order INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_resource_media_owner ON resource_media(resource_type,resource_id,sort_order,created_at);
CREATE TABLE IF NOT EXISTS workspace_collections(id TEXT PRIMARY KEY,scope_type TEXT NOT NULL DEFAULT 'world_bible',scope_id TEXT,name TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',icon TEXT NOT NULL DEFAULT '◇',sort_order INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS workspace_collection_links(collection_id TEXT NOT NULL,resource_type TEXT NOT NULL,resource_id TEXT NOT NULL,sort_order INTEGER NOT NULL DEFAULT 0,added_at TEXT NOT NULL,PRIMARY KEY(collection_id,resource_type,resource_id),FOREIGN KEY(collection_id) REFERENCES workspace_collections(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS saved_views(id TEXT PRIMARY KEY,scope_type TEXT NOT NULL DEFAULT 'world_bible',scope_id TEXT,name TEXT NOT NULL,resource_type TEXT NOT NULL DEFAULT 'all',query_json TEXT NOT NULL DEFAULT '{}',builtin INTEGER NOT NULL DEFAULT 0,sort_order INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS run_profiles(id TEXT PRIMARY KEY,project_id TEXT,name TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',profile_json TEXT NOT NULL DEFAULT '{}',builtin INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(project_id,name));
CREATE TABLE IF NOT EXISTS workspace_favorites(id TEXT PRIMARY KEY,project_id TEXT,resource_type TEXT NOT NULL,resource_id TEXT NOT NULL,label TEXT NOT NULL DEFAULT '',created_at TEXT NOT NULL,UNIQUE(project_id,resource_type,resource_id));
CREATE TABLE IF NOT EXISTS workspace_activity(id TEXT PRIMARY KEY,project_id TEXT,event_type TEXT NOT NULL,resource_type TEXT,resource_id TEXT,label TEXT NOT NULL DEFAULT '',detail_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_activity_project ON workspace_activity(project_id,created_at DESC);
CREATE TABLE IF NOT EXISTS workspace_issues(id TEXT PRIMARY KEY,project_id TEXT,world_id TEXT,branch_id TEXT,issue_type TEXT NOT NULL,severity TEXT NOT NULL DEFAULT 'warning',title TEXT NOT NULL,description TEXT NOT NULL DEFAULT '',resource_type TEXT,resource_id TEXT,status TEXT NOT NULL DEFAULT 'open',payload_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS workspace_jobs(id TEXT PRIMARY KEY,project_id TEXT,job_type TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'queued',progress REAL NOT NULL DEFAULT 0,message TEXT NOT NULL DEFAULT '',payload_json TEXT NOT NULL DEFAULT '{}',result_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS context_stack(id TEXT PRIMARY KEY,project_id TEXT,world_id TEXT,branch_id TEXT,scene_document_id TEXT,session_id TEXT,recipe_id TEXT,run_profile_id TEXT,references_json TEXT NOT NULL DEFAULT '[]',overrides_json TEXT NOT NULL DEFAULT '{}',updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS workspace_preferences(scope_type TEXT NOT NULL,scope_id TEXT NOT NULL,key TEXT NOT NULL,value_json TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(scope_type,scope_id,key));
CREATE TABLE IF NOT EXISTS user_profiles(id TEXT PRIMARY KEY,profile_json TEXT NOT NULL DEFAULT '{}',updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS presence_bindings(scope_type TEXT NOT NULL,scope_id TEXT NOT NULL,profile_json TEXT NOT NULL DEFAULT '{}',updated_at TEXT NOT NULL,PRIMARY KEY(scope_type,scope_id));
"#;

pub fn now() -> String {
    chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
}
pub fn new_id(prefix: &str) -> String {
    format!(
        "{}-{}-{}",
        prefix,
        chrono::Utc::now().format("%Y%m%dT%H%M%S"),
        &Uuid::new_v4().simple().to_string()[..8]
    )
}
fn dump(v: &Value) -> String {
    serde_json::to_string(v).unwrap_or_else(|_| "{}".into())
}
fn norm(s: &str) -> String {
    s.split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_lowercase()
}

#[derive(Clone)]
pub struct FoundationStore {
    pub store: Store,
}
impl FoundationStore {
    pub fn new(store: Store) -> ApiResult<Self> {
        store
            .connection()?
            .execute_batch(FOUNDATION_SCHEMA)
            .map_err(|e| ApiError::internal(e.to_string()))?;
        let f = Self { store };
        f.seed()?;
        Ok(f)
    }
    pub fn from_store(store: Store) -> Self {
        Self { store }
    }
    fn seed(&self) -> ApiResult<()> {
        let c = self.store.connection()?;
        let n = now();
        let views = [
            ("VIEW-WB-ALL", "All", "all"),
            ("VIEW-WB-CHAR", "Characters", "character"),
            ("VIEW-WB-LOC", "Locations", "location"),
            ("VIEW-WB-ITEM", "Items", "item"),
            ("VIEW-WB-ORG", "Organizations", "organization"),
            ("VIEW-WB-LORE", "Lore", "lore"),
        ];
        for (id, name, kind) in views {
            c.execute("INSERT OR IGNORE INTO saved_views(id,scope_type,name,resource_type,builtin,created_at,updated_at) VALUES(?,?,?,?,1,?,?)",params![id,"world_bible",name,kind,&n,&n]).map_err(|e|ApiError::internal(e.to_string()))?;
        }
        for (id, name, query, order) in [
            (
                "VIEW-WB-RECENT",
                "Recently changed",
                json!({"sort":"updated_at","direction":"desc"}),
                60,
            ),
            (
                "VIEW-WB-DETAIL",
                "Needs details",
                json!({"description_empty":true}),
                70,
            ),
        ] {
            c.execute("INSERT OR IGNORE INTO saved_views(id,scope_type,name,resource_type,query_json,builtin,sort_order,created_at,updated_at) VALUES(?,'world_bible',?,'all',?,1,?,?,?)",params![id,name,dump(&query),order,&n,&n])?;
        }
        for (id, name, description, recipe, reasoning, tokens, temp) in [
            (
                "PROFILE-STORY",
                "Story Writing",
                "Balanced long-form prose with scene, canon, and recent continuity.",
                "RECIPE-STORY",
                "off",
                4096,
                0.8,
            ),
            (
                "PROFILE-DIALOGUE",
                "Dialogue",
                "Character voice and relationship-heavy dialogue.",
                "RECIPE-DIALOGUE",
                "off",
                2048,
                0.85,
            ),
            (
                "PROFILE-LORE",
                "Lore Analysis",
                "Deeper world-state and canon inspection.",
                "RECIPE-LORE",
                "on",
                4096,
                0.55,
            ),
            (
                "PROFILE-FAST",
                "Fast Brainstorm",
                "Cheap, short exploratory generation.",
                "RECIPE-STORY",
                "off",
                1024,
                1.0,
            ),
        ] {
            let profile = json!({"context_recipe_id":recipe,"input_mode":"smart_hybrid","reasoning":reasoning,"visible_output_tokens":tokens,"temperature":temp,"projection_mode":"balanced","reasoning_reserve_tokens":4096,"top_p":0.95,"top_k":40,"min_p":0.0,"repeat_penalty":1.05,"generation_mode":"single","beat_count":4,"beat_tokens":2048,"total_story_target_tokens":8192});
            c.execute("INSERT OR IGNORE INTO run_profiles(id,project_id,name,description,profile_json,builtin,created_at,updated_at) VALUES(?,NULL,?,?,?,1,?,?)",params![id,name,description,dump(&profile),&n,&n])?;
        }
        Ok(())
    }
    fn row(&self, sql: &str, p: &[&dyn rusqlite::ToSql]) -> ApiResult<Option<Value>> {
        Ok(self.store.query(sql, p)?.into_iter().next())
    }
    pub fn lifecycle(&self, typ: &str, id: &str) -> ApiResult<Value> {
        Ok(self.row("SELECT * FROM resource_lifecycle WHERE resource_type=? AND resource_id=?",&[&typ,&id])?.unwrap_or(json!({"resource_type":typ,"resource_id":id,"archived_at":null,"trashed_at":null,"previous_state":{}})))
    }
    pub fn set_lifecycle(
        &self,
        typ: &str,
        id: &str,
        archived: Option<bool>,
        trashed: Option<bool>,
        previous: Option<&Value>,
    ) -> ApiResult<Value> {
        let old = self.lifecycle(typ, id)?;
        let a = archived
            .map(|v| if v { Some(now()) } else { None })
            .unwrap_or_else(|| {
                old.get("archived_at")
                    .and_then(Value::as_str)
                    .map(str::to_owned)
            });
        let t = trashed
            .map(|v| if v { Some(now()) } else { None })
            .unwrap_or_else(|| {
                old.get("trashed_at")
                    .and_then(Value::as_str)
                    .map(str::to_owned)
            });
        let prev = previous
            .map(dump)
            .unwrap_or_else(|| dump(old.get("previous_state").unwrap_or(&json!({}))));
        let c = self.store.connection()?;
        c.execute("INSERT INTO resource_lifecycle(resource_type,resource_id,archived_at,trashed_at,previous_state_json,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(resource_type,resource_id) DO UPDATE SET archived_at=excluded.archived_at,trashed_at=excluded.trashed_at,previous_state_json=excluded.previous_state_json,updated_at=excluded.updated_at",params![typ,id,a,t,prev,now()]).map_err(|e|ApiError::internal(e.to_string()))?;
        self.lifecycle(typ, id)
    }
    pub fn trash(&self, t: &str, id: &str, previous: Option<&Value>) -> ApiResult<Value> {
        self.set_lifecycle(t, id, None, Some(true), previous)
    }
    pub fn restore(&self, t: &str, id: &str) -> ApiResult<Value> {
        self.set_lifecycle(t, id, None, Some(false), None)
    }
    pub fn archive(&self, t: &str, id: &str, on: bool) -> ApiResult<Value> {
        self.set_lifecycle(t, id, Some(on), None, None)
    }
    pub fn is_hidden(
        &self,
        t: &str,
        id: &str,
        include_archived: bool,
        include_trashed: bool,
    ) -> ApiResult<bool> {
        let v = self.lifecycle(t, id)?;
        Ok(
            (!include_archived && v.get("archived_at").is_some_and(|x| !x.is_null()))
                || (!include_trashed && v.get("trashed_at").is_some_and(|x| !x.is_null())),
        )
    }
    pub fn list_trash(&self, limit: i64) -> ApiResult<Vec<Value>> {
        self.store.query("SELECT * FROM resource_lifecycle WHERE trashed_at IS NOT NULL ORDER BY trashed_at DESC LIMIT ?",&[&limit])
    }
    pub fn add_alias(&self, t: &str, id: &str, alias: &str) -> ApiResult<Value> {
        if alias.trim().is_empty() {
            return Err(ApiError::bad_request("alias must not be empty"));
        }
        let rid = new_id("ALIAS");
        let n = norm(alias);
        self.store.connection()?.execute("INSERT INTO resource_aliases(id,resource_type,resource_id,alias,normalized_alias,created_at) VALUES(?,?,?,?,?,?) ON CONFLICT(resource_type,resource_id,normalized_alias) DO UPDATE SET alias=excluded.alias",params![rid,t,id,alias.trim(),n,now()]).map_err(|e|ApiError::internal(e.to_string()))?;
        self.row("SELECT * FROM resource_aliases WHERE resource_type=? AND resource_id=? AND normalized_alias=?", &[&t,&id,&n])
            .map(|v| v.unwrap())
    }
    pub fn aliases(&self, t: &str, id: &str) -> ApiResult<Vec<Value>> {
        self.store.query("SELECT * FROM resource_aliases WHERE resource_type=? AND resource_id=? ORDER BY created_at",&[&t,&id])
    }
    pub fn list_aliases(&self, t: &str, id: &str) -> ApiResult<Vec<Value>> {
        self.aliases(t, id)
    }
    pub fn alias_matches(&self, q: &str, limit: i64) -> ApiResult<Vec<Value>> {
        let n = norm(q);
        self.store.query(
            "SELECT * FROM resource_aliases WHERE normalized_alias LIKE ? ORDER BY alias LIMIT ?",
            &[&format!("%{}%", n), &limit],
        )
    }
    pub fn delete_alias(&self, id: &str) -> ApiResult<bool> {
        Ok(self
            .store
            .connection()?
            .execute("DELETE FROM resource_aliases WHERE id=?", [id])
            .map_err(|e| ApiError::internal(e.to_string()))?
            > 0)
    }
    pub fn collection(&self, id: &str) -> ApiResult<Value> {
        let mut row = self
            .row("SELECT * FROM workspace_collections WHERE id=?", &[&id])?
            .ok_or_else(|| ApiError::not_found("collection not found"))?;
        row["links"]=json!(self.store.query("SELECT * FROM workspace_collection_links WHERE collection_id=? ORDER BY sort_order,added_at",&[&id])?);
        Ok(row)
    }
    pub fn get_collection(&self, id: &str) -> ApiResult<Value> {
        self.collection(id)
    }
    pub fn collections(&self, scope: &str, id: Option<&str>) -> ApiResult<Vec<Value>> {
        let rows=self.store.query("SELECT id FROM workspace_collections WHERE scope_type=? AND scope_id IS ? ORDER BY sort_order,name COLLATE NOCASE",&[&scope,&id])?;
        rows.iter()
            .map(|row| self.collection(row["id"].as_str().unwrap_or("")))
            .collect()
    }
    pub fn list_collections(&self, scope: &str, id: Option<&str>) -> ApiResult<Vec<Value>> {
        self.collections(scope, id)
    }
    pub fn create_collection(
        &self,
        name: &str,
        scope: &str,
        scope_id: Option<&str>,
        description: &str,
        icon: &str,
    ) -> ApiResult<Value> {
        let id = new_id("COLL");
        let n = now();
        self.store.connection()?.execute("INSERT INTO workspace_collections(id,scope_type,scope_id,name,description,icon,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",params![id,scope,scope_id,name,description,icon,n,n]).map_err(|e|ApiError::internal(e.to_string()))?;
        self.collection(&id)
    }
    pub fn collection_link(&self, cid: &str, t: &str, rid: &str, order: i64) -> ApiResult<Value> {
        self.collection(cid)?;
        let c = self.store.connection()?;
        c.execute("INSERT INTO workspace_collection_links(collection_id,resource_type,resource_id,sort_order,added_at) VALUES(?,?,?,?,?) ON CONFLICT(collection_id,resource_type,resource_id) DO UPDATE SET sort_order=excluded.sort_order",params![cid,t,rid,order,now()]).map_err(|e|ApiError::internal(e.to_string()))?;
        self.collection(cid)
    }
    pub fn delete_collection(&self, id: &str) -> ApiResult<bool> {
        Ok(self
            .store
            .connection()?
            .execute("DELETE FROM workspace_collections WHERE id=?", [id])
            .map_err(|e| ApiError::internal(e.to_string()))?
            > 0)
    }
    pub fn favorites(&self, project: Option<&str>) -> ApiResult<Vec<Value>> {
        match project{Some(p)=>self.store.query("SELECT * FROM workspace_favorites WHERE project_id=? OR project_id IS NULL ORDER BY created_at DESC",&[&p]),None=>self.store.query("SELECT * FROM workspace_favorites ORDER BY created_at DESC",&[])}
    }
    pub fn favorite(
        &self,
        project: Option<&str>,
        t: &str,
        rid: &str,
        label: &str,
    ) -> ApiResult<Value> {
        let id = new_id("FAV");
        let n = now();
        self.store.connection()?.execute("INSERT INTO workspace_favorites(id,project_id,resource_type,resource_id,label,created_at) VALUES(?,?,?,?,?,?) ON CONFLICT(project_id,resource_type,resource_id) DO UPDATE SET label=excluded.label",params![id,project,t,rid,label,n]).map_err(|e|ApiError::internal(e.to_string()))?;
        self.row("SELECT * FROM workspace_favorites WHERE project_id IS ? AND resource_type=? AND resource_id=?",&[&project,&t,&rid])?.ok_or_else(||ApiError::internal("favorite not readable"))
    }
    pub fn unfavorite(&self, p: Option<&str>, t: &str, id: &str) -> ApiResult<bool> {
        Ok(self.store.connection()?.execute("DELETE FROM workspace_favorites WHERE project_id IS ? AND resource_type=? AND resource_id=?",params![p,t,id]).map_err(|e|ApiError::internal(e.to_string()))?>0)
    }
    pub fn activity(&self, p: Option<&str>, limit: i64) -> ApiResult<Vec<Value>> {
        match p{Some(x)=>self.store.query("SELECT * FROM workspace_activity WHERE project_id=? OR project_id IS NULL ORDER BY created_at DESC LIMIT ?",&[&x,&limit]),None=>self.store.query("SELECT * FROM workspace_activity ORDER BY created_at DESC LIMIT ?",&[&limit])}
    }
    pub fn log_activity(
        &self,
        p: Option<&str>,
        event: &str,
        t: Option<&str>,
        id: Option<&str>,
        label: &str,
        detail: &Value,
    ) -> ApiResult<Value> {
        let rid = new_id("ACT");
        self.store.connection()?.execute("INSERT INTO workspace_activity(id,project_id,event_type,resource_type,resource_id,label,detail_json,created_at) VALUES(?,?,?,?,?,?,?,?)",params![rid,p,event,t,id,label,dump(detail),now()]).map_err(|e|ApiError::internal(e.to_string()))?;
        self.row("SELECT * FROM workspace_activity WHERE id=?", &[&rid])
            .map(|v| v.unwrap())
    }
    pub fn jobs(&self, p: Option<&str>, limit: i64) -> ApiResult<Vec<Value>> {
        match p {
            Some(x) => self.store.query(
                "SELECT * FROM workspace_jobs WHERE project_id=? ORDER BY updated_at DESC LIMIT ?",
                &[&x, &limit],
            ),
            None => self.store.query(
                "SELECT * FROM workspace_jobs ORDER BY updated_at DESC LIMIT ?",
                &[&limit],
            ),
        }
    }
    pub fn preferences(&self, scope: &str, id: &str) -> ApiResult<Value> {
        let rows = self.store.query(
            "SELECT key,value_json FROM workspace_preferences WHERE scope_type=? AND scope_id=?",
            &[&scope, &id],
        )?;
        let mut m = Map::new();
        for r in rows {
            if let Some(k) = r.get("key").and_then(Value::as_str) {
                m.insert(k.to_owned(), r.get("value").cloned().unwrap_or(Value::Null));
            }
        }
        Ok(Value::Object(m))
    }
    pub fn set_preference(&self, scope: &str, id: &str, key: &str, v: &Value) -> ApiResult<Value> {
        self.store.connection()?.execute("INSERT INTO workspace_preferences(scope_type,scope_id,key,value_json,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(scope_type,scope_id,key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at",params![scope,id,key,dump(v),now()]).map_err(|e|ApiError::internal(e.to_string()))?;
        self.preferences(scope, id)
    }
    pub fn saved_views(&self, scope: &str, id: Option<&str>) -> ApiResult<Vec<Value>> {
        match id{Some(v)=>self.store.query("SELECT * FROM saved_views WHERE scope_type=? AND scope_id=? ORDER BY sort_order,created_at",&[&scope,&v]),None=>self.store.query("SELECT * FROM saved_views WHERE scope_type=? ORDER BY sort_order,created_at",&[&scope])}
    }
    pub fn list_saved_views(&self, scope: &str, id: Option<&str>) -> ApiResult<Vec<Value>> {
        self.saved_views(scope, id)
    }
    pub fn save_view(
        &self,
        name: &str,
        scope: &str,
        id: Option<&str>,
        resource_type: &str,
        query: &Value,
    ) -> ApiResult<Value> {
        let rid = new_id("VIEW");
        let n = now();
        self.store.connection()?.execute("INSERT INTO saved_views(id,scope_type,scope_id,name,resource_type,query_json,builtin,created_at,updated_at) VALUES(?,?,?,?,?,?,0,?,?)",params![rid,scope,id,name,resource_type,dump(query),n,n]).map_err(|e|ApiError::internal(e.to_string()))?;
        self.row("SELECT * FROM saved_views WHERE id=?", &[&rid])
            .map(|v| v.unwrap())
    }
    pub fn run_profiles(&self, project: Option<&str>) -> ApiResult<Vec<Value>> {
        match project{Some(p)=>self.store.query("SELECT * FROM run_profiles WHERE project_id IS NULL OR project_id=? ORDER BY builtin DESC,name",&[&p]),None=>self.store.query("SELECT * FROM run_profiles WHERE project_id IS NULL ORDER BY builtin DESC,name",&[])}
    }
    pub fn list_run_profiles(&self, project: Option<&str>) -> ApiResult<Vec<Value>> {
        self.run_profiles(project)
    }
    pub fn save_run_profile(&self, p: &Value) -> ApiResult<Value> {
        let o = p
            .as_object()
            .ok_or_else(|| ApiError::bad_request("profile payload must be an object"))?;
        let id = o
            .get("id")
            .and_then(Value::as_str)
            .map(str::to_owned)
            .unwrap_or_else(|| new_id("PROFILE"));
        let n = now();
        let profile = o.get("profile").cloned().unwrap_or(json!({}));
        self.store.connection()?.execute("INSERT INTO run_profiles(id,project_id,name,description,profile_json,builtin,created_at,updated_at) VALUES(?,?,?, ?,?,0,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,description=excluded.description,profile_json=excluded.profile_json,updated_at=excluded.updated_at",params![id,o.get("project_id").and_then(Value::as_str),o.get("name").and_then(Value::as_str).unwrap_or("Custom"),o.get("description").and_then(Value::as_str).unwrap_or(""),dump(&profile),n,n]).map_err(|e|ApiError::internal(e.to_string()))?;
        self.row("SELECT * FROM run_profiles WHERE id=?", &[&id])
            .map(|v| v.unwrap())
    }
    pub fn delete_run_profile(&self, id: &str) -> ApiResult<bool> {
        Ok(self
            .store
            .connection()?
            .execute("DELETE FROM run_profiles WHERE id=? AND builtin=0", [id])
            .map_err(|e| ApiError::internal(e.to_string()))?
            > 0)
    }
    pub fn media(&self, t: Option<&str>, id: Option<&str>, cover: bool) -> ApiResult<Vec<Value>> {
        let mut sql = "SELECT * FROM resource_media WHERE 1=1".to_owned();
        let mut vals: Vec<String> = Vec::new();
        if let Some(v) = t {
            sql.push_str(" AND resource_type=?");
            vals.push(v.to_owned())
        }
        if let Some(v) = id {
            sql.push_str(" AND resource_id=?");
            vals.push(v.to_owned())
        }
        if cover {
            sql.push_str(" AND is_cover=1")
        }
        sql.push_str(" ORDER BY sort_order,created_at");
        let refs: Vec<&dyn rusqlite::ToSql> =
            vals.iter().map(|v| v as &dyn rusqlite::ToSql).collect();
        self.store.query(&sql, &refs)
    }
    pub fn list_media(
        &self,
        t: Option<&str>,
        id: Option<&str>,
        cover: bool,
    ) -> ApiResult<Vec<Value>> {
        self.media(t, id, cover)
    }
    fn media_root(&self) -> PathBuf {
        self.store
            .path
            .parent()
            .unwrap_or(Path::new("."))
            .join("media")
    }
    pub fn create_media(&self, p: &Value) -> ApiResult<Value> {
        use base64::Engine;
        let object = p
            .as_object()
            .ok_or_else(|| ApiError::bad_request("Media must be an object"))?;
        if object.contains_key("storage_path") {
            return Err(ApiError::bad_request(
                "Media storage paths are managed by Arline",
            ));
        }
        let data = object
            .get("data_url")
            .and_then(Value::as_str)
            .ok_or_else(|| ApiError::bad_request("media data_url is required"))?;
        let (metadata, encoded) = data
            .split_once(',')
            .ok_or_else(|| ApiError::bad_request("Invalid image data URL"))?;
        let mime = metadata
            .strip_prefix("data:")
            .and_then(|s| s.strip_suffix(";base64"))
            .ok_or_else(|| ApiError::bad_request("Expected a base64 image data URL"))?;
        if !matches!(
            mime,
            "image/png" | "image/jpeg" | "image/webp" | "image/gif"
        ) {
            return Err(ApiError::bad_request(
                "Supported images: PNG, JPEG, WebP, GIF",
            ));
        }
        if encoded.len() > 24 * 1024 * 1024 {
            return Err(ApiError::bad_request("Media exceeds 16 MiB"));
        }
        let bytes = base64::engine::general_purpose::STANDARD
            .decode(encoded)
            .map_err(|_| ApiError::bad_request("Invalid image base64"))?;
        if bytes.is_empty() || bytes.len() > 16 * 1024 * 1024 {
            return Err(ApiError::bad_request("Image must contain 1 byte to 16 MiB"));
        }
        let resource_type = object
            .get("resource_type")
            .and_then(Value::as_str)
            .unwrap_or("");
        let resource_id = object
            .get("resource_id")
            .and_then(Value::as_str)
            .unwrap_or("");
        let table = match resource_type {
            "world" => "worlds",
            "document" => "workspace_documents",
            "entity_family" => "entity_families",
            "entity_variant" => "entity_variants",
            _ => return Err(ApiError::bad_request("Invalid media owner type")),
        };
        if self.store.get(table, resource_id)?.is_none() {
            return Err(ApiError::not_found("Media owner not found"));
        }
        let root = self.media_root();
        fs::create_dir_all(&root)?;
        let id = new_id("MEDIA");
        let extension = match mime {
            "image/png" => "png",
            "image/jpeg" => "jpg",
            "image/webp" => "webp",
            "image/gif" => "gif",
            _ => "image",
        };
        let path = root.join(format!("{id}.{extension}"));
        let mut row = Map::new();
        for key in [
            "resource_type",
            "resource_id",
            "kind",
            "caption",
            "description",
            "description_source",
            "is_cover",
            "sort_order",
        ] {
            if let Some(v) = object.get(key) {
                row.insert(key.into(), v.clone());
            }
        }
        row.insert(
            "original_name".into(),
            json!(object
                .get("filename")
                .and_then(Value::as_str)
                .unwrap_or("image")),
        );
        row.insert("id".into(), json!(id));
        row.insert("mime_type".into(), json!(mime));
        row.insert("storage_path".into(), json!(path.to_string_lossy()));
        row.insert("created_at".into(), json!(now()));
        row.insert("updated_at".into(), json!(now()));
        fs::write(&path, bytes)?;
        let result = (|| -> ApiResult<Value> {
            let mut connection = self.store.connection()?;
            let transaction =
                connection.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
            if row.get("is_cover").and_then(Value::as_bool) == Some(true) {
                transaction.execute("UPDATE resource_media SET is_cover=0,updated_at=? WHERE resource_type=? AND resource_id=?",params![now(),resource_type,resource_id])?;
            }
            let filename = object
                .get("filename")
                .and_then(Value::as_str)
                .unwrap_or("image")
                .replace('\\', "/");
            let filename = filename
                .rsplit('/')
                .next()
                .unwrap_or("image")
                .chars()
                .take(240)
                .collect::<String>();
            transaction.execute("INSERT INTO resource_media(id,resource_type,resource_id,mime_type,original_name,storage_path,kind,caption,description,description_source,is_cover,sort_order,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",params![id,resource_type,resource_id,mime,filename,path.to_string_lossy(),object.get("kind").and_then(Value::as_str).unwrap_or("reference"),object.get("caption").and_then(Value::as_str).unwrap_or("").trim(),object.get("description").and_then(Value::as_str).unwrap_or("").trim(),object.get("description_source").and_then(Value::as_str).unwrap_or("manual"),object.get("is_cover").and_then(Value::as_bool).unwrap_or(false),object.get("sort_order").and_then(Value::as_i64).unwrap_or(0),now(),now()])?;
            transaction.commit()?;
            self.store
                .get("resource_media", &id)?
                .ok_or_else(|| ApiError::internal("Media was not saved"))
        })();
        match result {
            Ok(row) => Ok(public_media(row)),
            Err(error) => {
                let _ = fs::remove_file(path);
                Err(error)
            }
        }
    }
    pub fn update_media(&self, id: &str, p: &Value) -> ApiResult<Value> {
        let object = p
            .as_object()
            .ok_or_else(|| ApiError::bad_request("Media update must be an object"))?;
        let allowed = [
            "kind",
            "caption",
            "description",
            "description_source",
            "is_cover",
            "sort_order",
        ];
        if object.keys().any(|key| !allowed.contains(&key.as_str())) {
            return Err(ApiError::bad_request("Unsupported media update field"));
        }
        let mut current = self
            .store
            .get("resource_media", id)?
            .ok_or_else(|| ApiError::not_found("Media not found"))?;
        for (key, value) in object {
            if !value.is_null() {
                current[key] = value.clone();
            }
        }
        let mut connection = self.store.connection()?;
        let transaction =
            connection.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
        if object.get("is_cover").and_then(Value::as_bool) == Some(true) {
            transaction.execute("UPDATE resource_media SET is_cover=0,updated_at=? WHERE resource_type=? AND resource_id=?",params![now(),current["resource_type"].as_str(),current["resource_id"].as_str()])?;
        }
        transaction.execute("UPDATE resource_media SET kind=?,caption=?,description=?,description_source=?,is_cover=?,sort_order=?,updated_at=? WHERE id=?",params![current["kind"].as_str().unwrap_or("reference"),current["caption"].as_str().unwrap_or(""),current["description"].as_str().unwrap_or(""),current["description_source"].as_str().unwrap_or("manual"),current["is_cover"].as_bool().unwrap_or_else(||current["is_cover"].as_i64()==Some(1)),current["sort_order"].as_i64().unwrap_or(0),now(),id])?;
        transaction.commit()?;
        self.store
            .get("resource_media", id)?
            .map(public_media)
            .ok_or_else(|| ApiError::not_found("Media not found"))
    }
    pub fn delete_media(&self, id: &str) -> ApiResult<bool> {
        let row = self
            .store
            .get("resource_media", id)?
            .ok_or_else(|| ApiError::not_found("Media not found"))?;
        let root = self.media_root().canonicalize().ok();
        if let Some(path) = row
            .get("storage_path")
            .and_then(Value::as_str)
            .and_then(|p| Path::new(p).canonicalize().ok())
        {
            if !root.is_some_and(|root| path.starts_with(root)) {
                return Err(ApiError::bad_request(
                    "Media path is outside managed storage",
                ));
            }
            fs::remove_file(path)?;
        }
        self.store.delete("resource_media", id)
    }
    pub fn media_content(&self, id: &str) -> ApiResult<(Vec<u8>, String)> {
        let row = self
            .store
            .get("resource_media", id)?
            .ok_or_else(|| ApiError::not_found("Media not found"))?;
        let root = self
            .media_root()
            .canonicalize()
            .map_err(|_| ApiError::not_found("Media not found"))?;
        let path = Path::new(row["storage_path"].as_str().unwrap_or(""))
            .canonicalize()
            .map_err(|_| ApiError::not_found("Media not found"))?;
        if !path.starts_with(root) {
            return Err(ApiError::bad_request(
                "Media path is outside managed storage",
            ));
        }
        let mime = row["mime_type"]
            .as_str()
            .unwrap_or("application/octet-stream")
            .to_owned();
        Ok((fs::read(path)?, mime))
    }
    pub fn get_context(&self, id: &str) -> ApiResult<Value> {
        Ok(self
            .row("SELECT * FROM context_stack WHERE id=?", &[&id])?
            .unwrap_or(json!({"id":id,"project_id":null,"world_id":null,"branch_id":null,"scene_document_id":null,"session_id":null,"recipe_id":null,"run_profile_id":null,"references":[],"overrides":{},"updated_at":null})))
    }
    pub fn set_context(&self, id: &str, p: &Value) -> ApiResult<Value> {
        let mut row = p
            .as_object()
            .cloned()
            .ok_or_else(|| ApiError::bad_request("context payload must be an object"))?;
        row.remove("stack_id");
        row.retain(|key, _| {
            matches!(
                key.as_str(),
                "project_id"
                    | "world_id"
                    | "branch_id"
                    | "scene_document_id"
                    | "session_id"
                    | "recipe_id"
                    | "run_profile_id"
                    | "references"
                    | "overrides"
            )
        });
        for key in [
            "project_id",
            "world_id",
            "branch_id",
            "scene_document_id",
            "session_id",
            "recipe_id",
            "run_profile_id",
        ] {
            row.entry(key.to_owned()).or_insert(Value::Null);
        }
        row.entry("references".to_owned()).or_insert(json!([]));
        row.entry("overrides".to_owned()).or_insert(json!({}));
        row.insert("id".into(), json!(id));
        row.insert("updated_at".into(), json!(now()));
        if self.store.get("context_stack", id)?.is_some() {
            self.store.update("context_stack", id, Value::Object(row))
        } else {
            self.store.insert("context_stack", Value::Object(row))
        }
    }
    pub fn create_job(
        &self,
        typ: &str,
        project: Option<&str>,
        payload: &Value,
        message: &str,
    ) -> ApiResult<Value> {
        let id = new_id("JOB");
        let n = now();
        self.store.connection()?.execute("INSERT INTO workspace_jobs(id,project_id,job_type,status,progress,message,payload_json,result_json,created_at,updated_at) VALUES(?,?,?,'queued',0,?,?,'{}',?,?)",params![id,project,typ,message,dump(payload),n,n]).map_err(|e|ApiError::internal(e.to_string()))?;
        self.row("SELECT * FROM workspace_jobs WHERE id=?", &[&id])
            .map(|v| v.unwrap())
    }
    pub fn issue(&self, id: &str) -> ApiResult<Value> {
        self.row("SELECT * FROM workspace_issues WHERE id=?", &[&id])?
            .ok_or_else(|| ApiError::not_found("issue not found"))
    }
    pub fn get_issue(&self, id: &str) -> ApiResult<Value> {
        self.issue(id)
    }
    pub fn create_issue(&self, p: &Value) -> ApiResult<Value> {
        let o = p
            .as_object()
            .ok_or_else(|| ApiError::bad_request("issue payload must be an object"))?;
        let id = new_id("ISSUE");
        let n = now();
        self.store.connection()?.execute("INSERT INTO workspace_issues(id,project_id,world_id,branch_id,issue_type,severity,title,description,resource_type,resource_id,status,payload_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?, 'open',?,?,?)",params![id,o.get("project_id").and_then(Value::as_str),o.get("world_id").and_then(Value::as_str),o.get("branch_id").and_then(Value::as_str),o.get("issue_type").and_then(Value::as_str).unwrap_or("unknown"),o.get("severity").and_then(Value::as_str).unwrap_or("warning"),o.get("title").and_then(Value::as_str).unwrap_or("Issue"),o.get("description").and_then(Value::as_str).unwrap_or(""),o.get("resource_type").and_then(Value::as_str),o.get("resource_id").and_then(Value::as_str),dump(o.get("payload").unwrap_or(&json!({}))),n,n]).map_err(|e|ApiError::internal(e.to_string()))?;
        self.issue(&id)
    }
    pub fn resolve_issue(&self, id: &str, status: &str) -> ApiResult<Value> {
        let c = self.store.connection()?;
        if c.execute(
            "UPDATE workspace_issues SET status=?,updated_at=? WHERE id=?",
            params![status, now(), id],
        )
        .map_err(|e| ApiError::internal(e.to_string()))?
            == 0
        {
            return Err(ApiError::not_found("issue not found"));
        }
        self.issue(id)
    }
    pub fn user_profile(&self) -> ApiResult<Value> {
        if let Some(row) = self.row(
            "SELECT profile_json,updated_at FROM user_profiles WHERE id='default'",
            &[],
        )? {
            let mut p = row.get("profile").cloned().unwrap_or(json!({}));
            if let Some(o) = p.as_object_mut() {
                o.insert("id".into(), json!("default"));
                o.insert(
                    "updated_at".into(),
                    row.get("updated_at").cloned().unwrap_or(Value::Null),
                );
            }
            Ok(crate::profile::normalize(&p))
        } else {
            Ok(crate::profile::normalize(&json!({})))
        }
    }
    pub fn save_user_profile(&self, p: &Value) -> ApiResult<Value> {
        let mut p = crate::profile::normalize(p);
        if let Some(o) = p.as_object_mut() {
            o.remove("id");
            o.remove("updated_at");
        }
        let n = now();
        self.store.connection()?.execute("INSERT INTO user_profiles(id,profile_json,updated_at) VALUES('default',?,?) ON CONFLICT(id) DO UPDATE SET profile_json=excluded.profile_json,updated_at=excluded.updated_at",params![dump(&p),n]).map_err(|e|ApiError::internal(e.to_string()))?;
        self.user_profile()
    }
    pub fn presence_binding(&self, scope: &str, id: &str) -> ApiResult<Value> {
        if !matches!(scope, "world" | "branch") {
            return Err(ApiError::bad_request(
                "Presence scope must be world or branch",
            ));
        }
        Ok(self.row("SELECT profile_json,updated_at FROM presence_bindings WHERE scope_type=? AND scope_id=?",&[&scope,&id])?.map(|r|json!({"scope_type":scope,"scope_id":id,"profile":r.get("profile").cloned().unwrap_or(json!({})),"updated_at":r.get("updated_at").cloned().unwrap_or(Value::Null)})).unwrap_or(json!({"scope_type":scope,"scope_id":id,"profile":{},"updated_at":null})))
    }
    pub fn save_presence_binding(&self, scope: &str, id: &str, p: &Value) -> ApiResult<Value> {
        if !matches!(scope, "world" | "branch") {
            return Err(ApiError::bad_request(
                "Presence scope must be world or branch",
            ));
        }
        let n = now();
        self.store.connection()?.execute("INSERT INTO presence_bindings(scope_type,scope_id,profile_json,updated_at) VALUES(?,?,?,?) ON CONFLICT(scope_type,scope_id) DO UPDATE SET profile_json=excluded.profile_json,updated_at=excluded.updated_at",params![scope,id,dump(p),n]).map_err(|e|ApiError::internal(e.to_string()))?;
        self.presence_binding(scope, id)
    }
    pub fn extract_profile(&self, text: &str) -> Value {
        let mut fields = Vec::new();
        let clean = text.trim();
        for (key, label, pat, vis) in [
            (
                "preferred_name",
                "Preferred name",
                "dipanggil|called",
                "collaboration",
            ),
            ("full_name", "Full name", "nama saya|my name is", "private"),
        ] {
            if let Some(pos) = clean
                .to_lowercase()
                .find(pat.split('|').next().unwrap_or(""))
            {
                let start = pos + pat.split('|').next().unwrap_or("").len();
                let value = clean[start..]
                    .trim_matches(|c: char| c == ' ' || c == ':' || c == ',')
                    .split(['.', ','])
                    .next()
                    .unwrap_or("")
                    .trim();
                if !value.is_empty() {
                    fields.push(json!({"key":key,"label":label,"value":value,"visibility":vis,"confidence":0.98,"source":clean,"sensitive":false,"included":true}));
                }
            }
        }
        json!({"display_name":fields.iter().find(|x|x["key"]=="preferred_name").and_then(|x|x["value"].as_str()).unwrap_or(""),"fields":fields,"source_length":clean.len()})
    }
    pub fn extract_blueprint(&self, text: &str, current: &Value) -> Value {
        let mut out = current.as_object().cloned().unwrap_or_default();
        for key in [
            "wanted",
            "flexible",
            "suggested",
            "avoid",
            "open_questions",
            "narrative_desires",
            "relationship_intentions",
        ] {
            out.entry(key).or_insert_with(|| json!([]));
        }
        for clause in text
            .split([';', '\n'])
            .map(str::trim)
            .filter(|x| !x.is_empty())
        {
            let low = clause.to_lowercase();
            let key = if low.starts_with("avoid ")
                || low.starts_with("don't ")
                || low.starts_with("do not ")
            {
                "avoid"
            } else if low.starts_with("want ") || low.starts_with("i want ") {
                "wanted"
            } else if low.starts_with("open to ") || low.starts_with("maybe ") {
                "flexible"
            } else {
                "suggested"
            };
            if let Some(a) = out.get_mut(key).and_then(Value::as_array_mut) {
                a.push(json!(clause));
            }
        }
        Value::Object(out)
    }
    pub fn list_issues(
        &self,
        project: Option<&str>,
        status: Option<&str>,
        limit: i64,
    ) -> ApiResult<Vec<Value>> {
        match(project,status){(Some(p),Some(s))=>self.store.query("SELECT * FROM workspace_issues WHERE project_id=? AND status=? ORDER BY updated_at DESC LIMIT ?",&[&p,&s,&limit]),(Some(p),None)=>self.store.query("SELECT * FROM workspace_issues WHERE project_id=? ORDER BY updated_at DESC LIMIT ?",&[&p,&limit]),(None,Some(s))=>self.store.query("SELECT * FROM workspace_issues WHERE status=? ORDER BY updated_at DESC LIMIT ?",&[&s,&limit]),_=>self.store.query("SELECT * FROM workspace_issues ORDER BY updated_at DESC LIMIT ?",&[&limit])}
    }
}

fn public_media(mut row: Value) -> Value {
    if let Some(object) = row.as_object_mut() {
        object.remove("storage_path");
        object.insert(
            "content_url".into(),
            json!(format!(
                "/api/media/{}/content",
                object["id"].as_str().unwrap_or("")
            )),
        );
    }
    row
}
fn json_response(v: Value) -> Result<Response<Body>, ApiError> {
    Response::builder()
        .status(StatusCode::OK)
        .header(header::CONTENT_TYPE, "application/json")
        .body(Body::from(
            serde_json::to_vec(&v).map_err(|e| ApiError::internal(e.to_string()))?,
        ))
        .map_err(|e| ApiError::internal(e.to_string()))
}
pub async fn handle(
    state: crate::AppState,
    method: &str,
    path: &[&str],
    query: &HashMap<String, String>,
    body: Value,
) -> Option<Result<Response<Body>, ApiError>> {
    let f = FoundationStore::from_store(state.store.clone());
    let p = path;
    let q = |k: &str| query.get(k).map(String::as_str);
    if method == "GET" && matches!(path, ["media", _, "content"]) {
        return Some(f.media_content(path[1]).and_then(|(bytes, mime)| {
            Response::builder()
                .header(header::CONTENT_TYPE, mime)
                .header(header::X_CONTENT_TYPE_OPTIONS, "nosniff")
                .body(Body::from(bytes))
                .map_err(|e| ApiError::internal(e.to_string()))
        }));
    }
    if let Some(response) = memory::handle(state.clone(), method, path, query, body.clone()).await {
        return Some(response);
    }
    if method == "POST" && path == ["conversation", "promote-presence"] {
        let project = body.get("project_id").and_then(Value::as_str).unwrap_or("");
        let world = body.get("world_id").and_then(Value::as_str).unwrap_or("");
        let branch = body.get("branch_id").and_then(Value::as_str);
        let name = body
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or("")
            .trim();
        if project.is_empty() || world.is_empty() || name.is_empty() {
            return Some(Err(ApiError::bad_request(
                "project_id, world_id and name are required",
            )));
        }
        let slug = name
            .to_ascii_lowercase()
            .chars()
            .map(|c| if c.is_ascii_alphanumeric() { c } else { '-' })
            .collect::<String>()
            .trim_matches('-')
            .to_owned();
        let family = json!({"project_id":project,"entity_type":"character","name":name,"slug":slug,"description":"Promoted from a Story Lab Presence Blueprint.","shared_core":{"presence_blueprint":body.get("blueprint").cloned().unwrap_or(json!({}))}});
        let family = match crate::workspace::handle(
            &state,
            "POST",
            &["entities", "families"],
            query,
            &family,
        ) {
            Some(Ok(v)) => v,
            Some(Err(e)) => return Some(Err(e)),
            None => {
                return Some(Err(ApiError::internal(
                    "workspace family route unavailable",
                )))
            }
        };
        let fid = family.get("id").and_then(Value::as_str).unwrap_or("");
        let variant = json!({"family_id":fid,"world_id":world,"branch_id":branch,"display_name":name,"summary":"User-designed story Presence.","canon_status":"draft","attributes":{"presence_blueprint":body.get("blueprint").cloned().unwrap_or(json!({}))},"voice":{},"knowledge":{},"beliefs":{},"current_state":{}});
        let variant = match crate::workspace::handle(
            &state,
            "POST",
            &["entities", "variants"],
            query,
            &variant,
        ) {
            Some(Ok(v)) => v,
            Some(Err(e)) => return Some(Err(e)),
            None => {
                return Some(Err(ApiError::internal(
                    "workspace variant route unavailable",
                )))
            }
        };
        return Some(json_response(json!({"family":family,"variant":variant})));
    }
    if method == "POST" && path == ["user-profile", "entity"] {
        let project = body.get("project_id").and_then(Value::as_str).unwrap_or("");
        let world = body.get("world_id").and_then(Value::as_str).unwrap_or("");
        let branch = body.get("branch_id").and_then(Value::as_str);
        let name = body
            .get("name")
            .and_then(Value::as_str)
            .unwrap_or("")
            .trim();
        if project.is_empty() || world.is_empty() || name.is_empty() {
            return Some(Err(ApiError::bad_request(
                "project_id, world_id and name are required",
            )));
        }
        let aliases = body
            .get("preferred_names")
            .and_then(Value::as_array)
            .map(|a| {
                a.iter()
                    .filter_map(|v| v.get("value").and_then(Value::as_str))
                    .map(str::to_owned)
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default();
        let details = body
            .get("personal_details")
            .and_then(Value::as_object)
            .map(|m| {
                m.iter()
                    .filter_map(|(k, v)| {
                        let d = v.as_object()?;
                        let vis = d.get("visibility")?.as_str()?;
                        if !matches!(vis, "collaboration" | "story_presence")
                            || d.get("sensitive").and_then(Value::as_bool).unwrap_or(false)
                        {
                            return None;
                        }
                        Some((k.clone(), d.get("value")?.clone()))
                    })
                    .collect::<Map<_, _>>()
            })
            .unwrap_or_default();
        let snapshot = json!({"source":"personalization","display_name":name,"aliases":aliases,"about":body.get("about").and_then(Value::as_str).unwrap_or(""),"creative_profile":body.get("creative_profile").cloned().unwrap_or(json!({})),"personal_details":details,"presence_defaults":body.get("presence_defaults").cloned().unwrap_or(json!({}))});
        let slug = name
            .to_ascii_lowercase()
            .chars()
            .map(|c| if c.is_ascii_alphanumeric() { c } else { '-' })
            .collect::<String>()
            .trim_matches('-')
            .to_owned();
        let family_body = json!({"project_id":project,"entity_type":"character","name":name,"slug":slug,"description":format!("User-linked story identity: {}",body.get("about").and_then(Value::as_str).unwrap_or("")),"shared_core":{"user_profile_projection":snapshot}});
        let family = match crate::workspace::handle(
            &state,
            "POST",
            &["entities", "families"],
            query,
            &family_body,
        ) {
            Some(Ok(v)) => v,
            Some(Err(e)) => return Some(Err(e)),
            None => {
                return Some(Err(ApiError::internal(
                    "workspace family route unavailable",
                )))
            }
        };
        let fid = family.get("id").and_then(Value::as_str).unwrap_or("");
        let variant_body = json!({"family_id":fid,"world_id":world,"branch_id":branch,"display_name":name,"summary":"User-linked story identity.","canon_status":"draft","attributes":{"user_profile_projection":snapshot},"voice":{},"knowledge":{},"beliefs":{},"current_state":{}});
        let variant = match crate::workspace::handle(
            &state,
            "POST",
            &["entities", "variants"],
            query,
            &variant_body,
        ) {
            Some(Ok(v)) => v,
            Some(Err(e)) => return Some(Err(e)),
            None => {
                return Some(Err(ApiError::internal(
                    "workspace variant route unavailable",
                )))
            }
        };
        let mut profile = body.clone();
        if let Some(o) = profile.as_object_mut() {
            let mut presence = o.get("presence_defaults").cloned().unwrap_or(json!({}));
            if let Some(po) = presence.as_object_mut() {
                po.insert("mode".into(), json!("linked_entity"));
                po.insert("identity_source".into(), json!("self_entity"));
                po.insert(
                    "entity_family_id".into(),
                    family.get("id").cloned().unwrap_or(Value::Null),
                );
                po.insert(
                    "entity_variant_id".into(),
                    variant.get("id").cloned().unwrap_or(Value::Null),
                );
                po.insert("display_name".into(), json!(name));
            }
            o.insert("display_name".into(), json!(name));
            o.insert("presence_defaults".into(), presence);
        }
        let saved = match f.save_user_profile(&profile) {
            Ok(v) => v,
            Err(e) => return Some(Err(e)),
        };
        return Some(json_response(
            json!({"family":family,"variant":variant,"profile":saved}),
        ));
    }
    if method == "GET" && path == ["search"] {
        let needle = q("q").unwrap_or("").to_ascii_lowercase();
        if needle.trim().is_empty() {
            return Some(json_response(json!({"results":[]})));
        }
        let mut results = Vec::new();
        for (table, typ) in [
            ("projects", "project"),
            ("worlds", "world"),
            ("workspace_documents", "document"),
            ("entity_families", "entity_family"),
            ("entity_variants", "entity_variant"),
        ] {
            if let Ok(rows) = state.store.list(table, &[]) {
                for mut row in rows {
                    if row.to_string().to_ascii_lowercase().contains(&needle) {
                        if let Some(o) = row.as_object_mut() {
                            o.insert("type".into(), json!(typ));
                        }
                        results.push(row);
                    }
                }
            }
        }
        results.truncate(q("limit").and_then(|x| x.parse().ok()).unwrap_or(50));
        return Some(json_response(json!({"results":results})));
    }
    if method == "GET" && path == ["home"] {
        let project = q("project_id");
        let docs = state
            .store
            .list("workspace_documents", &[])
            .unwrap_or_default()
            .into_iter()
            .filter(|x| {
                project
                    .map(|p| x.get("project_id").and_then(Value::as_str) == Some(p))
                    .unwrap_or(true)
            })
            .take(8)
            .collect::<Vec<_>>();
        let issues = f.list_issues(project, q("status"), 8).unwrap_or_default();
        return Some(json_response(
            json!({"active_scene":null,"recent_documents":docs,"recent_chats":[],"issues":issues,"activity":f.activity(project,10).unwrap_or_default(),"feedback":{},"favorites":f.favorites(project).unwrap_or_default()}),
        ));
    }
    let result = match (method, p) {
        ("GET", ["lifecycle", t, id]) => f.lifecycle(t, id),
        ("POST", ["lifecycle", "trash"]) => f.trash(
            body.get("resource_type")
                .and_then(Value::as_str)
                .unwrap_or(""),
            body.get("resource_id")
                .and_then(Value::as_str)
                .unwrap_or(""),
            body.get("previous_state"),
        ),
        ("POST", ["lifecycle", "restore"]) => f.restore(
            body.get("resource_type")
                .and_then(Value::as_str)
                .unwrap_or(""),
            body.get("resource_id")
                .and_then(Value::as_str)
                .unwrap_or(""),
        ),
        ("POST", ["lifecycle", "archive"]) => f.archive(
            body.get("resource_type")
                .and_then(Value::as_str)
                .unwrap_or(""),
            body.get("resource_id")
                .and_then(Value::as_str)
                .unwrap_or(""),
            q("archived").unwrap_or("true") == "true",
        ),
        ("GET", ["trash"]) => f
            .list_trash(q("limit").and_then(|x| x.parse().ok()).unwrap_or(200))
            .map(|x| json!({"items":x})),
        ("POST", ["aliases"]) => f.add_alias(
            body.get("resource_type")
                .and_then(Value::as_str)
                .unwrap_or(""),
            body.get("resource_id")
                .and_then(Value::as_str)
                .unwrap_or(""),
            body.get("alias").and_then(Value::as_str).unwrap_or(""),
        ),
        ("DELETE", ["aliases", id]) => f.delete_alias(id).map(|x| json!({"deleted":x})),
        ("GET", ["aliases"]) => f
            .aliases(
                q("resource_type").unwrap_or(""),
                q("resource_id").unwrap_or(""),
            )
            .map(|x| json!({"aliases":x})),
        ("GET", ["collections"]) => f
            .collections(q("scope_type").unwrap_or("world_bible"), q("scope_id"))
            .map(|x| json!({"collections":x})),
        ("POST", ["collections"]) => f.create_collection(
            body.get("name").and_then(Value::as_str).unwrap_or(""),
            body.get("scope_type")
                .and_then(Value::as_str)
                .unwrap_or("world_bible"),
            body.get("scope_id").and_then(Value::as_str),
            body.get("description")
                .and_then(Value::as_str)
                .unwrap_or(""),
            body.get("icon").and_then(Value::as_str).unwrap_or("◇"),
        ),
        ("POST", ["collections", id, "links"]) => f.collection_link(
            id,
            body.get("resource_type")
                .and_then(Value::as_str)
                .unwrap_or(""),
            body.get("resource_id")
                .and_then(Value::as_str)
                .unwrap_or(""),
            body.get("sort_order").and_then(Value::as_i64).unwrap_or(0),
        ),
        ("DELETE", ["collections", id]) => f.delete_collection(id).map(|x| json!({"deleted":x})),
        ("GET", ["saved-views"]) => f
            .saved_views(q("scope_type").unwrap_or("world_bible"), q("scope_id"))
            .map(|x| json!({"views":x})),
        ("POST", ["saved-views"]) => f.save_view(
            body.get("name").and_then(Value::as_str).unwrap_or(""),
            body.get("scope_type")
                .and_then(Value::as_str)
                .unwrap_or("world_bible"),
            body.get("scope_id").and_then(Value::as_str),
            body.get("resource_type")
                .and_then(Value::as_str)
                .unwrap_or("all"),
            body.get("query").unwrap_or(&json!({})),
        ),
        ("GET", ["favorites"]) => f.favorites(q("project_id")).map(|x| json!({"favorites":x})),
        ("POST", ["favorites"]) => f.favorite(
            body.get("project_id").and_then(Value::as_str),
            body.get("resource_type")
                .and_then(Value::as_str)
                .unwrap_or(""),
            body.get("resource_id")
                .and_then(Value::as_str)
                .unwrap_or(""),
            body.get("label").and_then(Value::as_str).unwrap_or(""),
        ),
        ("DELETE", ["favorites"]) => f
            .unfavorite(
                q("project_id"),
                q("resource_type").unwrap_or(""),
                q("resource_id").unwrap_or(""),
            )
            .map(|x| json!({"deleted":x})),
        ("GET", ["activity"]) => f
            .activity(
                q("project_id"),
                q("limit").and_then(|x| x.parse().ok()).unwrap_or(50),
            )
            .map(|x| json!({"activity":x})),
        ("GET", ["jobs"]) => f
            .jobs(
                q("project_id"),
                q("limit").and_then(|x| x.parse().ok()).unwrap_or(100),
            )
            .map(|x| json!({"jobs":x})),
        ("GET", ["run-profiles"]) => f
            .run_profiles(q("project_id"))
            .map(|x| json!({"profiles":x})),
        ("POST", ["run-profiles"]) => f.save_run_profile(&body),
        ("DELETE", ["run-profiles", id]) => f.delete_run_profile(id).map(|x| json!({"deleted":x})),
        ("GET", ["preferences"]) => f.preferences(
            q("scope_type").unwrap_or("global"),
            q("scope_id").unwrap_or("default"),
        ),
        ("PUT", ["preferences"]) => f.set_preference(
            body.get("scope_type")
                .and_then(Value::as_str)
                .unwrap_or("global"),
            body.get("scope_id")
                .and_then(Value::as_str)
                .unwrap_or("default"),
            body.get("key").and_then(Value::as_str).unwrap_or(""),
            body.get("value").unwrap_or(&Value::Null),
        ),
        ("GET", ["issues"]) => f
            .list_issues(
                q("project_id"),
                q("status"),
                q("limit").and_then(|x| x.parse().ok()).unwrap_or(200),
            )
            .map(|x| json!({"issues":x})),
        ("POST", ["issues"]) => f.create_issue(&body),
        ("POST", ["issues", id, "resolve"]) => {
            f.resolve_issue(id, q("status").unwrap_or("resolved"))
        }
        ("GET", ["media"]) => f
            .media(
                q("resource_type"),
                q("resource_id"),
                q("cover_only") == Some("true"),
            )
            .map(|x| json!({"items":x.into_iter().map(public_media).collect::<Vec<_>>()})),
        ("POST", ["media"]) => f.create_media(&body),
        ("PATCH", ["media", id]) => f.update_media(id, &body),
        ("DELETE", ["media", id]) => f.delete_media(id).map(|x| json!({"deleted":x})),
        ("GET", ["context-stack"]) => f.get_context(q("stack_id").unwrap_or("default")),
        ("PUT", ["context-stack"]) => f.set_context(
            body.get("stack_id")
                .and_then(Value::as_str)
                .unwrap_or("default"),
            &body,
        ),
        ("GET", ["user-profile"]) => f.user_profile(),
        ("PUT", ["user-profile"]) => f.save_user_profile(&body),
        ("POST", ["user-profile", "extract"]) => {
            Ok(f.extract_profile(body.get("text").and_then(Value::as_str).unwrap_or("")))
        }
        ("GET", ["presence-bindings", scope, id]) => f.presence_binding(scope, id),
        ("PUT", ["presence-bindings", scope, id]) => {
            f.save_presence_binding(scope, id, body.get("profile").unwrap_or(&body))
        }
        ("POST", ["conversation", "blueprint", "extract"]) => Ok(
            json!({"blueprint":f.extract_blueprint(body.get("text").and_then(Value::as_str).unwrap_or(""),body.get("current").unwrap_or(&json!({})))}),
        ),
        ("POST", ["user-profile", "entity"]) => Err(ApiError::new(
            StatusCode::NOT_IMPLEMENTED,
            "user entity promotion requires the workspace domain service",
        )),
        _ => return None,
    };
    Some(result.and_then(json_response))
}
