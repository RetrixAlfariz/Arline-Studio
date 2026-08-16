from __future__ import annotations

import re


class DiscourseResolver:
    VERSION = "0.3.3"

    MARKERS = [
        ("sehingga", "RESULT"),
        ("karena", "CAUSE_OR_EXPLANATION"),
        ("makanya", "RESULT"),
        ("akibatnya", "RESULT"),
        ("gara-gara", "CAUSE"),
        ("walaupun", "CONCESSION"),
        ("meskipun", "CONCESSION"),
        ("tapi", "CONTRAST"),
        ("namun", "CONTRAST"),
        ("kalau", "CONDITION"),
        ("jika", "CONDITION"),
        ("lalu", "SEQUENCE"),
        ("kemudian", "SEQUENCE"),
    ]

    @classmethod
    def default(cls):
        return cls()

    def resolve(self, aspect_segments: dict) -> dict:
        relations = []
        out = []
        for seg in aspect_segments.get("segments", []):
            text = seg.get("normalized_text") or seg["text"]
            low = text.lower()
            markers = []
            for marker, kind in self.MARKERS:
                if re.search(rf"\b{re.escape(marker)}\b", low):
                    markers.append({"marker": marker, "type": kind})
                    relations.append({
                        "id": f"disc_{len(relations)+1:04d}",
                        "segment_id": seg["id"],
                        "type": kind,
                        "marker": marker,
                    })
            item = dict(seg)
            item["discourse_markers"] = markers
            out.append(item)
        return {"version": self.VERSION, "segments": out, "relations": relations, "diagnostics": []}
