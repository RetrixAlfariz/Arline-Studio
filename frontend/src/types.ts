export type AppView = "home" | "chat" | "manuscript" | "library" | "commands";
export type ThemeMode = "dark" | "light";

export type JsonMap = Record<string, unknown>;

export interface RuntimeConfig extends JsonMap {
  studio_version: string;
  server_url: string;
  api_key_configured?: boolean;
  model: string;
  gpu_ratio: number;
  context_length: number;
  input_mode: string;
  reasoning: string;
  projection_mode: string;
  temperature: number;
  top_p: number;
  top_k: number;
  min_p: number;
  repeat_penalty: number;
  visible_output_tokens: number;
  reasoning_reserve_tokens: number;
  generation_mode: string;
  beat_count: number;
  beat_tokens: number;
  total_story_target_tokens: number;
  modes?: Record<string, string>;
  reasoning_modes?: string[];
  projection_modes?: string[];
}

export interface Branch extends JsonMap {
  id: string;
  name: string;
  kind?: string;
  canon_status?: string;
}

export interface World extends JsonMap {
  id: string;
  name: string;
  description?: string;
  branches?: Branch[];
}

export interface Project extends JsonMap {
  id: string;
  name: string;
  description?: string;
  default_world_id?: string | null;
  pinned?: boolean;
}

export interface WorkspaceBootstrap extends JsonMap {
  projects: Project[];
  worlds: World[];
  run_profiles?: JsonMap[];
  document_types?: string[];
  entity_types?: string[];
  context_stack?: JsonMap | null;
}

export interface FolderNode extends JsonMap {
  id: string;
  name: string;
  children?: FolderNode[];
}

export interface DocumentItem extends JsonMap {
  id: string;
  project_id?: string;
  folder_id?: string | null;
  title: string;
  content?: string;
  document_type?: string;
  status?: string;
  updated_at?: string;
  created_at?: string;
}

export interface ProjectTree extends JsonMap {
  folders?: FolderNode[];
  folder_tree?: FolderNode[];
  documents?: DocumentItem[];
  tags?: JsonMap[];
  templates?: JsonMap[];
  conflicts?: JsonMap[];
}

export interface EntityFamily extends JsonMap {
  id: string;
  name: string;
  entity_type?: string;
  description?: string;
  shared_core?: JsonMap;
  folder_id?: string | null;
}

export interface EntityVariant extends JsonMap {
  id: string;
  family_id?: string;
  world_id?: string;
  branch_id?: string | null;
  display_name?: string;
  entity_type?: string;
  summary?: string;
  canon_status?: string;
  current_state?: JsonMap;
  attributes?: JsonMap;
}

export interface Relationship extends JsonMap {
  id: string;
  subject_family_id?: string;
  object_family_id?: string;
  subject_name?: string;
  object_name?: string;
  relation_type?: string;
  description?: string;
}

export interface WorldBible extends JsonMap {
  worlds?: World[];
  families?: EntityFamily[];
  variants?: EntityVariant[];
  relationships?: Relationship[];
  timeline?: JsonMap[];
  recipes?: JsonMap[];
  folders?: FolderNode[];
  folder_tree?: FolderNode[];
  collections?: JsonMap[];
  saved_views?: JsonMap[];
}

export interface Turn extends JsonMap {
  id: string;
  run_id?: string;
  user_prompt?: string;
  story?: string;
  created_at?: string;
  model?: string;
  feedback_status?: string;
}

export interface Session extends JsonMap {
  id: string;
  title: string;
  project_id?: string | null;
  world_id?: string | null;
  branch_id?: string | null;
  parent_session_id?: string | null;
  world_fork_id?: string | null;
  pinned?: boolean;
  scratch_mode?: boolean;
  updated_at?: string;
  created_at?: string;
  turns?: Turn[];
}

export interface ModelInfo extends JsonMap {
  key: string;
  display_name?: string;
  loaded?: boolean;
  max_context_length?: number | null;
  capabilities?: JsonMap;
}

export interface CommandDefinition extends JsonMap {
  id: string;
  label?: string;
  title?: string;
  description?: string;
  help?: string;
  usage?: string;
  aliases?: string[];
}

export interface CommandPayload extends JsonMap {
  commands?: CommandDefinition[];
  command_registry_version?: string;
  reference_selectors?: string[];
  dynamic_references?: string[];
}

export interface GenerationResult extends JsonMap {
  run_id?: string;
  session_id?: string;
  session_title?: string;
  turn_id?: string;
  story?: string;
  summary?: JsonMap;
  context_breakdown?: JsonMap;
  quality_report?: JsonMap;
  reasoning?: string;
}

export interface ReferenceItem {
  type: string;
  id: string;
  label: string;
  mode?: string;
  selector?: string | null;
}

export interface Selection {
  kind: "project" | "world" | "session" | "document" | "entity" | "relationship" | "analysis";
  id?: string;
  title: string;
  subtitle?: string;
  data?: unknown;
}
