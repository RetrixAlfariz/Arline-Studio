//! Spatial memory graph queries matching `src/memory/spatial.py`.
use crate::{store::Store, ApiError, ApiResult};
use serde_json::{json, Value};
use std::collections::{HashSet, VecDeque};

fn sql(e: rusqlite::Error) -> ApiError {
    ApiError::internal(e.to_string())
}

pub(crate) fn ensure(store: &Store) -> ApiResult<()> {
    store.connection()?.execute_batch(r#"
        CREATE TABLE IF NOT EXISTS spatial_edges(
            id TEXT PRIMARY KEY, world_id TEXT NOT NULL, branch_id TEXT,
            subject_type TEXT NOT NULL, subject_id TEXT NOT NULL, relation TEXT NOT NULL,
            object_type TEXT NOT NULL, object_id TEXT NOT NULL, structural INTEGER NOT NULL DEFAULT 1,
            valid_from_event_id TEXT, valid_to_event_id TEXT,
            valid_from_world_time_json TEXT, valid_to_world_time_json TEXT,
            story_order_from REAL, story_order_to REAL,
            authority TEXT NOT NULL DEFAULT 'user_accepted_world_canon', confidence REAL NOT NULL DEFAULT 1.0,
            status TEXT NOT NULL DEFAULT 'accepted', source_type TEXT NOT NULL DEFAULT 'manual', source_id TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_spatial_edges_subject ON spatial_edges(world_id,branch_id,subject_type,subject_id,relation,status);
        CREATE INDEX IF NOT EXISTS idx_spatial_edges_object ON spatial_edges(world_id,branch_id,object_type,object_id,relation,status);
    "#).map_err(sql)
}

fn edges(
    store: &Store,
    world: &str,
    branch: Option<&str>,
    node: &(String, String),
) -> ApiResult<Vec<Value>> {
    let rows = store.query("SELECT * FROM spatial_edges WHERE world_id=? AND (branch_id IS NULL OR branch_id IS ?) AND status='accepted' AND ((subject_type=? AND subject_id=?) OR (object_type=? AND object_id=?)) ORDER BY structural DESC,created_at", &[&world, &branch, &node.0, &node.1, &node.0, &node.1])?;
    Ok(rows
        .into_iter()
        .map(|mut row| {
            if let Some(v) = row.get_mut("structural") {
                *v = json!(v.as_i64().unwrap_or(0) != 0);
            }
            row
        })
        .collect())
}

/// Return a depth-limited BFS neighborhood, preserving the Python response shape.
pub fn neighborhood(
    store: &Store,
    world: &str,
    branch: Option<&str>,
    resource_type: &str,
    resource_id: &str,
    depth: i64,
) -> ApiResult<Value> {
    ensure(store)?;
    let depth = depth.clamp(0, 8) as usize;
    let root = (resource_type.to_owned(), resource_id.to_owned());
    let mut nodes = HashSet::from([root.clone()]);
    let mut frontier = VecDeque::from([(root, 0usize)]);
    let mut seen_edges = HashSet::new();
    let mut result_edges = Vec::new();
    while let Some((node, level)) = frontier.pop_front() {
        if level >= depth {
            continue;
        }
        for edge in edges(store, world, branch, &node)? {
            let id = edge
                .get("id")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_owned();
            if seen_edges.insert(id) {
                result_edges.push(edge.clone());
            }
            for pair in [
                (edge["subject_type"].clone(), edge["subject_id"].clone()),
                (edge["object_type"].clone(), edge["object_id"].clone()),
            ] {
                let next = (
                    pair.0.as_str().unwrap_or_default().to_owned(),
                    pair.1.as_str().unwrap_or_default().to_owned(),
                );
                if nodes.insert(next.clone()) {
                    frontier.push_back((next, level + 1));
                }
            }
        }
    }
    let mut node_values: Vec<Value> = nodes
        .into_iter()
        .map(|(kind, id)| json!({"type":kind,"id":id}))
        .collect();
    node_values.sort_by_key(|v| v.to_string());
    Ok(
        json!({"root":{"type":resource_type,"id":resource_id},"nodes":node_values,"edges":result_edges}),
    )
}

/// Return the shortest undirected edge path between two resources.
#[allow(clippy::too_many_arguments)]
pub fn path(
    store: &Store,
    world: &str,
    branch: Option<&str>,
    start_type: &str,
    start_id: &str,
    target_type: &str,
    target_id: &str,
    max_depth: i64,
) -> ApiResult<Value> {
    let graph = neighborhood(store, world, branch, start_type, start_id, max_depth)?;
    let target = (target_type, target_id);
    let mut adjacency = std::collections::HashMap::<(String, String), Vec<(String, Value)>>::new();
    for edge in graph["edges"].as_array().into_iter().flatten() {
        let left = (
            edge["subject_type"].as_str().unwrap_or_default().to_owned(),
            edge["subject_id"].as_str().unwrap_or_default().to_owned(),
        );
        let right = (
            edge["object_type"].as_str().unwrap_or_default().to_owned(),
            edge["object_id"].as_str().unwrap_or_default().to_owned(),
        );
        adjacency
            .entry(left.clone())
            .or_default()
            .push((format!("{}\u{1f}{}", right.0, right.1), edge.clone()));
        adjacency
            .entry(right)
            .or_default()
            .push((format!("{}\u{1f}{}", left.0, left.1), edge.clone()));
    }
    let start = (start_type.to_owned(), start_id.to_owned());
    let target_key = format!("{}\u{1f}{}", target.0, target.1);
    let mut queue = VecDeque::from([(start.clone(), Vec::<Value>::new())]);
    let mut seen = HashSet::from([start]);
    while let Some((node, trail)) = queue.pop_front() {
        if format!("{}\u{1f}{}", node.0, node.1) == target_key {
            return Ok(Value::Array(trail));
        }
        if trail.len() >= max_depth.max(0) as usize {
            continue;
        }
        for (next_key, edge) in adjacency.get(&node).into_iter().flatten() {
            let Some((next_type, next_id)) = next_key.split_once('\u{1f}') else {
                continue;
            };
            let next = (next_type.to_owned(), next_id.to_owned());
            if seen.insert(next.clone()) {
                let mut next_trail = trail.clone();
                next_trail.push(edge.clone());
                queue.push_back((next, next_trail));
            }
        }
    }
    Ok(Value::Array(Vec::new()))
}
