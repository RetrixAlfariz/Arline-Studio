//! Durable change notifications keep derived memory and temporal caches in step
//! with every workspace writer, including transactional clone/restore operations.
use crate::{foundation::memory, store::Store, ApiResult, AppState};
use std::collections::BTreeSet;

pub fn initialize(store: &Store) -> ApiResult<()> {
    let connection = store.connection()?;
    connection.execute_batch("CREATE TABLE IF NOT EXISTS native_change_queue(id INTEGER PRIMARY KEY AUTOINCREMENT,source_type TEXT NOT NULL,source_id TEXT NOT NULL,world_id TEXT,branch_id TEXT)")?;
    for (table, source) in [
        ("workspace_documents", "document"),
        ("entity_variants", "entity_variant"),
        ("canon_facts", "canon_fact"),
        ("relationships", "relationship"),
        ("timeline_events", "timeline_event"),
    ] {
        for (operation, record) in [("INSERT", "NEW"), ("UPDATE", "NEW"), ("DELETE", "OLD")] {
            connection.execute_batch(&format!(
                "CREATE TRIGGER IF NOT EXISTS native_{table}_{operation} AFTER {operation} ON {table} BEGIN INSERT INTO native_change_queue(source_type,source_id,world_id,branch_id) VALUES('{source}',{record}.id,{record}.world_id,{record}.branch_id); END;"
            ))?;
        }
        // Moving a resource must invalidate projections in its previous scope too.
        connection.execute_batch(&format!(
            "CREATE TRIGGER IF NOT EXISTS native_{table}_old_scope AFTER UPDATE ON {table} WHEN OLD.world_id IS NOT NEW.world_id OR OLD.branch_id IS NOT NEW.branch_id BEGIN INSERT INTO native_change_queue(source_type,source_id,world_id,branch_id) VALUES('{source}',OLD.id,OLD.world_id,OLD.branch_id); END;"
        ))?;
    }
    Ok(())
}

pub fn flush(state: &AppState) -> ApiResult<()> {
    let _guard = state
        .projection_gate
        .lock()
        .map_err(|_| crate::ApiError::internal("Projection refresh lock poisoned"))?;
    let changes = state
        .store
        .query("SELECT * FROM native_change_queue ORDER BY id", &[])?;
    let Some(last) = changes.last().and_then(|row| row["id"].as_i64()) else {
        return Ok(());
    };
    let mut sources = BTreeSet::new();
    let mut worlds = BTreeSet::new();
    for change in changes {
        if let (Some(kind), Some(id)) =
            (change["source_type"].as_str(), change["source_id"].as_str())
        {
            sources.insert((kind.to_owned(), id.to_owned()));
        }
        if let Some(world) = change["world_id"].as_str() {
            worlds.insert(world.to_owned());
        }
    }
    for (kind, id) in sources {
        memory::refresh_source(state, &kind, &id)?;
    }
    for world in worlds {
        if state.store.get("worlds", &world)?.is_none() {
            for table in ["current_state_projection", "state_intervals"] {
                state
                    .store
                    .execute(&format!("DELETE FROM {table} WHERE world_id=?"), &[&world])?;
            }
            continue;
        }
        memory::temporal::refresh_world(&state.store, &world, None)?;
        for branch in state
            .store
            .list("world_branches", &[("world_id", serde_json::json!(world))])?
        {
            if let Some(id) = branch["id"].as_str() {
                memory::temporal::refresh_world(&state.store, &world, Some(id))?;
            }
        }
    }
    state
        .store
        .execute("DELETE FROM native_change_queue WHERE id<=?", &[&last])?;
    Ok(())
}
