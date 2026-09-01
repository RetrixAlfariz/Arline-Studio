import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { AlertTriangle, BrainCircuit, Check, ChevronDown, ChevronUp, ClipboardPaste, Cpu, Database, Download, GripVertical, Library, Link2, MessageSquareText, Monitor, Moon, MoreHorizontal, Palette, Pause, Plus, RefreshCcw, RotateCcw, Save, Search, ShieldCheck, SlidersHorizontal, Sparkles, Sun, Trash2, UserPlus, UserRound, X } from "lucide-react";
import { studioApi } from "../api";
import { browserStorage } from "../browserStorage";
import { appearancePalette, DEFAULT_APPEARANCE, normalizeHex, readableForeground, resolveAccent } from "../theme";
import type { AppearanceSettings, EntityVariant, JsonMap, ModelInfo, PreferredName, RuntimeConfig, ThemeMode, ThemePreference, UserProfile, WorldBible } from "../types";
import { ArlineSelect, simpleOptions } from "./ArlineSelect";

interface SettingsDrawerProps {
  open: boolean;
  config: RuntimeConfig;
  onConfig: (config: RuntimeConfig) => void;
  appearance: AppearanceSettings;
  onAppearance: (appearance: AppearanceSettings) => void;
  activeProjectId: string;
  activeWorldId: string;
  activeBranchId: string;
  worldBible: WorldBible | null;
  onLibraryChanged: () => Promise<void> | void;
  onClose: () => void;
}

type SettingsTab = "general" | "personalization" | "runtime" | "generation" | "conversation" | "context" | "storage";
type ResetMode = "database" | "complete";
type ProfileVisibility = "private" | "collaboration" | "story_presence";
interface ExtractedProfileField {
  key: string;
  label: string;
  value: string;
  visibility: ProfileVisibility;
  confidence: number;
  source: string;
  sensitive: boolean;
  included: boolean;
}
interface PersonalDetailFieldConfig {
  key: string;
  label: string;
  placeholder: string;
  kind: "input" | "date" | "number" | "textarea";
  defaultVisibility: ProfileVisibility;
  wide?: boolean;
  sensitive?: boolean;
}
const ACCENT_PRESETS = ["#2F9B81", "#367FA8", "#6559B4", "#A34F78", "#B4633E", "#758344"];
const DEFAULT_MEMORY_CATEGORIES: Record<string, JsonMap> = {
  collaboration_preferences: { enabled: true, scope: "private", retention_days: 90, fields: {} },
  about_you: { enabled: true, scope: "private", retention_days: 180, fields: {} },
  story_presence: { enabled: false, scope: "selected_stories", retention_days: 180, fields: {} },
  conversation_insights: { enabled: true, scope: "private", retention_days: 90, fields: {} },
};
const DEFAULT_USER_PROFILE: UserProfile = { display_name: "", about: "", preferred_names: [], personal_details: {}, creative_profile: { genres: "", tone: "mixed", pacing: "balanced", description_density: "balanced" }, collaboration: { challenge_level: "balanced", assumption_tolerance: "balanced", initiative: "balanced" }, presence_defaults: { mode: "observer", identity_source: "profile", identity_style: "story_version", agency: "user_directed", perspective: "scene_defined", persistence: "session" }, story_lab: { exploration: "open" }, boundaries: { prefer: [], avoid: [], ask_before: [] }, memory_policy: { schema_version: 2, enabled: true, learn_from_chats: true, categories: DEFAULT_MEMORY_CATEGORIES, behavior: { ask_before_sensitive: true, forget_inactive_days: 90, prevent_personal_canon: true } } };
const PROFILE_VISIBILITY_OPTIONS = simpleOptions([["private", "Private", "Stored locally; excluded from ordinary collaboration"], ["collaboration", "Collaboration", "May help Arline address and understand you"], ["story_presence", "Story Presence", "Available when you explicitly enter a story"]]);
const PERSONAL_DETAIL_FIELDS: PersonalDetailFieldConfig[] = [
  { key: "full_name", label: "Full name", placeholder: "Your full name", kind: "input", defaultVisibility: "private" },
  { key: "birth_date", label: "Birth date", placeholder: "YYYY-MM-DD", kind: "date", defaultVisibility: "private" },
  { key: "height_cm", label: "Height (cm)", placeholder: "165", kind: "number", defaultVisibility: "story_presence" },
  { key: "appearance", label: "Appearance", placeholder: "Physical traits relevant to your Presence", kind: "textarea", defaultVisibility: "story_presence", wide: true },
  { key: "presentation", label: "Everyday presentation", placeholder: "Clothing, expression, or usual presentation", kind: "textarea", defaultVisibility: "story_presence", wide: true },
  { key: "skills", label: "Skills and abilities", placeholder: "Voice acting, languages, technical skills…", kind: "textarea", defaultVisibility: "collaboration", wide: true },
  { key: "sensitive_details", label: "Private physical details", placeholder: "Sensitive details stay private by default", kind: "textarea", defaultVisibility: "private", wide: true, sensitive: true },
  { key: "notes", label: "Additional notes", placeholder: "Anything that did not fit elsewhere", kind: "textarea", defaultVisibility: "private", wide: true },
];
const TONE_OPTIONS = simpleOptions([["grounded", "Grounded", "Natural, restrained, and believable"], ["dramatic", "Dramatic", "Heightened emotion and sharper turns"], ["dark", "Dark", "Weightier mood and unsettling edges"], ["whimsical", "Whimsical", "Playful, surprising, and light-footed"], ["mixed", "Mixed", "Let the scene determine the balance"]]);
const PACING_OPTIONS = simpleOptions([["slow_burn", "Slow-burn", "Give tension and detail room to develop"], ["balanced", "Balanced", "Move between reflection and momentum"], ["fast", "Fast-moving", "Prioritize action and decisive progression"]]);
const DENSITY_OPTIONS = simpleOptions([["minimal", "Minimal", "Use only details that move the scene"], ["balanced", "Balanced", "Blend atmosphere with forward movement"], ["detailed", "Detailed", "Favor texture, setting, and sensory depth"]]);
const CHALLENGE_OPTIONS = simpleOptions([["supportive", "Supportive", "Build on ideas before challenging them"], ["balanced", "Balanced", "Mix encouragement with direct critique"], ["critical", "Critical", "Stress-test weak assumptions proactively"]]);
const ASSUMPTION_OPTIONS = simpleOptions([["conservative", "Conservative", "Ask before filling important gaps"], ["balanced", "Balanced", "Infer low-risk details and flag uncertainty"], ["exploratory", "Exploratory", "Offer bolder possibilities for consideration"]]);
const NAME_CONTEXT_OPTIONS = simpleOptions([["default", "Default everywhere", "Fallback when no other rule matches"], ["formal", "Formal conversations", "Analyst and formal collaboration"], ["casual", "Casual chats", "Story Lab and relaxed conversation"], ["story_presence", "Story Presence", "When you enter or rehearse inside a story"]]);
const MEMORY_SCOPE_OPTIONS = simpleOptions([["private", "Private", "Only your local collaboration context"], ["selected_stories", "Selected stories", "Available to an explicitly selected story Presence"], ["all_chats", "All chats", "Available across collaboration chats"]]);
const MEMORY_RETENTION_OPTIONS = simpleOptions([["0", "Until I delete it"], ["30", "30 days"], ["90", "90 days"], ["180", "180 days"], ["365", "1 year"]]);
const MEMORY_CATEGORY_META = [
  { id: "collaboration_preferences", label: "Collaboration preferences", copy: "Writing style, boundaries, and how Arline should work with you.", fields: [["writing_preferences", "Writing preferences"], ["boundaries", "Creative boundaries"], ["collaboration_contract", "Collaboration contract"]] },
  { id: "about_you", label: "About you", copy: "Identity and profile details you explicitly shared.", fields: [["identity", "Identity and preferred names"], ["personal_details", "Personal details"], ["appearance", "Appearance and presentation"]] },
  { id: "story_presence", label: "Story Presence", copy: "Your reusable identity and presentation inside selected stories.", fields: [["identity", "Presence identity"], ["appearance", "Presence appearance"], ["boundaries", "Presence boundaries"], ["relationship_context", "Relationship context"]] },
  { id: "conversation_insights", label: "Conversation insights", copy: "Non-canon patterns and decisions from collaboration chats.", fields: [["recurring_ideas", "Recurring ideas"], ["resolved_decisions", "Resolved decisions"], ["story_lab", "Story Lab preferences"]] },
] as const;

function normalizeUserProfile(profile: UserProfile): UserProfile {
  const rawPolicy = (profile.memory_policy || {}) as JsonMap;
  const rawCategories = (rawPolicy.categories || {}) as JsonMap;
  const categories = Object.fromEntries(Object.entries(DEFAULT_MEMORY_CATEGORIES).map(([key, defaults]) => [key, { ...defaults, ...((rawCategories[key] as JsonMap) || {}), fields: { ...((defaults.fields as JsonMap) || {}), ...((((rawCategories[key] as JsonMap) || {}).fields as JsonMap) || {}) } }]));
  let names = Array.isArray(profile.preferred_names) ? profile.preferred_names.filter((name) => name?.value?.trim()) : [];
  if (!names.length) {
    const preferred = profile.personal_details?.preferred_name as JsonMap | undefined;
    const value = String(preferred?.value || profile.display_name || "").trim();
    if (value) names = [{ id: "name-1", value, context: "default", primary: true }];
  }
  const primaryIndex = Math.max(0, names.findIndex((name) => name.primary));
  names = names.map((name, index) => ({ ...name, id: name.id || `name-${index + 1}`, context: name.context || "default", primary: index === primaryIndex }));
  return { ...DEFAULT_USER_PROFILE, ...profile, preferred_names: names, display_name: names[primaryIndex]?.value || profile.display_name || "", memory_policy: { ...DEFAULT_USER_PROFILE.memory_policy, ...rawPolicy, categories, behavior: { ...((DEFAULT_USER_PROFILE.memory_policy.behavior as JsonMap) || {}), ...((rawPolicy.behavior as JsonMap) || {}) } } };
}

export function SettingsDrawer({ open, config, onConfig, appearance, onAppearance, activeProjectId, activeWorldId, activeBranchId, worldBible, onLibraryChanged, onClose }: SettingsDrawerProps) {
  const [tab, setTab] = useState<SettingsTab>("general");
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [apiKey, setApiKey] = useState("");
  const [status, setStatus] = useState("");
  const [loadingModels, setLoadingModels] = useState(false);
  const [resetMode, setResetMode] = useState<ResetMode | null>(null);
  const [resetConfirmation, setResetConfirmation] = useState("");
  const [resetting, setResetting] = useState(false);
  const [userProfile, setUserProfile] = useState<UserProfile>(DEFAULT_USER_PROFILE);
  const [createdCharacterVariants, setCreatedCharacterVariants] = useState<EntityVariant[]>([]);
  const [savingSelfEntity, setSavingSelfEntity] = useState(false);
  const [profileImportOpen, setProfileImportOpen] = useState(false);
  const [profileImportText, setProfileImportText] = useState("");
  const [profileImportName, setProfileImportName] = useState("");
  const [profileImportDraft, setProfileImportDraft] = useState<ExtractedProfileField[]>([]);
  const [extractingProfile, setExtractingProfile] = useState(false);
  const [expandedMemory, setExpandedMemory] = useState("story_presence");
  const [memorySearch, setMemorySearch] = useState("");
  const [memoryClearOpen, setMemoryClearOpen] = useState(false);
  const [memoryClearSelection, setMemoryClearSelection] = useState<string[]>([]);

  useEffect(() => {
    if (!open) setStatus("");
    if (open) void studioApi.userProfile().then((profile) => setUserProfile(normalizeUserProfile(profile))).catch(() => setUserProfile(DEFAULT_USER_PROFILE));
  }, [open]);

  const characterVariants = useMemo(() => {
    const families = new Set((worldBible?.families || []).filter((family) => family.entity_type === "character").map((family) => family.id));
    const variants = [...(worldBible?.variants || []), ...createdCharacterVariants];
    return variants.filter((variant, index) => families.has(String(variant.family_id || "")) || createdCharacterVariants.includes(variant)).filter((variant, index, all) => all.findIndex((item) => item.id === variant.id) === index).filter((variant) => !variant.world_id || variant.world_id === activeWorldId);
  }, [worldBible, createdCharacterVariants, activeWorldId]);

  const identitySource = String(userProfile.presence_defaults.identity_source || (userProfile.presence_defaults.entity_variant_id ? "linked_entity" : "profile"));
  const linkedVariantId = String(userProfile.presence_defaults.entity_variant_id || "");
  const linkedVariant = characterVariants.find((variant) => variant.id === linkedVariantId);

  if (!open) return null;

  const patch = <K extends keyof RuntimeConfig>(key: K, value: RuntimeConfig[K]) => onConfig({ ...config, [key]: value });

  const refreshModels = async () => {
    setLoadingModels(true);
    setStatus("");
    try {
      const result = await studioApi.models(config.server_url, apiKey);
      setModels(result.models || []);
      setStatus(`Found ${result.models?.length || 0} model(s)`);
    } catch (error) {
      setStatus((error as Error).message);
    } finally {
      setLoadingModels(false);
    }
  };

  const save = async () => {
    setStatus("Saving…");
    browserStorage.set("arline:theme", appearance.mode);
    browserStorage.set("arline:accent", normalizeHex(appearance.accent));
    browserStorage.set("arline:contrast", appearance.contrast);
    try {
      await studioApi.saveSettings({
        server_url: config.server_url,
        api_key: apiKey || null,
        model: config.model,
        gpu_ratio: config.gpu_ratio,
        context_length: config.context_length,
        input_mode: config.input_mode,
        reasoning: config.reasoning,
        projection_mode: config.projection_mode,
        temperature: config.temperature,
        top_p: config.top_p,
        top_k: config.top_k,
        min_p: config.min_p,
        repeat_penalty: config.repeat_penalty,
        visible_output_tokens: config.visible_output_tokens,
        reasoning_reserve_tokens: config.reasoning_reserve_tokens,
        generation_mode: config.generation_mode,
        beat_count: config.beat_count,
        beat_tokens: config.beat_tokens,
        total_story_target_tokens: config.total_story_target_tokens,
      });
      await studioApi.saveUserProfile(userProfile);
      setStatus("Settings saved. Appearance is local; API keys remain session-only.");
    } catch (error) {
      setStatus(`Appearance saved locally. Runtime settings failed: ${(error as Error).message}`);
    }
  };

  const patchProfileSection = (section: keyof UserProfile, values: JsonMap) => setUserProfile((current) => ({ ...current, [section]: { ...((current[section] as JsonMap) || {}), ...values } }));

  const patchPersonalDetail = (key: string, values: JsonMap) => setUserProfile((current) => ({
    ...current,
    personal_details: {
      ...(current.personal_details || {}),
      [key]: { ...(((current.personal_details || {})[key] as JsonMap) || {}), ...values },
    },
  }));

  const updatePreferredNames = (nextNames: PreferredName[]) => setUserProfile((current) => {
    const cleaned = nextNames.map((name, index) => ({ ...name, id: name.id || `name-${Date.now()}-${index}` }));
    const requestedPrimary = cleaned.findIndex((name) => name.primary);
    const primaryIndex = cleaned.length ? Math.max(0, requestedPrimary) : -1;
    const names = cleaned.map((name, index) => ({ ...name, primary: index === primaryIndex }));
    const primary = names[primaryIndex];
    return {
      ...current,
      display_name: primary?.value || "",
      preferred_names: names,
      personal_details: {
        ...current.personal_details,
        preferred_name: primary ? { ...((current.personal_details.preferred_name as JsonMap) || {}), value: primary.value, visibility: "collaboration" } : undefined,
      },
    };
  });

  const addPreferredName = () => updatePreferredNames([...userProfile.preferred_names, { id: `name-${Date.now()}`, value: "", context: userProfile.preferred_names.length ? "casual" : "default", primary: !userProfile.preferred_names.length }]);
  const patchPreferredName = (id: string, values: Partial<PreferredName>) => updatePreferredNames(userProfile.preferred_names.map((name) => name.id === id ? { ...name, ...values } : values.primary ? { ...name, primary: false } : name));
  const movePreferredName = (id: string, direction: -1 | 1) => {
    const names = [...userProfile.preferred_names];
    const index = names.findIndex((name) => name.id === id);
    const target = index + direction;
    if (index < 0 || target < 0 || target >= names.length) return;
    [names[index], names[target]] = [names[target], names[index]];
    updatePreferredNames(names);
  };

  const memoryPolicy = userProfile.memory_policy as JsonMap;
  const memoryCategories = (memoryPolicy.categories || {}) as JsonMap;
  const memoryBehavior = (memoryPolicy.behavior || {}) as JsonMap;
  const patchMemory = (values: JsonMap) => patchProfileSection("memory_policy", values);
  const patchMemoryCategory = (categoryId: string, values: JsonMap) => patchMemory({ categories: { ...memoryCategories, [categoryId]: { ...((memoryCategories[categoryId] as JsonMap) || {}), ...values } } });
  const patchMemoryField = (categoryId: string, fieldId: string, enabled: boolean) => {
    const category = (memoryCategories[categoryId] as JsonMap) || {};
    const fields = (category.fields as JsonMap) || {};
    patchMemoryCategory(categoryId, { fields: { ...fields, [fieldId]: enabled } });
  };

  const memoryCount = (categoryId: string) => {
    const filled = (value: unknown): number => {
      if (Array.isArray(value)) return value.filter(Boolean).length;
      if (value && typeof value === "object") return Object.values(value as JsonMap).filter((item) => item !== "" && item !== null && item !== undefined && (!Array.isArray(item) || item.length)).length;
      return value ? 1 : 0;
    };
    if (categoryId === "collaboration_preferences") return filled(userProfile.creative_profile) + filled(userProfile.collaboration) + filled(userProfile.boundaries);
    if (categoryId === "about_you") return filled(userProfile.about) + filled(userProfile.personal_details) + userProfile.preferred_names.length;
    if (categoryId === "story_presence") return filled(userProfile.presence_defaults) + userProfile.preferred_names.filter((name) => name.context === "story_presence").length;
    return filled(userProfile.story_lab);
  };

  const exportPersonalMemory = () => {
    const payload = JSON.stringify({ exported_at: new Date().toISOString(), preferred_names: userProfile.preferred_names, about: userProfile.about, personal_details: userProfile.personal_details, creative_profile: userProfile.creative_profile, collaboration: userProfile.collaboration, presence_defaults: userProfile.presence_defaults, story_lab: userProfile.story_lab, boundaries: userProfile.boundaries, memory_policy: userProfile.memory_policy }, null, 2);
    const url = URL.createObjectURL(new Blob([payload], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url; link.download = "arline-personal-memory.json"; link.click(); URL.revokeObjectURL(url);
    setStatus("Personal memory exported locally.");
  };

  const clearSelectedMemory = () => {
    setUserProfile((current) => {
      const next = { ...current };
      if (memoryClearSelection.includes("collaboration_preferences")) { next.creative_profile = {}; next.collaboration = {}; next.boundaries = { prefer: [], avoid: [], ask_before: [] }; }
      if (memoryClearSelection.includes("about_you")) { next.about = ""; next.personal_details = {}; next.preferred_names = []; next.display_name = ""; }
      if (memoryClearSelection.includes("story_presence")) next.presence_defaults = { ...DEFAULT_USER_PROFILE.presence_defaults };
      if (memoryClearSelection.includes("conversation_insights")) next.story_lab = { ...DEFAULT_USER_PROFILE.story_lab };
      return next;
    });
    setMemoryClearOpen(false); setMemoryClearSelection([]);
    setStatus("Selected personal memory cleared from this draft. Save settings to commit.");
  };

  const extractProfile = async () => {
    if (!profileImportText.trim() || extractingProfile) return;
    setExtractingProfile(true);
    setStatus("Analyzing profile text…");
    try {
      const result = await studioApi.extractUserProfile(profileImportText.trim());
      setProfileImportName(result.display_name || userProfile.display_name);
      setProfileImportDraft((result.fields || []).map((field) => ({
        key: String(field.key || "notes"), label: String(field.label || "Profile detail"), value: String(field.value || ""),
        visibility: String(field.visibility || "private") as ProfileVisibility, confidence: Number(field.confidence || 0),
        source: String(field.source || ""), sensitive: Boolean(field.sensitive), included: field.included !== false,
      })));
      setStatus(`Found ${result.fields?.length || 0} editable profile field(s). Review before applying.`);
    } catch (error) {
      setStatus((error as Error).message || "Could not analyze profile text.");
    } finally {
      setExtractingProfile(false);
    }
  };

  const applyProfileDraft = () => {
    const details = { ...(userProfile.personal_details || {}) };
    let extractedPreferredName = "";
    for (const field of profileImportDraft.filter((item) => item.included && item.value.trim())) {
      if (field.key === "preferred_name") extractedPreferredName = field.value.trim();
      else details[field.key] = { value: field.value.trim(), visibility: field.visibility, sensitive: field.sensitive };
    }
    setUserProfile((current) => {
      const preferred = extractedPreferredName || profileImportName.trim();
      const existing = current.preferred_names || [];
      const names = preferred
        ? [{ id: existing.find((name) => name.primary)?.id || `name-${Date.now()}`, value: preferred, context: "default" as const, primary: true }, ...existing.filter((name) => !name.primary && name.value.toLowerCase() !== preferred.toLowerCase())]
        : existing;
      return { ...current, display_name: preferred || current.display_name, preferred_names: names, personal_details: details };
    });
    setProfileImportOpen(false);
    setProfileImportDraft([]);
    setProfileImportText("");
    setStatus("Profile draft applied. Review the editable fields, then save settings.");
  };

  const useProfileIdentity = () => patchProfileSection("presence_defaults", { mode: "self", identity_source: "profile", entity_family_id: null, entity_variant_id: null, display_name: userProfile.display_name });

  const linkCharacter = (entityVariantId: string) => {
    const variant = characterVariants.find((item) => item.id === entityVariantId);
    patchProfileSection("presence_defaults", {
      mode: entityVariantId ? "linked_entity" : "self",
      identity_source: entityVariantId ? "linked_entity" : "profile",
      entity_family_id: variant?.family_id || null,
      entity_variant_id: entityVariantId || null,
      display_name: variant?.display_name || userProfile.display_name,
    });
  };

  const saveSelfEntity = async () => {
    if (!activeWorldId || !userProfile.display_name.trim() || savingSelfEntity) return;
    setSavingSelfEntity(true);
    setStatus(identitySource === "self_entity" ? "Syncing your Library identity…" : "Creating your Library identity…");
    try {
      const result = await studioApi.saveUserAsEntity({
        project_id: activeProjectId || null, world_id: activeWorldId,
        branch_id: activeBranchId || null, name: userProfile.display_name,
        about: userProfile.about, creative_profile: userProfile.creative_profile,
        preferred_names: userProfile.preferred_names,
        personal_details: userProfile.personal_details,
        presence_defaults: userProfile.presence_defaults,
        entity_variant_id: identitySource === "self_entity" ? linkedVariantId || null : null,
      });
      setUserProfile(normalizeUserProfile(result.profile));
      setCreatedCharacterVariants((current) => [...current.filter((item) => item.id !== result.variant.id), result.variant as EntityVariant]);
      await onLibraryChanged();
      setStatus(identitySource === "self_entity" ? "Your Library identity is synced." : "Your profile is now linked to a Library character.");
    } catch (error) {
      setStatus((error as Error).message || "Could not save your Library identity.");
    } finally {
      setSavingSelfEntity(false);
    }
  };

  const closeReset = () => {
    if (resetting) return;
    setResetMode(null);
    setResetConfirmation("");
  };

  const performReset = async () => {
    if (!resetMode) return;
    setResetting(true);
    setStatus("Resetting local data…");
    try {
      await studioApi.resetStorage(resetMode, resetConfirmation);
      browserStorage.clearArline();
      location.reload();
    } catch (error) {
      setStatus((error as Error).message);
      setResetting(false);
    }
  };

  return (
    <>
      <div className="drawer-scrim" onMouseDown={onClose} />
      <aside className="settings-drawer">
        <header><div><span className="eyebrow">Arline Studio</span><h2>Settings</h2></div><button className="icon-control" onClick={onClose}><X size={16} /></button></header>
        <div className="settings-body">
          <nav>
            <button className={tab === "general" ? "active" : ""} onClick={() => setTab("general")}><Palette size={14} />General</button>
            <button className={tab === "personalization" ? "active" : ""} onClick={() => setTab("personalization")}><UserRound size={14} />Personalization</button>
            <button className={tab === "runtime" ? "active" : ""} onClick={() => setTab("runtime")}><Cpu size={14} />Models & Runtime</button>
            <button className={tab === "generation" ? "active" : ""} onClick={() => setTab("generation")}><SlidersHorizontal size={14} />Generation</button>
            <button className={tab === "conversation" ? "active" : ""} onClick={() => setTab("conversation")}><MessageSquareText size={14} />Conversation</button>
            <button className={tab === "context" ? "active" : ""} onClick={() => setTab("context")}><RefreshCcw size={14} />Context</button>
            <button className={tab === "storage" ? "active" : ""} onClick={() => setTab("storage")}><Database size={14} />Data & Storage</button>
          </nav>
          <section className="settings-panel">
            {tab === "general" && <>
              <PanelHeading title="General" description="Shape how Arline looks without sacrificing legibility. Accent choices are adapted separately for dark and light surfaces." />
              <section className="appearance-section">
                <div className="settings-block-heading"><div><strong>Appearance</strong><span>Theme behavior and brand accent</span></div><button className="settings-reset" onClick={() => { onAppearance(DEFAULT_APPEARANCE); setStatus("Arline appearance restored. Save to keep it."); }}><RotateCcw size={12} />Reset</button></div>

                <div className="appearance-field"><span>Theme</span><div className="theme-choice-grid">
                  <ThemeChoice value="system" label="System" icon={<Monitor size={15} />} current={appearance.mode} onChange={(mode) => onAppearance({ ...appearance, mode })} />
                  <ThemeChoice value="dark" label="Dark" icon={<Moon size={15} />} current={appearance.mode} onChange={(mode) => onAppearance({ ...appearance, mode })} />
                  <ThemeChoice value="light" label="Light" icon={<Sun size={15} />} current={appearance.mode} onChange={(mode) => onAppearance({ ...appearance, mode })} />
                </div></div>

                <div className="appearance-field"><span>Accent color</span><div className="accent-control"><label className="custom-color"><input type="color" value={normalizeHex(appearance.accent)} onChange={(event) => onAppearance({ ...appearance, accent: event.target.value.toUpperCase() })} /><span><strong>Custom</strong><small>{normalizeHex(appearance.accent)}</small></span></label><div className="accent-swatches" aria-label="Accent presets">{ACCENT_PRESETS.map((color) => <button key={color} className={normalizeHex(appearance.accent) === color ? "active" : ""} style={{ backgroundColor: color }} title={color} aria-label={`Use accent ${color}`} onClick={() => onAppearance({ ...appearance, accent: color })}>{normalizeHex(appearance.accent) === color ? <Check size={11} /> : null}</button>)}</div></div><p>Arline preserves your hue, then corrects saturation and lightness per theme.</p></div>

                <div className="appearance-field"><span>Contrast</span><div className="contrast-choice"><button className={appearance.contrast === "standard" ? "active" : ""} onClick={() => onAppearance({ ...appearance, contrast: "standard" })}><strong>Standard</strong><small>Calm borders and surfaces</small></button><button className={appearance.contrast === "high" ? "active" : ""} onClick={() => onAppearance({ ...appearance, contrast: "high" })}><strong>High</strong><small>Stronger separation and focus</small></button></div></div>
              </section>

              <section className="appearance-preview-section"><div className="settings-block-heading"><div><strong>Live preview</strong><span>Both themes remain readable with one accent</span></div><span className="contrast-safe"><Check size={11} />Contrast safeguarded</span></div><div className="appearance-previews"><AppearancePreview theme="dark" accent={appearance.accent} /><AppearancePreview theme="light" accent={appearance.accent} /></div></section>
            </>}

            {tab === "personalization" && <div className="personalization-panel">
              <PanelHeading title="Personalization" description="Editable collaboration defaults. These may seed suggestions, but never become story canon by themselves." />
              <section className="personalization-summary"><span className="eyebrow">How Arline knows you</span><h4>{userProfile.display_name || "Your profile"}</h4><p>{userProfile.about || "Add a short description so Arline can collaborate with you more naturally."}</p></section>
              <section className="settings-card profile-you-card">
                <div className="settings-block-heading"><div><strong>You</strong><span>Human identity for collaboration, separate from Library characters</span></div><button className="settings-reset" onClick={() => setProfileImportOpen((value) => !value)}><ClipboardPaste size={12} />Import text</button></div>
                {profileImportOpen && <div className="profile-importer">
                  <div className="profile-import-intro"><span><Sparkles size={14} /></span><div><strong>Turn a description into editable fields</strong><small>Analysis creates a local draft. Nothing is saved or added to the Library until you confirm it.</small></div></div>
                  <label><span>Profile description</span><textarea value={profileImportText} onChange={(event) => setProfileImportText(event.target.value)} placeholder="Paste a natural-language description about yourself…" /></label>
                  <div className="profile-import-actions"><button className="secondary-action" onClick={() => { setProfileImportOpen(false); setProfileImportDraft([]); }}><X size={12} />Cancel</button><button className="primary-action" disabled={!profileImportText.trim() || extractingProfile} onClick={() => void extractProfile()}>{extractingProfile ? <RefreshCcw className="spin" size={12} /> : <Sparkles size={12} />}{extractingProfile ? "Analyzing…" : "Analyze text"}</button></div>
                  {profileImportDraft.length > 0 && <div className="profile-import-review">
                    <header><div><strong>Review extracted details</strong><small>Edit, exclude, or change visibility before applying.</small></div><span>{profileImportDraft.filter((field) => field.included).length} included</span></header>
                    <label className="profile-import-display"><span>Suggested display name</span><input value={profileImportName} onChange={(event) => setProfileImportName(event.target.value)} /></label>
                    <div className="profile-import-fields">{profileImportDraft.map((field, index) => <article className={!field.included ? "excluded" : ""} key={`${field.key}-${index}`}>
                      <header><label className="profile-field-check"><input type="checkbox" checked={field.included} onChange={(event) => setProfileImportDraft((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, included: event.target.checked } : item))} /><span>{field.label}</span></label><div>{field.sensitive && <span className="sensitive-badge"><ShieldCheck size={10} />Sensitive</span>}<span className="confidence-badge">{Math.round(field.confidence * 100)}%</span></div></header>
                      <textarea value={field.value} disabled={!field.included} onChange={(event) => setProfileImportDraft((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, value: event.target.value } : item))} />
                      <div className="profile-field-meta"><ArlineSelect density="compact" ariaLabel={`${field.label} visibility`} value={field.visibility} options={PROFILE_VISIBILITY_OPTIONS} onValueChange={(visibility) => setProfileImportDraft((current) => current.map((item, itemIndex) => itemIndex === index ? { ...item, visibility: visibility as ProfileVisibility } : item))} /><details><summary>Source</summary><p>{field.source}</p></details></div>
                    </article>)}</div>
                    <button className="primary-action profile-apply" onClick={applyProfileDraft}><Check size={12} />Apply to editable profile</button>
                  </div>}
                </div>}
                <div className="preferred-name-editor">
                  <div className="preferred-name-heading"><div><strong>Names Arline can use</strong><span>Rules are checked from top to bottom. The primary name is the fallback.</span></div><button className="secondary-action small" onClick={() => setStatus(`Default: ${userProfile.preferred_names.find((name) => name.primary)?.value || "not set"} · Formal: ${userProfile.preferred_names.find((name) => name.context === "formal")?.value || "primary"} · Casual: ${userProfile.preferred_names.find((name) => name.context === "casual")?.value || "primary"} · Story Presence: ${userProfile.preferred_names.find((name) => name.context === "story_presence")?.value || "primary"}`)}><MessageSquareText size={12} />Test addressing</button></div>
                  <div className="preferred-name-list">
                    {userProfile.preferred_names.map((name, index) => <div className={`preferred-name-row${name.primary ? " primary" : ""}`} key={name.id}>
                      <span className="name-drag"><GripVertical size={13} /></span>
                      <label><span>Name{name.primary && <em>Primary</em>}</span><input value={name.value} onChange={(event) => patchPreferredName(name.id, { value: event.target.value })} placeholder="Preferred name" /></label>
                      <label><span>Used in</span><ArlineSelect density="compact" ariaLabel={`${name.value || "Name"} usage context`} value={name.primary ? "default" : name.context} options={NAME_CONTEXT_OPTIONS} onValueChange={(context) => patchPreferredName(name.id, { context: context as PreferredName["context"] })} /></label>
                      <div className="name-row-actions"><button title="Move up" disabled={index === 0} onClick={() => movePreferredName(name.id, -1)}><ChevronUp size={12} /></button><button title="Move down" disabled={index === userProfile.preferred_names.length - 1} onClick={() => movePreferredName(name.id, 1)}><ChevronDown size={12} /></button><button title="More name details" onClick={() => patchPreferredName(name.id, { language: name.language === undefined ? "" : undefined })}><MoreHorizontal size={13} /></button>{!name.primary && <button title="Set as primary" onClick={() => patchPreferredName(name.id, { primary: true, context: "default" })}><Check size={12} /></button>}<button className="danger" title="Remove name" disabled={userProfile.preferred_names.length === 1} onClick={() => updatePreferredNames(userProfile.preferred_names.filter((item) => item.id !== name.id))}><X size={12} /></button></div>
                      {name.language !== undefined && <div className="name-metadata"><label><span>Pronunciation <em>optional</em></span><input value={name.pronunciation || ""} onChange={(event) => patchPreferredName(name.id, { pronunciation: event.target.value })} placeholder="How it sounds" /></label><label><span>Language <em>optional</em></span><input value={name.language || ""} onChange={(event) => patchPreferredName(name.id, { language: event.target.value })} placeholder="e.g. Indonesian" /></label></div>}
                    </div>)}
                    <button className="add-preferred-name" onClick={addPreferredName}><Plus size={13} />Add preferred name</button>
                  </div>
                </div>
                <details className="profile-details-disclosure">
                  <summary><span><strong>Profile details</strong><small>About you, personal details, appearance, and skills</small></span><ChevronDown size={13} /></summary>
                  <label className="about-you-field"><span>About you</span><textarea value={userProfile.about} onChange={(event) => setUserProfile({ ...userProfile, about: event.target.value })} placeholder="Interests, work, communication context, or anything useful that does not fit a structured field" /></label>
                  <div className="personal-details-editor">
                  <div className="personal-details-heading"><div><strong>Personal details</strong><span>Imported details remain editable. Visibility controls where each detail may be used.</span></div><ShieldCheck size={14} /></div>
                  <div className="personal-details-grid">{PERSONAL_DETAIL_FIELDS.map((field) => {
                    const detail = ((userProfile.personal_details || {})[field.key] as JsonMap | undefined) || {};
                    const value = String(detail.value || "");
                    const visibility = String(detail.visibility || field.defaultVisibility);
                    return <label className={field.wide ? "wide" : ""} key={field.key}><span>{field.label}{field.sensitive && <em>Private by default</em>}</span>{field.kind === "textarea" ? <textarea value={value} onChange={(event) => patchPersonalDetail(field.key, { value: event.target.value, sensitive: Boolean(field.sensitive) })} placeholder={field.placeholder} /> : <input type={field.kind === "date" ? "date" : field.kind === "number" ? "number" : "text"} value={value} onChange={(event) => patchPersonalDetail(field.key, { value: event.target.value, sensitive: Boolean(field.sensitive) })} placeholder={field.placeholder} />}<ArlineSelect density="compact" ariaLabel={`${field.label} visibility`} value={visibility} options={PROFILE_VISIBILITY_OPTIONS} onValueChange={(nextVisibility) => patchPersonalDetail(field.key, { visibility: nextVisibility, sensitive: Boolean(field.sensitive) })} /></label>;
                  })}</div>
                  </div>
                </details>
              </section>
              <section className="settings-card identity-source-card">
                <div className="settings-block-heading"><div><strong>Story identity</strong><span>Choose how your human profile becomes a Presence inside stories</span></div><span className={`identity-state ${identitySource}`}><Link2 size={11} />{identitySource === "self_entity" ? "Self entity" : identitySource === "linked_entity" ? "Library linked" : "Profile only"}</span></div>
                <div className="identity-choice-grid">
                  <button className={identitySource === "profile" ? "active" : ""} onClick={useProfileIdentity}><UserRound size={16} /><span><strong>Use my profile</strong><small>Enter stories as yourself without creating canon</small></span>{identitySource === "profile" && <Check size={12} />}</button>
                  <button className={identitySource !== "profile" ? "active" : ""} onClick={() => patchProfileSection("presence_defaults", { mode: "linked_entity", identity_source: linkedVariantId ? identitySource : "linked_entity" })}><Library size={16} /><span><strong>Use a Library entity</strong><small>Reference an existing character or create yourself</small></span>{identitySource !== "profile" && <Check size={12} />}</button>
                </div>
                {identitySource !== "profile" && <div className="identity-entity-controls">
                  <label><span>Referenced character</span><ArlineSelect ariaLabel="Referenced character" value={linkedVariantId} options={[{ value: "", label: "Choose a Library character…", description: characterVariants.length ? "No character selected" : "Your Library has no character variants yet" }, ...characterVariants.map((variant) => ({ value: variant.id, label: variant.display_name || variant.id, description: `${variant.canon_status || "draft"} · ${variant.summary || "No summary"}` }))]} onValueChange={linkCharacter} menuMinWidth={320} /></label>
                  {linkedVariant && <div className="linked-identity-preview"><span className="identity-avatar"><UserRound size={16} /></span><div><strong>{linkedVariant.display_name || "Linked character"}</strong><small>{identitySource === "self_entity" ? "Created from your Personalization profile" : "Existing Library character reference"} · {linkedVariant.canon_status || "draft"}</small></div><Check size={13} /></div>}
                  <div className="identity-create-row"><div><strong>{identitySource === "self_entity" ? "Keep your self entity current" : "Make yourself a character"}</strong><small>{identitySource === "self_entity" ? "Sync name, About you, and Creative Profile to the linked variant." : "Create a draft Library character in the active world using this profile."}</small></div><button className="secondary-action" disabled={savingSelfEntity || !activeWorldId || !userProfile.display_name.trim()} onClick={() => void saveSelfEntity()}>{savingSelfEntity ? <RefreshCcw className="spin" size={13} /> : <UserPlus size={13} />}{savingSelfEntity ? "Saving…" : identitySource === "self_entity" ? "Sync entity" : "Create myself"}</button></div>
                  {!activeWorldId && <p className="identity-help error">Choose a world before creating your self entity.</p>}
                  {!userProfile.display_name.trim() && <p className="identity-help">Add a display name first.</p>}
                </div>}
              </section>
              <section className="settings-card"><div className="settings-block-heading"><div><strong>Creative Profile</strong><span>Soft preferences; explicit project instructions still win</span></div></div><div className="settings-grid"><label><span>Genres</span><input value={String(userProfile.creative_profile.genres || "")} onChange={(event) => patchProfileSection("creative_profile", { genres: event.target.value })} placeholder="Fantasy, mystery…" /></label><label><span>Tone</span><ArlineSelect ariaLabel="Tone" value={String(userProfile.creative_profile.tone || "mixed")} options={TONE_OPTIONS} onValueChange={(tone) => patchProfileSection("creative_profile", { tone })} /></label><label><span>Pacing</span><ArlineSelect ariaLabel="Pacing" value={String(userProfile.creative_profile.pacing || "balanced")} options={PACING_OPTIONS} onValueChange={(pacing) => patchProfileSection("creative_profile", { pacing })} /></label><label><span>Description</span><ArlineSelect ariaLabel="Description density" value={String(userProfile.creative_profile.description_density || "balanced")} options={DENSITY_OPTIONS} onValueChange={(description_density) => patchProfileSection("creative_profile", { description_density })} /></label></div></section>
              <section className="settings-card"><div className="settings-block-heading"><div><strong>Working with Arline</strong><span>Your collaboration contract</span></div></div><div className="settings-grid"><label><span>Challenge level</span><ArlineSelect ariaLabel="Challenge level" value={String(userProfile.collaboration.challenge_level || "balanced")} options={CHALLENGE_OPTIONS} onValueChange={(challenge_level) => patchProfileSection("collaboration", { challenge_level })} /></label><label><span>Assumptions</span><ArlineSelect ariaLabel="Assumption tolerance" value={String(userProfile.collaboration.assumption_tolerance || "balanced")} options={ASSUMPTION_OPTIONS} onValueChange={(assumption_tolerance) => patchProfileSection("collaboration", { assumption_tolerance })} /></label></div></section>
              <section className="settings-card"><div className="settings-block-heading"><div><strong>Creative boundaries</strong><span>One item per line; Arline treats these as collaboration constraints, not canon</span></div></div><div className="settings-grid"><label><span>Prefer</span><textarea value={((userProfile.boundaries.prefer as string[] | undefined) || []).join("\n")} onChange={(event) => patchProfileSection("boundaries", { prefer: event.target.value.split("\n").map((item) => item.trim()).filter(Boolean) })} placeholder="Themes or treatment to favor" /></label><label><span>Avoid</span><textarea value={((userProfile.boundaries.avoid as string[] | undefined) || []).join("\n")} onChange={(event) => patchProfileSection("boundaries", { avoid: event.target.value.split("\n").map((item) => item.trim()).filter(Boolean) })} placeholder="Themes, tropes, or treatment to avoid" /></label><label><span>Ask before</span><textarea value={((userProfile.boundaries.ask_before as string[] | undefined) || []).join("\n")} onChange={(event) => patchProfileSection("boundaries", { ask_before: event.target.value.split("\n").map((item) => item.trim()).filter(Boolean) })} placeholder="Changes that require confirmation" /></label></div></section>
              <section className="settings-card memory-privacy-card">
                <div className="settings-block-heading"><div><strong>Memory & privacy</strong><span>Control what Arline remembers, where it may be used, and for how long</span></div><label className="session-learning"><span>New chats</span><ArlineSelect density="compact" ariaLabel="Learning from new chats" value={Boolean(memoryPolicy.learn_from_chats ?? true) ? "learn" : "do_not_learn"} options={simpleOptions([["learn", "Learn from chats", "Allow permitted personal insights"], ["do_not_learn", "Do not learn", "Use saved context without retaining new personal insights"]])} onValueChange={(value) => patchMemory({ learn_from_chats: value === "learn" })} /></label></div>
                <div className={`memory-master${memoryPolicy.enabled === false ? " paused" : ""}`}><span><BrainCircuit size={18} /></span><div><strong>{memoryPolicy.enabled === false ? "Personal memory is paused" : "Personal memory is on"}</strong><small>{memoryPolicy.enabled === false ? "Arline will not use saved personal context until you resume it." : "Only enabled categories are added to collaboration context. Story canon memory is separate."}</small></div><label className="toggle-control"><input type="checkbox" checked={memoryPolicy.enabled !== false} onChange={(event) => patchMemory({ enabled: event.target.checked })} /><span /></label></div>
                <div className="memory-category-list">
                  {MEMORY_CATEGORY_META.filter((meta) => !memorySearch || `${meta.label} ${meta.copy} ${meta.fields.flat().join(" ")}`.toLowerCase().includes(memorySearch.toLowerCase())).map((meta) => {
                    const category = (memoryCategories[meta.id] as JsonMap) || {};
                    const fields = (category.fields as JsonMap) || {};
                    const expanded = expandedMemory === meta.id;
                    return <article className={`memory-category${expanded ? " expanded" : ""}`} key={meta.id}>
                      <div className="memory-category-row"><span className="memory-category-icon">{meta.id === "about_you" ? <UserRound size={15} /> : meta.id === "story_presence" ? <Library size={15} /> : meta.id === "conversation_insights" ? <Sparkles size={15} /> : <Palette size={15} />}</span><div className="memory-category-copy"><strong>{meta.label}</strong><small>{meta.copy}</small></div><label className="toggle-control"><input type="checkbox" checked={category.enabled !== false} onChange={(event) => patchMemoryCategory(meta.id, { enabled: event.target.checked })} /><span /></label><span className="memory-item-count">{memoryCount(meta.id)} items</span><button className="memory-review" onClick={() => setExpandedMemory(expanded ? "" : meta.id)}>Review{expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}</button></div>
                      {expanded && <div className="memory-category-detail">
                        <div className="memory-policy-row"><label><span>Usage scope</span><ArlineSelect density="compact" ariaLabel={`${meta.label} usage scope`} value={String(category.scope || "private")} options={MEMORY_SCOPE_OPTIONS} onValueChange={(scope) => patchMemoryCategory(meta.id, { scope })} /></label><label><span>Retention</span><ArlineSelect density="compact" ariaLabel={`${meta.label} retention`} value={String(category.retention_days ?? 90)} options={MEMORY_RETENTION_OPTIONS} onValueChange={(days) => patchMemoryCategory(meta.id, { retention_days: Number(days) })} /></label><span><small>Last used</small><strong>Not tracked yet</strong></span></div>
                        <div className="memory-field-list">{meta.fields.map(([fieldId, label]) => <label key={fieldId}><span><strong>{label}</strong><small>{fieldId === "relationship_context" ? "Only explicit relationship context for your Presence" : "Can be included when this category is allowed"}</small></span><span className="toggle-control compact"><input type="checkbox" checked={fields[fieldId] !== false} onChange={(event) => patchMemoryField(meta.id, fieldId, event.target.checked)} /><span /></span></label>)}</div>
                      </div>}
                    </article>;
                  })}
                </div>
                <div className="memory-behavior"><div><strong>Memory behavior</strong><span>Safety rules apply before category settings.</span></div><label><span><strong>Ask before saving sensitive details</strong><small>Arline must request permission before retaining sensitive personal information.</small></span><span className="toggle-control"><input type="checkbox" checked={memoryBehavior.ask_before_sensitive !== false} onChange={(event) => patchMemory({ behavior: { ...memoryBehavior, ask_before_sensitive: event.target.checked } })} /><span /></span></label><label><span><strong>Forget inactive insights after 90 days</strong><small>Applies to conversational insights that have not been reused.</small></span><span className="toggle-control"><input type="checkbox" checked={Number(memoryBehavior.forget_inactive_days || 0) > 0} onChange={(event) => patchMemory({ behavior: { ...memoryBehavior, forget_inactive_days: event.target.checked ? 90 : 0 } })} /><span /></span></label><label><span><strong>Never turn personal memory into story canon automatically</strong><small>Personal context can guide collaboration but requires an explicit canon action.</small></span><span className="toggle-control"><input type="checkbox" checked={memoryBehavior.prevent_personal_canon !== false} onChange={(event) => patchMemory({ behavior: { ...memoryBehavior, prevent_personal_canon: event.target.checked } })} /><span /></span></label></div>
                <div className="memory-data-controls"><div><strong>Data controls</strong><span>Access and manage the personal context stored in this profile.</span></div><label className="memory-search"><Search size={13} /><input value={memorySearch} onChange={(event) => setMemorySearch(event.target.value)} placeholder="Search memory controls" /></label><button onClick={exportPersonalMemory}><Download size={13} />Export</button><button onClick={() => patchMemory({ enabled: memoryPolicy.enabled === false })}>{memoryPolicy.enabled === false ? <BrainCircuit size={13} /> : <Pause size={13} />}{memoryPolicy.enabled === false ? "Resume memory" : "Pause all"}</button><button className="danger" onClick={() => setMemoryClearOpen(true)}><Trash2 size={13} />Clear selected</button></div>
              </section>
            </div>}

            {tab === "runtime" && <>
              <PanelHeading title="Models & Runtime" description="The UI is TypeScript now; the model runtime remains local Python + LM Studio." />
              <label><span>LM Studio server</span><input value={config.server_url} onChange={(event) => patch("server_url", event.target.value)} /></label>
              <label><span>API token</span><input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={config.api_key_configured ? "Configured securely · optional override" : "Optional session token"} /></label>
              <button className="secondary-action wide" onClick={() => void refreshModels()} disabled={loadingModels}><RefreshCcw size={13} className={loadingModels ? "spin" : ""} />Refresh models</button>
              <button className="secondary-action wide" onClick={async () => { setStatus("Reloading model…"); try { await studioApi.reloadModel({ server_url: config.server_url, api_key: apiKey || null, model: config.model, gpu_ratio: config.gpu_ratio, context_length: config.context_length }); setStatus("Model reload requested"); } catch (error) { setStatus((error as Error).message); } }} disabled={!config.model}><RefreshCcw size={13} />Apply / Reload model</button>
              <label><span>Model</span><ArlineSelect ariaLabel="Model" value={config.model || ""} options={[{ value: "", label: "Select model…", description: "Refresh models to discover local runtimes" }, ...models.map((model) => ({ value: model.key, label: model.display_name || model.key, description: model.loaded ? "Loaded and ready" : "Available in LM Studio" })), ...(config.model && !models.some((model) => model.key === config.model) ? [{ value: config.model, label: config.model, description: "Configured model" }] : [])]} onValueChange={(model) => patch("model", model)} menuMinWidth={300} /></label>
              <label><span>GPU offload <em>{Number(config.gpu_ratio || 0).toFixed(2)}</em></span><input type="range" min={0} max={1} step={0.05} value={config.gpu_ratio} onChange={(event) => patch("gpu_ratio", Number(event.target.value))} /></label>
              <label><span>Context length</span><input type="number" min={1024} step={1024} value={config.context_length} onChange={(event) => patch("context_length", Number(event.target.value))} /></label>
            </>}

            {tab === "generation" && <>
              <PanelHeading title="Generation" description="These values are sent through the existing PromptPayload contract." />
              <div className="settings-grid">
                <label><span>Input mode</span><ArlineSelect ariaLabel="Input mode" value={config.input_mode} options={Object.entries(config.modes || { smart_hybrid: "Smart Hybrid", wcf: "WCF only", raw: "Raw only", wcf_raw: "WCF + Raw", aif_core: "AIF-Core" }).map(([value, label]) => ({ value, label }))} onValueChange={(input_mode) => patch("input_mode", input_mode)} /></label>
                <label><span>Reasoning</span><ArlineSelect ariaLabel="Reasoning" value={config.reasoning} options={(config.reasoning_modes || ["off", "on", "low", "medium", "high"]).map((value) => ({ value, label: value === "off" ? "Off" : value.charAt(0).toUpperCase() + value.slice(1) }))} onValueChange={(reasoning) => patch("reasoning", reasoning)} /></label>
                <NumberSetting label="Temperature" value={config.temperature} min={0} max={2} step={0.05} onChange={(value) => patch("temperature", value)} />
                <NumberSetting label="Top P" value={config.top_p} min={0} max={1} step={0.01} onChange={(value) => patch("top_p", value)} />
                <NumberSetting label="Top K" value={config.top_k} min={1} step={1} onChange={(value) => patch("top_k", value)} />
                <NumberSetting label="Min P" value={config.min_p} min={0} max={1} step={0.01} onChange={(value) => patch("min_p", value)} />
                <NumberSetting label="Repeat penalty" value={config.repeat_penalty} min={0.8} max={1.5} step={0.01} onChange={(value) => patch("repeat_penalty", value)} />
                <NumberSetting label="Visible output" value={config.visible_output_tokens} min={256} step={256} onChange={(value) => patch("visible_output_tokens", value)} />
                <NumberSetting label="Reasoning reserve" value={config.reasoning_reserve_tokens} min={0} step={256} onChange={(value) => patch("reasoning_reserve_tokens", value)} />
              </div>
            </>}

            {tab === "context" && <>
              <PanelHeading title="Context" description="Context is assembled by the Python memory, discovery, and workspace layers. The React UI only visualizes and requests it." />
              <label><span>Projection mode</span><ArlineSelect ariaLabel="Projection mode" value={config.projection_mode} options={(config.projection_modes || ["off", "conservative", "balanced", "vivid"]).map((value) => ({ value, label: value.charAt(0).toUpperCase() + value.slice(1) }))} onValueChange={(projection_mode) => patch("projection_mode", projection_mode)} /></label>
              <div className="settings-info"><strong>Context length</strong><span>{Number(config.context_length).toLocaleString()} tokens</span></div>
              <div className="settings-info"><strong>Output reservation</strong><span>{Number(config.visible_output_tokens + (config.reasoning === "off" ? 0 : config.reasoning_reserve_tokens)).toLocaleString()} tokens</span></div>
              <p className="settings-copy">Opening Library sheets is navigation only. Use explicit references from Chat to add them to a generation context.</p>
            </>}

            {tab === "storage" && <>
              <PanelHeading title="Data & Storage" description="Runtime databases, media, backups, and output remain owned by the backend." />
              <div className="settings-info"><strong>Frontend storage</strong><span>Only UI preferences and unsent recovery drafts</span></div>
              <div className="settings-info"><strong>Canonical storage</strong><span>Python WorkspaceStore / SQLite</span></div>
              <div className="settings-info"><strong>Native acceleration</strong><span>Rust adapter remains available</span></div>
              <p className="settings-copy">The TSX migration deliberately does not duplicate canonical state into browser storage. That would be convenient right until two sources of truth start fencing.</p>
              <section className="danger-zone">
                <div className="danger-zone-heading"><AlertTriangle size={15} /><div><strong>Danger zone</strong><span>These actions cannot be undone from the active database.</span></div></div>
                <div className="danger-action">
                  <div><strong>Reset database</strong><p>Remove projects, chats, Library/canon, memory, and discovery data. A timestamped recovery backup is kept.</p></div>
                  <button className="danger-button" onClick={() => setResetMode("database")}><RefreshCcw size={13} />Reset</button>
                </div>
                <div className="danger-action destructive">
                  <div><strong>Complete reset</strong><p>Also remove media, datasets, generated output, backups, and local UI state. Configuration and models are preserved.</p></div>
                  <button className="danger-button solid" onClick={() => setResetMode("complete")}><Trash2 size={13} />Delete all</button>
                </div>
              </section>
            </>}

            {tab === "conversation" && <>
              <PanelHeading title="Conversation" description="Defaults for new chats. Existing sessions keep their own mode, Presence, Perspective, and exploration choices." />
              <section className="settings-card"><div className="settings-block-heading"><div><strong>Story Presence defaults</strong><span>Safe starting points; story identity remains session-scoped</span></div></div><div className="settings-grid"><label><span>Default Presence</span><ArlineSelect ariaLabel="Default Presence" value={String(userProfile.presence_defaults.mode || "observer")} options={simpleOptions([["observer", "Observer", "Watch without entering the story"], ["self", "As myself", "Use your personal Presence"], ["ask", "Ask each time", "Choose when a new chat begins"]])} onValueChange={(mode) => patchProfileSection("presence_defaults", { mode })} /></label><label><span>Identity style</span><ArlineSelect ariaLabel="Identity style" value={String(userProfile.presence_defaults.identity_style || "story_version")} options={simpleOptions([["close_self", "Close self"], ["story_version", "Story version"], ["avatar", "Avatar"]])} onValueChange={(identity_style) => patchProfileSection("presence_defaults", { identity_style })} /></label><label><span>Perspective</span><ArlineSelect ariaLabel="Perspective" value={String(userProfile.presence_defaults.perspective || "scene_defined")} options={simpleOptions([["scene_defined", "Scene-defined"], ["first", "First person"], ["second", "Second person"], ["third_limited", "Third limited"]])} onValueChange={(perspective) => patchProfileSection("presence_defaults", { perspective })} /></label><label><span>Persistence</span><ArlineSelect ariaLabel="Persistence" value={String(userProfile.presence_defaults.persistence || "session")} options={simpleOptions([["session", "Session"], ["ask", "Ask before reusing"], ["branch", "Branch"]])} onValueChange={(persistence) => patchProfileSection("presence_defaults", { persistence })} /></label></div></section>
              <section className="settings-card"><div className="settings-block-heading"><div><strong>Story Lab defaults</strong><span>Creative freedom without changing sampling temperature</span></div></div><label><span>Exploration</span><ArlineSelect ariaLabel="Exploration" value={String(userProfile.story_lab.exploration || "open")} options={simpleOptions([["grounded", "Grounded", "Stay close to established material"], ["open", "Open", "Explore plausible alternatives"], ["unbound", "Unbound", "Invite radical possibilities"]])} onValueChange={(exploration) => patchProfileSection("story_lab", { exploration })} /></label></section>
              <section className="settings-card"><div className="settings-block-heading"><div><strong>Conversation defaults</strong><span>Used only when a new chat has no scoped Presence binding</span></div></div><div className="settings-grid"><label><span>Default mode</span><ArlineSelect ariaLabel="Default conversation mode" value={String(userProfile.collaboration.default_conversation_mode || "story_writer")} options={simpleOptions([["story_writer", "Story Writer", "Write polished story prose"], ["story_lab", "Story Lab", "Explore without establishing canon"], ["interactive", "Interactive", "Enter the story with protected agency"], ["analyst", "Analyst", "Inspect without continuing the story"], ["character_room", "Character Room", "Explore dialogue chemistry"]])} onValueChange={(default_conversation_mode) => patchProfileSection("collaboration", { default_conversation_mode })} menuMinWidth={280} /></label><label><span>Story Lab focus</span><ArlineSelect ariaLabel="Story Lab focus" value={String(userProfile.story_lab.focus || "plot")} options={simpleOptions([["plot", "Plot"], ["character", "Character"], ["world", "World"], ["relationship", "Relationship"], ["scene", "Scene"], ["my_presence", "My Presence"]])} onValueChange={(focus) => patchProfileSection("story_lab", { focus })} /></label></div></section>
            </>}
          </section>
        </div>
        <footer><span>{status}</span><button className="primary-action small" onClick={() => void save()}><Save size={13} />Save settings</button></footer>
      </aside>
      {resetMode && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) closeReset(); }}>
        <section className="modal reset-modal" role="dialog" aria-modal="true" aria-labelledby="reset-title">
          <button className="icon-control modal-close" onClick={closeReset} disabled={resetting}><X size={15} /></button>
          <AlertTriangle className="reset-warning-icon" size={24} />
          <h2 id="reset-title">{resetMode === "complete" ? "Completely reset Arline?" : "Reset the database?"}</h2>
          <p>{resetMode === "complete"
            ? "All canonical data, chats, media, exports, generated output, backups, and UI-local state will be permanently removed. Runtime configuration and installed models remain untouched."
            : "All canonical data, chats, memory, and discovery state will be removed. A recovery backup of each database will be created first."}</p>
          <label><span>Type <strong>{resetMode === "complete" ? "DELETE EVERYTHING" : "RESET DATABASE"}</strong> to continue</span><input autoFocus value={resetConfirmation} onChange={(event) => setResetConfirmation(event.target.value)} disabled={resetting} /></label>
          <div className="modal-actions">
            <button onClick={closeReset} disabled={resetting}>Cancel</button>
            <button className="danger-button solid" onClick={() => void performReset()} disabled={resetting || resetConfirmation !== (resetMode === "complete" ? "DELETE EVERYTHING" : "RESET DATABASE")}>
              {resetting ? <RefreshCcw className="spin" size={13} /> : <Trash2 size={13} />}{resetting ? "Resetting…" : "Confirm reset"}
            </button>
          </div>
        </section>
      </div>}
      {memoryClearOpen && <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) setMemoryClearOpen(false); }}>
        <section className="modal memory-clear-modal" role="dialog" aria-modal="true" aria-labelledby="memory-clear-title">
          <button className="icon-control modal-close" onClick={() => setMemoryClearOpen(false)}><X size={15} /></button>
          <Trash2 className="reset-warning-icon" size={22} />
          <h2 id="memory-clear-title">Clear selected personal memory?</h2>
          <p>Select the profile categories to clear. Nothing is removed until you save Settings.</p>
          <div className="memory-clear-options">{MEMORY_CATEGORY_META.map((meta) => <label key={meta.id}><input type="checkbox" checked={memoryClearSelection.includes(meta.id)} onChange={(event) => setMemoryClearSelection((current) => event.target.checked ? [...current, meta.id] : current.filter((id) => id !== meta.id))} /><span><strong>{meta.label}</strong><small>{memoryCount(meta.id)} stored profile item(s)</small></span></label>)}</div>
          <div className="modal-actions"><button onClick={() => setMemoryClearOpen(false)}>Cancel</button><button className="danger-button solid" disabled={!memoryClearSelection.length} onClick={clearSelectedMemory}><Trash2 size={13} />Clear selected</button></div>
        </section>
      </div>}
    </>
  );
}

function PanelHeading({ title, description }: { title: string; description: string }) {
  return <div className="settings-heading"><span className="eyebrow">Settings</span><h3>{title}</h3><p>{description}</p></div>;
}

function NumberSetting({ label, value, min, max, step, onChange }: { label: string; value: number; min?: number; max?: number; step?: number; onChange: (value: number) => void }) {
  return <label><span>{label}</span><input type="number" value={value} min={min} max={max} step={step} onChange={(event) => onChange(Number(event.target.value))} /></label>;
}

function ThemeChoice({ value, label, icon, current, onChange }: { value: ThemePreference; label: string; icon: ReactNode; current: ThemePreference; onChange: (value: ThemePreference) => void }) {
  return <button className={current === value ? "active" : ""} onClick={() => onChange(value)}>{icon}<span>{label}</span>{current === value ? <Check size={11} /> : null}</button>;
}

function AppearancePreview({ theme, accent }: { theme: ThemeMode; accent: string }) {
  const safeAccent = resolveAccent(accent, theme);
  const palette = appearancePalette(accent, theme);
  const style = {
    "--preview-accent": safeAccent,
    "--preview-accent-text": readableForeground(safeAccent),
    "--preview-bg": palette.surface,
    "--preview-surface": palette.surface2,
    "--preview-line": palette.lineStrong,
    "--preview-text": palette.text,
    "--preview-muted": palette.muted,
  } as CSSProperties;
  return <article className="appearance-preview" data-preview-theme={theme} style={style}>
    <header><span className="appearance-preview-logo" /><div><strong>Arline</strong><small>{theme} theme</small></div></header>
    <div className="preview-copy"><span>Shared knowledge</span><strong>Story workspace</strong><p>A calm surface with accessible emphasis.</p></div>
    <div className="preview-actions"><button>Selected</button><span>Secondary</span></div>
  </article>;
}
