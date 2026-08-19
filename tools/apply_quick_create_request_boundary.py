from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"Missing expected block in {path}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace(
    "src/interface/web/static/js/quick-create.js",
    "  window.ArlineQuickCreate = { decodeCreateAs, inferRelationship };\n",
    "  window.ArlineQuickCreate = { decodeCreateAs, inferRelationship, preparePayload, previewOverride };\n",
)

old = '''  function relationshipPreviewResponse(body) {
    const variants = scopedVariants(libraryCache || {});
    const inferred = inferRelationship(body.text || "", variants);
    const subject = variants.find((v) => v.id === inferred.subject_id);
    const object = variants.find((v) => v.id === inferred.object_id);
    const data = {
      kind: "relationship",
      entity_type: null,
      name: subject && object ? `${subject.display_name} ↔ ${object.display_name}` : (String(body.text || "").trim() || "Relationship"),
      description: inferred.relation_type || "Choose subject, relation, and object below",
      confidence: inferred.resolved ? 0.95 : 0.55,
      attributes: {}, shared_core: {}, document_type: null,
      warnings: inferred.resolved ? [] : ["Resolve two existing entities and a relationship type before creating."],
      detected: inferred.relation_type ? [inferred.relation_type] : [],
    };
    return new Response(JSON.stringify(data), { status: 200, headers: { "Content-Type": "application/json" } });
  }

  window.fetch = async function (input, init = {}) {
    const url = typeof input === "string" ? input : input?.url || "";
    const isQuick = url.includes("/api/quick-create");
    if (!isQuick || !init?.body || typeof init.body !== "string") return originalFetch(input, init);
    let body;
    try { body = JSON.parse(init.body); } catch (_) { return originalFetch(input, init); }
    const mode = decodeCreateAs(byId("quickCreateKind")?.value || body.forced_kind || "");
    if (url.includes("/api/quick-create/preview") && mode.kind === "relationship") return relationshipPreviewResponse(body);
    if (mode.kind) body.forced_kind = mode.kind;
    if (mode.entity_type) body.entity_type = mode.entity_type;
    if (mode.document_type) body.document_type = mode.document_type;
    Object.assign(body, scopePayload(mode));
    const response = await originalFetch(input, { ...init, body: JSON.stringify(body) });
    if (url.includes("/api/quick-create/preview") && response.ok && (mode.entity_type || mode.document_type)) {
      const data = await response.clone().json();
      if (mode.entity_type) data.entity_type = mode.entity_type;
      if (mode.document_type) data.document_type = mode.document_type;
      return new Response(JSON.stringify(data), { status: response.status, statusText: response.statusText, headers: { "Content-Type": "application/json" } });
    }
    return response;
  };
'''
new = '''  function preparePayload(body = {}) {
    const next = { ...body };
    const mode = decodeCreateAs(byId("quickCreateKind")?.value || next.forced_kind || "");
    if (mode.kind) next.forced_kind = mode.kind;
    if (mode.entity_type) next.entity_type = mode.entity_type;
    if (mode.document_type) next.document_type = mode.document_type;
    Object.assign(next, scopePayload(mode));
    return next;
  }

  function previewOverride(body = {}) {
    const mode = decodeCreateAs(byId("quickCreateKind")?.value || body.forced_kind || "");
    if (mode.kind !== "relationship") return null;
    const variants = scopedVariants(libraryCache || {});
    const inferred = inferRelationship(body.text || "", variants);
    const subject = variants.find((v) => v.id === inferred.subject_id);
    const object = variants.find((v) => v.id === inferred.object_id);
    return {
      kind: "relationship",
      entity_type: null,
      name: subject && object ? `${subject.display_name} ↔ ${object.display_name}` : (String(body.text || "").trim() || "Relationship"),
      description: inferred.relation_type || "Choose subject, relation, and object below",
      confidence: inferred.resolved ? 0.95 : 0.55,
      attributes: {},
      shared_core: {},
      document_type: null,
      warnings: inferred.resolved ? [] : ["Resolve two existing entities and a relationship type before creating."],
      detected: inferred.relation_type ? [inferred.relation_type] : [],
    };
  }
'''
replace("src/interface/web/static/js/quick-create.js", old, new)

replace(
    "src/interface/web/static/arline.js",
    '''    const preview = await api("/api/quick-create/preview", { method: "POST", body: { text, forced_kind: forced, project_id: state.activeProject?.id || null, world_id: state.activeWorld?.id || null, branch_id: state.activeBranch?.id || null, folder_id: state.activeWorldFolderId || null } }); state.quickCreatePreview = preview;
''',
    '''    const rawBody = { text, forced_kind: forced, project_id: state.activeProject?.id || null, world_id: state.activeWorld?.id || null, branch_id: state.activeBranch?.id || null, folder_id: state.activeWorldFolderId || null };
    const body = window.ArlineQuickCreate?.preparePayload?.(rawBody) || rawBody;
    const preview = window.ArlineQuickCreate?.previewOverride?.(body)
      || await api("/api/quick-create/preview", { method: "POST", body });
    state.quickCreatePreview = preview;
''',
)

replace(
    "src/interface/web/static/arline.js",
    '''    const result=await api("/api/quick-create",{method:"POST",body:{text,forced_kind:byId("quickCreateKind").value||null,project_id:state.activeProject?.id||null,world_id:state.activeWorld?.id||null,branch_id:state.activeBranch?.id||null,folder_id:preview.kind==="entity"?state.activeWorldFolderId:null}});
''',
    '''    const rawBody={text,forced_kind:byId("quickCreateKind").value||null,project_id:state.activeProject?.id||null,world_id:state.activeWorld?.id||null,branch_id:state.activeBranch?.id||null,folder_id:preview.kind==="entity"?state.activeWorldFolderId:null};
    const body=window.ArlineQuickCreate?.preparePayload?.(rawBody)||rawBody;
    const result=await api("/api/quick-create",{method:"POST",body});
''',
)

print("Quick Create request boundary applied")
