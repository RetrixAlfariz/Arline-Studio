from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Missing expected block in {path}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace(
    "src/discovery/web.py",
    '''    event_bus=get_domain_event_bus(discovery.store.path)
    def turn_created(event):
        turn=event.payload.get("turn") or {};tid=turn.get("id")
        if not tid:return
        try:discovery.capture_turn(tid,source_kind="user_prompt");turn["_discovery_report"]=persisted_turn_report(tid,"user_prompt")
        except Exception as exc:turn["_discovery_report"]={"turn_id":tid,"source_kind":"user_prompt","propositions":0,"instances":0,"error":str(exc)};report_failure(f"turn:{tid}",exc)
    def feedback_changed(event):
        turn=event.payload.get("turn") or {};tid=turn.get("id");status=turn.get("feedback_status");kind=None
        if not tid:return
        try:
            if status=="accepted":discovery.store.set_source_kind_active(tid,"user_edited_prose",active=False,reason="feedback_replaced");kind="accepted_generation"
            elif status=="edited_accept":discovery.store.set_source_kind_active(tid,"accepted_generation",active=False,reason="feedback_replaced");kind="user_edited_prose"
            elif status=="rejected":discovery.store.set_source_kind_active(tid,"accepted_generation",active=False,reason="feedback_rejected");discovery.store.set_source_kind_active(tid,"user_edited_prose",active=False,reason="feedback_rejected")
            if kind:discovery.capture_turn(tid,source_kind=kind);turn["_discovery_report"]=persisted_turn_report(tid,kind)
        except Exception as exc:report_failure(f"feedback:{tid}",exc)
    def session_deleted(event):
        sid=event.payload.get("session_id")
        if sid:
            try:discovery.set_session_active(sid,active=False,reason="source_deleted")
            except Exception as exc:report_failure(f"session:{sid}",exc)
    def scope_deleted(event):
        for sid in event.payload.get("session_ids") or []:
            try:discovery.set_session_active(sid,active=False,reason="scope_deleted")
            except Exception as exc:report_failure(f"scope:{sid}",exc)
    def trashed(event):
        p=event.payload;sid=p.get("resource_id")
        if p.get("resource_type")=="session" and sid:
            try:discovery.set_session_active(sid,active=False,reason="source_trashed")
            except Exception as exc:report_failure(f"trash:{sid}",exc)
    def restored(event):
        p=event.payload;sid=p.get("resource_id")
        if p.get("resource_type")!="session" or not sid:return
        try:
            with discovery.store._lock,discovery.store.connection() as con:con.execute("UPDATE discovery_instances SET active=1,invalidation_reason=NULL,updated_at=datetime('now') WHERE source_session_id=? AND invalidation_reason='source_trashed'",(sid,))
        except Exception as exc:report_failure(f"restore:{sid}",exc)
    for name,handler,key in (("history.turn_created",turn_created,"discovery.turn"),("history.feedback_changed",feedback_changed,"discovery.feedback"),("history.session_deleted",session_deleted,"discovery.delete"),("history.scope_deleted",scope_deleted,"discovery.scope"),("foundation.resource_trashed",trashed,"discovery.trash"),("foundation.resource_restored",restored,"discovery.restore")):event_bus.subscribe(name,handler,key=key)
    memory_service._v121_discovery_events_bound=True;memory_service._v121_discovery_hooks_bound=True
''',
    '''    def turn_created(event):
        turn = event.payload.get("turn") or {}
        turn_id = turn.get("id")
        if not turn_id:
            return
        try:
            discovery.capture_turn(turn_id, source_kind="user_prompt")
            turn["_discovery_report"] = persisted_turn_report(turn_id, "user_prompt")
        except Exception as exc:
            turn["_discovery_report"] = {
                "turn_id": turn_id,
                "source_kind": "user_prompt",
                "propositions": 0,
                "instances": 0,
                "error": str(exc),
            }
            report_failure(f"turn:{turn_id}", exc)

    def feedback_changed(event):
        turn = event.payload.get("turn") or {}
        turn_id = turn.get("id")
        status = turn.get("feedback_status")
        source_kind = None
        if not turn_id:
            return
        try:
            if status == "accepted":
                discovery.store.set_source_kind_active(
                    turn_id, "user_edited_prose", active=False, reason="feedback_replaced"
                )
                source_kind = "accepted_generation"
            elif status == "edited_accept":
                discovery.store.set_source_kind_active(
                    turn_id, "accepted_generation", active=False, reason="feedback_replaced"
                )
                source_kind = "user_edited_prose"
            elif status == "rejected":
                discovery.store.set_source_kind_active(
                    turn_id, "accepted_generation", active=False, reason="feedback_rejected"
                )
                discovery.store.set_source_kind_active(
                    turn_id, "user_edited_prose", active=False, reason="feedback_rejected"
                )
            if source_kind:
                discovery.capture_turn(turn_id, source_kind=source_kind)
                turn["_discovery_report"] = persisted_turn_report(turn_id, source_kind)
        except Exception as exc:
            report_failure(f"feedback:{turn_id}", exc)

    def session_deleted(event):
        session_id = event.payload.get("session_id")
        if not session_id:
            return
        try:
            discovery.set_session_active(session_id, active=False, reason="source_deleted")
        except Exception as exc:
            report_failure(f"session:{session_id}", exc)

    def scope_deleted(event):
        for session_id in event.payload.get("session_ids") or []:
            try:
                discovery.set_session_active(session_id, active=False, reason="scope_deleted")
            except Exception as exc:
                report_failure(f"scope:{session_id}", exc)

    def resource_trashed(event):
        payload = event.payload
        session_id = payload.get("resource_id")
        if payload.get("resource_type") != "session" or not session_id:
            return
        try:
            discovery.set_session_active(session_id, active=False, reason="source_trashed")
        except Exception as exc:
            report_failure(f"trash:{session_id}", exc)

    def resource_restored(event):
        payload = event.payload
        session_id = payload.get("resource_id")
        if payload.get("resource_type") != "session" or not session_id:
            return
        try:
            with discovery.store._lock, discovery.store.connection() as con:
                con.execute(
                    "UPDATE discovery_instances SET active=1,invalidation_reason=NULL,"
                    "updated_at=datetime('now') WHERE source_session_id=? "
                    "AND invalidation_reason='source_trashed'",
                    (session_id,),
                )
        except Exception as exc:
            report_failure(f"restore:{session_id}", exc)

    # History and Workspace may intentionally live in different SQLite files.
    # Subscribe to the bus that owns each authoritative source instead of
    # assuming the default single-database layout.
    history_bus = get_domain_event_bus(memory_service.history.path)
    workspace_bus = get_domain_event_bus(discovery.store.path)
    for name, handler, key in (
        ("history.turn_created", turn_created, "discovery.turn"),
        ("history.feedback_changed", feedback_changed, "discovery.feedback"),
        ("history.session_deleted", session_deleted, "discovery.delete"),
        ("history.scope_deleted", scope_deleted, "discovery.scope"),
    ):
        history_bus.subscribe(name, handler, key=key)
    for name, handler, key in (
        ("foundation.resource_trashed", resource_trashed, "discovery.trash"),
        ("foundation.resource_restored", resource_restored, "discovery.restore"),
    ):
        workspace_bus.subscribe(name, handler, key=key)

    # Compatibility/status markers only. No authoritative method is replaced.
    memory_service._v121_discovery_events_bound = True
    memory_service._v121_discovery_hooks_bound = True
''',
)

replace(
    "src/memory/web.py",
    '''    def _timeline_changed(domain_event):
        event=domain_event.payload.get("event") or {};world_id=event.get("world_id");refresh=getattr(service,"refresh_timeline_state",None)
        if not world_id or not callable(refresh):return
        try:refresh(world_id,event.get("branch_id"))
        except Exception as exc:
            reporter=getattr(service,"_report_refresh_failure",None)
            if callable(reporter):reporter(f"timeline:{world_id}",exc)
    get_domain_event_bus(getattr(store,"path","arline-memory.db")).subscribe("workspace.timeline_event_created",_timeline_changed,key="memory.timeline_refresh")
    service._v121_timeline_refresh_hook_bound=True
''',
    '''    def _timeline_changed(domain_event):
        event = domain_event.payload.get("event") or {}
        world_id = event.get("world_id")
        refresh = getattr(service, "refresh_timeline_state", None)
        if not world_id or not callable(refresh):
            return
        try:
            refresh(world_id, event.get("branch_id"))
        except Exception as exc:
            reporter = getattr(service, "_report_refresh_failure", None)
            if callable(reporter):
                reporter(f"timeline:{world_id}", exc)

    workspace = getattr(service, "workspace", None)
    workspace_path = getattr(workspace, "path", getattr(store, "path", "arline-memory.db"))
    get_domain_event_bus(workspace_path).subscribe(
        "workspace.timeline_event_created",
        _timeline_changed,
        key="memory.timeline_refresh",
    )
    # Compatibility/status marker only. WorkspaceStore is not monkey-patched.
    service._v121_timeline_refresh_hook_bound = True
''',
)

replace(
    "src/history/store.py",
    '''        emit_domain_event(self.path,"history.session_deleted",{"session_id":session_id})
''',
    '''        emit_domain_event(
            self.path,
            "history.session_deleted",
            {"session_id": session_id},
        )
''',
)
replace(
    "src/history/store.py",
    '''        filters=[];params=[]
        for column,value in (("project_id",project_id),("world_id",world_id),("branch_id",branch_id)):
            if value is not None:filters.append(f"{column}=?");params.append(value)
        if not filters:raise ValueError("At least one scope id is required")
        with self._lock,self._connection() as con:
            rows=con.execute(f"SELECT id FROM sessions WHERE {' AND '.join(filters)}",params).fetchall()
            session_ids=[str(x["id"]) for x in rows]
            cur=con.execute(f"DELETE FROM sessions WHERE {' AND '.join(filters)}",params);deleted=max(0,cur.rowcount)
        emit_domain_event(self.path,"history.scope_deleted",{"project_id":project_id,"world_id":world_id,"branch_id":branch_id,"session_ids":session_ids,"deleted_count":deleted})
        return deleted
''',
    '''        filters: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("project_id", project_id),
            ("world_id", world_id),
            ("branch_id", branch_id),
        ):
            if value is not None:
                filters.append(f"{column}=?")
                params.append(value)
        if not filters:
            raise ValueError("At least one scope id is required")

        with self._lock, self._connection() as con:
            rows = con.execute(
                f"SELECT id FROM sessions WHERE {' AND '.join(filters)}",
                params,
            ).fetchall()
            session_ids = [str(row["id"]) for row in rows]
            cur = con.execute(
                f"DELETE FROM sessions WHERE {' AND '.join(filters)}",
                params,
            )
            deleted = max(0, cur.rowcount)

        emit_domain_event(
            self.path,
            "history.scope_deleted",
            {
                "project_id": project_id,
                "world_id": world_id,
                "branch_id": branch_id,
                "session_ids": session_ids,
                "deleted_count": deleted,
            },
        )
        return deleted
''',
)
replace(
    "src/history/store.py",
    '''        result=self.get_turn(turn_id)
        emit_domain_event(self.path,"history.turn_created",{"turn":result})
        return result
''',
    '''        result = self.get_turn(turn_id)
        emit_domain_event(self.path, "history.turn_created", {"turn": result})
        return result
''',
)
replace(
    "src/history/store.py",
    '''        result=self.get_turn(turn_id)
        emit_domain_event(self.path,"history.feedback_changed",{"turn":result})
        return result
''',
    '''        result = self.get_turn(turn_id)
        emit_domain_event(self.path, "history.feedback_changed", {"turn": result})
        return result
''',
)

replace(
    "src/memory/store.py",
    '''    def __init__(self, database_path: Path | str, *, backup_before_migration: bool = True):
        self.path=Path(database_path);self.path.parent.mkdir(parents=True,exist_ok=True);self._lock=RLock()
        self.last_migration_backup=backup_sqlite_before_migrations(self.path,{"memory_meta":self.SCHEMA_VERSION}) if backup_before_migration else None
        self.fts_available=True;self._init_db()
''',
    '''    def __init__(
        self,
        database_path: Path | str,
        *,
        backup_before_migration: bool = True,
    ):
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self.last_migration_backup = (
            backup_sqlite_before_migrations(
                self.path,
                {"memory_meta": self.SCHEMA_VERSION},
            )
            if backup_before_migration
            else None
        )
        self.fts_available = True
        self._init_db()
''',
)

print("event spine polish applied")
