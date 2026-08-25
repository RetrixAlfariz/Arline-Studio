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
  forkSession: (sessionId: string, throughTurnId?: string) => api<Session>(`/api/sessions/${encodeURIComponent(sessionId)}/fork`, {
    method: "POST",
    body: { through_turn_id: throughTurnId || null },
  }),
  deleteSession: (sessionId: string) => api<{ ok: boolean }>(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" }),
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
    return api<{ items: JsonMap[] }>(`/api/timeline?${query}`);
  },
  continuity: (payload: Record<string, unknown>) => api<Record<string, unknown>>("/api/analyze", { method: "POST", body: { ...payload, analysis_mode: "continuity" } }),
  snapshot: (payload: Record<string, unknown>) => api<Record<string, unknown>>("/api/snapshots", { method: "POST", body: payload }),
  lifecycle: (action: "archive" | "restore", resourceType: string, resourceId: string) => api<Record<string, unknown>>(`/api/lifecycle/${action}`, { method: "POST", body: { resource_type: resourceType, resource_id: resourceId } }),
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
