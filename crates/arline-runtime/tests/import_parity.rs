use arline_runtime::import::import_legacy_workspace;
use rusqlite::Connection;
use std::fs;

#[test]
fn split_legacy_history_and_workspace_merge_without_touching_sources() {
    let temp = tempfile::tempdir().unwrap();
    let legacy = temp.path().join("legacy");
    let target = temp.path().join("native/workspace.db");
    fs::create_dir_all(&legacy).unwrap();
    let workspace = legacy.join("workspace.sqlite");
    let history = legacy.join("history.sqlite");
    let wc = Connection::open(&workspace).unwrap();
    wc.execute_batch("CREATE TABLE projects(id TEXT PRIMARY KEY, name TEXT); INSERT INTO projects VALUES('P-1','Imported');").unwrap();
    let hc = Connection::open(&history).unwrap();
    hc.execute_batch("CREATE TABLE sessions(id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL); CREATE TABLE turns(id TEXT PRIMARY KEY, session_id TEXT NOT NULL, user_prompt TEXT NOT NULL, story TEXT NOT NULL); INSERT INTO sessions VALUES('S-1','Chat','2026-01-01','2026-01-01'); INSERT INTO turns VALUES('T-1','S-1','hello','world');").unwrap();
    let workspace_before = fs::read(&workspace).unwrap();
    let history_before = fs::read(&history).unwrap();
    let report = import_legacy_workspace(&history, &workspace, &target).unwrap();
    assert_eq!(report.history_sessions, 1);
    assert_eq!(report.history_turns, 1);
    let imported = Connection::open(&target).unwrap();
    assert_eq!(
        imported
            .query_row("SELECT name FROM projects WHERE id='P-1'", [], |r| r
                .get::<_, String>(0))
            .unwrap(),
        "Imported"
    );
    assert_eq!(
        imported
            .query_row("SELECT title FROM sessions WHERE id='S-1'", [], |r| r
                .get::<_, String>(0))
            .unwrap(),
        "Chat"
    );
    assert_eq!(
        imported
            .query_row("SELECT story FROM turns WHERE id='T-1'", [], |r| r
                .get::<_, String>(0))
            .unwrap(),
        "world"
    );
    assert_eq!(fs::read(&workspace).unwrap(), workspace_before);
    assert_eq!(fs::read(&history).unwrap(), history_before);
}

#[test]
fn same_source_uses_existing_copy_path_without_double_import() {
    let temp = tempfile::tempdir().unwrap();
    let source = temp.path().join("source.sqlite");
    let target = temp.path().join("target/workspace.db");
    let c = Connection::open(&source).unwrap();
    c.execute_batch("CREATE TABLE sample(value TEXT); INSERT INTO sample VALUES('kept');")
        .unwrap();
    let report = import_legacy_workspace(&source, &source, &target).unwrap();
    assert_eq!(report.history_sessions, 0);
    assert_eq!(
        Connection::open(target)
            .unwrap()
            .query_row("SELECT value FROM sample", [], |r| r.get::<_, String>(0))
            .unwrap(),
        "kept"
    );
}
