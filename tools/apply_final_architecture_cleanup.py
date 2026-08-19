from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Missing expected block in {path}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# One migration backup at application startup; standalone stores retain their
# own backup hook when no application-level boundary has already run.
replace(
    "src/interface/web/app.py",
    '''        lmstudio_api_key=initial_cfg.lmstudio.api_key,
    )
    media_root = workspace_path.parent / "media"
''',
    '''        lmstudio_api_key=initial_cfg.lmstudio.api_key,
    )
    memory_service._combined_migration_backup_complete = True
    media_root = workspace_path.parent / "media"
''',
)
replace(
    "src/discovery/web.py",
    '''        discovery_store = DiscoveryStore(memory_service.store.path)
        discovery = DiscoveryService(
''',
    '''        discovery_store = DiscoveryStore(
            memory_service.store.path,
            backup_before_migration=not bool(
                getattr(memory_service, "_combined_migration_backup_complete", False)
            ),
        )
        discovery = DiscoveryService(
''',
)

# Bulk Trash belongs to the Library owner, not a runtime compatibility shim.
bulk_archive = '''async function bulkArchiveSelected() {
  const ids=[...state.worldSelection]; if(!ids.length||!confirm(`Archive ${ids.length} selected Library sheets?`))return;
  for(const id of ids)await api("/api/lifecycle/archive?archived=true",{method:"POST",body:{resource_type:"entity_family",resource_id:id}});
  clearWorldSelection();await loadProjectData();toast(`Archived ${ids.length} sheets`);
}
'''
bulk_trash = bulk_archive + '''async function bulkTrashSelected() {
  const ids = [...state.worldSelection];
  if (!ids.length || !confirm(`Move ${ids.length} selected Library sheets to Trash?\\n\\nThey remain recoverable from Activity Center, or immediately with Ctrl+Z.`)) return;

  const selectedIds = new Set(ids);
  const selectedVariantIds = new Set(
    (state.variants || [])
      .filter((variant) => selectedIds.has(variant.family_id))
      .map((variant) => variant.id),
  );
  const resources = ids.map((id) => ({
    resourceType: "entity_family",
    resourceId: id,
    label: (state.families || []).find((item) => item.id === id)?.name || id,
  }));
  const moved = [];
  const failed = [];

  for (const resource of resources) {
    try {
      await api("/api/lifecycle/trash", {
        method: "POST",
        body: { resource_type: resource.resourceType, resource_id: resource.resourceId },
      });
      moved.push(resource);
    } catch (error) {
      failed.push({ ...resource, error });
    }
  }

  if (moved.length) {
    const movedIds = new Set(moved.map((item) => item.resourceId));
    lastUndo = { type: "restore_bulk", resources: moved };
    state.selectedReferences = (state.selectedReferences || []).filter((ref) => {
      if (ref.type === "entity_family" && movedIds.has(ref.id)) return false;
      if (ref.type === "entity_variant" && selectedVariantIds.has(ref.id)) return false;
      return true;
    });
    updateContextChipUI();
    scheduleContextStackSync();
  }

  state.worldSelection = new Set(failed.map((item) => item.resourceId));
  await loadProjectData();
  updateWorldBulkBar();
  if (failed.length) toast(`Moved ${moved.length}/${resources.length} sheets to Trash · ${failed.length} failed`, 6000);
  else toast(`Moved ${moved.length} Library sheets to Trash · Ctrl+Z to undo`, 5000);
}
'''
replace("src/interface/web/static/arline.js", bulk_archive, bulk_trash)

replace(
    "src/interface/web/static/arline.js",
    '''  const action = lastUndo; lastUndo = null;
  if (action.type === "restore") {
''',
    '''  const action = lastUndo; lastUndo = null;
  if (action.type === "restore_bulk") {
    const failed = [];
    for (const resource of action.resources || []) {
      try {
        await api("/api/lifecycle/restore", {
          method: "POST",
          body: { resource_type: resource.resourceType, resource_id: resource.resourceId },
        });
      } catch (error) {
        failed.push({ ...resource, error });
      }
    }
    lastUndo = failed.length ? { type: "restore_bulk", resources: failed } : null;
    await loadProjectData();
    if (failed.length) toast(`Restore incomplete · ${failed.length} item(s) can be retried with Ctrl+Z`, 6000);
    else toast(`Restored ${(action.resources || []).length} Library sheets`);
    return;
  }
  if (action.type === "restore") {
''',
)
replace(
    "src/interface/web/static/arline.js",
    '''  on("bulkMoveBtn", "click", bulkMoveSelected); on("bulkCollectionBtn", "click", bulkAddCollection); on("bulkArchiveBtn", "click", bulkArchiveSelected); on("bulkClearBtn", "click", clearWorldSelection);
''',
    '''  on("bulkMoveBtn", "click", bulkMoveSelected); on("bulkCollectionBtn", "click", bulkAddCollection); on("bulkArchiveBtn", "click", bulkArchiveSelected); on("bulkTrashBtn", "click", bulkTrashSelected); on("bulkClearBtn", "click", clearWorldSelection);
''',
)

replace(
    "src/interface/web/static/index.html",
    '''<button id="bulkArchiveBtn" class="tiny-btn">Archive</button><button id="bulkClearBtn" class="tiny-btn">Clear</button>''',
    '''<button id="bulkArchiveBtn" class="tiny-btn">Archive</button><button id="bulkTrashBtn" class="tiny-danger-btn">Trash</button><button id="bulkClearBtn" class="tiny-btn">Clear</button>''',
)
replace(
    "src/interface/web/static/index.html",
    '''  <script src="/static/arline.js?v=1.2.2-hardening" defer></script>
  <script src="/static/js/compat.js?v=1.2.2-hardening" defer></script>
  <script src="/static/js/memory.js?v=1.2.2-hardening" defer></script>
''',
    '''  <script src="/static/arline.js?v=1.2.2-hardening" defer></script>
  <script src="/static/js/quick-create.js?v=1.2.2-hardening" defer></script>
  <script src="/static/js/discovery-sheets.js?v=1.2.2-hardening" defer></script>
  <script src="/static/js/memory.js?v=1.2.2-hardening" defer></script>
''',
)

print("final architecture cleanup applied")
