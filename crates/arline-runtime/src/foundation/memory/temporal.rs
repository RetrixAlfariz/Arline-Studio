//! Temporal memory state, epistemic intervals, and story-thread projections.
use crate::{store::Store, ApiError, ApiResult};
use rusqlite::OptionalExtension;
use serde_json::{json, Value};

fn sql(e: rusqlite::Error) -> ApiError {
    ApiError::internal(e.to_string())
}
fn newid(prefix: &str) -> String {
    format!("{}-{}", prefix, uuid::Uuid::new_v4())
}
pub(crate) fn ensure(store: &Store) -> ApiResult<()> {
    store.connection()?.execute_batch(r#"
        CREATE TABLE IF NOT EXISTS current_state_projection(
            world_id TEXT NOT NULL, branch_id TEXT, owner_type TEXT NOT NULL,
            owner_id TEXT NOT NULL, state_key TEXT NOT NULL, value_json TEXT NOT NULL,
            source_type TEXT NOT NULL, source_id TEXT, authority TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(world_id,branch_id,owner_type,owner_id,state_key)
        );
        CREATE TABLE IF NOT EXISTS state_intervals(
            id TEXT PRIMARY KEY, world_id TEXT NOT NULL, branch_id TEXT,
            owner_type TEXT NOT NULL, owner_id TEXT NOT NULL, state_key TEXT NOT NULL,
            value_json TEXT NOT NULL, valid_from_event_id TEXT, valid_to_event_id TEXT,
            valid_from_world_time_json TEXT, valid_to_world_time_json TEXT,
            story_order_from REAL, story_order_to REAL, source_type TEXT NOT NULL,
            source_id TEXT, authority TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'accepted',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_state_intervals_lookup
            ON state_intervals(world_id,branch_id,owner_type,owner_id,state_key,story_order_from,story_order_to);
        CREATE TABLE IF NOT EXISTS epistemic_intervals(
            id TEXT PRIMARY KEY, world_id TEXT NOT NULL, branch_id TEXT,
            character_variant_id TEXT NOT NULL, topic_type TEXT NOT NULL, topic_id TEXT NOT NULL,
            state_type TEXT NOT NULL, value_json TEXT NOT NULL, confidence REAL NOT NULL DEFAULT 1.0,
            valid_from_event_id TEXT, valid_to_event_id TEXT,
            valid_from_world_time_json TEXT, valid_to_world_time_json TEXT,
            story_order_from REAL, story_order_to REAL, source_type TEXT NOT NULL,
            source_id TEXT, status TEXT NOT NULL DEFAULT 'accepted', created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_epistemic_lookup
            ON epistemic_intervals(world_id,branch_id,character_variant_id,topic_type,topic_id,state_type);
        CREATE TABLE IF NOT EXISTS story_threads(
            id TEXT PRIMARY KEY, project_id TEXT, world_id TEXT NOT NULL, branch_id TEXT,
            thread_type TEXT NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'open', authority TEXT NOT NULL DEFAULT 'user_accepted_world_canon',
            confidence REAL NOT NULL DEFAULT 1.0, source_type TEXT NOT NULL DEFAULT 'manual', source_id TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS story_thread_links(
            thread_id TEXT NOT NULL, resource_type TEXT NOT NULL, resource_id TEXT NOT NULL,
            relation TEXT NOT NULL DEFAULT 'related', PRIMARY KEY(thread_id,resource_type,resource_id)
        );
    "#).map_err(sql)
}
fn decoded(mut row: Value, key: &str, out: &str) -> Value {
    if row.get(out).is_some() {
        return row;
    }
    if let Some(raw) = row.get(key).and_then(Value::as_str) {
        if let Ok(value) = serde_json::from_str(raw) {
            row[out] = value;
        }
    }
    row
}
fn json_field(row: &Value, json_key: &str, decoded_key: &str) -> Value {
    row.get(decoded_key)
        .cloned()
        .or_else(|| {
            row.get(json_key)
                .and_then(Value::as_str)
                .and_then(|raw| serde_json::from_str(raw).ok())
        })
        .unwrap_or(Value::Null)
}

fn recorded_before_or_equal(recorded: Option<&str>, cutoff: Option<&str>) -> bool {
    let Some(limit) = cutoff else {
        return true;
    };
    let Some(value) = recorded else {
        return false;
    };
    match (
        chrono::DateTime::parse_from_rfc3339(value),
        chrono::DateTime::parse_from_rfc3339(limit),
    ) {
        (Ok(left), Ok(right)) => left <= right,
        _ => value <= limit,
    }
}

fn visible_timeline_events(
    store: &Store,
    world: &str,
    branch: Option<&str>,
) -> ApiResult<Vec<Value>> {
    let rows = store.query(
        "SELECT * FROM timeline_events WHERE world_id=? ORDER BY order_key,created_at,id",
        &[&world],
    )?;
    let mut cutoffs =
        std::collections::HashMap::<Option<String>, Option<String>>::from([(None, None)]);
    if let Some(target) = branch {
        let mut current = Some(target.to_owned());
        let mut child_created = None;
        let mut seen = std::collections::HashSet::new();
        while let Some(id) = current {
            if !seen.insert(id.clone()) {
                break;
            }
            let row = store
                .query("SELECT * FROM world_branches WHERE id=?", &[&id])?
                .into_iter()
                .next();
            let Some(row) = row else {
                break;
            };
            cutoffs.insert(Some(id), child_created.clone());
            child_created = row["created_at"].as_str().map(str::to_owned);
            current = row["parent_branch_id"].as_str().map(str::to_owned);
        }
    }
    Ok(rows
        .into_iter()
        .filter(|event| {
            let status = event["status"]
                .as_str()
                .unwrap_or_default()
                .to_ascii_lowercase();
            if status != "canon" && status != "accepted" {
                return false;
            }
            if event["owner_type"].as_str().is_none_or(str::is_empty)
                || event["owner_id"].as_str().is_none_or(str::is_empty)
            {
                return false;
            }
            let patch = json_field(event, "state_patch_json", "state_patch");
            if !patch.is_object() || patch.as_object().is_none_or(|v| v.is_empty()) {
                return false;
            }
            let event_branch = event["branch_id"].as_str().map(str::to_owned);
            let Some(cutoff) = cutoffs.get(&event_branch) else {
                return false;
            };
            cutoff.as_ref().is_none_or(|limit| {
                recorded_before_or_equal(event["created_at"].as_str(), Some(limit))
            })
        })
        .collect())
}

pub fn current_state(
    store: &Store,
    world: &str,
    branch: Option<&str>,
    owner_type: &str,
    owner_id: &str,
    state_key: Option<&str>,
) -> ApiResult<Value> {
    ensure(store)?;
    let mut sqlq="SELECT * FROM current_state_projection WHERE world_id=? AND branch_id IS ? AND owner_type=? AND owner_id=?".to_owned();
    let mut params: Vec<Box<dyn rusqlite::ToSql>> = vec![
        Box::new(world.to_owned()),
        Box::new(branch.map(str::to_owned)),
        Box::new(owner_type.to_owned()),
        Box::new(owner_id.to_owned()),
    ];
    if let Some(key) = state_key {
        sqlq.push_str(" AND state_key=?");
        params.push(Box::new(key.to_owned()));
    }
    sqlq.push_str(" ORDER BY state_key");
    let refs: Vec<&dyn rusqlite::ToSql> = params.iter().map(|p| p.as_ref()).collect();
    let rows = store.query(&sqlq, &refs)?;
    Ok(Value::Array(
        rows.into_iter()
            .map(|r| decoded(r, "value_json", "value"))
            .collect(),
    ))
}

pub fn state_at(
    store: &Store,
    world: &str,
    branch: Option<&str>,
    owner_type: &str,
    owner_id: &str,
    story_order: Option<f64>,
) -> ApiResult<Value> {
    ensure(store)?;
    let mut rows = if branch.is_some() {
        store.query("SELECT * FROM state_intervals WHERE world_id=? AND (branch_id IS NULL OR branch_id IS ?) AND owner_type=? AND owner_id=? AND status='accepted' ORDER BY state_key,story_order_from DESC", &[&world,&branch,&owner_type,&owner_id])?
    } else {
        store.query("SELECT * FROM state_intervals WHERE world_id=? AND branch_id IS NULL AND owner_type=? AND owner_id=? AND status='accepted' ORDER BY state_key,story_order_from DESC", &[&world,&owner_type,&owner_id])?
    };
    let mut seen = std::collections::HashSet::new();
    rows.retain(|r| {
        let key = r["state_key"].as_str().unwrap_or_default().to_owned();
        story_order.is_none_or(|at| {
            r["story_order_from"].as_f64().is_none_or(|from| from <= at)
                && r["story_order_to"].as_f64().is_none_or(|to| at < to)
        }) && seen.insert(key)
    });
    Ok(Value::Array(
        rows.into_iter()
            .map(|r| decoded(r, "value_json", "value"))
            .collect(),
    ))
}

/// Resolve interval visibility by a JSON world-time value rather than story order.
pub fn state_at_world_time(
    store: &Store,
    world: &str,
    branch: Option<&str>,
    owner_type: &str,
    owner_id: &str,
    world_time: &Value,
) -> ApiResult<Value> {
    ensure(store)?;
    let rows = if branch.is_some() {
        store.query("SELECT * FROM state_intervals WHERE world_id=? AND (branch_id IS NULL OR branch_id IS ?) AND owner_type=? AND owner_id=? AND status='accepted' ORDER BY state_key,story_order_from DESC", &[&world,&branch,&owner_type,&owner_id])?
    } else {
        store.query("SELECT * FROM state_intervals WHERE world_id=? AND branch_id IS NULL AND owner_type=? AND owner_id=? AND status='accepted' ORDER BY state_key,story_order_from DESC", &[&world,&owner_type,&owner_id])?
    };
    let wanted = world_time
        .as_f64()
        .or_else(|| world_time.as_str().and_then(|v| v.parse::<f64>().ok()));
    let mut seen = std::collections::HashSet::new();
    let mut visible = Vec::new();
    for row in rows {
        let key = row["state_key"].as_str().unwrap_or_default().to_owned();
        if seen.contains(&key) {
            continue;
        }
        let from = row["valid_from_world_time_json"]
            .as_str()
            .and_then(|v| serde_json::from_str::<Value>(v).ok())
            .and_then(|v| v.as_f64());
        let to = row["valid_to_world_time_json"]
            .as_str()
            .and_then(|v| serde_json::from_str::<Value>(v).ok())
            .and_then(|v| v.as_f64());
        if wanted
            .is_none_or(|at| from.is_none_or(|start| start <= at) && to.is_none_or(|end| at < end))
        {
            seen.insert(key);
            visible.push(decoded(row, "value_json", "value"));
        }
    }
    Ok(Value::Array(visible))
}

/// Rebuild the current state projection from canon facts and ordered timeline patches.
pub fn refresh_world(store: &Store, world: &str, branch: Option<&str>) -> ApiResult<Value> {
    ensure(store)?;
    let facts = if branch.is_some() {
        store.query(
            "SELECT * FROM canon_facts WHERE world_id=? AND branch_id IS ? AND status='canon' ORDER BY created_at,id",
            &[&world, &branch],
        )?
    } else {
        store.query(
            "SELECT * FROM canon_facts WHERE world_id=? AND branch_id IS NULL AND status='canon' ORDER BY created_at,id",
            &[&world],
        )?
    };
    let mut fact_by_key = std::collections::BTreeMap::<(String, String, String), Value>::new();
    for fact in facts {
        let owner_type = fact["owner_type"].as_str().unwrap_or_default();
        let owner_id = fact["owner_id"].as_str().unwrap_or_default();
        let path = fact["path"].as_str().unwrap_or_default();
        if owner_type.is_empty() || owner_id.is_empty() || path.is_empty() {
            continue;
        }
        fact_by_key.insert(
            (owner_type.to_owned(), owner_id.to_owned(), path.to_owned()),
            fact,
        );
    }
    let events = visible_timeline_events(store, world, branch)?;
    let mut states = std::collections::BTreeMap::<(String, String, String), Value>::new();
    let mut latest_sources = std::collections::BTreeMap::<(String, String, String), String>::new();
    for (key, fact) in &fact_by_key {
        states.insert(key.clone(), json_field(fact, "value_json", "value"));
    }
    for event in &events {
        let patch = json_field(event, "state_patch_json", "state_patch");
        let Some(items) = patch.as_object() else {
            continue;
        };
        let owner_type = event["owner_type"].as_str().unwrap_or("event");
        let owner_id = event["owner_id"]
            .as_str()
            .unwrap_or(event["id"].as_str().unwrap_or_default());
        for (key, value) in items {
            states.insert(
                (owner_type.to_owned(), owner_id.to_owned(), key.clone()),
                value.clone(),
            );
            latest_sources.insert(
                (owner_type.to_owned(), owner_id.to_owned(), key.clone()),
                event["id"].as_str().unwrap_or_default().to_owned(),
            );
        }
    }
    let now = chrono::Utc::now().to_rfc3339();
    let mut connection = store.connection()?;
    let con = connection.transaction_with_behavior(rusqlite::TransactionBehavior::Immediate)?;
    con.execute("DELETE FROM current_state_projection WHERE world_id=? AND branch_id IS ? AND source_type='timeline_event'", rusqlite::params![world, branch]).map_err(sql)?;
    con.execute("DELETE FROM state_intervals WHERE world_id=? AND branch_id IS ? AND source_type='timeline_event'", rusqlite::params![world, branch]).map_err(sql)?;
    let fact_ids: Vec<String> = fact_by_key
        .values()
        .filter_map(|fact| fact["id"].as_str().map(str::to_owned))
        .collect();
    if fact_ids.is_empty() {
        con.execute("DELETE FROM current_state_projection WHERE world_id=? AND branch_id IS ? AND source_type='canon_fact'", rusqlite::params![world, branch]).map_err(sql)?;
        con.execute("DELETE FROM state_intervals WHERE world_id=? AND branch_id IS ? AND source_type='canon_fact'", rusqlite::params![world, branch]).map_err(sql)?;
    } else {
        let marks = std::iter::repeat_n("?", fact_ids.len())
            .collect::<Vec<_>>()
            .join(",");
        let mut params: Vec<Box<dyn rusqlite::ToSql>> = vec![
            Box::new(world.to_owned()),
            Box::new(branch.map(str::to_owned)),
        ];
        params.extend(
            fact_ids
                .iter()
                .cloned()
                .map(|id| Box::new(id) as Box<dyn rusqlite::ToSql>),
        );
        let refs: Vec<&dyn rusqlite::ToSql> = params.iter().map(|p| p.as_ref()).collect();
        con.execute(&format!("DELETE FROM current_state_projection WHERE world_id=? AND branch_id IS ? AND source_type='canon_fact' AND source_id NOT IN ({marks})"), refs.as_slice()).map_err(sql)?;
        let refs: Vec<&dyn rusqlite::ToSql> = params.iter().map(|p| p.as_ref()).collect();
        con.execute(&format!("DELETE FROM state_intervals WHERE world_id=? AND branch_id IS ? AND source_type='canon_fact' AND source_id NOT IN ({marks})"), refs.as_slice()).map_err(sql)?;
    }
    // NULL branch keys do not collide under SQLite's composite primary key;
    // rebuild every derived canon-fact row to keep refresh idempotent.
    con.execute("DELETE FROM current_state_projection WHERE world_id=? AND branch_id IS ? AND source_type='canon_fact'", rusqlite::params![world, branch]).map_err(sql)?;
    con.execute("DELETE FROM state_intervals WHERE world_id=? AND branch_id IS ? AND source_type='canon_fact'", rusqlite::params![world, branch]).map_err(sql)?;
    for ((owner_type, owner_id, state_key), fact) in &fact_by_key {
        let manual = con.query_row("SELECT 1 FROM state_intervals WHERE world_id=? AND branch_id IS ? AND owner_type=? AND owner_id=? AND state_key=? AND status='accepted' AND source_type NOT IN ('timeline_event','canon_fact') LIMIT 1",rusqlite::params![world,branch,owner_type,owner_id,state_key],|row|row.get::<_,i64>(0)).optional().map_err(sql)?.is_some()
            || con.query_row("SELECT 1 FROM current_state_projection WHERE world_id=? AND branch_id IS ? AND owner_type=? AND owner_id=? AND state_key=? AND source_type NOT IN ('timeline_event','canon_fact') LIMIT 1",rusqlite::params![world,branch,owner_type,owner_id,state_key],|row|row.get::<_,i64>(0)).optional().map_err(sql)?.is_some();
        if manual {
            continue;
        }
        let value = json_field(fact, "value_json", "value");
        let source_id = fact["id"].as_str();
        con.execute("INSERT INTO state_intervals(id,world_id,branch_id,owner_type,owner_id,state_key,value_json,story_order_from,source_type,source_id,authority,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",rusqlite::params![newid("STATEINT"),world,branch,owner_type,owner_id,state_key,serde_json::to_string(&value).unwrap_or_else(|_|"null".to_owned()),Option::<f64>::None,"canon_fact",source_id,"user_accepted_world_canon","accepted",now]).map_err(sql)?;
        con.execute("INSERT INTO current_state_projection(world_id,branch_id,owner_type,owner_id,state_key,value_json,source_type,source_id,authority,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(world_id,branch_id,owner_type,owner_id,state_key) DO UPDATE SET value_json=excluded.value_json,source_type=excluded.source_type,source_id=excluded.source_id,authority=excluded.authority,updated_at=excluded.updated_at",rusqlite::params![world,branch,owner_type,owner_id,state_key,serde_json::to_string(&value).unwrap_or_else(|_|"null".to_owned()),"canon_fact",source_id,"user_accepted_world_canon",now]).map_err(sql)?;
    }
    let mut skipped = std::collections::HashSet::new();
    let mut diagnostics = Vec::new();
    for event in &events {
        let patch = json_field(event, "state_patch_json", "state_patch");
        let owner_type = event["owner_type"].as_str().unwrap_or_default();
        let owner_id = event["owner_id"].as_str().unwrap_or_default();
        for key in patch.as_object().into_iter().flat_map(|items| items.keys()) {
            if fact_by_key.contains_key(&(
                owner_type.to_owned(),
                owner_id.to_owned(),
                key.to_owned(),
            )) {
                skipped.insert((owner_type.to_owned(), owner_id.to_owned(), key.to_owned()));
                continue;
            }
            let interval = con.query_row("SELECT source_type,source_id FROM state_intervals WHERE world_id=? AND branch_id IS ? AND owner_type=? AND owner_id=? AND state_key=? AND status='accepted' AND source_type!='timeline_event' LIMIT 1",rusqlite::params![world,branch,owner_type,owner_id,key],|row|row.get::<_,String>(0)).optional().map_err(sql)?;
            let current = con.query_row("SELECT source_type,source_id FROM current_state_projection WHERE world_id=? AND branch_id IS ? AND owner_type=? AND owner_id=? AND state_key=? AND source_type!='timeline_event' LIMIT 1",rusqlite::params![world,branch,owner_type,owner_id,key],|row|row.get::<_,String>(0)).optional().map_err(sql)?;
            if (interval.is_some() || current.is_some())
                && skipped.insert((owner_type.to_owned(), owner_id.to_owned(), key.to_owned()))
            {
                let conflict = interval.or(current).unwrap_or_else(|| "manual".to_owned());
                diagnostics.push(format!(
                    "Skipped {}:{}.{} in branch {}: accepted state from {}.",
                    owner_type,
                    owner_id,
                    key,
                    branch.unwrap_or("<global>"),
                    conflict
                ));
            }
        }
    }
    for event in &events {
        let patch = json_field(event, "state_patch_json", "state_patch");
        let Some(items) = patch.as_object() else {
            continue;
        };
        let owner_type = event["owner_type"].as_str().unwrap_or("event");
        let owner_id = event["owner_id"]
            .as_str()
            .unwrap_or(event["id"].as_str().unwrap_or_default());
        for (key, value) in items {
            if skipped.contains(&(owner_type.to_owned(), owner_id.to_owned(), key.to_owned())) {
                continue;
            }
            let current_order = event["order_key"].as_f64();
            let next = events
                .iter()
                .filter_map(|next| {
                    let order = next["order_key"].as_f64()?;
                    let patch = json_field(next, "state_patch_json", "state_patch");
                    (order > current_order.unwrap_or(f64::NEG_INFINITY)
                        && patch.get(key).is_some()
                        && next["owner_type"].as_str() == Some(owner_type)
                        && next["owner_id"].as_str() == Some(owner_id))
                    .then_some((order, next))
                })
                .min_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
            let next_order = next.as_ref().map(|v| v.0);
            let next_event_id = next.as_ref().and_then(|v| v.1["id"].as_str());
            let from_time = event.get("time_label").filter(|v| !v.is_null());
            let to_time = next
                .as_ref()
                .and_then(|v| v.1.get("time_label"))
                .filter(|v| !v.is_null());
            con.execute("INSERT INTO state_intervals(id,world_id,branch_id,owner_type,owner_id,state_key,value_json,valid_from_event_id,valid_to_event_id,valid_from_world_time_json,valid_to_world_time_json,story_order_from,story_order_to,source_type,source_id,authority,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rusqlite::params![newid("STATEINT"),world,branch,owner_type,owner_id,key,serde_json::to_string(value).unwrap_or_else(|_|"null".to_owned()),event["id"].as_str(),next_event_id,from_time.map(|v| serde_json::to_string(v).unwrap_or_else(|_|"null".to_owned())),to_time.map(|v| serde_json::to_string(v).unwrap_or_else(|_|"null".to_owned())),current_order,next_order,"timeline_event",event["id"].as_str(),"accepted_event","accepted",now]).map_err(sql)?;
        }
    }
    for ((owner_type, owner_id, state_key), value) in &states {
        let key = (owner_type.clone(), owner_id.clone(), state_key.clone());
        if skipped.contains(&key) || !latest_sources.contains_key(&key) {
            continue;
        }
        con.execute("INSERT INTO current_state_projection(world_id,branch_id,owner_type,owner_id,state_key,value_json,source_type,source_id,authority,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(world_id,branch_id,owner_type,owner_id,state_key) DO UPDATE SET value_json=excluded.value_json,source_type=excluded.source_type,source_id=excluded.source_id,authority=excluded.authority,updated_at=excluded.updated_at",rusqlite::params![world,branch,owner_type,owner_id,state_key,serde_json::to_string(value).unwrap_or_else(|_|"null".to_owned()),"timeline_event",latest_sources.get(&(owner_type.clone(),owner_id.clone(),state_key.clone())),"accepted_event",now]).map_err(sql)?;
    }
    con.commit().map_err(sql)?;
    Ok(
        json!({"world_id":world,"branch_id":branch,"state_count":states.len(),"fact_count":fact_by_key.len(),"event_count":events.len(),"skipped_keys":skipped.len(),"diagnostics":diagnostics}),
    )
}

pub fn epistemic(
    store: &Store,
    world: &str,
    branch: Option<&str>,
    variant: &str,
    topic_type: Option<&str>,
    topic_id: Option<&str>,
    story_order: Option<f64>,
) -> ApiResult<Value> {
    ensure(store)?;
    let mut rows=store.query("SELECT * FROM epistemic_intervals WHERE world_id=? AND (branch_id IS NULL OR branch_id IS ?) AND character_variant_id=? AND status='accepted' ORDER BY created_at DESC", &[&world,&branch,&variant])?;
    rows.retain(|r| {
        topic_type.is_none_or(|x| r["topic_type"] == x)
            && topic_id.is_none_or(|x| r["topic_id"] == x)
            && story_order.is_none_or(|at| {
                r["story_order_from"].as_f64().is_none_or(|from| from <= at)
                    && r["story_order_to"].as_f64().is_none_or(|to| at < to)
            })
    });
    Ok(Value::Array(
        rows.into_iter()
            .map(|r| decoded(r, "value_json", "value"))
            .collect(),
    ))
}

pub fn threads(
    store: &Store,
    world: &str,
    branch: Option<&str>,
    status: Option<&str>,
    resource_type: Option<&str>,
    resource_id: Option<&str>,
) -> ApiResult<Value> {
    ensure(store)?;
    let mut rows=store.query("SELECT t.* FROM story_threads t WHERE t.world_id=? AND (t.branch_id IS NULL OR t.branch_id IS ?) ORDER BY t.updated_at DESC", &[&world,&branch])?;
    rows.retain(|r| status.is_none_or(|x| r["status"] == x));
    if let (Some(kind), Some(id)) = (resource_type, resource_id) {
        let linked = store.query(
            "SELECT thread_id FROM story_thread_links WHERE resource_type=? AND resource_id=?",
            &[&kind, &id],
        )?;
        let ids = linked
            .into_iter()
            .filter_map(|v| v["thread_id"].as_str().map(str::to_owned))
            .collect::<std::collections::HashSet<_>>();
        rows.retain(|r| ids.contains(r["id"].as_str().unwrap_or_default()));
    }
    for row in &mut rows {
        let id = row["id"].as_str().unwrap_or_default();
        row["links"] = Value::Array(
            store.query("SELECT * FROM story_thread_links WHERE thread_id=?", &[&id])?,
        );
    }
    Ok(Value::Array(rows))
}
