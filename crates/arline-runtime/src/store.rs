use crate::{ApiError, ApiResult};
use rusqlite::{backup::Backup, params_from_iter, types::Value as SqlValue, Connection, ToSql};
use serde_json::{Map, Value};
use std::{
    collections::{HashMap, HashSet},
    fs,
    path::{Path, PathBuf},
    sync::atomic::{AtomicU64, Ordering},
    time::{SystemTime, UNIX_EPOCH},
};

const SCHEMA_VERSION: i64 = 7;
static NEXT_ID: AtomicU64 = AtomicU64::new(1);

#[derive(Clone)]
pub struct Store {
    pub path: PathBuf,
}

impl Store {
    pub fn open(path: impl AsRef<Path>) -> ApiResult<Self> {
        let path = path.as_ref().to_path_buf();
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)
                .map_err(|e| ApiError::internal(format!("create database directory: {}", e)))?;
        }
        let existed = path.is_file();
        let store = Self { path };
        let con = store.connection()?;
        let has_meta = con
            .query_row(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='workspace_meta'",
                [],
                |r| r.get::<_, i64>(0),
            )
            .map_err(sql_error)?
            > 0;
        if existed && !has_meta {
            let has_tables = con.query_row("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'", [], |r| r.get::<_, i64>(0)).map_err(sql_error)? > 0;
            if has_tables {
                return Err(ApiError::internal(
                    "existing database has an unknown workspace schema",
                ));
            }
        }
        if has_meta {
            let version = con
                .query_row(
                    "SELECT value FROM workspace_meta WHERE key='schema_version'",
                    [],
                    |r| r.get::<_, String>(0),
                )
                .optional()
                .map_err(sql_error)?
                .and_then(|v| v.parse::<i64>().ok())
                .unwrap_or(0);
            if version > SCHEMA_VERSION {
                return Err(ApiError::internal(format!(
                    "database schema {} is newer than runtime {}",
                    version, SCHEMA_VERSION
                )));
            }
            if version < SCHEMA_VERSION && existed {
                backup_database(&store.path, version)?;
            }
        }
        con.execute_batch(include_str!("schema.sql"))
            .map_err(sql_error)?;
        migrate_columns(&con)?;
        validate_schema_shape(&con)?;
        seed_defaults(&con)?;
        con.execute("INSERT INTO workspace_meta(key,value) VALUES('schema_version',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", [SCHEMA_VERSION.to_string()]).map_err(sql_error)?;
        Ok(store)
    }

    pub fn connection(&self) -> ApiResult<Connection> {
        let con = Connection::open(&self.path).map_err(sql_error)?;
        con.execute_batch(
            "PRAGMA foreign_keys=ON; PRAGMA busy_timeout=30000; PRAGMA journal_mode=WAL;",
        )
        .map_err(sql_error)?;
        Ok(con)
    }

    pub fn query(&self, sql: &str, params: &[&dyn ToSql]) -> ApiResult<Vec<Value>> {
        let con = self.connection()?;
        let mut stmt = con.prepare(sql).map_err(sql_error)?;
        let names: Vec<String> = stmt
            .column_names()
            .iter()
            .map(|s| (*s).to_owned())
            .collect();
        let rows = stmt
            .query_map(params, |row| row_to_json(row, &names))
            .map_err(sql_error)?;
        rows.collect::<Result<Vec<_>, _>>().map_err(sql_error)
    }

    pub fn execute(&self, sql: &str, params: &[&dyn ToSql]) -> ApiResult<usize> {
        self.connection()?.execute(sql, params).map_err(sql_error)
    }

    pub fn get(&self, table: &str, id: &str) -> ApiResult<Option<Value>> {
        validate_identifier(table)?;
        let rows = self.query(
            &format!("SELECT * FROM {} WHERE id=? LIMIT 1", table),
            &[&id],
        )?;
        Ok(rows.into_iter().next())
    }

    pub fn list(&self, table: &str, filters: &[(&str, Value)]) -> ApiResult<Vec<Value>> {
        validate_identifier(table)?;
        let columns = table_columns(&self.connection()?, table)?;
        let mut clauses = Vec::new();
        let mut values = Vec::new();
        for (key, value) in filters {
            validate_identifier(key)?;
            if columns.contains(*key) {
                clauses.push(format!("{}=?", key));
                values.push(json_to_sql(value)?);
            }
        }
        let sql = if clauses.is_empty() {
            format!("SELECT * FROM {}", table)
        } else {
            format!("SELECT * FROM {} WHERE {}", table, clauses.join(" AND "))
        };
        let refs: Vec<&dyn ToSql> = values.iter().map(|v| v as &dyn ToSql).collect();
        self.query(&sql, &refs)
    }

    pub fn insert(&self, table: &str, payload: Value) -> ApiResult<Value> {
        validate_identifier(table)?;
        let object = payload
            .as_object()
            .ok_or_else(|| ApiError::bad_request("payload must be a JSON object"))?;
        let columns = table_columns(&self.connection()?, table)?;
        let mut data = object.clone();
        data.entry(String::from("id"))
            .or_insert_with(|| Value::String(new_id()));
        if matches!(
            table,
            "projects" | "worlds" | "world_branches" | "entity_families"
        ) && !data.contains_key("slug")
        {
            if let Some(name) = data.get("name").and_then(Value::as_str) {
                let base = slugify(name);
                let slug = self.unique_generated_slug(table, &data, &base)?;
                data.insert("slug".into(), Value::String(slug));
            }
        }
        for key in data.keys() {
            if key != "id"
                && !columns.contains(key.as_str())
                && !columns.contains(format!("{}_json", key).as_str())
            {
                return Err(ApiError::bad_request(format!(
                    "unknown field '{}' for table '{}'",
                    key, table
                )));
            }
        }
        let now = now_string();
        for key in ["created_at", "updated_at"] {
            if columns.contains(key) {
                data.entry(String::from(key))
                    .or_insert_with(|| Value::String(now.clone()));
            }
        }
        let fields: Vec<String> = data
            .keys()
            .filter_map(|k| {
                if columns.contains(k.as_str()) {
                    Some(k.clone())
                } else if columns.contains(format!("{}_json", k).as_str()) {
                    Some(format!("{}_json", k))
                } else {
                    None
                }
            })
            .collect();
        if fields.is_empty() {
            return Err(ApiError::bad_request("no known fields in payload"));
        }
        let sql = format!(
            "INSERT INTO {} ({}) VALUES ({})",
            table,
            fields
                .iter()
                .map(|k| k.to_string())
                .collect::<Vec<_>>()
                .join(","),
            vec!["?"; fields.len()].join(",")
        );
        let values: Vec<SqlValue> = fields
            .iter()
            .map(|k| {
                let key = k.strip_suffix("_json").unwrap_or(k);
                json_to_sql(data.get(key).or_else(|| data.get(k)).unwrap())
            })
            .collect::<ApiResult<_>>()?;
        let refs: Vec<&dyn ToSql> = values.iter().map(|v| v as &dyn ToSql).collect();
        self.connection()?
            .execute(&sql, params_from_iter(refs))
            .map_err(sql_error)?;
        self.get(
            table,
            data.get("id").and_then(Value::as_str).unwrap_or_default(),
        )?
        .ok_or_else(|| ApiError::internal("inserted row could not be read"))
    }

    fn unique_generated_slug(
        &self,
        table: &str,
        data: &Map<String, Value>,
        base: &str,
    ) -> ApiResult<String> {
        let con = self.connection()?;
        for suffix in 0..10_000u32 {
            let candidate = if suffix == 0 {
                base.to_owned()
            } else {
                format!("{}-{}", base, suffix + 1)
            };
            let exists = match table {
                "projects" => con
                    .query_row(
                        "SELECT EXISTS(SELECT 1 FROM projects WHERE slug=?)",
                        [&candidate],
                        |row| row.get::<_, bool>(0),
                    )
                    .map_err(sql_error)?,
                "worlds" => {
                    let project_id = data.get("project_id").and_then(Value::as_str).unwrap_or("");
                    con.query_row(
                        "SELECT EXISTS(SELECT 1 FROM worlds WHERE project_id=? AND slug=?)",
                        rusqlite::params![project_id, candidate],
                        |row| row.get::<_, bool>(0),
                    )
                    .map_err(sql_error)?
                }
                "world_branches" => {
                    let world_id = data.get("world_id").and_then(Value::as_str).unwrap_or("");
                    con.query_row(
                        "SELECT EXISTS(SELECT 1 FROM world_branches WHERE world_id=? AND slug=?)",
                        rusqlite::params![world_id, candidate],
                        |row| row.get::<_, bool>(0),
                    )
                    .map_err(sql_error)?
                }
                "entity_families" => {
                    let project_id = data.get("project_id").and_then(Value::as_str).unwrap_or("");
                    let entity_type = data
                        .get("entity_type")
                        .and_then(Value::as_str)
                        .unwrap_or("");
                    con.query_row(
                        "SELECT EXISTS(SELECT 1 FROM entity_families WHERE project_id=? AND entity_type=? AND slug=?)",
                        rusqlite::params![project_id, entity_type, candidate],
                        |row| row.get::<_, bool>(0),
                    )
                    .map_err(sql_error)?
                }
                _ => false,
            };
            if !exists {
                return Ok(candidate);
            }
        }
        Err(ApiError::bad_request("could not derive a unique slug"))
    }

    pub fn update(&self, table: &str, id: &str, patch: Value) -> ApiResult<Value> {
        validate_identifier(table)?;
        let object = patch
            .as_object()
            .ok_or_else(|| ApiError::bad_request("patch must be a JSON object"))?;
        let columns = table_columns(&self.connection()?, table)?;
        let mut fields = Vec::new();
        let mut values = Vec::new();
        for (key, value) in object {
            validate_identifier(key)?;
            if key != "id"
                && !columns.contains(key.as_str())
                && !columns.contains(format!("{}_json", key).as_str())
            {
                return Err(ApiError::bad_request(format!(
                    "unknown field '{}' for table '{}'",
                    key, table
                )));
            }
            if key != "id" {
                let column = if columns.contains(key.as_str()) {
                    key.clone()
                } else if columns.contains(format!("{}_json", key).as_str()) {
                    format!("{}_json", key)
                } else {
                    String::new()
                };
                if !column.is_empty() {
                    fields.push(format!("{}=?", column));
                    values.push(json_to_sql(value)?);
                }
            }
        }
        if columns.contains("updated_at") {
            fields.push("updated_at=?".into());
            values.push(SqlValue::Text(now_string()));
        }
        if fields.is_empty() {
            return self
                .get(table, id)?
                .ok_or_else(|| ApiError::not_found("row not found"));
        }
        values.push(SqlValue::Text(id.to_owned()));
        let changed = self
            .connection()?
            .execute(
                &format!("UPDATE {} SET {} WHERE id=?", table, fields.join(",")),
                params_from_iter(values.iter()),
            )
            .map_err(sql_error)?;
        if changed == 0 {
            return Err(ApiError::not_found("row not found"));
        }
        self.get(table, id)?
            .ok_or_else(|| ApiError::not_found("row not found"))
    }

    pub fn delete(&self, table: &str, id: &str) -> ApiResult<bool> {
        validate_identifier(table)?;
        Ok(self
            .connection()?
            .execute(&format!("DELETE FROM {} WHERE id=?", table), [id])
            .map_err(sql_error)?
            > 0)
    }
    pub fn delete_folder(&self, id: &str) -> ApiResult<bool> {
        let mut con = self.connection()?;
        let tx = con.transaction().map_err(sql_error)?;
        let project_id: String = tx
            .query_row(
                "SELECT project_id FROM workspace_folders WHERE id=?",
                [id],
                |r| r.get(0),
            )
            .optional()
            .map_err(sql_error)?
            .ok_or_else(|| ApiError::not_found("folder not found"))?;
        let mut children: HashMap<Option<String>, Vec<String>> = HashMap::new();
        let mut rows = tx
            .prepare("SELECT id,parent_id FROM workspace_folders WHERE project_id=?")
            .map_err(sql_error)?;
        let folder_rows = rows
            .query_map([&project_id], |r| {
                Ok((r.get::<_, String>(0)?, r.get::<_, Option<String>>(1)?))
            })
            .map_err(sql_error)?;
        for row in folder_rows {
            let (child, parent) = row.map_err(sql_error)?;
            children.entry(parent).or_default().push(child);
        }
        drop(rows);
        let mut descendants = Vec::new();
        let mut visited = HashSet::new();
        let mut pending = vec![id.to_owned()];
        while let Some(current) = pending.pop() {
            if !visited.insert(current.clone()) {
                continue;
            }
            descendants.push(current.clone());
            pending.extend(children.get(&Some(current)).cloned().unwrap_or_default());
        }
        // Detach every child pointing at the deleted subtree, including
        // corrupt legacy rows from another project; those rows must survive.
        for descendant in &descendants {
            tx.execute(
                "UPDATE workspace_folders SET parent_id=NULL WHERE parent_id=?",
                [descendant],
            )
            .map_err(sql_error)?;
            tx.execute(
                "DELETE FROM project_manifest_refs WHERE resource_type='folder' AND resource_id=?",
                [descendant],
            )
            .map_err(sql_error)?;
            tx.execute(
                "DELETE FROM project_overlays WHERE owner_type='folder' AND owner_id=?",
                [descendant],
            )
            .map_err(sql_error)?;
            tx.execute(
                "DELETE FROM staged_changes WHERE owner_type='folder' AND owner_id=?",
                [descendant],
            )
            .map_err(sql_error)?;
            tx.execute(
                "DELETE FROM context_pins WHERE resource_type='folder' AND resource_id=?",
                [descendant],
            )
            .map_err(sql_error)?;
            tx.execute(
                "DELETE FROM workspace_revisions WHERE resource_type='folder' AND resource_id=?",
                [descendant],
            )
            .map_err(sql_error)?;
        }
        let mut changed = 0usize;
        for descendant in &descendants {
            changed += tx
                .execute("DELETE FROM workspace_folders WHERE id=?", [descendant])
                .map_err(sql_error)?;
        }
        tx.commit().map_err(sql_error)?;
        Ok(changed > 0)
    }

    pub fn update_folder(&self, id: &str, patch: &Value) -> ApiResult<Value> {
        let object = patch
            .as_object()
            .ok_or_else(|| ApiError::bad_request("patch must be an object"))?;
        let mut con = self.connection()?;
        let tx = con.transaction().map_err(sql_error)?;
        let current: (String, Option<String>, Option<String>, Option<String>) = tx
            .query_row(
                "SELECT project_id,world_id,branch_id,parent_id FROM workspace_folders WHERE id=?",
                [id],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?)),
            )
            .optional()
            .map_err(sql_error)?
            .ok_or_else(|| ApiError::not_found("folder not found"))?;
        if let Some(parent) = object.get("parent_id") {
            if let Some(parent_id) = parent.as_str() {
                if parent_id == id {
                    return Err(ApiError::bad_request("folder cannot be its own parent"));
                }
                let parent_scope: (String, Option<String>, Option<String>) = tx
                    .query_row(
                        "SELECT project_id,world_id,branch_id FROM workspace_folders WHERE id=?",
                        [parent_id],
                        |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
                    )
                    .map_err(sql_error)?;
                if parent_scope.0 != current.0
                    || parent_scope.1 != current.1
                    || parent_scope.2 != current.2
                {
                    return Err(ApiError::bad_request(
                        "folder parent must share project, world, and branch scope",
                    ));
                }
                let mut cursor = Some(parent_id.to_owned());
                let mut seen = HashSet::new();
                for depth in 0..=100 {
                    let Some(cursor_id) = cursor else { break };
                    if !seen.insert(cursor_id.clone()) || cursor_id == id {
                        return Err(ApiError::bad_request("folder parent cycle detected"));
                    }
                    if depth == 100 {
                        return Err(ApiError::bad_request(
                            "folder nesting exceeds maximum depth",
                        ));
                    }
                    cursor = tx
                        .query_row(
                            "SELECT parent_id FROM workspace_folders WHERE id=?",
                            [&cursor_id],
                            |r| r.get(0),
                        )
                        .optional()
                        .map_err(sql_error)?
                        .flatten();
                }
            } else if !parent.is_null() {
                return Err(ApiError::bad_request("parent_id must be a string or null"));
            }
        }
        let columns = table_columns(&tx, "workspace_folders")?;
        let mut fields = Vec::new();
        let mut values = Vec::new();
        for (key, value) in object {
            validate_identifier(key)?;
            if key == "id" || !columns.contains(key.as_str()) {
                return Err(ApiError::bad_request(format!(
                    "unknown folder field '{}'",
                    key
                )));
            }
            fields.push(format!("{}=?", key));
            values.push(json_to_sql(value)?);
        }
        if fields.is_empty() {
            tx.rollback().map_err(sql_error)?;
            drop(con);
            return self
                .get("workspace_folders", id)?
                .ok_or_else(|| ApiError::not_found("folder not found"));
        }
        fields.push("updated_at=?".into());
        values.push(SqlValue::Text(now_string()));
        values.push(SqlValue::Text(id.to_owned()));
        tx.execute(
            &format!(
                "UPDATE workspace_folders SET {} WHERE id=?",
                fields.join(",")
            ),
            params_from_iter(values.iter()),
        )
        .map_err(sql_error)?;
        tx.commit().map_err(sql_error)?;
        self.get("workspace_folders", id)?
            .ok_or_else(|| ApiError::not_found("folder not found"))
    }
}

fn backup_database(path: &Path, version: i64) -> ApiResult<PathBuf> {
    let stamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let backup_path = path.with_extension(format!(
        "schema-v{}-before-v{}-{}.bak",
        version, SCHEMA_VERSION, stamp
    ));
    let source = Connection::open(path).map_err(sql_error)?;
    let mut destination = Connection::open(&backup_path).map_err(sql_error)?;
    let backup = Backup::new(&source, &mut destination).map_err(sql_error)?;
    backup
        .run_to_completion(5, std::time::Duration::from_millis(50), None)
        .map_err(sql_error)?;
    drop(backup);
    drop(destination);
    Ok(backup_path)
}

fn migrate_columns(con: &Connection) -> ApiResult<()> {
    let columns = table_columns(con, "entity_families")?;
    if !columns.contains("folder_id") {
        con.execute("ALTER TABLE entity_families ADD COLUMN folder_id TEXT", [])
            .map_err(sql_error)?;
    }
    Ok(())
}

fn validate_schema_shape(con: &Connection) -> ApiResult<()> {
    let reference = Connection::open_in_memory().map_err(sql_error)?;
    reference
        .execute_batch(include_str!("schema.sql"))
        .map_err(sql_error)?;
    let mut tables = reference
        .prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        .map_err(sql_error)?;
    let names = tables
        .query_map([], |row| row.get::<_, String>(0))
        .map_err(sql_error)?
        .collect::<Result<Vec<_>, _>>()
        .map_err(sql_error)?;
    for table in names {
        let exists: bool = con
            .query_row(
                "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type='table' AND name=?)",
                [&table],
                |row| row.get(0),
            )
            .map_err(sql_error)?;
        if !exists {
            continue;
        }
        let expected = table_columns(&reference, &table)?;
        let actual = table_columns(con, &table)?;
        if let Some(missing) = expected.difference(&actual).next() {
            return Err(ApiError::internal(format!(
                "existing table '{}' is missing required column '{}'",
                table, missing
            )));
        }
    }
    Ok(())
}

fn seed_defaults(con: &Connection) -> ApiResult<()> {
    let now = now_string();
    con.execute(
        "INSERT OR IGNORE INTO projects(id,name,slug,description,pinned,archived,default_world_id,settings_json,created_at,updated_at) VALUES(?,?,?,?,0,1,?,?,?,?)",
        rusqlite::params!["PROJ-WORLD-BIBLE", "Library", "__world-bible__", "Internal backing scope for global Arline canon.", "WORLD-BIBLE-MAIN", r#"{"system":true,"role":"world_bible"}"#, now, now],
    ).map_err(sql_error)?;
    con.execute(
        "INSERT OR IGNORE INTO worlds(id,project_id,parent_world_id,name,slug,description,canon_status,inheritance_mode,settings_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        rusqlite::params!["WORLD-BIBLE-MAIN", "PROJ-WORLD-BIBLE", rusqlite::types::Value::Null, "Main", "main", "Primary shared world.", "canon", "none", r#"{"system_seed":true}"#, now, now],
    ).map_err(sql_error)?;
    con.execute(
        "INSERT OR IGNORE INTO world_branches(id,world_id,parent_branch_id,name,slug,description,kind,canon_status,base_snapshot_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        rusqlite::params!["BRANCH-BIBLE-MAIN", "WORLD-BIBLE-MAIN", rusqlite::types::Value::Null, "Main", "main", "Primary timeline", "main", "canon", rusqlite::types::Value::Null, now, now],
    ).map_err(sql_error)?;
    for (id, name, entity_type, description, payload) in [
        (
            "TPL-GLOBAL-CHARACTER",
            "Character",
            "character",
            "Identity, personality, voice, knowledge, relationships, history, and current state.",
            r#"{"shared_core":{"identity":{},"appearance_baseline":{}},"attributes":{"personality":{},"appearance":{},"occupation":null},"voice":{"register":"follow_context","rhythm":null,"terms_of_address":[]},"knowledge":{},"beliefs":{},"current_state":{}}"#,
        ),
        (
            "TPL-GLOBAL-LOCATION",
            "Location",
            "location",
            "Spatial, sensory, social, and world-rule context.",
            r#"{"shared_core":{"kind":null},"attributes":{"geometry":{},"atmosphere":{},"access":{}},"current_state":{}}"#,
        ),
        (
            "TPL-GLOBAL-ITEM",
            "Item",
            "item",
            "Physical properties, ownership, affordances, and state.",
            r#"{"shared_core":{"kind":null},"attributes":{"material":null,"dimensions":{},"affordances":[]},"current_state":{}}"#,
        ),
        (
            "TPL-GLOBAL-ORGANIZATION",
            "Organization",
            "organization",
            "Members, structure, goals, knowledge, and relationships.",
            r#"{"shared_core":{"kind":null},"attributes":{"purpose":null,"hierarchy":{},"members":[]},"knowledge":{},"current_state":{}}"#,
        ),
        (
            "TPL-GLOBAL-WORLD-RULE",
            "World Rule",
            "world_rule",
            "A bounded law, mechanism, exception, and consequence.",
            r#"{"shared_core":{"domain":null},"attributes":{"rule":null,"mechanism":null,"exceptions":[],"consequences":[]}}"#,
        ),
    ] {
        con.execute(
            "INSERT OR IGNORE INTO entity_templates(id,project_id,name,entity_type,description,template_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            rusqlite::params![id, rusqlite::types::Value::Null, name, entity_type, description, payload, now, now],
        ).map_err(sql_error)?;
    }
    Ok(())
}

fn validate_identifier(value: &str) -> ApiResult<()> {
    if value.is_empty()
        || !value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_')
    {
        return Err(ApiError::bad_request("invalid SQL identifier"));
    }
    Ok(())
}
fn table_columns(con: &Connection, table: &str) -> ApiResult<HashSet<String>> {
    validate_identifier(table)?;
    let mut stmt = con
        .prepare(&format!("PRAGMA table_info({})", table))
        .map_err(sql_error)?;
    let rows = stmt
        .query_map([], |row| row.get::<_, String>(1))
        .map_err(sql_error)?;
    rows.collect::<Result<HashSet<_>, _>>().map_err(sql_error)
}
pub(crate) fn json_to_sql(value: &Value) -> ApiResult<SqlValue> {
    Ok(match value {
        Value::Null => SqlValue::Null,
        Value::Bool(v) => SqlValue::Integer(i64::from(*v)),
        Value::Number(v) if v.as_i64().is_some() => SqlValue::Integer(v.as_i64().unwrap()),
        Value::Number(v) => SqlValue::Real(
            v.as_f64()
                .ok_or_else(|| ApiError::bad_request("invalid number"))?,
        ),
        Value::String(v) => SqlValue::Text(v.clone()),
        Value::Array(_) | Value::Object(_) => SqlValue::Text(
            serde_json::to_string(value).map_err(|e| ApiError::bad_request(e.to_string()))?,
        ),
    })
}
fn row_to_json(row: &rusqlite::Row<'_>, names: &[String]) -> rusqlite::Result<Value> {
    let mut out = Map::new();
    for (i, name) in names.iter().enumerate() {
        let raw: SqlValue = row.get(i)?;
        let key = name.strip_suffix("_json").unwrap_or(name).to_owned();
        let value = if name.ends_with("_json") {
            match raw {
                SqlValue::Null => Value::Null,
                SqlValue::Text(s) => serde_json::from_str(&s).unwrap_or(Value::String(s)),
                _ => Value::Null,
            }
        } else if matches!(name.as_str(), "pinned" | "archived" | "builtin") {
            Value::Bool(matches!(raw, SqlValue::Integer(v) if v != 0))
        } else {
            match raw {
                SqlValue::Null => Value::Null,
                SqlValue::Integer(v) => Value::Number(v.into()),
                SqlValue::Real(v) => serde_json::Number::from_f64(v)
                    .map(Value::Number)
                    .unwrap_or(Value::Null),
                SqlValue::Text(v) => Value::String(v),
                SqlValue::Blob(v) => Value::String(String::from_utf8_lossy(&v).into_owned()),
            }
        };
        out.insert(key, value);
    }
    Ok(Value::Object(out))
}
fn sql_error(error: rusqlite::Error) -> ApiError {
    ApiError::internal(error.to_string())
}
fn now_string() -> String {
    chrono::Utc::now().to_rfc3339()
}
fn slugify(value: &str) -> String {
    let mut slug = String::new();
    for ch in value.chars() {
        if ch.is_ascii_alphanumeric() {
            slug.push(ch.to_ascii_lowercase());
        } else if !slug.ends_with('-') {
            slug.push('-');
        }
    }
    let slug = slug.trim_matches('-');
    if slug.is_empty() {
        "untitled".into()
    } else {
        slug.to_owned()
    }
}
fn new_id() -> String {
    format!(
        "rust-{}-{}",
        now_string(),
        NEXT_ID.fetch_add(1, Ordering::Relaxed)
    )
}
trait OptionalRow<T> {
    fn optional(self) -> rusqlite::Result<Option<T>>;
}
impl<T> OptionalRow<T> for rusqlite::Result<T> {
    fn optional(self) -> rusqlite::Result<Option<T>> {
        match self {
            Ok(v) => Ok(Some(v)),
            Err(rusqlite::Error::QueryReturnedNoRows) => Ok(None),
            Err(e) => Err(e),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::env;

    fn temp_path(name: &str) -> PathBuf {
        env::temp_dir().join(format!(
            "arline-runtime-{}-{}-{}.db",
            name,
            std::process::id(),
            NEXT_ID.fetch_add(1, Ordering::Relaxed)
        ))
    }

    #[test]
    fn opens_schema_and_round_trips_json_fields() {
        let path = temp_path("crud");
        let store = Store::open(&path).expect("open");
        let row = store
            .insert(
                "projects",
                serde_json::json!({"name":"Test","slug":"test","settings":{"language":"id"}}),
            )
            .expect("insert");
        assert_eq!(row["name"], "Test");
        assert_eq!(row["settings"]["language"], "id");
        assert_eq!(
            store
                .get("projects", row["id"].as_str().unwrap())
                .expect("get")
                .unwrap()["slug"],
            "test"
        );
        let _ = fs::remove_file(path);
    }

    #[test]
    fn generated_slugs_are_unique_within_each_scope() {
        let path = temp_path("slugs");
        let store = Store::open(&path).expect("open");
        let first = store
            .insert("projects", serde_json::json!({"name":"Same Name"}))
            .expect("first");
        let second = store
            .insert("projects", serde_json::json!({"name":"Same Name"}))
            .expect("second");
        assert_eq!(first["slug"], "same-name");
        assert_eq!(second["slug"], "same-name-2");
        let _ = fs::remove_file(path);
    }

    #[test]
    fn rejects_existing_workspace_with_missing_required_column() {
        let path = temp_path("missing-column");
        let con = Connection::open(&path).expect("db");
        con.execute_batch(
            "CREATE TABLE workspace_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);\
             INSERT INTO workspace_meta VALUES('schema_version','6');\
             CREATE TABLE projects(id TEXT PRIMARY KEY,name TEXT NOT NULL);",
        )
        .expect("legacy db");
        drop(con);
        let result = Store::open(&path);
        assert!(result.is_err());
        assert!(result
            .err()
            .unwrap()
            .message
            .contains("missing required column"));
        let _ = fs::remove_file(path);
    }

    #[test]
    fn rejects_non_workspace_existing_database() {
        let path = temp_path("unknown");
        let con = Connection::open(&path).expect("db");
        con.execute("CREATE TABLE foreign_table (id TEXT PRIMARY KEY)", [])
            .expect("table");
        drop(con);
        assert!(Store::open(&path).is_err());
        let _ = fs::remove_file(path);
    }

    #[test]
    fn preserves_scoped_document_and_rejects_unknown_fields() {
        let path = temp_path("scope");
        let store = Store::open(&path).expect("open");
        let project = store
            .insert("projects", serde_json::json!({"name":"P","slug":"p"}))
            .expect("project");
        let document = store
            .insert(
                "workspace_documents",
                serde_json::json!({
                    "project_id": project["id"],
                    "title": "Scene",
                    "content": "body",
                    "status": "planned"
                }),
            )
            .expect("document");
        assert_eq!(document["project_id"], project["id"]);
        assert!(store
            .insert(
                "workspace_documents",
                serde_json::json!({"project_id": project["id"], "title":"Bad", "not_a_column":true})
            )
            .is_err());
        let _ = fs::remove_file(path);
    }

    #[test]
    fn backup_captures_wal_commits() {
        let path = temp_path("wal-backup");
        let con = Connection::open(&path).expect("connection");
        con.pragma_update(None, "journal_mode", "WAL").expect("wal");
        drop(con);
        let store = Store::open(&path).expect("open");
        store
            .insert("projects", serde_json::json!({"name":"WAL","slug":"wal"}))
            .expect("insert");
        let backup = backup_database(&path, 6).expect("backup");
        let backup_con = Connection::open(&backup).expect("backup db");
        let count: i64 = backup_con
            .query_row(
                "SELECT count(*) FROM projects WHERE slug='wal'",
                [],
                |row| row.get(0),
            )
            .expect("count");
        assert_eq!(count, 1);
        drop(backup_con);
        let _ = fs::remove_file(path);
        let _ = fs::remove_file(backup);
    }

    #[test]
    fn folder_delete_detaches_corrupt_foreign_links_and_removes_owned_tree() {
        let path = temp_path("folder-delete");
        let store = Store::open(&path).expect("open");
        let first = store
            .insert("projects", serde_json::json!({"name":"One","slug":"one"}))
            .expect("project");
        let second = store
            .insert("projects", serde_json::json!({"name":"Two","slug":"two"}))
            .expect("project");
        let root = store
            .insert(
                "workspace_folders",
                serde_json::json!({"project_id":first["id"],"name":"Root"}),
            )
            .expect("root");
        let child = store
            .insert(
                "workspace_folders",
                serde_json::json!({"project_id":first["id"],"parent_id":root["id"],"name":"Child"}),
            )
            .expect("child");
        let foreign = store
            .insert(
                "workspace_folders",
                serde_json::json!({"project_id":second["id"],"parent_id":root["id"],"name":"Foreign"}),
            )
            .expect("foreign");
        assert!(store
            .delete_folder(root["id"].as_str().unwrap())
            .expect("delete"));
        assert!(store
            .get("workspace_folders", child["id"].as_str().unwrap())
            .expect("child")
            .is_none());
        let foreign_after = store
            .get("workspace_folders", foreign["id"].as_str().unwrap())
            .expect("foreign")
            .expect("preserved");
        assert_eq!(foreign_after["parent_id"], Value::Null);
        let _ = fs::remove_file(path);
    }

    #[test]
    fn folder_update_rejects_cross_scope_and_cycles_but_allows_clear_parent() {
        let path = temp_path("folder-update");
        let store = Store::open(&path).expect("open");
        let first = store
            .insert("projects", serde_json::json!({"name":"One","slug":"one"}))
            .expect("project");
        let second = store
            .insert("projects", serde_json::json!({"name":"Two","slug":"two"}))
            .expect("project");
        let parent = store
            .insert(
                "workspace_folders",
                serde_json::json!({"project_id":first["id"],"name":"Parent"}),
            )
            .expect("parent");
        let child = store
            .insert("workspace_folders", serde_json::json!({"project_id":first["id"],"parent_id":parent["id"],"name":"Child"}))
            .expect("child");
        let foreign = store
            .insert(
                "workspace_folders",
                serde_json::json!({"project_id":second["id"],"name":"Foreign"}),
            )
            .expect("foreign");
        assert!(store
            .update_folder(
                parent["id"].as_str().unwrap(),
                &serde_json::json!({"parent_id": parent["id"]})
            )
            .is_err());
        assert!(store
            .update_folder(
                child["id"].as_str().unwrap(),
                &serde_json::json!({"parent_id": foreign["id"]})
            )
            .is_err());
        let cleared = store
            .update_folder(
                child["id"].as_str().unwrap(),
                &serde_json::json!({"parent_id": null}),
            )
            .expect("clear");
        assert_eq!(cleared["parent_id"], Value::Null);
        let _ = fs::remove_file(path);
    }
}
