//! Bounded, scope checked context assembly for native generation.
//!
//! This module intentionally returns plain text.  It is a grounding boundary,
//! rather than a second prompt or WCF implementation: every record is selected
//! from the active project/world/branch and is labelled with its authority.

use crate::{ApiError, ApiResult, AppState};
use serde_json::{json, Value};

const DEFAULT_CHAR_CAP: usize = 12_000;
const MAX_CHAR_CAP: usize = 64_000;

fn text(value: Option<&Value>) -> Option<&str> {
    value
        .and_then(Value::as_str)
        .filter(|value| !value.trim().is_empty())
}

fn bad(message: impl Into<String>) -> ApiError {
    ApiError::bad_request(message)
}

fn project_world_linked(state: &AppState, project_id: &str, world_id: &str) -> ApiResult<bool> {
    let world = state
        .store
        .get("worlds", world_id)?
        .ok_or_else(|| bad("world_id does not exist"))?;
    if text(world.get("project_id")) == Some(project_id) {
        return Ok(true);
    }
    Ok(state
        .store
        .list(
            "project_world_links",
            &[
                ("project_id", json!(project_id)),
                ("world_id", json!(world_id)),
            ],
        )?
        .into_iter()
        .next()
        .is_some())
}

fn world_owner_project(state: &AppState, world_id: Option<&str>) -> ApiResult<Option<String>> {
    let Some(world_id) = world_id else {
        return Ok(None);
    };
    Ok(state
        .store
        .get("worlds", world_id)?
        .and_then(|world| text(world.get("project_id")).map(ToOwned::to_owned)))
}

fn project_owned(row: &Value, project_id: &str, world_owner: Option<&str>) -> bool {
    let owner = text(row.get("project_id"));
    owner == Some(project_id) || world_owner.is_some_and(|world_owner| owner == Some(world_owner))
}

fn row_field<'a>(row: &'a Value, keys: &[&str]) -> Option<&'a Value> {
    keys.iter().find_map(|key| row.get(*key))
}

fn validate_scope(
    state: &AppState,
    body: &Value,
) -> ApiResult<(String, Option<String>, Option<String>)> {
    let project_id = text(body.get("project_id"))
        .ok_or_else(|| bad("project_id is required to build generation context"))?
        .to_owned();
    if state.store.get("projects", &project_id)?.is_none() {
        return Err(bad("project_id does not exist"));
    }
    let world_id = text(body.get("world_id")).map(ToOwned::to_owned);
    let branch_id = text(body.get("branch_id")).map(ToOwned::to_owned);
    if let Some(world_id) = world_id.as_deref() {
        if !project_world_linked(state, &project_id, world_id)? {
            return Err(bad("world_id is not owned by or linked to project_id"));
        }
    }
    if let Some(branch_id) = branch_id.as_deref() {
        let world_id = world_id
            .as_deref()
            .ok_or_else(|| bad("world_id is required when branch_id is set"))?;
        let branch = state
            .store
            .get("world_branches", branch_id)?
            .ok_or_else(|| bad("branch_id does not exist"))?;
        if text(branch.get("world_id")) != Some(world_id) {
            return Err(bad("branch_id does not belong to world_id"));
        }
    }
    Ok((project_id, world_id, branch_id))
}

fn scope_matches_owned(
    row: &Value,
    project_id: &str,
    world_owner: Option<&str>,
    world_id: Option<&str>,
    branch_id: Option<&str>,
) -> bool {
    if !project_owned(row, project_id, world_owner) {
        return false;
    }
    let row_world = text(row.get("world_id"));
    let row_branch = text(row.get("branch_id"));
    if world_id.is_some_and(|world| row_world.is_some_and(|row_world| row_world != world))
        || world_id.is_none() && row_world.is_some()
    {
        return false;
    }
    if branch_id.is_some_and(|branch| row_branch.is_some_and(|row_branch| row_branch != branch))
        || branch_id.is_none() && row_branch.is_some()
    {
        return false;
    }
    true
}

fn variant_scope_matches(row: &Value, world_id: Option<&str>, branch_id: Option<&str>) -> bool {
    let Some(world) = world_id else { return false };
    text(row.get("world_id")) == Some(world)
        && (branch_id.is_none()
            || text(row.get("branch_id")) == branch_id
            || text(row.get("branch_id")).is_none())
}

fn reference_scope_ok(
    state: &AppState,
    reference: &Value,
    project_id: &str,
    world_id: Option<&str>,
    branch_id: Option<&str>,
) -> ApiResult<Value> {
    let typ = text(reference.get("type")).ok_or_else(|| bad("reference type is required"))?;
    let id = text(reference.get("id")).ok_or_else(|| bad("reference id is required"))?;
    let global = reference
        .get("global")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let table = match typ {
        "project" => "projects",
        "world" => "worlds",
        "branch" | "world_branch" => "world_branches",
        "document" | "scene" => "workspace_documents",
        "entity_family" | "family" => "entity_families",
        "entity_variant" | "variant" => "entity_variants",
        "relationship" => "relationships",
        "fact" | "canon_fact" => "canon_facts",
        _ => return Err(bad(format!("unsupported reference type '{typ}'"))),
    };
    let row = state
        .store
        .get(table, id)?
        .ok_or_else(|| bad(format!("reference {typ}/{id} does not exist")))?;
    let world_owner = world_owner_project(state, world_id)?;
    let valid = match typ {
        "project" => text(row.get("id")) == Some(project_id),
        "world" => {
            let owner = text(row.get("project_id"));
            owner == Some(project_id)
                || state
                    .store
                    .list(
                        "project_world_links",
                        &[("project_id", json!(project_id)), ("world_id", json!(id))],
                    )?
                    .into_iter()
                    .next()
                    .is_some()
        }
        "branch" | "world_branch" => {
            if let Some(world) = text(row.get("world_id")) {
                world_id.is_some_and(|selected| selected == world)
                    && project_world_linked(state, project_id, world)?
            } else {
                false
            }
        }
        "entity_family" | "family" => project_owned(&row, project_id, world_owner.as_deref()),
        "entity_variant" | "variant" => {
            let family_id = text(row.get("family_id"));
            let family = family_id
                .and_then(|family_id| state.store.get("entity_families", family_id).ok().flatten());
            text(family.as_ref().and_then(|family| family.get("project_id")))
                .is_some_and(|owner| owner == project_id || world_owner.as_deref() == Some(owner))
                && variant_scope_matches(&row, world_id, branch_id)
        }
        "relationship" => {
            let matches = world_id.is_some_and(|world| text(row.get("world_id")) == Some(world))
                && (branch_id.is_none()
                    || text(row.get("branch_id")).is_none()
                    || text(row.get("branch_id")) == branch_id);
            if !matches {
                false
            } else {
                let subject = text(row_field(&row, &["subject_variant_id", "from_variant_id"]))
                    .and_then(|id| state.store.get("entity_variants", id).ok().flatten());
                let family = subject
                    .as_ref()
                    .and_then(|variant| text(variant.get("family_id")))
                    .and_then(|id| state.store.get("entity_families", id).ok().flatten());
                text(family.as_ref().and_then(|family| family.get("project_id"))).is_some_and(
                    |owner| owner == project_id || world_owner.as_deref() == Some(owner),
                )
            }
        }
        "document" | "scene" | "fact" | "canon_fact" => scope_matches_owned(
            &row,
            project_id,
            world_owner.as_deref(),
            world_id,
            branch_id,
        ),
        _ => false,
    };
    if !valid && !global {
        return Err(bad(format!(
            "reference {typ}/{id} is outside the active scope"
        )));
    }
    Ok(json!({"type": typ, "id": id, "global": global, "row": row}))
}

fn safe_collaboration_profile(state: &AppState, mode: &str, prompt: &str) -> ApiResult<Value> {
    let row = state.store.get("user_profiles", "default")?;
    let Some(profile) = row.and_then(|row| row.get("profile").cloned()) else {
        return Ok(json!({}));
    };
    Ok(sanitize_profile_projection(
        &crate::profile::personalization(&profile, mode, prompt),
    ))
}

fn profile_private_key(key: &str) -> bool {
    let lower = key.to_ascii_lowercase();
    [
        "private",
        "sensitive",
        "secret",
        "password",
        "email",
        "phone",
        "address",
    ]
    .iter()
    .any(|part| lower.contains(part))
}

fn sanitize_profile_projection(value: &Value) -> Value {
    match value {
        Value::Object(map) => {
            let mut clean = serde_json::Map::new();
            for (key, child) in map {
                if profile_private_key(key)
                    || child
                        .get("sensitive")
                        .and_then(Value::as_bool)
                        .unwrap_or(false)
                {
                    continue;
                }
                clean.insert(key.clone(), sanitize_profile_projection(child));
            }
            Value::Object(clean)
        }
        Value::Array(items) => Value::Array(
            items
                .iter()
                .map(sanitize_profile_projection)
                .filter(|item| !item.is_null())
                .collect(),
        ),
        other => other.clone(),
    }
}

fn append_bounded(out: &mut String, cap: usize, label: &str, value: &Value) {
    if out.chars().count() >= cap {
        return;
    }
    let encoded = serde_json::to_string(value).unwrap_or_else(|_| "{}".to_owned());
    let line = format!("{label}: {encoded}\n");
    let remaining = cap.saturating_sub(out.chars().count());
    if line.chars().count() <= remaining {
        out.push_str(&line);
    } else if remaining > 1 {
        out.push_str(&line.chars().take(remaining - 1).collect::<String>());
        out.push('\n');
    }
}

fn char_cap(state: &AppState) -> usize {
    let config = state.runtime_config().ok();
    let configured = config
        .as_ref()
        .map(|config| {
            config.u64(
                "context_budget.max_chars",
                config.u64("history.continuity_chars", DEFAULT_CHAR_CAP as u64),
            )
        })
        .unwrap_or(DEFAULT_CHAR_CAP as u64);
    (configured as usize).clamp(512, MAX_CHAR_CAP)
}

/// Build bounded generation grounding from an explicit, validated workspace scope.
pub fn build_context(state: &AppState, body: &Value) -> ApiResult<String> {
    let (project_id, world_id, branch_id) = validate_scope(state, body)?;
    let world_owner = world_owner_project(state, world_id.as_deref())?;
    let cap = char_cap(state);
    let closing = "</ARLINE_CONTEXT>";
    let content_cap = cap.saturating_sub(closing.chars().count());
    let mut output = format!(
        "<ARLINE_CONTEXT>\nSCOPE: project={project_id} world={} branch={}\n",
        world_id.as_deref().unwrap_or("global"),
        branch_id.as_deref().unwrap_or("global")
    );

    let references = body
        .get("references")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let mut selected = Vec::new();
    for reference in references {
        selected.push(reference_scope_ok(
            state,
            &reference,
            &project_id,
            world_id.as_deref(),
            branch_id.as_deref(),
        )?);
    }
    for reference in selected {
        append_bounded(&mut output, content_cap, "REFERENCE", &reference);
    }

    if let Some(active) = state
        .store
        .list(
            "project_active_scenes",
            &[("project_id", json!(&project_id))],
        )?
        .into_iter()
        .next()
    {
        if active
            .get("world_id")
            .is_none_or(|value| value.is_null() || text(Some(value)) == world_id.as_deref())
            && active
                .get("branch_id")
                .is_none_or(|value| value.is_null() || text(Some(value)) == branch_id.as_deref())
        {
            if let Some(document_id) =
                text(row_field(&active, &["scene_document_id", "document_id"]))
            {
                if let Some(document) = state.store.get("workspace_documents", document_id)? {
                    if scope_matches_owned(
                        &document,
                        &project_id,
                        world_owner.as_deref(),
                        world_id.as_deref(),
                        branch_id.as_deref(),
                    ) {
                        append_bounded(
                            &mut output,
                            content_cap,
                            "ACTIVE_SCENE",
                            &json!({"title":document["title"],"content":document["content"],"status":document["status"],"authority":"workspace_document"}),
                        );
                    }
                }
            }
        }
    }

    for fact in state.store.list("canon_facts", &[])? {
        if scope_matches_owned(
            &fact,
            &project_id,
            world_owner.as_deref(),
            world_id.as_deref(),
            branch_id.as_deref(),
        ) && text(fact.get("status")) == Some("canon")
        {
            append_bounded(
                &mut output,
                content_cap,
                "CANON_FACT",
                &json!({"path":fact["path"],"value":fact["value"],"authority":fact["authority"],"status":fact["status"]}),
            );
        }
    }

    if let Some(world) = world_id.as_deref() {
        for variant in state
            .store
            .list("entity_variants", &[("world_id", json!(world))])?
        {
            if !variant_scope_matches(&variant, Some(world), branch_id.as_deref())
                || text(variant.get("canon_status")) != Some("canon")
            {
                continue;
            }
            let Some(family_id) = text(variant.get("family_id")) else {
                continue;
            };
            let Some(family) = state.store.get("entity_families", family_id)? else {
                continue;
            };
            if !project_owned(&family, &project_id, world_owner.as_deref()) {
                continue;
            }
            append_bounded(
                &mut output,
                content_cap,
                "ENTITY_VARIANT",
                &json!({"name":variant["display_name"],"summary":variant["summary"],"attributes":variant["attributes"],"current_state":variant["current_state"],"family":family["name"],"authority":"canon"}),
            );
        }
        for relationship in state
            .store
            .list("relationships", &[("world_id", json!(world))])?
        {
            if branch_id.is_some()
                && text(relationship.get("branch_id"))
                    .is_some_and(|branch| Some(branch) != branch_id.as_deref())
            {
                continue;
            }
            if text(relationship.get("canon_status")) != Some("canon") {
                continue;
            }
            let subject_id = text(row_field(
                &relationship,
                &["subject_variant_id", "from_variant_id"],
            ));
            let Some(subject) =
                subject_id.and_then(|id| state.store.get("entity_variants", id).ok().flatten())
            else {
                continue;
            };
            let family_id = text(subject.get("family_id"));
            let Some(family) =
                family_id.and_then(|id| state.store.get("entity_families", id).ok().flatten())
            else {
                continue;
            };
            if !project_owned(&family, &project_id, world_owner.as_deref()) {
                continue;
            }
            let subject = row_field(&relationship, &["subject_variant_id", "from_variant_id"])
                .cloned()
                .unwrap_or(Value::Null);
            let object = row_field(&relationship, &["object_variant_id", "to_variant_id"])
                .cloned()
                .unwrap_or(Value::Null);
            append_bounded(
                &mut output,
                content_cap,
                "RELATIONSHIP",
                &json!({"subject_variant_id":subject,"object_variant_id":object,"relation_type":relationship["relation_type"],"attributes":relationship["attributes"],"authority":"canon"}),
            );
        }
    }

    let collaboration = safe_collaboration_profile(
        state,
        body.get("conversation_mode")
            .and_then(Value::as_str)
            .unwrap_or("story_writer"),
        body.get("prompt").and_then(Value::as_str).unwrap_or(""),
    )?;
    if collaboration
        .as_object()
        .is_some_and(|value| !value.is_empty())
    {
        append_bounded(
            &mut output,
            content_cap,
            "AUTHOR_COLLABORATION",
            &collaboration,
        );
    }
    if output.chars().count() > content_cap {
        output = output.chars().take(content_cap).collect();
    }
    output.push_str(closing);
    Ok(output)
}
