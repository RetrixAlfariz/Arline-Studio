"use strict";

// Central command metadata. Execution lives in the single command dispatcher in arline.js.
window.ARLINE_COMMANDS = [
  { id: "continue", label: "/continue", description: "Continue the active scene", action: "insert", text: "/continue " },
  { id: "rewrite", label: "/rewrite", description: "Rewrite selected/current material", action: "insert", text: "/rewrite " },
  { id: "mono", label: "/mono", description: "Character-aware monologue seed; internal by default, delivery modifiers supported", action: "insert", text: "/mono @character \"intent or thought\" " },
  { id: "dia", label: "/dia", description: "Character-aware interaction rail; beat-driven rather than fixed alternating turns", action: "insert", text: "/dia @characterA@characterB \"topic or interaction goal\" " },
  { id: "ambience", label: "/ambience", description: "Guide scene atmosphere, sensory palette, and pacing without changing canon", action: "insert", text: "/ambience slow \"scene atmosphere\" " },
  { id: "intimacy", label: "/intimacy", description: "Guide character-aware intimate scene dynamics, pacing, and aftermath", action: "insert", text: "/intimacy @character slow \"scene intent\" " },
  { id: "analyze", label: "/analyze", description: "Analyze the current prompt without generation", action: "analyze" },
  { id: "new-scene", label: "Create scene", description: "Create a new scene document", action: "new-document" },
  { id: "new-character", label: "Create character", description: "Create a character family and current-world variant", action: "new-character" },
  { id: "new-template", label: "Create entity template", description: "Create a reusable character/location/item sheet structure", action: "new-template" },
  { id: "conflicts", label: "Resolve conflicts", description: "Review contradictory facts in the active scope", action: "conflicts" },
  { id: "sandbox", label: "Open sandbox branch", description: "Create a non-canonical what-if branch", action: "sandbox" },
  { id: "snapshot", label: "Save world snapshot", description: "Checkpoint current world/branch state", action: "snapshot" },
  { id: "switch-world", label: "Switch world", description: "Choose another world or AU", action: "world-picker" },
  { id: "dataset", label: "Open Feedback Lab", description: "Review generated prose, comparisons, and advanced exports", action: "data" },
  { id: "inspector", label: "Open context/runtime inspector", description: "Inspect context assembly, trace, validator, and model runtime", action: "inspector" },
  { id: "new-any", label: "/new", description: "Create an entity, world, folder, document, or project from natural text", action: "quick-create" },
  { id: "scratch", label: "/scratch", description: "Toggle scratch mode; exploration does not enter canon staging", action: "scratch" },
  { id: "fork", label: "/fork", description: "Fork the active chat from its latest turn", action: "fork-chat" },
  { id: "context", label: "/context", description: "Open explainable context assembly", action: "context" },
  { id: "continuity", label: "/continuity", description: "Run continuity lint for this project and world", action: "continuity" },
  { id: "scene", label: "/scene", description: "Set or inspect the active narrative scene", action: "active-scene" },
  { id: "import", label: "Import manuscript", description: "Import Markdown/text into the current Project binder", action: "import-manuscript" },
  { id: "activity", label: "Open Activity Center", description: "Review issues, recover Trash, and inspect recent actions", action: "activity" },
];
