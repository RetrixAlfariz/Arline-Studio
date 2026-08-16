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
    VERSION = "0.1"

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
    ) -> WorkspaceContext:
        if not project_id:
            return WorkspaceContext(self.VERSION, "", {}, estimated_tokens=0)

        project = self.store.get_project(project_id)
        if not world_id:
            world_id = project.get("default_world_id")
        world = self.store.get_world(world_id) if world_id else None
        if world and not branch_id:
            main = next((x for x in world.get("branches", []) if x.get("kind") == "main"), None)
            branch_id = main.get("id") if main else None
        branch = self.store.get_branch(branch_id) if branch_id else None
        refs = self._normalize_refs(references or [])
        pins = self.store.list_pins(project_id, world_id=world_id, branch_id=branch_id)

        selected: list[dict[str, Any]] = []
        auto_selected: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        def add(resource_type: str, resource_id: str, *, explicit: bool, reason: str):
            key = (resource_type, resource_id)
            if key in seen or len(selected) >= self.max_items:
                return
            item = self._resource(resource_type, resource_id, world_id, branch_id)
            if item is None:
                return
            seen.add(key)
            item["selection_reason"] = reason
            selected.append(item)
            if not explicit:
                auto_selected.append({
                    "type": resource_type,
                    "id": resource_id,
                    "label": item.get("label", resource_id),
                    "reason": reason,
                })

        for ref in refs:
            add(ref["type"], ref["id"], explicit=True, reason="explicit @ reference")
        for pin in pins:
            add(pin["resource_type"], pin["resource_id"], explicit=False, reason=f"pinned {pin['scope']} context")

        # Automatically include relationships connecting explicitly selected variants.
        variant_ids = {item["id"] for item in selected if item["type"] == "entity_variant"}
        if world_id and variant_ids:
            relationships = self.store.list_relationships(world_id=world_id, branch_id=branch_id)
            for rel in relationships:
                if rel["subject_variant_id"] in variant_ids or rel["object_variant_id"] in variant_ids:
                    add("relationship", rel["id"], explicit=False, reason="relationship connected to explicit reference")

        lines = ["@ARLINE-WORKSPACE 0.1", "", "[SCOPE]"]
        lines.append(f"project: {project['name']}")
        if world:
            lineage = " → ".join(x["name"] for x in world.get("lineage", []))
            lines.append(f"world: {world['name']} ({world['canon_status']})")
            if lineage:
                lines.append(f"world lineage: {lineage}")
        if branch:
            lines.append(f"branch: {branch['name']} ({branch['kind']}; {branch['canon_status']})")
            if branch["kind"] in {"sandbox", "what_if"}:
                lines.append("scope rule: branch changes are non-canonical until explicitly promoted")

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
                "project": project["name"],
                "project_settings": project.get("settings") or {},
                "world_id": world_id,
                "world": world["name"] if world else None,
                "world_settings": (world or {}).get("settings") or {},
                "branch_id": branch_id,
                "branch": branch["name"] if branch else None,
                "branch_kind": branch["kind"] if branch else None,
                "branch_canon_status": branch.get("canon_status") if branch else None,
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
            out.append({"type": typ, "id": rid, "label": ref.get("label") or rid})
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
        lines = [f"- {item['label']} [{typ}] — {item['selection_reason']}"]
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
                for fact in facts[:16]:
                    lines.append(f"    - {fact['path']} = {self._compact_json(fact.get('value'))} ({fact['status']})")
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
                lines.append(f"  content: {content[:2200]}{'…' if len(content) > 2200 else ''}")
            lines.append(f"  status: {data.get('status')}; type: {data.get('document_type')}")
        elif typ == "world":
            lines.append(f"  status: {data.get('canon_status')}; description: {data.get('description') or '-'}")
        return lines
