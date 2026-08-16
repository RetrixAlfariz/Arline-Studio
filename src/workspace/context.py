from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

from .store import WorkspaceStore


@dataclass(slots=True)
class WorkspaceContext:
    version: str
    text: str
    scope: dict[str, Any]
    explicit_references: list[dict[str, Any]] = field(default_factory=list)
    auto_selected: list[dict[str, Any]] = field(default_factory=list)
    pinned: list[dict[str, Any]] = field(default_factory=list)
    estimated_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "text": self.text,
            "scope": self.scope,
            "explicit_references": self.explicit_references,
            "auto_selected": self.auto_selected,
            "pinned": self.pinned,
            "estimated_tokens": self.estimated_tokens,
        }


class WorkspaceContextResolver:
    VERSION = "0.2"

    def __init__(self, store: WorkspaceStore, *, max_items: int = 24):
        self.store = store
        self.max_items = max_items

    def resolve(
        self,
        *,
        project_id: str | None,
        world_id: str | None,
        branch_id: str | None,
        references: list[dict[str, Any]] | None = None,
        recipe_id: str | None = None,
    ) -> WorkspaceContext:
        project = self.store.get_project(project_id) if project_id else None
        if not world_id:
            world_id = (project or {}).get("default_world_id")
        world = self.store.get_world(world_id) if world_id else None
        if world and not branch_id:
            main = next((x for x in world.get("branches", []) if x.get("kind") == "main"), None)
            branch_id = main.get("id") if main else None
        branch = self.store.get_branch(branch_id) if branch_id else None
        refs = self._normalize_refs(references or [])
        pins = self.store.list_pins(project_id, world_id=world_id, branch_id=branch_id) if project_id else []
        manifest_refs = self.store.list_project_manifest_refs(project_id) if project_id else []
        active_scene = self.store.get_active_scene(project_id) if project_id else None
        scene_card = self.store.get_scene_card(active_scene["document_id"]) if active_scene and active_scene.get("document_id") else None
        overlays = self.store.list_project_overlays(
            project_id, world_id=world_id, branch_id=branch_id
        ) if project_id else []
        recipes = self.store.list_context_recipes(project_id)
        recipe = next((item for item in recipes if item["id"] == recipe_id), None)
        if recipe is None:
            recipe = next((item for item in recipes if item["id"] == "RECIPE-STORY"), None)
        policy = (recipe or {}).get("recipe") or {}

        def enabled(key: str, default: bool = True) -> bool:
            value = policy.get(key, default)
            return value is not False and value not in {"off", "none", 0}

        selected: list[dict[str, Any]] = []
        auto_selected: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        def add(resource_type: str, resource_id: str, *, explicit: bool, reason: str, mode: str = "context"):
            key = (resource_type, resource_id)
            if key in seen or len(selected) >= self.max_items:
                return
            item = self._resource(resource_type, resource_id, world_id, branch_id)
            if item is None:
                return
            seen.add(key)
            item["selection_reason"] = reason
            item["context_mode"] = mode if mode in {"mention", "context", "deep"} else "context"
            selected.append(item)
            if not explicit:
                auto_selected.append({
                    "type": resource_type,
                    "id": resource_id,
                    "label": item.get("label", resource_id),
                    "reason": reason,
                })

        if enabled("explicit_refs", True):
            for ref in refs:
                add(ref["type"], ref["id"], explicit=True, reason=f"explicit @ reference · {ref.get('mode', 'context')}", mode=ref.get("mode", "context"))
        if enabled("pins", True):
            for pin in pins:
                add(pin["resource_type"], pin["resource_id"], explicit=False, reason=f"pinned {pin['scope']} context")
        if enabled("project_manifest", True):
            for ref in manifest_refs:
                add(ref["resource_type"], ref["resource_id"], explicit=False, reason="project working set")

        # The narrative cursor is a first-class context anchor. Pull its linked
        # document/POV/location/participants into the semantic working set.
        if active_scene and enabled("active_scene", True):
            if active_scene.get("document_id") and enabled("project_documents", True):
                add("document", active_scene["document_id"], explicit=False, reason="active scene document")
            scene_entity_mode = "deep" if str(policy.get("voice", "")).lower() == "deep" else "context"
            if active_scene.get("pov_variant_id"):
                add("entity_variant", active_scene["pov_variant_id"], explicit=False, reason="active scene POV", mode=scene_entity_mode)
            if active_scene.get("location_variant_id"):
                add("entity_variant", active_scene["location_variant_id"], explicit=False, reason="active scene location")
            for variant_id in (active_scene.get("participants") or [])[:16]:
                add("entity_variant", variant_id, explicit=False, reason="present in active scene", mode=scene_entity_mode)

        # Automatically include relationships connecting selected variants when
        # the recipe asks for relationship state.
        variant_ids = {item["id"] for item in selected if item["type"] == "entity_variant"}
        if world_id and variant_ids and enabled("relationships", True):
            relationships = self.store.list_relationships(world_id=world_id, branch_id=branch_id)
            for rel in relationships:
                if rel["subject_variant_id"] in variant_ids or rel["object_variant_id"] in variant_ids:
                    add("relationship", rel["id"], explicit=False, reason="relationship connected to selected entity")

        lines = ["@ARLINE-WORKSPACE 0.1", "", "[SCOPE]"]
        if project:
            lines.append(f"project: {project['name']}")
        if recipe:
            lines.append(f"context recipe: {recipe['name']}")
        if world:
            lineage = " → ".join(x["name"] for x in world.get("lineage", []))
            lines.append(f"world: {world['name']} ({world['canon_status']})")
            if lineage:
                lines.append(f"world lineage: {lineage}")
        if branch:
            lines.append(f"branch: {branch['name']} ({branch['kind']}; {branch['canon_status']})")
            if branch["kind"] in {"sandbox", "what_if"}:
                lines.append("scope rule: branch changes are non-canonical until explicitly promoted")

        if active_scene and enabled("active_scene", True):
            lines.extend(["", "[ACTIVE SCENE]"])
            if active_scene.get("document_id"):
                try:
                    doc = self.store.get_document(active_scene["document_id"])
                    lines.append(f"document: {doc['title']}")
                except KeyError:
                    pass
            if active_scene.get("narrative_time"):
                lines.append(f"narrative time: {active_scene['narrative_time']}")
            if active_scene.get("pov_variant_id"):
                try:
                    pov = self.store.get_variant(active_scene["pov_variant_id"])
                    lines.append(f"POV: {pov['display_name']}")
                except KeyError:
                    pass
            if active_scene.get("location_variant_id"):
                try:
                    loc = self.store.get_variant(active_scene["location_variant_id"])
                    lines.append(f"location: {loc['display_name']}")
                except KeyError:
                    pass
            if scene_card and scene_card.get("target_outcome"):
                lines.append(f"target outcome: {scene_card['target_outcome']}")
            if scene_card and scene_card.get("status"):
                lines.append(f"scene status: {scene_card['status']}")
            if active_scene.get("participants"):
                participant_names = []
                for variant_id in active_scene["participants"][:16]:
                    try:
                        participant_names.append(self.store.get_variant(variant_id)["display_name"])
                    except KeyError:
                        continue
                if participant_names:
                    lines.append("present: " + ", ".join(participant_names))

        # Context recipes can ask for compact/relevant/deep canon exposure.
        # Selected variants already render their own facts above; this section
        # surfaces wider world truth without forcing every prompt to carry the
        # entire Bible.
        world_canon_mode = str(policy.get("world_canon", "relevant") or "relevant").lower()
        if world_id and enabled("world_canon", True):
            facts = self.store.list_facts(world_id=world_id, branch_id=branch_id)
            selected_owners = {(item["type"], item["id"]) for item in selected}
            if world_canon_mode == "compact":
                canon_facts = [fact for fact in facts if fact.get("owner_type") == "world"][:12]
            elif world_canon_mode == "deep":
                canon_facts = facts[:64]
            else:
                canon_facts = [
                    fact for fact in facts
                    if fact.get("owner_type") == "world"
                    or (fact.get("owner_type"), fact.get("owner_id")) in selected_owners
                ][:28]
            if canon_facts:
                lines.extend(["", f"[WORLD CANON · {world_canon_mode.upper()}]"])
                for fact in canon_facts:
                    lines.append(
                        f"- {fact.get('owner_type')}:{fact.get('owner_id')} "
                        f"{fact.get('path')} = {self._compact_json(fact.get('value'), 700)} "
                        f"({fact.get('status')})"
                    )

        if overlays and enabled("project_overlays", True):
            lines.extend(["", "[PROJECT OVERLAYS]"])
            for overlay in overlays[:24]:
                lines.append(
                    f"- {overlay['owner_type']}:{overlay['owner_id']} {overlay['path']} = "
                    f"{self._compact_json(overlay.get('value'))}"
                )

        if world_id and enabled("timeline", False):
            timeline = self.store.list_timeline_events(world_id, branch_id=branch_id)
            if timeline:
                lines.extend(["", "[TIMELINE]"])
                for event in timeline[-20:]:
                    prefix = f"{event.get('time_label')}: " if event.get("time_label") else ""
                    lines.append(f"- {prefix}{event.get('summary', '')}")
                    if event.get("state_patch"):
                        lines.append(f"  state patch: {self._compact_json(event['state_patch'], 600)}")

        if project_id and enabled("conflicts", False):
            conflicts = self.store.list_conflicts(project_id=project_id, world_id=world_id, branch_id=branch_id, status="open")
            staged = self.store.list_staged_changes(project_id, status="pending", world_id=world_id, branch_id=branch_id)
            if conflicts or staged:
                lines.extend(["", "[CONTINUITY REVIEW]"])
                for conflict in conflicts[:16]:
                    lines.append(f"- conflict {conflict.get('path')}: {self._compact_json(conflict.get('left'), 300)} ↔ {self._compact_json(conflict.get('right'), 300)}")
                for change in staged[:16]:
                    lines.append(f"- pending {change.get('owner_type')}:{change.get('owner_id')} {change.get('path')} → {self._compact_json(change.get('proposed_value'), 500)}")

        if selected:
            lines.extend(["", "[REFERENCED CONTEXT]"])
            for item in selected:
                lines.extend(self._render_resource(item))

        text = "\n".join(lines).rstrip() + "\n"
        return WorkspaceContext(
            version=self.VERSION,
            text=text,
            scope={
                "project_id": project_id,
                "project": project["name"] if project else None,
                "project_settings": (project or {}).get("settings") or {},
                "world_id": world_id,
                "world": world["name"] if world else None,
                "world_settings": (world or {}).get("settings") or {},
                "branch_id": branch_id,
                "branch": branch["name"] if branch else None,
                "branch_kind": branch["kind"] if branch else None,
                "branch_canon_status": branch.get("canon_status") if branch else None,
                "context_recipe_id": recipe.get("id") if recipe else None,
                "context_recipe": recipe.get("name") if recipe else None,
                "context_policy": policy,
                "active_scene": active_scene,
                "scene_card": scene_card,
            },
            explicit_references=refs,
            auto_selected=auto_selected,
            pinned=pins,
            estimated_tokens=max(1, len(text) // 4) if text else 0,
        )

    @staticmethod
    def _normalize_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for ref in refs:
            typ = str(ref.get("type") or "").strip()
            rid = str(ref.get("id") or "").strip()
            if not typ or not rid or (typ, rid) in seen:
                continue
            seen.add((typ, rid))
            mode = str(ref.get("mode") or "context").strip().lower()
            if mode not in {"mention", "context", "deep"}:
                mode = "context"
            out.append({"type": typ, "id": rid, "label": ref.get("label") or rid, "mode": mode})
        return out

    def _resource(
        self, resource_type: str, resource_id: str, world_id: str | None, branch_id: str | None
    ) -> dict[str, Any] | None:
        try:
            if resource_type == "entity_variant":
                item = self.store.get_variant(resource_id)
                return {"type": resource_type, "id": resource_id, "label": item["display_name"], "data": item}
            if resource_type == "entity_family":
                family = self.store.get_entity_family(resource_id)
                variant = self.store.resolve_variant(resource_id, world_id, branch_id) if world_id else None
                return {
                    "type": "entity_variant" if variant else resource_type,
                    "id": variant["id"] if variant else resource_id,
                    "label": variant["display_name"] if variant else family["name"],
                    "data": variant or family,
                }
            if resource_type == "relationship":
                item = self.store.get_relationship(resource_id)
                return {
                    "type": resource_type,
                    "id": resource_id,
                    "label": f"{item['subject_name']} ↔ {item['object_name']}",
                    "data": item,
                }
            if resource_type == "document":
                item = self.store.get_document(resource_id)
                return {"type": resource_type, "id": resource_id, "label": item["title"], "data": item}
            if resource_type == "world":
                item = self.store.get_world(resource_id)
                return {"type": resource_type, "id": resource_id, "label": item["name"], "data": item}
        except KeyError:
            return None
        return None

    @staticmethod
    def _compact_json(value: Any, max_chars: int = 1800) -> str:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        return text if len(text) <= max_chars else text[:max_chars] + "…"

    def _render_resource(self, item: dict[str, Any]) -> list[str]:
        data = item["data"]
        typ = item["type"]
        mode = item.get("context_mode", "context")
        lines = [f"- {item['label']} [{typ}; {mode}] — {item['selection_reason']}"]
        if mode == "mention":
            if typ == "entity_variant" and data.get("canon_status"):
                lines.append(f"  identity only; canon status: {data['canon_status']}")
            elif typ == "relationship":
                lines.append(f"  identity only: {data['subject_name']} —{data['relation_type']}→ {data['object_name']}")
            elif typ == "document":
                lines.append(f"  identity only; type: {data.get('document_type')}")
            elif typ == "world":
                lines.append(f"  identity only; canon status: {data.get('canon_status')}")
            return lines
        if typ == "entity_variant":
            if data.get("summary"):
                lines.append(f"  summary: {data['summary']}")
            if data.get("shared_core"):
                lines.append(f"  shared core: {self._compact_json(data['shared_core'])}")
            for key, label in (
                ("attributes", "world-specific attributes"),
                ("current_state", "current state"),
                ("voice", "voice"),
                ("knowledge", "knowledge"),
                ("beliefs", "beliefs/misconceptions"),
            ):
                if data.get(key):
                    lines.append(f"  {label}: {self._compact_json(data[key])}")
            if data.get("canon_status"):
                lines.append(f"  canon status: {data['canon_status']}")
            facts = data.get("facts") or []
            if facts:
                lines.append("  facts:")
                for fact in facts[:32 if mode == "deep" else 16]:
                    lines.append(f"    - {fact['path']} = {self._compact_json(fact.get('value'))} ({fact['status']})")
            if mode == "deep":
                relationships = data.get("relationships") or []
                if relationships:
                    lines.append("  connected relationships:")
                    for rel in relationships[:24]:
                        lines.append(f"    - {rel['subject_name']} —{rel['relation_type']}→ {rel['object_name']} ({rel.get('canon_status', '-')})")
        elif typ == "relationship":
            lines.append(
                f"  relation: {data['subject_name']} —{data['relation_type']}→ {data['object_name']}"
            )
            lines.append(f"  status: {data['status']}; canon: {data['canon_status']}")
            if data.get("attributes"):
                lines.append(f"  details: {self._compact_json(data['attributes'])}")
        elif typ == "document":
            content = (data.get("content") or "").strip()
            if content:
                limit = 8000 if mode == "deep" else 2200
                lines.append(f"  content: {content[:limit]}{'…' if len(content) > limit else ''}")
            lines.append(f"  status: {data.get('status')}; type: {data.get('document_type')}")
        elif typ == "world":
            lines.append(f"  status: {data.get('canon_status')}; description: {data.get('description') or '-'}")
        return lines
