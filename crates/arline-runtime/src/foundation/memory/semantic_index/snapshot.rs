use super::*;

pub(super) enum Eligibility {
    Current(Snapshot),
    NeedsRefresh,
    Excluded,
}
#[derive(Clone, Debug)]
pub(super) struct Snapshot {
    pub chunk: Value,
    pub source_stamp: String,
}

/// Uses the caller's connection, including the IMMEDIATE commit transaction.
/// It rechecks authoritative source content, not just a lagging memory projection.
pub(super) fn capture(connection: &Connection, chunk: &Value) -> ApiResult<Eligibility> {
    if chunk["semantic_status"] != "active"
        || chunk["trust_level"] == "quarantined"
        || chunk["authority"] == "scratch"
    {
        return Ok(Eligibility::Excluded);
    }
    let kind = chunk["source_type"].as_str().unwrap_or_default();
    let table = match kind {
        "document" => "workspace_documents",
        "entity_variant" => "entity_variants",
        "canon_fact" => "canon_facts",
        "relationship" => "relationships",
        "timeline_event" => "timeline_events",
        "turn" | "chat_window" => "turns",
        _ => return Ok(Eligibility::Excluded),
    };
    let id = chunk["source_id"].as_str().unwrap_or_default();
    let Some(source) = query_connection(
        connection,
        &format!("SELECT * FROM {table} WHERE id=?"),
        &[&id],
    )?
    .pop() else {
        return Ok(Eligibility::Excluded);
    };
    let mut source_rows = vec![source.clone()];
    let owner_ref = match kind {
        "entity_variant" => Some(("entity_families", "family_id")),
        "turn" | "chat_window" => Some(("sessions", "session_id")),
        _ => Some(("worlds", "world_id")),
    };
    if let Some((table, key)) = owner_ref {
        if let Some(id) = source[key].as_str() {
            let Some(row) = query_connection(
                connection,
                &format!("SELECT * FROM {table} WHERE id=?"),
                &[&id],
            )?
            .pop() else {
                return Ok(Eligibility::Excluded);
            };
            source_rows.push(row);
        }
    }
    if source_rows
        .iter()
        .any(|row| row["archived"] == true || row["scratch_mode"] == true)
    {
        return Ok(Eligibility::Excluded);
    }
    let mut owners = vec![(
        if kind == "canon_fact" {
            "fact"
        } else if matches!(kind, "turn" | "chat_window") {
            "turn"
        } else {
            kind
        },
        id.to_owned(),
    )];
    for (key, owner) in [
        ("project_id", "project"),
        ("world_id", "world"),
        ("branch_id", "branch"),
        ("session_id", "session"),
        ("family_id", "entity_family"),
    ] {
        for row in source_rows.iter().chain(std::iter::once(chunk)) {
            if let Some(value) = row[key].as_str() {
                owners.push((owner, value.into()));
            }
        }
    }
    let mut roots = source_rows
        .iter()
        .filter_map(|row| row["folder_id"].as_str().map(str::to_owned))
        .collect::<Vec<_>>();
    roots.sort();
    roots.dedup();
    for root in roots {
        let mut folder = Some(root);
        let mut seen = HashSet::new();
        while let Some(id) = folder {
            if !seen.insert(id.clone()) {
                return Ok(Eligibility::Excluded);
            }
            owners.push(("folder", id.clone()));
            let next = query_connection(
                connection,
                "SELECT * FROM workspace_folders WHERE id=?",
                &[&id],
            )?
            .pop();
            folder = next
                .as_ref()
                .and_then(|row| row["parent_id"].as_str().map(str::to_owned));
            if let Some(row) = next {
                source_rows.push(row);
            }
        }
    }
    for (owner, id) in owners {
        let hidden:i64=connection.query_row("SELECT count(*) FROM resource_lifecycle WHERE resource_type=? AND resource_id=? AND (trashed_at IS NOT NULL OR archived_at IS NOT NULL)",params![owner,id],|r|r.get(0))?;
        if hidden > 0 {
            return Ok(Eligibility::Excluded);
        }
    }
    let text = super::super::source_text(kind, &source);
    let revision = format!("base_sha256:{}", digest(&text));
    let chunk_text = chunk["text"].as_str().unwrap_or_default();
    if chunk["source_revision"] != revision || chunk["checksum"] != digest(chunk_text) {
        return Ok(Eligibility::NeedsRefresh);
    }
    // A direct source move cannot retain its old project's index eligibility.
    let project = source_rows
        .iter()
        .find_map(|row| row["project_id"].as_str().filter(|s| !s.is_empty()));
    if project != chunk["project_id"].as_str().filter(|s| !s.is_empty()) {
        return Ok(Eligibility::NeedsRefresh);
    }
    Ok(Eligibility::Current(Snapshot {
        chunk: chunk.clone(),
        source_stamp: digest(
            &serde_json::to_string(&source_rows).map_err(|e| invalid(e.to_string()))?,
        ),
    }))
}

pub(super) fn unchanged(connection: &Connection, captured: &Snapshot) -> ApiResult<bool> {
    let id = captured.chunk["id"].as_str().unwrap_or_default();
    let Some(current) =
        query_connection(connection, "SELECT * FROM memory_chunks WHERE id=?", &[&id])?.pop()
    else {
        return Ok(false);
    };
    for field in [
        "source_revision",
        "checksum",
        "chunker_version",
        "project_id",
        "world_id",
        "branch_id",
        "session_id",
        "source_type",
        "source_id",
        "authority",
        "trust_level",
    ] {
        if current[field] != captured.chunk[field] {
            return Ok(false);
        }
    }
    Ok(
        matches!(capture(connection,&current)?,Eligibility::Current(ref snap) if snap.source_stamp==captured.source_stamp),
    )
}
