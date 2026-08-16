from __future__ import annotations


class StructuralParser:
    VERSION = "0.3.3"

    @classmethod
    def default(cls):
        return cls()

    def parse(self, text: str):
        spans = []
        stack = []
        diagnostics = []
        matching = {"]": "[", ")": "("}

        for i, ch in enumerate(text):
            if ch in "[(":
                stack.append({
                    "open": ch,
                    "start": i,
                    "recovered_unclosed": False,
                })
                continue

            if ch not in "])":
                continue

            expected = matching[ch]
            match_idx = None
            for idx in range(len(stack) - 1, -1, -1):
                if stack[idx]["open"] == expected:
                    match_idx = idx
                    break

            if match_idx is None:
                diagnostics.append({
                    "type": "unmatched_closing_group",
                    "position": i,
                    "character": ch,
                })
                continue

            # Recover dangling inner groups before the matched opener.
            for rec0 in stack[match_idx + 1:]:
                rec = dict(rec0)
                rec["end"] = i
                rec["recovered_unclosed"] = True
                spans.append(rec)
                diagnostics.append({
                    "type": "recovered_unclosed_group",
                    "start": rec["start"],
                    "end": i,
                    "opener": rec["open"],
                })

            rec = dict(stack[match_idx])
            rec["end"] = i + 1
            rec["close"] = ch
            spans.append(rec)
            stack = stack[:match_idx]

        # Recover any groups still open at EOF.
        for rec0 in stack:
            rec = dict(rec0)
            rec["end"] = len(text)
            rec["recovered_unclosed"] = True
            spans.append(rec)
            diagnostics.append({
                "type": "recovered_unclosed_group",
                "start": rec["start"],
                "end": len(text),
                "opener": rec["open"],
            })

        # De-duplicate exact spans.
        dedup = {}
        for s in spans:
            if s["end"] <= s["start"] + 1:
                continue
            key = (s["start"], s["end"], s["open"])
            old = dedup.get(key)
            if old is None or (
                old.get("recovered_unclosed")
                and not s.get("recovered_unclosed")
            ):
                dedup[key] = s
        spans = list(dedup.values())
        spans.sort(key=lambda x: (x["start"], -x["end"]))

        # Parent = smallest containing span.
        for s in spans:
            parents = [
                q for q in spans
                if q is not s
                and q["start"] < s["start"]
                and q["end"] >= s["end"]
            ]
            s["parent_span"] = (
                min(parents, key=lambda q: q["end"] - q["start"])
                if parents else None
            )

        for idx, s in enumerate(spans, 1):
            s["id"] = f"grp_{idx:04d}"

        for s in spans:
            par = s["parent_span"]
            s["parent_id"] = par["id"] if par else None
            children = [
                q for q in spans
                if q.get("parent_span") is s
            ]
            children.sort(key=lambda q: q["start"])
            s["children"] = [q["id"] for q in children]

            inner_start = s["start"] + 1
            inner_end = (
                s["end"]
                if s.get("recovered_unclosed")
                else s["end"] - 1
            )
            s["text"] = text[inner_start:inner_end]

            pieces = []
            cursor = inner_start
            for child in children:
                if child["start"] >= cursor:
                    pieces.append(text[cursor:child["start"]])
                cursor = max(cursor, child["end"])
            pieces.append(text[cursor:inner_end])
            s["own_text"] = " ".join(
                p.strip() for p in pieces if p.strip()
            )

        top = sorted(
            [s for s in spans if s["parent_id"] is None],
            key=lambda x: x["start"],
        )
        raw_nodes = []
        cursor = 0
        for s in top:
            if s["start"] > cursor and text[cursor:s["start"]].strip():
                raw_nodes.append({
                    "type": "prose",
                    "text": text[cursor:s["start"]],
                    "own_text": text[cursor:s["start"]],
                    "start": cursor,
                    "end": s["start"],
                    "parent_id": None,
                    "children": [],
                    "recovered_unclosed": False,
                })
            cursor = max(cursor, s["end"])

        if cursor < len(text) and text[cursor:].strip():
            raw_nodes.append({
                "type": "prose",
                "text": text[cursor:],
                "own_text": text[cursor:],
                "start": cursor,
                "end": len(text),
                "parent_id": None,
                "children": [],
                "recovered_unclosed": False,
            })

        for s in spans:
            raw_nodes.append({
                "type": "bracket_note" if s["open"] == "[" else "parenthetical",
                "text": s["text"],
                "own_text": s["own_text"],
                "start": s["start"],
                "end": s["end"],
                "parent_id": s["parent_id"],
                "children": s["children"],
                "group_id": s["id"],
                "recovered_unclosed": bool(s.get("recovered_unclosed")),
            })

        raw_nodes.sort(
            key=lambda n: (
                n["start"],
                0 if n["type"] == "prose" else 1,
                n["end"],
            )
        )
        for i, node in enumerate(raw_nodes, 1):
            node["id"] = f"str_{i:04d}"

        group_to_struct = {
            n.get("group_id"): n["id"]
            for n in raw_nodes if n.get("group_id")
        }
        for node in raw_nodes:
            if node.get("parent_id"):
                node["parent_id"] = group_to_struct.get(
                    node["parent_id"], node["parent_id"]
                )
            node["children"] = [
                group_to_struct.get(x, x)
                for x in node.get("children", [])
            ]

        return {
            "version": self.VERSION,
            "nodes": raw_nodes,
            "diagnostics": diagnostics,
        }
