import type {
  CommandPayload,
  JsonMap,
  DocumentItem,
  GenerationResult,
  ModelInfo,
  Project,
  ProjectTree,
  ReferenceItem,
  RuntimeConfig,
  Session,
  WorkspaceBootstrap,
  WorldBible,
  MediaItem,
} from "./types";

type RequestInitJson = Omit<RequestInit, "body"> & { body?: unknown };

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function api<T>(path: string, options: RequestInitJson = {}): Promise<T> {
  const headers = new Headers(options.headers);
  let body: BodyInit | undefined;
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(options.body);
  }
  const response = await fetch(path, { ...options, headers, body });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const payload = (await response.json()) as { detail?: string; message?: string };
      message = payload.detail || payload.message || message;
    } catch {
      // Keep HTTP status fallback.
    }
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) return (await response.json()) as T;
  return (await response.text()) as T;
}

function qs(values: Record<string, string | number | boolean | null | undefined>) {
  const query = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
  });
  const encoded = query.toString();
  return encoded ? `?${encoded}` : "";
}

export const studioApi = {
  config: () => api<RuntimeConfig>("/api/config"),
  resetStorage: (mode: "database" | "complete", confirmation: string) => api<{
    ok: boolean;
    mode: string;
    backups: string[];
    removed_directories: string[];
    restart_required: boolean;
  }>("/api/storage/reset", { method: "POST", body: { mode, confirmation } }),
  saveSettings: (payload: Record<string, unknown>) => api<Record<string, unknown>>("/api/settings", { method: "POST", body: payload }),
  models: (serverUrl: string, apiKey?: string) => api<{ models: ModelInfo[] }>("/api/models/query", {
    method: "POST",
    body: { server_url: serverUrl || null, api_key: apiKey || null },
  }),
  reloadModel: (payload: Record<string, unknown>) => api<JsonMap>("/api/model/reload", { method: "POST", body: payload }),
  bootstrap: (stackId: string) => api<WorkspaceBootstrap>(`/api/workspace/bootstrap?stack_id=${encodeURIComponent(stackId)}`),
  projects: () => api<{ projects: Project[] }>("/api/projects"),
  project: (projectId: string) => api<Project>(`/api/projects/${encodeURIComponent(projectId)}`),
  projectTree: (projectId: string, worldId?: string, branchId?: string) => {
    const query = new URLSearchParams();
    if (worldId) query.set("world_id", worldId);
    if (branchId) query.set("branch_id", branchId);
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return api<ProjectTree>(`/api/projects/${encodeURIComponent(projectId)}/tree${suffix}`);
  },
  worldBible: (projectId?: string, worldId?: string, branchId?: string) => {
    const query = new URLSearchParams();
    if (projectId) query.set("project_id", projectId);
    if (worldId) query.set("world_id", worldId);
    if (branchId) query.set("branch_id", branchId);
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return api<WorldBible>(`/api/world-bible${suffix}`);
  },
  sessions: (projectId?: string, worldId?: string, branchId?: string) => {
    const query = new URLSearchParams({ limit: "120" });
    if (projectId) query.set("project_id", projectId);
    if (worldId) query.set("world_id", worldId);
    if (branchId) query.set("branch_id", branchId);
    return api<{ sessions: Session[] }>(`/api/sessions?${query}`);
  },
  session: (sessionId: string) => api<Session>(`/api/sessions/${encodeURIComponent(sessionId)}`),
  updateSession: (sessionId: string, payload: Record<string, unknown>) => api<Session>(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: "PATCH", body: payload }),
  sessionForks: (sessionId: string) => api<{ sessions: Session[] }>(`/api/sessions/${encodeURIComponent(sessionId)}/forks`),
  forkSession: (sessionId: string, throughTurnId?: string) => api<Session>(`/api/sessions/${encodeURIComponent(sessionId)}/fork`, {
    method: "POST",
    body: { through_turn_id: throughTurnId || null },
  }),
  deleteSession: (sessionId: string) => api<{ ok: boolean }>(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" }),
  turn: (turnId: string) => api<JsonMap>(`/api/turns/${encodeURIComponent(turnId)}`),
  deleteTurn: (turnId: string) => api<{ ok: boolean }>(`/api/turns/${encodeURIComponent(turnId)}`, { method: "DELETE" }),
  feedback: (turnId: string, payload: Record<string, unknown>) => api<JsonMap>(`/api/turns/${encodeURIComponent(turnId)}/feedback`, { method: "POST", body: payload }),
  commands: () => api<CommandPayload>("/api/commands"),
  mentions: (query: string, projectId?: string, worldId?: string, branchId?: string) => {
    const params = new URLSearchParams({ q: query, limit: "12" });
    if (projectId) params.set("project_id", projectId);
    if (worldId) params.set("world_id", worldId);
    if (branchId) params.set("branch_id", branchId);
    return api<{ results: Array<Record<string, unknown>> }>(`/api/mentions?${params}`);
  },
  analyze: (payload: Record<string, unknown>) => api<Record<string, unknown>>("/api/analyze", { method: "POST", body: payload }),
  document: (documentId: string) => api<DocumentItem>(`/api/documents/${encodeURIComponent(documentId)}`),
  createDocument: (payload: Record<string, unknown>) => api<DocumentItem>("/api/documents", { method: "POST", body: payload }),
  updateDocument: (documentId: string, payload: Record<string, unknown>) => api<DocumentItem>(`/api/documents/${encodeURIComponent(documentId)}`, { method: "PATCH", body: payload }),
  deleteDocument: (documentId: string) => api<{ ok: boolean }>(`/api/documents/${encodeURIComponent(documentId)}`, { method: "DELETE" }),
  folders: (projectId: string, worldId?: string, branchId?: string) => api<{ folders: JsonMap[] }>(`/api/folders${qs({ project_id: projectId, world_id: worldId, branch_id: branchId })}`),
  createFolder: (payload: Record<string, unknown>) => api<JsonMap>("/api/folders", { method: "POST", body: payload }),
  updateFolder: (id: string, payload: Record<string, unknown>) => api<JsonMap>(`/api/folders/${encodeURIComponent(id)}`, { method: "PATCH", body: payload }),
  deleteFolder: (id: string) => api<{ ok: boolean }>(`/api/folders/${encodeURIComponent(id)}`, { method: "DELETE" }),
  revisions: (resourceType: string, resourceId: string) => api<{ revisions: JsonMap[] }>(`/api/revisions/${encodeURIComponent(resourceType)}/${encodeURIComponent(resourceId)}`),
  restoreRevision: (id: string, note = "restored in React Studio") => api<JsonMap>(`/api/revisions/${encodeURIComponent(id)}/restore`, { method: "POST", body: { note } }),
  sceneDependencies: (documentId: string) => api<{ dependencies: JsonMap[]; valid?: boolean }>(`/api/scenes/${encodeURIComponent(documentId)}/dependencies`),
  createSceneDependency: (payload: Record<string, unknown>) => api<JsonMap>("/api/scenes/dependencies", { method: "POST", body: payload }),
  deleteSceneDependency: (id: string) => api<{ ok: boolean }>(`/api/scenes/dependencies/${encodeURIComponent(id)}`, { method: "DELETE" }),
  activeScene: (projectId: string) => api<JsonMap>(`/api/projects/${encodeURIComponent(projectId)}/active-scene`),
  setActiveScene: (projectId: string, payload: Record<string, unknown>) => api<JsonMap>(`/api/projects/${encodeURIComponent(projectId)}/active-scene`, { method: "PUT", body: payload }),
  sceneCards: (projectId: string) => api<{ cards: JsonMap[] }>(`/api/projects/${encodeURIComponent(projectId)}/scene-cards`),
  saveSceneCard: (projectId: string, documentId: string, payload: Record<string, unknown>) => api<JsonMap>(`/api/projects/${encodeURIComponent(projectId)}/scene-cards/${encodeURIComponent(documentId)}`, { method: "PUT", body: payload }),
  trash: (resourceType: string, resourceId: string) => api<{ ok?: boolean }>("/api/lifecycle/trash", {
    method: "POST",
    body: { resource_type: resourceType, resource_id: resourceId },
  }),
  quickCreatePreview: (payload: Record<string, unknown>) => api<Record<string, unknown>>("/api/quick-create/preview", { method: "POST", body: payload }),
  quickCreate: (payload: Record<string, unknown>) => api<Record<string, unknown>>("/api/quick-create", { method: "POST", body: payload }),
  media: (params: { resourceType?: string; resourceId?: string; coverOnly?: boolean } = {}) => {
    const query = new URLSearchParams();
    if (params.resourceType) query.set("resource_type", params.resourceType);
    if (params.resourceId) query.set("resource_id", params.resourceId);
    if (params.coverOnly) query.set("cover_only", "true");
    return api<{ items: MediaItem[] }>(`/api/media?${query}`);
  },
  timeline: (worldId: string, branchId?: string) => {
    const query = new URLSearchParams({ world_id: worldId });
    if (branchId) query.set("branch_id", branchId);
    return api<{ events: JsonMap[] }>(`/api/timeline?${query}`);
  },
  createTimelineEvent: (payload: Record<string, unknown>) => api<JsonMap>("/api/timeline", { method: "POST", body: payload }),
  timelineState: (worldId: string, ownerType: string, ownerId: string, branchId?: string, atOrder?: number) => api<JsonMap>(`/api/timeline/state${qs({ world_id: worldId, owner_type: ownerType, owner_id: ownerId, branch_id: branchId, at_order: atOrder })}`),
  continuity: (projectId: string, worldId?: string, branchId?: string) => api<JsonMap>(`/api/projects/${encodeURIComponent(projectId)}/continuity${qs({ world_id: worldId, branch_id: branchId })}`),
  snapshot: (payload: Record<string, unknown>) => api<Record<string, unknown>>("/api/snapshots", { method: "POST", body: payload }),
  snapshots: (worldId: string) => api<{ snapshots: JsonMap[] }>(`/api/snapshots${qs({ world_id: worldId })}`),
  restoreSnapshot: (id: string, branchName?: string) => api<JsonMap>(`/api/snapshots/${encodeURIComponent(id)}/restore`, { method: "POST", body: { branch_name: branchName || null } }),
  deleteSnapshot: (id: string) => api<{ ok: boolean }>(`/api/snapshots/${encodeURIComponent(id)}`, { method: "DELETE" }),
  lifecycle: (action: "archive" | "restore", resourceType: string, resourceId: string) => api<Record<string, unknown>>(`/api/lifecycle/${action}`, { method: "POST", body: { resource_type: resourceType, resource_id: resourceId } }),
  projectsHome: (projectId?: string) => api<JsonMap>(`/api/home${qs({ project_id: projectId })}`),
  search: (query: string, projectId?: string) => api<{ results: JsonMap[] }>(`/api/search${qs({ q: query, project_id: projectId })}`),
  activity: (projectId?: string) => api<{ items: JsonMap[] }>(`/api/activity${qs({ project_id: projectId })}`),
  issues: (projectId?: string) => api<{ issues: JsonMap[] }>(`/api/issues${qs({ project_id: projectId })}`),
  resolveIssue: (id: string) => api<JsonMap>(`/api/issues/${encodeURIComponent(id)}/resolve`, { method: "POST", body: {} }),
  contextStack: (stackId = "default") => api<JsonMap>(`/api/context-stack${qs({ stack_id: stackId })}`),
  saveContextStack: (payload: Record<string, unknown>) => api<JsonMap>("/api/context-stack", { method: "PUT", body: payload }),
  favorites: (projectId?: string) => api<{ favorites: JsonMap[] }>(`/api/favorites${qs({ project_id: projectId })}`),
  addFavorite: (payload: Record<string, unknown>) => api<JsonMap>("/api/favorites", { method: "POST", body: payload }),
  removeFavorite: (resourceType: string, resourceId: string) => api<{ ok: boolean }>(`/api/favorites${qs({ resource_type: resourceType, resource_id: resourceId })}`, { method: "DELETE" }),
  trashItems: () => api<{ items: JsonMap[] }>("/api/trash"),
  purgeTrashItem: (type: string, id: string) => api<{ ok: boolean }>(`/api/trash/${encodeURIComponent(type)}/${encodeURIComponent(id)}`, { method: "DELETE" }),
  backups: () => api<{ backups: JsonMap[] }>("/api/backups"),
  importPreview: (payload: Record<string, unknown>) => api<JsonMap>("/api/import/manuscript/preview", { method: "POST", body: payload }),
  importManuscript: (payload: Record<string, unknown>) => api<JsonMap>("/api/import/manuscript", { method: "POST", body: payload }),
  exportProjectUrl: (projectId: string) => `/api/export/project/${encodeURIComponent(projectId)}`,
  exportWorldBibleUrl: (projectId?: string, worldId?: string) => `/api/export/world-bible${qs({ project_id: projectId, world_id: worldId })}`,
  feedbackQueue: (projectId?: string) => api<{ items: JsonMap[] }>(`/api/feedback/queue${qs({ project_id: projectId })}`),
  feedbackComparisons: (projectId?: string) => api<{ items: JsonMap[] }>(`/api/feedback/comparisons${qs({ project_id: projectId })}`),
  datasetStats: () => api<JsonMap>("/api/dataset/stats"),
  exportDatasetUrl: (kind: string) => `/api/dataset/export/${encodeURIComponent(kind)}`,
  contract: () => api<{ content: string }>("/api/contract"),
  saveContract: (content: string) => api<JsonMap>("/api/contract", { method: "POST", body: { content } }),
  ablation: (payload: Record<string, unknown>) => api<JsonMap>("/api/ablation", { method: "POST", body: payload }),
  trace: (cacheId: string, traceId: string) => api<JsonMap>(`/api/trace/${encodeURIComponent(cacheId)}/${encodeURIComponent(traceId)}`),
  runProfiles: (projectId?: string) => api<{ profiles: JsonMap[] }>(`/api/run-profiles${qs({ project_id: projectId })}`),
  saveRunProfile: (payload: Record<string, unknown>) => api<JsonMap>("/api/run-profiles", { method: "POST", body: payload }),
  deleteRunProfile: (id: string) => api<{ ok: boolean }>(`/api/run-profiles/${encodeURIComponent(id)}`, { method: "DELETE" }),
  contextRecipes: (projectId?: string) => api<{ recipes: JsonMap[] }>(`/api/context/recipes${qs({ project_id: projectId })}`),
  createContextRecipe: (projectId: string, payload: Record<string, unknown>) => api<JsonMap>(`/api/projects/${encodeURIComponent(projectId)}/context-recipes`, { method: "POST", body: payload }),
  facts: (projectId?: string, worldId?: string, branchId?: string) => api<{ facts: JsonMap[] }>(`/api/facts${qs({ project_id: projectId, world_id: worldId, branch_id: branchId })}`),
  createFact: (payload: Record<string, unknown>) => api<JsonMap>("/api/facts", { method: "POST", body: payload }),
  retconPreview: (payload: Record<string, unknown>) => api<JsonMap>("/api/retcon/preview", { method: "POST", body: payload }),
  retconApply: (payload: Record<string, unknown>) => api<JsonMap>("/api/retcon/apply", { method: "POST", body: payload }),
  createWorld: (payload: Record<string, unknown>) => api<JsonMap>("/api/worlds", { method: "POST", body: payload }),
  updateWorld: (id: string, payload: Record<string, unknown>) => api<JsonMap>(`/api/worlds/${encodeURIComponent(id)}`, { method: "PATCH", body: payload }),
  deleteWorld: (id: string) => api<{ ok: boolean }>(`/api/worlds/${encodeURIComponent(id)}`, { method: "DELETE" }),
  createBranch: (payload: Record<string, unknown>) => api<JsonMap>("/api/branches", { method: "POST", body: payload }),
  createSandbox: (worldId: string, name = "Sandbox") => api<JsonMap>(`/api/worlds/${encodeURIComponent(worldId)}/sandbox${qs({ name })}`, { method: "POST" }),
  compareWorlds: (left: string, right: string) => api<JsonMap>(`/api/worlds/compare/${encodeURIComponent(left)}/${encodeURIComponent(right)}`),
  compareBranches: (left: string, right: string) => api<JsonMap>(`/api/branches/compare/${encodeURIComponent(left)}/${encodeURIComponent(right)}`),
  mergeBranch: (source: string, payload: Record<string, unknown>) => api<JsonMap>(`/api/branches/${encodeURIComponent(source)}/merge`, { method: "POST", body: payload }),
  entityFamily: (id: string) => api<JsonMap>(`/api/entities/families/${encodeURIComponent(id)}`),
  createEntityFamily: (payload: Record<string, unknown>) => api<JsonMap>("/api/entities/families", { method: "POST", body: payload }),
  updateEntityFamily: (id: string, payload: Record<string, unknown>) => api<JsonMap>(`/api/entities/families/${encodeURIComponent(id)}`, { method: "PATCH", body: payload }),
  deleteEntityFamily: (id: string) => api<{ ok: boolean }>(`/api/entities/families/${encodeURIComponent(id)}`, { method: "DELETE" }),
  createVariant: (payload: Record<string, unknown>) => api<JsonMap>("/api/entities/variants", { method: "POST", body: payload }),
  updateVariant: (id: string, payload: Record<string, unknown>) => api<JsonMap>(`/api/entities/variants/${encodeURIComponent(id)}`, { method: "PATCH", body: payload }),
  relationship: (id: string) => api<JsonMap>(`/api/relationships/${encodeURIComponent(id)}`),
  createRelationship: (payload: Record<string, unknown>) => api<JsonMap>("/api/relationships", { method: "POST", body: payload }),
  updateRelationship: (id: string, payload: Record<string, unknown>) => api<JsonMap>(`/api/relationships/${encodeURIComponent(id)}`, { method: "PATCH", body: payload }),
  deleteRelationship: (id: string) => api<{ ok: boolean }>(`/api/relationships/${encodeURIComponent(id)}`, { method: "DELETE" }),
  collections: (scopeId?: string) => api<{ collections: JsonMap[] }>(`/api/collections${qs({ scope_id: scopeId })}`),
  createCollection: (payload: Record<string, unknown>) => api<JsonMap>("/api/collections", { method: "POST", body: payload }),
  linkCollection: (id: string, payload: Record<string, unknown>) => api<JsonMap>(`/api/collections/${encodeURIComponent(id)}/links`, { method: "POST", body: payload }),
  savedViews: (scopeId?: string) => api<{ views: JsonMap[] }>(`/api/saved-views${qs({ scope_id: scopeId })}`),
  createSavedView: (payload: Record<string, unknown>) => api<JsonMap>("/api/saved-views", { method: "POST", body: payload }),
  tags: (projectId?: string) => api<{ tags: JsonMap[] }>(`/api/tags${qs({ project_id: projectId })}`),
  createTag: (payload: Record<string, unknown>) => api<JsonMap>("/api/tags", { method: "POST", body: payload }),
  linkTag: (tagId: string, payload: Record<string, unknown>) => api<JsonMap>(`/api/tags/${encodeURIComponent(tagId)}/link`, { method: "POST", body: payload }),
  aliases: (resourceType: string, resourceId: string) => api<{ aliases: JsonMap[] }>(`/api/aliases${qs({ resource_type: resourceType, resource_id: resourceId })}`),
  createAlias: (payload: Record<string, unknown>) => api<JsonMap>("/api/aliases", { method: "POST", body: payload }),
  deleteAlias: (id: string) => api<{ ok: boolean }>(`/api/aliases/${encodeURIComponent(id)}`, { method: "DELETE" }),
  promoteCanon: (payload: Record<string, unknown>) => api<JsonMap>("/api/canon/promote", { method: "POST", body: payload }),
  unpinContext: (id: string) => api<{ ok: boolean }>(`/api/context/pins/${encodeURIComponent(id)}`, { method: "DELETE" }),
  parseDirectives: (payload: Record<string, unknown>) => api<JsonMap>("/api/directives/parse", { method: "POST", body: payload }),
  compareVariants: (left: string, right: string) => api<JsonMap>(`/api/entities/variants/compare/${encodeURIComponent(left)}/${encodeURIComponent(right)}`),
  deleteFact: (id: string) => api<{ ok: boolean }>(`/api/facts/${encodeURIComponent(id)}`, { method: "DELETE" }),
  jobs: () => api<{ jobs: JsonMap[] }>("/api/jobs"),
  preferences: () => api<JsonMap>("/api/preferences"),
  savePreference: (payload: Record<string, unknown>) => api<JsonMap>("/api/preferences", { method: "PUT", body: payload }),
  mergeEntityPreview: (payload: Record<string, unknown>) => api<JsonMap>("/api/library/entity-merge/preview", { method: "POST", body: payload }),
  mergeEntity: (payload: Record<string, unknown>) => api<JsonMap>("/api/library/entity-merge", { method: "POST", body: payload }),
  deleteOverlay: (id: string) => api<{ ok: boolean }>(`/api/overlays/${encodeURIComponent(id)}`, { method: "DELETE" }),
  linkProjectWorld: (payload: Record<string, unknown>) => api<JsonMap>("/api/projects/world-link", { method: "POST", body: payload }),
  resource: (type: string, id: string) => api<JsonMap>(`/api/resources/${encodeURIComponent(type)}/${encodeURIComponent(id)}`),
  deleteSavedView: (id: string) => api<{ ok: boolean }>(`/api/saved-views/${encodeURIComponent(id)}`, { method: "DELETE" }),
  templates: (projectId?: string) => api<{ templates: JsonMap[] }>(`/api/templates${qs({ project_id: projectId })}`),
  createTemplate: (payload: Record<string, unknown>) => api<JsonMap>("/api/templates", { method: "POST", body: payload }),
  deleteTemplate: (id: string) => api<{ ok: boolean }>(`/api/templates/${encodeURIComponent(id)}`, { method: "DELETE" }),
  backlinks: (resourceType: string, resourceId: string) => api<JsonMap>(`/api/backlinks/${encodeURIComponent(resourceType)}/${encodeURIComponent(resourceId)}`),
  pinContext: (payload: Record<string, unknown>) => api<JsonMap>("/api/context/pins", { method: "POST", body: payload }),
  stateProposals: (payload: Record<string, unknown>) => api<JsonMap>("/api/state-proposals", { method: "POST", body: payload }),
  stagedChanges: (projectId: string) => api<{ changes: JsonMap[] }>(`/api/projects/${encodeURIComponent(projectId)}/staged-changes`),
  createStagedChange: (projectId: string, payload: Record<string, unknown>) => api<JsonMap>(`/api/projects/${encodeURIComponent(projectId)}/staged-changes`, { method: "POST", body: payload }),
  resolveStagedChange: (id: string, accept: boolean) => api<JsonMap>(`/api/staged-changes/${encodeURIComponent(id)}/resolve`, { method: "POST", body: { accept } }),
  createOverlay: (projectId: string, payload: Record<string, unknown>) => api<JsonMap>(`/api/projects/${encodeURIComponent(projectId)}/overlays`, { method: "POST", body: payload }),
  conflicts: (projectId?: string) => api<{ conflicts: JsonMap[] }>(`/api/conflicts${qs({ project_id: projectId })}`),
  resolveConflict: (id: string, payload: Record<string, unknown>) => api<JsonMap>(`/api/conflicts/${encodeURIComponent(id)}/resolve`, { method: "POST", body: payload }),
  updateMedia: (id: string, payload: Record<string, unknown>) => api<JsonMap>(`/api/media/${encodeURIComponent(id)}`, { method: "PATCH", body: payload }),
  createMedia: (payload: Record<string, unknown>) => api<JsonMap>("/api/media", { method: "POST", body: payload }),
  deleteMedia: (id: string) => api<{ ok: boolean }>(`/api/media/${encodeURIComponent(id)}`, { method: "DELETE" }),
  describeMedia: (id: string, payload: Record<string, unknown>) => api<JsonMap>(`/api/media/${encodeURIComponent(id)}/describe`, { method: "POST", body: payload }),
  memoryStatus: () => api<JsonMap>("/api/memory/status"),
  memoryQuery: (payload: Record<string, unknown>) => api<JsonMap>("/api/memory/query", { method: "POST", body: payload }),
  memoryBackfill: (payload: Record<string, unknown> = {}) => api<JsonMap>("/api/memory/backfill", { method: "POST", body: payload }),
};

export function runtimePayload(
  config: RuntimeConfig,
  scope: { projectId?: string; worldId?: string; branchId?: string; sessionId?: string },
  prompt: string,
  references: ReferenceItem[],
  overrides: Partial<RuntimeConfig> = {},
): Record<string, unknown> {
  const next = { ...config, ...overrides };
  return {
    prompt,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
    session_id: scope.sessionId || null,
    project_id: scope.projectId || null,
    world_id: scope.worldId || null,
    branch_id: scope.branchId || null,
    references: references.map((item) => ({ ...item, mode: item.mode || "context", selector: item.selector || null })),
    server_url: next.server_url || "http://127.0.0.1:1234",
    api_key: null,
    model: next.model || "",
    gpu_ratio: Number(next.gpu_ratio ?? 1),
    context_length: Number(next.context_length ?? 32768),
    input_mode: next.input_mode || "smart_hybrid",
    reasoning: next.reasoning || "off",
    projection_mode: next.projection_mode || "balanced",
    temperature: Number(next.temperature ?? 0.8),
    top_p: Number(next.top_p ?? 0.95),
    top_k: Number(next.top_k ?? 40),
    min_p: Number(next.min_p ?? 0),
    repeat_penalty: Number(next.repeat_penalty ?? 1.05),
    visible_output_tokens: Number(next.visible_output_tokens ?? 4096),
    reasoning_reserve_tokens: Number(next.reasoning_reserve_tokens ?? 4096),
    generation_mode: next.generation_mode || "single",
    beat_count: Number(next.beat_count ?? 4),
    beat_tokens: Number(next.beat_tokens ?? 2048),
    total_story_target_tokens: Number(next.total_story_target_tokens ?? 8192),
    scratch_mode: false,
  };
}

export interface StreamEvent {
  type: string;
  data: Record<string, unknown>;
}

async function consumeSse(response: Response, onEvent: (event: StreamEvent) => void | Promise<void>) {
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: string; message?: string };
      message = body.detail || body.message || message;
    } catch {
      // Keep status fallback.
    }
    throw new ApiError(message, response.status);
  }
  if (!response.body) throw new Error("Streaming response body is unavailable");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const dispatch = async (frame: string) => {
    if (!frame.trim()) return;
    let eventName = "message";
    const dataLines: string[] = [];
    for (const line of frame.split(/\r?\n/)) {
      if (line.startsWith("event:")) eventName = line.slice(6).trim() || "message";
      if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
    }
    if (!dataLines.length) return;
    const raw = dataLines.join("\n");
    let data: Record<string, unknown> = { value: raw };
    try {
      const parsed = JSON.parse(raw) as unknown;
      data = typeof parsed === "object" && parsed !== null ? parsed as Record<string, unknown> : { value: parsed };
    } catch {
      data = { value: raw };
    }
    await onEvent({ type: eventName, data });
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let match: RegExpMatchArray | null;
    while ((match = buffer.match(/\r?\n\r?\n/)) && match.index !== undefined) {
      const frame = buffer.slice(0, match.index);
      buffer = buffer.slice(match.index + match[0].length);
      await dispatch(frame);
    }
  }
  buffer += decoder.decode();
  if (buffer.trim()) await dispatch(buffer);
}

export async function streamGeneration(
  payload: Record<string, unknown>,
  onEvent: (event: StreamEvent) => void | Promise<void>,
  signal?: AbortSignal,
): Promise<GenerationResult | null> {
  if (payload.generation_mode === "beats") {
    const result = await api<GenerationResult>("/api/generate", { method: "POST", body: payload, signal });
    await onEvent({ type: "done", data: result });
    return result;
  }
  const response = await fetch("/api/generate/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  let finalResult: GenerationResult | null = null;
  await consumeSse(response, async (event) => {
    if (event.type === "error") throw new Error(String(event.data.message || "Generation failed"));
    if (event.type === "done") finalResult = event.data as GenerationResult;
    await onEvent(event);
  });
  return finalResult;
}
