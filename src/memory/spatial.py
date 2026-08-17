from __future__ import annotations

from collections import deque
from typing import Any


INVERSE_RELATIONS = {
    "contains": "part_of",
    "part_of": "contains",
    "inside": "contains",
    "stored_in": "contains",
    "on": "supports",
    "under": "above",
    "mounted_on": "supports",
    "opens_into": "entrance_to",
    "connected_to": "connected_to",
    "adjacent_to": "adjacent_to",
}


class SpatialMemory:
    def __init__(self, store):
        self.store = store

    def link(self, **values: Any) -> dict[str, Any]:
        return self.store.create_spatial_edge(**values)

    def unlink(self, edge_id: str) -> None:
        self.store.delete_spatial_edge(edge_id)

    def neighborhood(self, *, world_id: str, branch_id: str | None,
                     resource_type: str, resource_id: str, depth: int = 2) -> dict[str, Any]:
        return self.store.spatial_neighborhood(
            world_id=world_id, branch_id=branch_id,
            resource_type=resource_type, resource_id=resource_id, depth=depth,
        )

    def path(self, *, world_id: str, branch_id: str | None,
             start_type: str, start_id: str, target_type: str, target_id: str,
             max_depth: int = 8) -> list[dict[str, Any]]:
        graph = self.neighborhood(
            world_id=world_id, branch_id=branch_id,
            resource_type=start_type, resource_id=start_id, depth=max_depth,
        )
        adjacency: dict[tuple[str, str], list[tuple[tuple[str, str], dict[str, Any]]]] = {}
        for edge in graph["edges"]:
            left=(edge["subject_type"],edge["subject_id"]); right=(edge["object_type"],edge["object_id"])
            adjacency.setdefault(left,[]).append((right,edge)); adjacency.setdefault(right,[]).append((left,edge))
        start=(start_type,start_id); target=(target_type,target_id)
        queue=deque([(start,[])]); seen={start}
        while queue:
            node,path=queue.popleft()
            if node==target: return path
            if len(path)>=max_depth: continue
            for neighbor,edge in adjacency.get(node,[]):
                if neighbor in seen: continue
                seen.add(neighbor); queue.append((neighbor,path+[edge]))
        return []
