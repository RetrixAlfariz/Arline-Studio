//! Stateful workspace routes which are shared by the web and native clients.
//! This module deliberately uses the Store boundary so JSON columns, scope
//! validation and SQLite error mapping remain consistent with legacy routes.
use crate::{ApiError, ApiResult, AppState};
use rusqlite::params;
use serde_json::{json, Map, Value};
use std::collections::HashMap;
use uuid::Uuid;

pub fn handle(
    state: &AppState,
    method: &str,
    path: &[&str],
    query: &HashMap<String, String>,
    body: &Value,
) -> Option<ApiResult<Value>> {
    let m = method.to_ascii_uppercase();
    let h = *path.first()?;
    let owned = matches!(
        h,
        "worlds"
            | "branches"
            | "entities"
            | "snapshots"
            | "projects"
            | "overlays"
            | "staged-changes"
            | "timeline"
            | "scenes"
            | "tags"
            | "context"
            | "canon"
            | "retcon"
            | "complexdomain"
            | "backlinks"
    );
    if !owned {
        return None;
    }
    let r = match (m.as_str(), h) {
        ("POST", "worlds") if path.get(2) == Some(&"fork") => fork_world(state, path[1], body),
        ("POST", "worlds") if path.get(2) == Some(&"sandbox") => sandbox(state, path[1], query),
        ("GET", "worlds") if path.get(1) == Some(&"compare") => {
            compare_worlds(state, path.get(2).copied(), path.get(3).copied())
        }
        ("GET", "branches") if path.get(1) == Some(&"compare") => {
            compare_branches(state, path.get(2).copied(), path.get(3).copied())
        }
        ("POST", "branches") if path.get(2) == Some(&"merge") => merge_branch(state, path[1], body),
        ("POST", "branches") if path.len() == 1 => create_branch(state, body),
        ("PATCH", "branches") | ("PUT", "branches") if path.len() > 1 => {
            update_row(state, "world_branches", path.get(1).copied(), body)
        }
        ("DELETE", "branches") if path.len() > 1 => {
            delete_row(state, "world_branches", path.get(1).copied())
        }
        ("GET", "entities")
            if path.get(1) == Some(&"variants") && path.get(2) == Some(&"compare") =>
        {
            compare_variants(state, path.get(3).copied(), path.get(4).copied())
        }
        ("POST", "snapshots") if path.get(2) == Some(&"restore") => {
            restore_snapshot(state, path[1], body)
        }
        ("POST", "snapshots") if path.len() == 1 => create_snapshot(state, body),
        ("GET", "snapshots") => {
            list_query(state, "world_snapshots", query).map(|v| json!({"snapshots":v}))
        }
        ("DELETE", "snapshots") if path.len() > 1 => {
            delete_row(state, "world_snapshots", path.get(1).copied())
        }
        ("GET", "projects") if path.get(2) == Some(&"manifest") && path.get(3) == Some(&"refs") => {
            list_scope(state, "project_manifest_refs", path[1], query)
        }
        ("GET", "projects") if path.get(2) == Some(&"manifest") => project_manifest(state, path[1]),
        ("POST", "projects")
            if path.get(2) == Some(&"manifest") && path.get(3) == Some(&"refs") =>
        {
            manifest(state, path[1], body, false)
        }
        ("DELETE", "projects")
            if path.get(2) == Some(&"manifest") && path.get(3) == Some(&"refs") =>
        {
            manifest_delete(state, path[1], query)
        }
        ("GET", "projects") if path.get(2) == Some(&"continuity") => {
            continuity(state, path[1], query)
        }
        ("GET", "projects") if path.get(2) == Some(&"staged-changes") => {
            staged_list(state, path[1], query)
        }
        ("POST", "projects") if path.get(2) == Some(&"staged-changes") => {
            scoped_project_insert(state, "staged_changes", path[1], body)
        }
        ("GET", "projects") if path.get(2) == Some(&"overlays") => {
            let mut q = query.clone();
            q.insert("project_id".into(), path[1].into());
            list_query(state, "project_overlays", &q)
        }
        ("POST", "projects") if path.get(2) == Some(&"overlays") => {
            scoped_project_insert(state, "project_overlays", path[1], body)
        }
        ("PATCH", "projects") | ("PUT", "projects") if path.get(2) == Some(&"overlays") => {
            update_row(state, "project_overlays", path.get(3).copied(), body)
        }
        ("DELETE", "projects") if path.get(2) == Some(&"overlays") => {
            delete_row(state, "project_overlays", path.get(3).copied())
        }
        ("POST", "projects") if path.get(2) == Some(&"context-recipes") => {
            scoped_project_insert(state, "context_recipes", path[1], body)
        }
        ("PUT", "projects") if path.get(2) == Some(&"scene-cards") => {
            scene_card(state, path[1], path.get(3).copied(), body)
        }
        ("GET", "projects") if path.get(2) == Some(&"scene-cards") => scene_cards(state, path[1]),
        ("DELETE", "projects") if path.get(2) == Some(&"scene-cards") => {
            delete_scene_card(state, path[1], path.get(3).copied())
        }
        ("POST", "staged-changes") if path.len() > 2 && path.get(2) == Some(&"resolve") => {
            resolve_stage(state, path[1], body)
        }
        ("POST", "staged-changes") if path.len() == 1 => {
            insert_scoped(state, "staged_changes", body)
        }
        ("GET", "staged-changes") => staged_list_query(state, query),
        ("GET", "timeline") if path.get(1) == Some(&"state") => timeline_state(state, query),
        ("GET", "timeline") => timeline(state, query),
        ("GET", "backlinks") => backlinks_path(state, path, query),
        ("GET", "scenes") if path.get(1) == Some(&"dependencies") => {
            list_query(state, "scene_dependencies", query)
        }
        ("GET", "scenes") if path.get(2) == Some(&"dependencies") => list_query(
            state,
            "scene_dependencies",
            &HashMap::from([(String::from("scene_document_id"), path[1].into())]),
        ),
        ("POST", "scenes") if path.get(1) == Some(&"dependencies") => {
            insert_scoped(state, "scene_dependencies", body)
        }
        ("PATCH", "scenes") | ("PUT", "scenes") if path.get(1) == Some(&"dependencies") => {
            update_row(state, "scene_dependencies", path.get(2).copied(), body)
        }
        ("DELETE", "scenes") if path.get(1) == Some(&"dependencies") => {
            delete_row(state, "scene_dependencies", path.get(2).copied())
        }
        ("POST", "tags") if path.get(2) == Some(&"link") => tag_link_path(state, path, body),
        ("DELETE", "tags") if path.get(2) == Some(&"link") => tag_unlink_path(state, path, query),
        ("GET", "context") if path.get(1) == Some(&"pins") => {
            list_query(state, "context_pins", query)
        }
        ("POST", "context") if path.get(1) == Some(&"pins") => {
            insert_scoped(state, "context_pins", body)
        }
        ("DELETE", "context") if path.get(1) == Some(&"pins") && path.len() > 2 => {
            delete_row(state, "context_pins", path.get(2).copied())
        }
        ("DELETE", "context") if path.get(1) == Some(&"pins") => delete_pin(state, query),
        ("GET", "context") if path.get(1) == Some(&"recipes") => {
            list_query(state, "context_recipes", query).map(|v| json!({"recipes":v}))
        }
        ("POST", "context") if path.get(1) == Some(&"recipes") => {
            insert_scoped(state, "context_recipes", body)
        }
        ("PATCH", "context") | ("PUT", "context") if path.get(1) == Some(&"recipes") => {
            update_row(state, "context_recipes", path.get(2).copied(), body)
        }
        ("DELETE", "context") if path.get(1) == Some(&"recipes") => {
            delete_row(state, "context_recipes", path.get(2).copied())
        }
        ("GET", "canon") if path.get(1) == Some(&"promote") => {
            Ok(json!({"preview":true,"message":"Use POST to promote canon"}))
        }
        ("POST", "canon") if path.get(1) == Some(&"promote") => promote(state, body),
        ("POST", "retcon") if path.get(1) == Some(&"preview") => retcon_preview(state, body),
        ("POST", "retcon") if path.get(1) == Some(&"apply") => retcon_apply(state, body),
        ("GET", "complexdomain") => Ok(json!({"items":[]})),
        ("POST", "complexdomain") => complexdomain(body),
        ("PATCH", "complexdomain") | ("PUT", "complexdomain") => complexdomain(body),
        ("DELETE", "complexdomain") => Ok(json!({"ok":true})),
        ("GET", "overlays") => list_query(state, "project_overlays", query),
        ("POST", "overlays") => insert_scoped(state, "project_overlays", body),
        ("PATCH", "overlays") | ("PUT", "overlays") => {
            update_row(state, "project_overlays", path.get(1).copied(), body)
        }
        ("DELETE", "overlays") => delete_row(state, "project_overlays", path.get(1).copied()),
        _ => return None,
    };
    Some(r)
}

fn id() -> String {
    Uuid::new_v4().to_string()
}
fn req<'a>(p: Option<&'a str>, n: &str) -> ApiResult<&'a str> {
    p.ok_or_else(|| ApiError::bad_request(format!("{n} is required")))
}
fn list_query(s: &AppState, t: &str, q: &HashMap<String, String>) -> ApiResult<Value> {
    let mut v = Vec::new();
    for (k, x) in q {
        v.push((k.as_str(), json!(x)));
    }
    Ok(Value::Array(s.store.list(t, &v)?))
}
fn insert_scoped(s: &AppState, t: &str, b: &Value) -> ApiResult<Value> {
    let o = b
        .as_object()
        .ok_or_else(|| ApiError::bad_request("payload must be an object"))?;
    if let Some(p) = o.get("project_id").and_then(Value::as_str) {
        if s.store.get("projects", p)?.is_none() {
            return Err(ApiError::not_found("project not found"));
        }
    };
    s.store.insert(t, b.clone())
}
fn scoped_project_insert(s: &AppState, t: &str, p: &str, b: &Value) -> ApiResult<Value> {
    if s.store.get("projects", p)?.is_none() {
        return Err(ApiError::not_found("project not found"));
    };
    let mut x = b.clone();
    x.as_object_mut()
        .ok_or_else(|| ApiError::bad_request("payload must be an object"))?
        .insert("project_id".into(), json!(p));
    insert_scoped(s, t, &x)
}
fn update_row(s: &AppState, t: &str, i: Option<&str>, b: &Value) -> ApiResult<Value> {
    s.store.update(t, req(i, "id")?, b.clone())
}
fn delete_row(s: &AppState, t: &str, i: Option<&str>) -> ApiResult<Value> {
    Ok(json!({"ok":s.store.delete(t,req(i,"id")?)?}))
}
fn list_scope(s: &AppState, t: &str, p: &str, q: &HashMap<String, String>) -> ApiResult<Value> {
    if s.store.get("projects", p)?.is_none() {
        return Err(ApiError::not_found("project not found"));
    }
    let mut x = q.clone();
    x.insert("project_id".into(), p.into());
    list_query(s, t, &x)
}
fn project_manifest(s: &AppState, p: &str) -> ApiResult<Value> {
    let project = s
        .store
        .get("projects", p)?
        .ok_or_else(|| ApiError::not_found("project not found"))?;
    let refs = s
        .store
        .list("project_manifest_refs", &[("project_id", json!(p))])?;
    let active = s
        .store
        .list("project_active_scenes", &[("project_id", json!(p))])?
        .into_iter()
        .next()
        .unwrap_or(Value::Null);
    let overlays = s
        .store
        .list("project_overlays", &[("project_id", json!(p))])?;
    Ok(json!({"project":project,"refs":refs,"active_scene":active,"overlays":overlays}))
}

fn fork_world(s: &AppState, source: &str, b: &Value) -> ApiResult<Value> {
    let src = s
        .store
        .get("worlds", source)?
        .ok_or_else(|| ApiError::not_found("world not found"))?;
    let mut con = s.store.connection()?;
    let tx = con.transaction()?;
    let wid = id();
    let now = chrono::Utc::now().to_rfc3339();
    let name = b.get("name").and_then(Value::as_str).unwrap_or("Fork");
    let slug = name.to_ascii_lowercase().replace(' ', "-");
    tx.execute("INSERT INTO worlds(id,project_id,parent_world_id,name,slug,description,canon_status,inheritance_mode,settings_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",params![wid,src["project_id"].as_str(),source,name,format!("{}-{}",slug,&wid[..8]),b.get("description").and_then(Value::as_str).unwrap_or(""),b.get("canon_status").and_then(Value::as_str).unwrap_or("what_if"),"snapshot","{}",now,now])?;
    let mut map = HashMap::new();
    let vars = scoped_rows(s, "entity_variants", source, &Value::Null)?;
    for row in vars {
        let n = id();
        map.insert(row["id"].as_str().unwrap_or("").to_owned(), n.clone());
        tx.execute("INSERT INTO entity_variants(id,family_id,world_id,branch_id,inherit_from_variant_id,display_name,summary,canon_status,attributes_json,voice_json,knowledge_json,beliefs_json,current_state_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",params![n,row["family_id"].as_str(),wid,Option::<String>::None,row["id"].as_str(),row["display_name"].as_str(),row["summary"].as_str().unwrap_or(""),row["canon_status"].as_str().unwrap_or("draft"),row["attributes_json"].as_str().unwrap_or("{}"),row["voice_json"].as_str().unwrap_or("{}"),row["knowledge_json"].as_str().unwrap_or("{}"),row["beliefs_json"].as_str().unwrap_or("{}"),row["current_state_json"].as_str().unwrap_or("{}"),now,now])?;
    }
    for row in scoped_rows(s, "relationships", source, &Value::Null)? {
        let sub = map.get(row["subject_variant_id"].as_str().unwrap_or(""));
        let obj = map.get(row["object_variant_id"].as_str().unwrap_or(""));
        if let (Some(sub), Some(obj)) = (sub, obj) {
            tx.execute("INSERT INTO relationships(id,world_id,branch_id,subject_variant_id,object_variant_id,relation_type,status,canon_status,attributes_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",params![id(),wid,Option::<String>::None,sub,obj,row["relation_type"].as_str(),row["status"].as_str().unwrap_or("current"),row["canon_status"].as_str().unwrap_or("draft"),row["attributes_json"].as_str().unwrap_or("{}"),now,now])?;
        }
    }
    for row in scoped_rows(s, "canon_facts", source, &Value::Null)? {
        let owner = map
            .get(row["owner_id"].as_str().unwrap_or(""))
            .map(String::as_str)
            .unwrap_or(row["owner_id"].as_str().unwrap_or(""));
        tx.execute("INSERT INTO canon_facts(id,project_id,world_id,branch_id,owner_type,owner_id,path,value_json,status,authority,source_type,source_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",params![id(),row["project_id"].as_str(),wid,Option::<String>::None,row["owner_type"].as_str(),owner,row["path"].as_str(),row["value_json"].as_str().unwrap_or("null"),row["status"].as_str().unwrap_or("canon"),row["authority"].as_str().unwrap_or("user_explicit"),"world_inheritance",row["id"].as_str(),now,now])?;
    }
    for row in scoped_rows(s, "timeline_events", source, &Value::Null)? {
        tx.execute("INSERT INTO timeline_events(id,world_id,branch_id,owner_type,owner_id,time_label,order_key,event_type,summary,state_patch_json,source_type,source_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",params![id(),wid,Option::<String>::None,row["owner_type"].as_str(),map.get(row["owner_id"].as_str().unwrap_or("")).map(String::as_str).or(row["owner_id"].as_str()),row["time_label"].as_str().unwrap_or(""),row["order_key"].as_f64().unwrap_or(0.0),row["event_type"].as_str().unwrap_or("event"),row["summary"].as_str().unwrap_or(""),row["state_patch_json"].as_str().unwrap_or("{}"),"world_inheritance",row["id"].as_str(),row["status"].as_str().unwrap_or("canon"),now,now])?;
    }
    tx.commit()?;
    s.store
        .get("worlds", &wid)?
        .ok_or_else(|| ApiError::internal("fork could not be read"))
}
fn sandbox(s: &AppState, w: &str, q: &HashMap<String, String>) -> ApiResult<Value> {
    let world = s
        .store
        .get("worlds", w)?
        .ok_or_else(|| ApiError::not_found("world not found"))?;
    let mut b = json!({"world_id":w,"name":q.get("name").cloned().unwrap_or_else(||"Sandbox".into()),"kind":"sandbox","canon_status":"what_if"});
    b.as_object_mut()
        .unwrap()
        .insert("parent_branch_id".into(), Value::Null);
    let _ = world;
    s.store.insert("world_branches", b)
}
fn create_branch(s: &AppState, b: &Value) -> ApiResult<Value> {
    let world = req(b.get("world_id").and_then(Value::as_str), "world_id")?;
    if s.store.get("worlds", world)?.is_none() {
        return Err(ApiError::not_found("world not found"));
    }
    let mut x = b.clone();
    let o = x
        .as_object_mut()
        .ok_or_else(|| ApiError::bad_request("payload must be an object"))?;
    o.entry("kind").or_insert(json!("sandbox"));
    o.entry("canon_status").or_insert(json!("what_if"));
    if let Some(parent) = o.get("parent_branch_id").and_then(Value::as_str) {
        let p = s
            .store
            .get("world_branches", parent)?
            .ok_or_else(|| ApiError::not_found("parent branch not found"))?;
        if p["world_id"] != json!(world) {
            return Err(ApiError::bad_request(
                "parent branch belongs to another world",
            ));
        }
    }
    s.store.insert("world_branches", x)
}
fn compare_worlds(s: &AppState, a: Option<&str>, b: Option<&str>) -> ApiResult<Value> {
    let l = s
        .store
        .get("worlds", req(a, "left")?)?
        .ok_or_else(|| ApiError::not_found("left world not found"))?;
    let r = s
        .store
        .get("worlds", req(b, "right")?)?
        .ok_or_else(|| ApiError::not_found("right world not found"))?;
    if l["project_id"] != r["project_id"] {
        return Err(ApiError::bad_request(
            "World comparison requires the same project",
        ));
    }
    let lv = s.store.list(
        "entity_variants",
        &[("world_id", json!(a.unwrap())), ("branch_id", Value::Null)],
    )?;
    let rv = s.store.list(
        "entity_variants",
        &[("world_id", json!(b.unwrap())), ("branch_id", Value::Null)],
    )?;
    let mut rows = Vec::new();
    for x in lv.iter().chain(rv.iter()) {
        let fid = x["family_id"].as_str().unwrap_or("");
        if rows.iter().any(|z: &Value| z["family_id"] == fid) {
            continue;
        }
        let left = lv.iter().find(|z| z["family_id"].as_str() == Some(fid));
        let right = rv.iter().find(|z| z["family_id"].as_str() == Some(fid));
        rows.push(json!({"family_id":fid,"left":left,"right":right,"difference":{"kind":if left==right{"same"}else if left.is_none(){"right_only"}else if right.is_none(){"left_only"}else{"changed"}}}));
    }
    Ok(json!({"left":l,"right":r,"entities":rows}))
}
fn compare_variants(s: &AppState, a: Option<&str>, b: Option<&str>) -> ApiResult<Value> {
    compare_scoped(s, "id", a, b, "entity_variants")
}
fn compare_scoped(
    s: &AppState,
    _k: &str,
    a: Option<&str>,
    b: Option<&str>,
    t: &str,
) -> ApiResult<Value> {
    let l = s
        .store
        .get(t, req(a, "left")?)?
        .ok_or_else(|| ApiError::not_found("left resource not found"))?;
    let r = s
        .store
        .get(t, req(b, "right")?)?
        .ok_or_else(|| ApiError::not_found("right resource not found"))?;
    let scope_l = l
        .get("project_id")
        .or_else(|| l.get("world_id"))
        .and_then(Value::as_str);
    let scope_r = r
        .get("project_id")
        .or_else(|| r.get("world_id"))
        .and_then(Value::as_str);
    if scope_l.is_some() && scope_r.is_some() && scope_l != scope_r {
        return Err(ApiError::bad_request(
            "resources belong to different scopes",
        ));
    }
    let mut fields = Map::new();
    if let (Some(lo), Some(ro)) = (l.as_object(), r.as_object()) {
        for k in lo.keys() {
            if k != "id" && lo.get(k) != ro.get(k) {
                fields.insert(k.clone(), json!({"left":lo.get(k),"right":ro.get(k)}));
            }
        }
    }
    Ok(json!({"left":l,"right":r,"difference":{"fields":fields}}))
}
fn compare_branches(s: &AppState, a: Option<&str>, b: Option<&str>) -> ApiResult<Value> {
    let l = s
        .store
        .get("world_branches", req(a, "left")?)?
        .ok_or_else(|| ApiError::not_found("left branch not found"))?;
    let r = s
        .store
        .get("world_branches", req(b, "right")?)?
        .ok_or_else(|| ApiError::not_found("right branch not found"))?;
    if l["world_id"] != r["world_id"] {
        return Err(ApiError::bad_request(
            "Branch comparison requires branches from the same world",
        ));
    }
    let world = l["world_id"].as_str().unwrap();
    let le = s.store.list(
        "entity_variants",
        &[("world_id", json!(world)), ("branch_id", json!(a.unwrap()))],
    )?;
    let re = s.store.list(
        "entity_variants",
        &[("world_id", json!(world)), ("branch_id", json!(b.unwrap()))],
    )?;
    Ok(
        json!({"world":s.store.get("worlds",world)?,"left":l,"right":r,"entities":diff_rows(&le,&re),"relationships":[],"facts":{"left":s.store.list("canon_facts",&[("world_id",json!(world)),("branch_id",json!(a.unwrap()))])?,"right":s.store.list("canon_facts",&[("world_id",json!(world)),("branch_id",json!(b.unwrap()))])?}}),
    )
}
fn diff_rows(l: &[Value], r: &[Value]) -> Vec<Value> {
    let mut out = Vec::new();
    for x in l.iter().chain(r.iter()) {
        let k = x["family_id"].as_str().unwrap_or("");
        if out.iter().any(|z: &Value| z["family_id"] == k) {
            continue;
        }
        let a = l.iter().find(|z| z["family_id"].as_str() == Some(k));
        let b = r.iter().find(|z| z["family_id"].as_str() == Some(k));
        if a != b {
            out.push(json!({"kind":"entity","family_id":k,"left":a,"right":b,"difference":{"kind":"changed"}}));
        }
    }
    out
}
fn merge_branch(s: &AppState, source: &str, b: &Value) -> ApiResult<Value> {
    let target = req(
        b.get("target_branch_id").and_then(Value::as_str),
        "target_branch_id",
    )?;
    let src = s
        .store
        .get("world_branches", source)?
        .ok_or_else(|| ApiError::not_found("source branch not found"))?;
    let dst = s
        .store
        .get("world_branches", target)?
        .ok_or_else(|| ApiError::not_found("target branch not found"))?;
    if src["world_id"] != dst["world_id"] {
        return Err(ApiError::bad_request(
            "branches must belong to the same world",
        ));
    }
    let changes = b
        .get("changes")
        .and_then(Value::as_array)
        .ok_or_else(|| ApiError::bad_request("changes must be an array"))?;
    let mut merged = Vec::new();
    let mut skipped = Vec::new();
    for c in changes {
        match c.get("kind").and_then(Value::as_str) {
            Some("entity") => {
                let fam = req(c.get("family_id").and_then(Value::as_str), "family_id")?;
                let srcv = s
                    .store
                    .list(
                        "entity_variants",
                        &[
                            ("world_id", src["world_id"].clone()),
                            ("branch_id", json!(source)),
                            ("family_id", json!(fam)),
                        ],
                    )?
                    .into_iter()
                    .next();
                if let Some(mut row) = srcv {
                    row.as_object_mut()
                        .unwrap()
                        .insert("id".into(), json!(id()));
                    row.as_object_mut()
                        .unwrap()
                        .insert("branch_id".into(), json!(target));
                    s.store.insert("entity_variants", row)?;
                    merged.push(json!({"kind":"entity","family_id":fam}));
                } else {
                    skipped.push(json!({"change":c,"reason":"source variant missing"}));
                }
            }
            Some("fact") => {
                let fid = req(c.get("fact_id").and_then(Value::as_str), "fact_id")?;
                let mut row = s
                    .store
                    .get("canon_facts", fid)?
                    .ok_or_else(|| ApiError::not_found("fact not found"))?;
                row.as_object_mut()
                    .unwrap()
                    .insert("id".into(), json!(id()));
                row.as_object_mut()
                    .unwrap()
                    .insert("branch_id".into(), json!(target));
                s.store.insert("canon_facts", row)?;
                merged.push(json!({"kind":"fact","source_id":fid}));
            }
            _ => skipped.push(json!({"change":c,"reason":"unsupported merge kind"})),
        }
    }
    Ok(json!({"source":src,"target":dst,"merged":merged,"skipped":skipped}))
}
fn scoped_rows(s: &AppState, t: &str, w: &str, b: &Value) -> ApiResult<Vec<Value>> {
    if b.is_null() {
        s.store.query(
            &format!("SELECT * FROM {t} WHERE world_id=? AND branch_id IS NULL"),
            &[&w],
        )
    } else {
        s.store
            .list(t, &[("world_id", json!(w)), ("branch_id", b.clone())])
    }
}
fn create_snapshot(s: &AppState, b: &Value) -> ApiResult<Value> {
    let p = req(b.get("project_id").and_then(Value::as_str), "project_id")?;
    let w = req(b.get("world_id").and_then(Value::as_str), "world_id")?;
    let bid = b.get("branch_id").cloned().unwrap_or(Value::Null);
    let payload = json!({"schema":"arline-world-snapshot-0.1","variants":scoped_rows(s,"entity_variants",w,&bid)?,"relationships":scoped_rows(s,"relationships",w,&bid)?,"facts":scoped_rows(s,"canon_facts",w,&bid)?,"timeline":scoped_rows(s,"timeline_events",w,&bid)?});
    s.store.insert("world_snapshots",json!({"id":id(),"project_id":p,"world_id":w,"branch_id":bid,"name":b.get("name").and_then(Value::as_str).unwrap_or("Snapshot"),"description":b.get("description").and_then(Value::as_str).unwrap_or(""),"payload":payload}))
}
fn restore_snapshot(s: &AppState, sid: &str, b: &Value) -> ApiResult<Value> {
    let snap = s
        .store
        .get("world_snapshots", sid)?
        .ok_or_else(|| ApiError::not_found("snapshot not found"))?;
    let name = b
        .get("branch_name")
        .and_then(Value::as_str)
        .unwrap_or("Restored snapshot");
    let br=s.store.insert("world_branches",json!({"world_id":snap["world_id"],"name":name,"kind":"sandbox","canon_status":"what_if","base_snapshot_id":sid}))?;
    let payload = snap
        .get("payload_json")
        .and_then(Value::as_str)
        .and_then(|x| serde_json::from_str::<Value>(x).ok())
        .unwrap_or_else(|| snap.get("payload").cloned().unwrap_or(json!({})));
    let mut map = HashMap::new();
    for mut row in payload["variants"].as_array().cloned().unwrap_or_default() {
        let old = row["id"].as_str().unwrap_or("").to_owned();
        let n = id();
        map.insert(old, n.clone());
        row.as_object_mut().unwrap().insert("id".into(), json!(n));
        row.as_object_mut()
            .unwrap()
            .insert("branch_id".into(), br["id"].clone());
        row.as_object_mut()
            .unwrap()
            .insert("canon_status".into(), json!("what_if"));
        s.store.insert("entity_variants", row)?;
    }
    for mut row in payload["relationships"]
        .as_array()
        .cloned()
        .unwrap_or_default()
    {
        if let (Some(sub), Some(obj)) = (
            map.get(row["subject_variant_id"].as_str().unwrap_or("")),
            map.get(row["object_variant_id"].as_str().unwrap_or("")),
        ) {
            row.as_object_mut()
                .unwrap()
                .insert("id".into(), json!(id()));
            row.as_object_mut()
                .unwrap()
                .insert("branch_id".into(), br["id"].clone());
            row.as_object_mut()
                .unwrap()
                .insert("subject_variant_id".into(), json!(sub));
            row.as_object_mut()
                .unwrap()
                .insert("object_variant_id".into(), json!(obj));
            s.store.insert("relationships", row)?;
        }
    }
    for mut row in payload["facts"].as_array().cloned().unwrap_or_default() {
        row.as_object_mut()
            .unwrap()
            .insert("id".into(), json!(id()));
        row.as_object_mut()
            .unwrap()
            .insert("branch_id".into(), br["id"].clone());
        row.as_object_mut()
            .unwrap()
            .insert("status".into(), json!("what_if"));
        s.store.insert("canon_facts", row)?;
    }
    Ok(json!({"snapshot_id":sid,"branch_id":br["id"],"mode":"new_sandbox_branch"}))
}
fn manifest(s: &AppState, p: &str, b: &Value, _: bool) -> ApiResult<Value> {
    let mut x = b.clone();
    x.as_object_mut()
        .unwrap()
        .insert("project_id".into(), json!(p));
    insert_scoped(s, "project_manifest_refs", &x)
}
fn manifest_delete(s: &AppState, p: &str, q: &HashMap<String, String>) -> ApiResult<Value> {
    let t = req(q.get("resource_type").map(String::as_str), "resource_type")?;
    let r = req(q.get("resource_id").map(String::as_str), "resource_id")?;
    let n=s.store.connection()?.execute("DELETE FROM project_manifest_refs WHERE project_id=? AND resource_type=? AND resource_id=?",params![p,t,r])?;
    Ok(json!({"ok":n>0}))
}
fn scene_cards(s: &AppState, p: &str) -> ApiResult<Value> {
    Ok(Value::Array(s.store.list(
        "project_scene_cards",
        &[("project_id", json!(p))],
    )?))
}
fn delete_scene_card(s: &AppState, p: &str, d: Option<&str>) -> ApiResult<Value> {
    let d = req(d, "document_id")?;
    let n = s.store.connection()?.execute(
        "DELETE FROM project_scene_cards WHERE document_id=? AND project_id=?",
        params![d, p],
    )?;
    Ok(json!({"ok":n>0}))
}
fn staged_value(mut row: Value) -> Value {
    if let Some(o) = row.as_object_mut() {
        for (raw, key) in [
            ("old_value_json", "old_value"),
            ("proposed_value_json", "proposed_value"),
        ] {
            if let Some(v) = o
                .get(raw)
                .and_then(Value::as_str)
                .and_then(|x| serde_json::from_str(x).ok())
            {
                o.insert(key.into(), v);
            }
        }
    }
    row
}
fn staged_list(s: &AppState, p: &str, q: &HashMap<String, String>) -> ApiResult<Value> {
    if s.store.get("projects", p)?.is_none() {
        return Err(ApiError::not_found("project not found"));
    }
    let mut x = q.clone();
    x.insert("project_id".into(), p.into());
    staged_list_query(s, &x)
}
fn staged_list_query(s: &AppState, q: &HashMap<String, String>) -> ApiResult<Value> {
    let rows = list_query(s, "staged_changes", q)?
        .as_array()
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .map(staged_value)
        .collect::<Vec<_>>();
    Ok(json!({"changes":rows}))
}
fn scene_card(s: &AppState, p: &str, d: Option<&str>, b: &Value) -> ApiResult<Value> {
    let d = req(
        d.or_else(|| b.get("document_id").and_then(Value::as_str)),
        "document_id",
    )?;
    let doc = s
        .store
        .get("workspace_documents", d)?
        .ok_or_else(|| ApiError::not_found("document not found"))?;
    if doc.get("project_id").and_then(Value::as_str) != Some(p) {
        return Err(ApiError::bad_request("document does not belong to project"));
    }
    let mut x = b.clone();
    x.as_object_mut()
        .unwrap()
        .insert("document_id".into(), json!(d));
    x.as_object_mut()
        .unwrap()
        .insert("project_id".into(), json!(p));
    s.store.connection()?.execute(
        "DELETE FROM project_scene_cards WHERE document_id=?",
        params![d],
    )?;
    s.store.insert("project_scene_cards", x)
}
fn resolve_stage(s: &AppState, id_: &str, b: &Value) -> ApiResult<Value> {
    let row = s
        .store
        .get("staged_changes", id_)?
        .ok_or_else(|| ApiError::not_found("staged change not found"))?;
    let accept = b.get("accept").and_then(Value::as_bool).unwrap_or(false);
    if accept {
        let proposed = row
            .get("proposed_value_json")
            .and_then(Value::as_str)
            .and_then(|x| serde_json::from_str::<Value>(x).ok())
            .or_else(|| row.get("proposed_value").cloned())
            .unwrap_or(Value::Null);
        let project = row["project_id"].as_str().unwrap_or("");
        let world = row.get("world_id").and_then(Value::as_str);
        let branch = row.get("branch_id").and_then(Value::as_str);
        let owner_type = row["owner_type"].as_str().unwrap_or("");
        let owner_id = row["owner_id"].as_str().unwrap_or("");
        let path = row["path"].as_str().unwrap_or("");
        let prior=s.store.query("SELECT id,value_json FROM canon_facts WHERE project_id=? AND owner_type=? AND owner_id=? AND path=? AND world_id IS ? AND branch_id IS ? AND status NOT IN ('retconned','deprecated')",&[&project,&owner_type,&owner_id,&path,&world,&branch])?;
        let fact=s.store.insert("canon_facts",json!({"id":id(),"project_id":project,"world_id":world,"branch_id":branch,"owner_type":owner_type,"owner_id":owner_id,"path":path,"value":proposed,"status":"canon","authority":"user_promoted","source_type":"staged_change","source_id":id_}))?;
        for old in prior {
            if old["value_json"] != fact["value_json"] {
                let _=s.store.insert("workspace_conflicts",json!({"id":id(),"project_id":project,"world_id":world,"branch_id":branch,"owner_type":owner_type,"owner_id":owner_id,"path":path,"left":old["value_json"],"right":fact["value_json"],"conflict_class":"same_scope_value_conflict","status":"open"}));
            }
        }
    }
    let out = s.store.update(
        "staged_changes",
        id_,
        json!({"status":if accept{"accepted"}else{"rejected"}}),
    )?;
    Ok(staged_value(out))
}
fn timeline(s: &AppState, q: &HashMap<String, String>) -> ApiResult<Value> {
    list_query(s, "timeline_events", q).map(|v| json!({"events":v}))
}
fn timeline_state(s: &AppState, q: &HashMap<String, String>) -> ApiResult<Value> {
    let w = req(q.get("world_id").map(String::as_str), "world_id")?;
    let owner = req(q.get("owner_id").map(String::as_str), "owner_id")?;
    let mut rows=s.store.query("SELECT * FROM timeline_events WHERE world_id=? AND owner_id=? ORDER BY order_key,created_at",&[&w,&owner])?;
    let at = q.get("at_order").and_then(|x| x.parse::<f64>().ok());
    if let Some(a) = at {
        rows.retain(|x| x["order_key"].as_f64().unwrap_or(0.0) <= a);
    }
    Ok(json!({"world_id":w,"owner_id":owner,"events":rows,"state":{}}))
}
fn backlinks(s: &AppState, q: &HashMap<String, String>) -> ApiResult<Value> {
    let id = req(q.get("resource_id").map(String::as_str), "resource_id")?;
    let typ = q.get("resource_type").map(String::as_str).unwrap_or("");
    let mut out = Vec::new();
    if typ == "entity_variant" || typ == "world" || typ == "branch" {
        out.extend(s.store.query("SELECT id,relation_type,subject_variant_id,object_variant_id,world_id,branch_id FROM relationships WHERE subject_variant_id=? OR object_variant_id=?",&[&id,&id])?);
    }
    out.extend(s.store.query(
        "SELECT * FROM project_manifest_refs WHERE resource_type=? AND resource_id=?",
        &[&typ, &id],
    )?);
    out.extend(s.store.query(
        "SELECT * FROM scene_dependencies WHERE target_type=? AND target_id=?",
        &[&typ, &id],
    )?);
    out.extend(s.store.query(
        "SELECT * FROM workspace_tag_links WHERE resource_type=? AND resource_id=?",
        &[&typ, &id],
    )?);
    Ok(json!({"resource_type":typ,"resource_id":id,"links":out,"count":out.len()}))
}
fn backlinks_path(s: &AppState, path: &[&str], q: &HashMap<String, String>) -> ApiResult<Value> {
    let typ = req(path.get(1).copied(), "resource_type")?;
    let rid = req(path.get(2).copied(), "resource_id")?;
    let mut x = q.clone();
    x.insert("resource_id".into(), rid.into());
    x.insert("resource_type".into(), typ.into());
    backlinks(s, &x)
}
fn tag_link_path(s: &AppState, path: &[&str], b: &Value) -> ApiResult<Value> {
    let tag = req(path.get(1).copied(), "tag_id")?;
    let mut x = b.clone();
    x.as_object_mut()
        .ok_or_else(|| ApiError::bad_request("payload must be an object"))?
        .insert("tag_id".into(), json!(tag));
    tag_link(s, &x)
}
fn tag_unlink_path(s: &AppState, path: &[&str], q: &HashMap<String, String>) -> ApiResult<Value> {
    let tag = req(path.get(1).copied(), "tag_id")?;
    let typ = req(q.get("resource_type").map(String::as_str), "resource_type")?;
    let rid = req(q.get("resource_id").map(String::as_str), "resource_id")?;
    tag_unlink(
        s,
        &json!({"tag_id":tag,"resource_type":typ,"resource_id":rid}),
    )
}
fn tag_link(s: &AppState, b: &Value) -> ApiResult<Value> {
    s.store.connection()?.execute(
        "INSERT OR IGNORE INTO workspace_tag_links(tag_id,resource_type,resource_id) VALUES(?,?,?)",
        params![
            b["tag_id"].as_str(),
            b["resource_type"].as_str(),
            b["resource_id"].as_str()
        ],
    )?;
    Ok(b.clone())
}
fn tag_unlink(s: &AppState, b: &Value) -> ApiResult<Value> {
    s.store.connection()?.execute(
        "DELETE FROM workspace_tag_links WHERE tag_id=? AND resource_type=? AND resource_id=?",
        params![
            b["tag_id"].as_str(),
            b["resource_type"].as_str(),
            b["resource_id"].as_str()
        ],
    )?;
    Ok(json!({"ok":true}))
}
fn delete_pin(s: &AppState, q: &HashMap<String, String>) -> ApiResult<Value> {
    let n = s.store.connection()?.execute(
        "DELETE FROM context_pins WHERE id=?",
        params![req(q.get("id").map(String::as_str), "id")?],
    )?;
    Ok(json!({"ok":n>0}))
}
fn continuity(s: &AppState, p: &str, q: &HashMap<String, String>) -> ApiResult<Value> {
    if s.store.get("projects", p)?.is_none() {
        return Err(ApiError::not_found("project not found"));
    }
    let world = q.get("world_id");
    let branch = q.get("branch_id");
    let mut warnings = Vec::new();
    let mut sql="SELECT owner_type,owner_id,path,COUNT(DISTINCT value_json) AS variants FROM canon_facts WHERE status NOT IN ('retconned','deprecated')".to_owned();
    let mut vals: Vec<String> = Vec::new();
    if let Some(w) = world {
        sql.push_str(" AND world_id=?");
        vals.push(w.clone());
    }
    sql.push_str(" GROUP BY owner_type,owner_id,path HAVING variants>1");
    let refs: Vec<&dyn rusqlite::ToSql> = vals.iter().map(|x| x as &dyn rusqlite::ToSql).collect();
    for row in s.store.query(&sql, &refs)? {
        warnings.push(json!({"severity":"warning","kind":"competing_facts","message":format!("{}:{} has competing values for {}",row["owner_type"],row["owner_id"],row["path"]),"owner_type":row["owner_type"],"owner_id":row["owner_id"],"path":row["path"]}));
    }
    let mut q2 = HashMap::new();
    q2.insert("project_id".into(), p.into());
    if let Some(w) = world {
        q2.insert("world_id".into(), w.clone());
    }
    if let Some(b) = branch {
        q2.insert("branch_id".into(), b.clone());
    }
    Ok(
        json!({"warnings":warnings,"warning_count":warnings.len(),"active_scene":null,"pending_changes":staged_list_query(s,&q2)?["changes"]}),
    )
}
fn promote(s: &AppState, b: &Value) -> ApiResult<Value> {
    let owner_type = req(b.get("owner_type").and_then(Value::as_str), "owner_type")?;
    let owner_id = req(b.get("owner_id").and_then(Value::as_str), "owner_id")?;
    let path = req(b.get("path").and_then(Value::as_str), "path")?;
    let project = b.get("project_id").and_then(Value::as_str).unwrap_or("");
    let world = b.get("world_id").and_then(Value::as_str);
    let branch = b.get("branch_id").and_then(Value::as_str);
    s.store.insert("canon_facts",json!({"id":id(),"project_id":project,"world_id":world,"branch_id":branch,"owner_type":owner_type,"owner_id":owner_id,"path":path,"value":b.get("value").cloned().unwrap_or(Value::Null),"status":"canon","authority":"user_promoted","source_type":"manual","source_id":b.get("source_id")}))
}
fn retcon_preview(s: &AppState, b: &Value) -> ApiResult<Value> {
    let owner_type = req(b.get("owner_type").and_then(Value::as_str), "owner_type")?;
    let owner_id = req(b.get("owner_id").and_then(Value::as_str), "owner_id")?;
    let path = req(b.get("path").and_then(Value::as_str), "path")?;
    let project = b.get("project_id").and_then(Value::as_str).unwrap_or("");
    let world = b.get("world_id").and_then(Value::as_str).unwrap_or("");
    let current=s.store.query("SELECT * FROM canon_facts WHERE owner_type=? AND owner_id=? AND path=? AND status NOT IN ('retconned','deprecated')",&[&owner_type,&owner_id,&path])?;
    let relationships = s.store.query(
        "SELECT * FROM relationships WHERE subject_variant_id=? OR object_variant_id=?",
        &[&owner_id, &owner_id],
    )?;
    let documents=s.store.query("SELECT id,title,document_type FROM workspace_documents WHERE project_id=? AND (content LIKE ? OR content LIKE ?)",&[&project,&format!("%{}%",owner_id),&format!("%{}%",path)])?;
    Ok(
        json!({"owner":{"type":owner_type,"id":owner_id,"label":owner_id},"path":path,"current_facts":current,"new_value":b.get("new_value").cloned().unwrap_or(Value::Null),"impact":{"relationships":relationships,"documents":documents,"turns":[],"dataset_samples_may_require_review":0},"options":["apply_retcon","create_world_fork","keep_unresolved"],"world_id":world}),
    )
}
fn retcon_apply(s: &AppState, b: &Value) -> ApiResult<Value> {
    let project = req(b.get("project_id").and_then(Value::as_str), "project_id")?;
    let world = req(b.get("world_id").and_then(Value::as_str), "world_id")?;
    let owner_type = req(b.get("owner_type").and_then(Value::as_str), "owner_type")?;
    let owner_id = req(b.get("owner_id").and_then(Value::as_str), "owner_id")?;
    let path = req(b.get("path").and_then(Value::as_str), "path")?;
    let branch = b.get("branch_id").and_then(Value::as_str);
    let now = chrono::Utc::now().to_rfc3339();
    let old=s.store.query("SELECT id FROM canon_facts WHERE project_id=? AND world_id=? AND branch_id IS ? AND owner_type=? AND owner_id=? AND path=? AND status NOT IN ('retconned','deprecated')",&[&project,&world,&branch,&owner_type,&owner_id,&path])?;
    for row in old {
        s.store.update(
            "canon_facts",
            row["id"].as_str().unwrap_or(""),
            json!({"status":"retconned"}),
        )?;
    }
    let out=s.store.insert("canon_facts",json!({"id":id(),"project_id":project,"world_id":world,"branch_id":branch,"owner_type":owner_type,"owner_id":owner_id,"path":path,"value":b.get("new_value").cloned().unwrap_or(Value::Null),"status":"canon","authority":"user_explicit","source_type":"retcon","source_id":b.get("source_id")}))?;
    let _=s.store.insert("workspace_revisions",json!({"id":id(),"resource_type":"canon_fact","resource_id":out["id"],"version":1,"content":out,"note":b.get("note").and_then(Value::as_str).unwrap_or("retcon"),"created_at":now}));
    Ok(out)
}
fn complexdomain(b: &Value) -> ApiResult<Value> {
    let mut x = b.clone();
    if let Some(o) = x.as_object_mut() {
        o.entry("normalized").or_insert(json!(true));
    }
    Ok(x)
}
