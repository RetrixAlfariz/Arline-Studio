//! Copy-only legacy import. Never open the source for writing or retain source media paths.
use crate::{ApiError, ApiResult};
use rusqlite::{Connection, OpenFlags};
use std::{fs, path::Path, time::Duration};

#[derive(Debug, Default)]
pub struct ImportReport {
    pub media_copied: usize,
    pub media_missing: usize,
    pub history_sessions: usize,
    pub history_turns: usize,
}

const CHAT_SCHEMA: &str = r#"
CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, pinned INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0, project TEXT, project_id TEXT, world_id TEXT, branch_id TEXT, folder_id TEXT, session_kind TEXT NOT NULL DEFAULT 'chat', tags_json TEXT NOT NULL DEFAULT '[]', workspace_refs_json TEXT NOT NULL DEFAULT '[]', parent_session_id TEXT, forked_from_turn_id TEXT, scratch_mode INTEGER NOT NULL DEFAULT 0, conversation_mode TEXT NOT NULL DEFAULT 'story_writer', conversation_profile_json TEXT NOT NULL DEFAULT '{}', mode_events_json TEXT NOT NULL DEFAULT '[]', world_fork_id TEXT, last_model TEXT, last_mode TEXT, last_reasoning TEXT);
CREATE TABLE IF NOT EXISTS turns (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, run_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, user_prompt TEXT NOT NULL, story TEXT NOT NULL, model TEXT, mode TEXT, reasoning TEXT, projection_mode TEXT, reasoning_text TEXT NOT NULL DEFAULT '', stats_json TEXT NOT NULL DEFAULT '{}', wcf TEXT NOT NULL DEFAULT '', aif_core TEXT NOT NULL DEFAULT '', session_context TEXT NOT NULL DEFAULT '', workspace_context TEXT NOT NULL DEFAULT '', workspace_scope_json TEXT NOT NULL DEFAULT '{}', workspace_refs_json TEXT NOT NULL DEFAULT '[]', lineage_json TEXT NOT NULL DEFAULT '{}', projections_json TEXT NOT NULL DEFAULT '[]', post_validation_json TEXT NOT NULL DEFAULT '{}', wcf_validation_json TEXT NOT NULL DEFAULT '{}', feedback_status TEXT NOT NULL DEFAULT 'unreviewed', feedback_issues_json TEXT NOT NULL DEFAULT '[]', feedback_note TEXT NOT NULL DEFAULT '', edited_story TEXT NOT NULL DEFAULT '', FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE);
"#;

fn table_columns(connection: &Connection, schema: &str, table: &str) -> ApiResult<Vec<String>> {
    let sql = format!("SELECT name FROM {schema}.pragma_table_info(?)");
    let mut statement = connection
        .prepare(&sql)
        .map_err(|e| ApiError::internal(e.to_string()))?;
    let rows = statement
        .query_map([table], |row| row.get::<_, String>(0))
        .map_err(|e| ApiError::internal(e.to_string()))?;
    rows.collect::<Result<Vec<_>, _>>()
        .map_err(|e| ApiError::internal(e.to_string()))
}

fn import_table(connection: &Connection, table: &str) -> ApiResult<usize> {
    let source = table_columns(connection, "legacy", table)?;
    let target = table_columns(connection, "main", table)?;
    let columns: Vec<String> = source
        .into_iter()
        .filter(|column| target.contains(column))
        .collect();
    if columns.is_empty() {
        return Ok(0);
    }
    let quoted = columns
        .iter()
        .map(|c| format!("\"{c}\""))
        .collect::<Vec<_>>()
        .join(",");
    let sql = format!(
        "INSERT OR IGNORE INTO main.\"{table}\" ({quoted}) SELECT {quoted} FROM legacy.\"{table}\""
    );
    connection
        .execute(&sql, [])
        .map_err(|e| ApiError::internal(e.to_string()))
}

/// Import the legacy split configuration without mutating either source DB.
/// `history_source` is the configured history.database_path and
/// `workspace_source` is workspace.database_path from the Python config.
pub fn import_legacy_workspace(
    history_source: &Path,
    workspace_source: &Path,
    target: &Path,
) -> ApiResult<ImportReport> {
    if history_source == workspace_source {
        return import_workspace(workspace_source, target);
    }
    let mut report = import_workspace(workspace_source, target)?;
    let history_path = history_source.canonicalize()?;
    let history = Connection::open_with_flags(&history_path, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    let check: String = history.query_row("PRAGMA quick_check", [], |r| r.get(0))?;
    if check != "ok" {
        return Err(ApiError::bad_request(
            "Source history failed SQLite quick_check",
        ));
    }
    let mut destination = Connection::open(target)?;
    destination
        .execute_batch(CHAT_SCHEMA)
        .map_err(|e| ApiError::internal(e.to_string()))?;
    destination
        .execute(
            "ATTACH DATABASE ? AS legacy",
            [history_path.to_string_lossy().as_ref()],
        )
        .map_err(|e| ApiError::internal(e.to_string()))?;
    let transaction = destination
        .transaction()
        .map_err(|e| ApiError::internal(e.to_string()))?;
    report.history_sessions = import_table(&transaction, "sessions")?;
    report.history_turns = import_table(&transaction, "turns")?;
    transaction
        .commit()
        .map_err(|e| ApiError::internal(e.to_string()))?;
    destination
        .execute_batch("DETACH DATABASE legacy")
        .map_err(|e| ApiError::internal(e.to_string()))?;
    Ok(report)
}

pub fn import_workspace(source: &Path, target: &Path) -> ApiResult<ImportReport> {
    if target.exists() {
        return Err(ApiError::bad_request(
            "Import destination already exists; choose a fresh --data-dir",
        ));
    }
    let source_path = source.canonicalize()?;
    let parent = target
        .parent()
        .ok_or_else(|| ApiError::bad_request("Import destination needs a directory"))?;
    fs::create_dir_all(parent)?;
    let parent = parent.canonicalize()?;
    if source_path.parent() == Some(parent.as_path()) || parent.join("media").exists() {
        return Err(ApiError::bad_request(
            "Import requires a fresh destination separate from the source workspace",
        ));
    }
    let source = Connection::open_with_flags(&source_path, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    let check: String = source.query_row("PRAGMA quick_check", [], |r| r.get(0))?;
    if check != "ok" {
        return Err(ApiError::bad_request(
            "Source workspace failed SQLite quick_check",
        ));
    }
    let staging = parent.join(format!(".import-{}", uuid::Uuid::new_v4()));
    fs::create_dir(&staging)?;
    let result = (|| {
        let mut destination = Connection::open(staging.join("workspace.db"))?;
        {
            let backup = rusqlite::backup::Backup::new(&source, &mut destination)?;
            backup.run_to_completion(128, Duration::from_millis(10), None)?;
        }
        let has_media:bool=destination.query_row("SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type='table' AND name='resource_media')",[],|r|r.get(0))?;
        let mut report = ImportReport::default();
        if has_media {
            fs::create_dir(staging.join("media"))?;
            let rows = {
                let mut statement =
                    destination.prepare("SELECT id,storage_path FROM resource_media")?;
                let rows = statement
                    .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))?;
                rows.collect::<Result<Vec<_>, _>>()?
            };
            let source_media = source_path.parent().unwrap().join("media");
            let managed = source_media.canonicalize().ok();
            for (id, raw) in rows {
                let raw = Path::new(&raw);
                let path = if raw.is_absolute() {
                    raw.to_owned()
                } else {
                    source_path.parent().unwrap().join(raw)
                };
                let name = format!("{}", uuid::Uuid::new_v4());
                match path.canonicalize() {
                    Ok(path) => {
                        if !managed.as_ref().is_some_and(|base| path.starts_with(base))
                            || !path.is_file()
                        {
                            return Err(ApiError::bad_request(
                                "A media record points outside the source managed media directory",
                            ));
                        }
                        fs::copy(path, staging.join("media").join(&name))?;
                        report.media_copied += 1;
                    }
                    Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                        report.media_missing += 1
                    }
                    Err(error) => return Err(error.into()),
                }
                destination.execute(
                    "UPDATE resource_media SET storage_path=? WHERE id=?",
                    [
                        parent.join("media").join(name).to_string_lossy().as_ref(),
                        &id,
                    ],
                )?;
            }
        }
        destination
            .close()
            .map_err(|(_, error)| ApiError::from(error))?;
        // Destination was checked before backup; hard_link publishes without overwriting
        // a file created by another launcher while the import was running.
        fs::hard_link(staging.join("workspace.db"), target)?;
        if staging.join("media").exists() {
            if let Err(error) = fs::rename(staging.join("media"), parent.join("media")) {
                let _ = fs::remove_file(target);
                return Err(error.into());
            }
        }
        Ok(report)
    })();
    let _ = fs::remove_dir_all(&staging);
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn copy_includes_uncheckpointed_wal_and_rehomes_media_without_source_changes() {
        let temp = tempfile::tempdir().unwrap();
        let old = temp.path().join("old");
        let new = temp.path().join("new");
        fs::create_dir_all(old.join("media")).unwrap();
        let media = old.join("media/picture.png");
        fs::write(&media, b"original image").unwrap();
        let db = old.join("workspace.db");
        let source = Connection::open(&db).unwrap();
        source.execute_batch("PRAGMA journal_mode=WAL; PRAGMA wal_autocheckpoint=0; CREATE TABLE writing(text TEXT); INSERT INTO writing VALUES('keep this draft'); CREATE TABLE resource_media(id TEXT PRIMARY KEY,storage_path TEXT);").unwrap();
        source
            .execute(
                "INSERT INTO resource_media VALUES('image',?)",
                [media.to_string_lossy().as_ref()],
            )
            .unwrap();
        let report = import_workspace(&db, &new.join("workspace.db")).unwrap();
        assert_eq!(report.media_copied, 1);
        let copy = Connection::open(new.join("workspace.db")).unwrap();
        let text: String = copy
            .query_row("SELECT text FROM writing", [], |r| r.get(0))
            .unwrap();
        assert_eq!(text, "keep this draft");
        let path: String = copy
            .query_row("SELECT storage_path FROM resource_media", [], |r| r.get(0))
            .unwrap();
        assert!(Path::new(&path).starts_with(new.canonicalize().unwrap()));
        fs::write(path, b"changed copy").unwrap();
        assert_eq!(fs::read(&media).unwrap(), b"original image");
        assert_eq!(
            source
                .query_row("SELECT storage_path FROM resource_media", [], |r| r
                    .get::<_, String>(0))
                .unwrap(),
            media.to_string_lossy()
        );
        assert!(import_workspace(&db, &new.join("workspace.db")).is_err());
    }
    #[test]
    fn import_refuses_media_outside_source_managed_directory() {
        let temp = tempfile::tempdir().unwrap();
        let old = temp.path().join("old");
        fs::create_dir(&old).unwrap();
        let protected = temp.path().join("protected.txt");
        fs::write(&protected, b"keep me").unwrap();
        let source = old.join("workspace.db");
        let c = Connection::open(&source).unwrap();
        c.execute_batch("CREATE TABLE resource_media(id TEXT,storage_path TEXT)")
            .unwrap();
        c.execute(
            "INSERT INTO resource_media VALUES('bad',?)",
            [protected.to_string_lossy().as_ref()],
        )
        .unwrap();
        let target = temp.path().join("new/workspace.db");
        assert!(import_workspace(&source, &target).is_err());
        assert!(!target.exists());
        assert_eq!(fs::read(protected).unwrap(), b"keep me");
    }
}
