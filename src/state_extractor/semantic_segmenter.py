from __future__ import annotations

import re


class SemanticSegmenter:
    VERSION = "0.3.3"

    @classmethod
    def default(cls):
        return cls()

    def roles(self, text: str):
        low = text.lower()
        roles = set()

        if any(x in low for x in (
            "fokus ", "eksplorasi ", "buat ", "jangan ", "tuliskan ",
            "cerita sangat", "sangat-sangat panjang",
        )):
            roles.add("directive")

        if re.search(
            r"\bcerita\b.{0,120}\b(?:kali\s+pertama|pertama\s+kali)\b",
            low, re.S,
        ):
            roles.update({"scenario_request", "directive"})

        if re.search(
            r"\b[\w'-]+\s+(?:membuat\s*(?:ku|aku)?|menyuruh\s*(?:ku|aku)?)\s+memakai\b",
            low,
        ):
            roles.add("scenario_event")

        if any(x in low for x in (
            "bisa bantu", "tolong", "jelaskan", "jelasin", "berapa", "seberapa",
        )):
            roles.add("request")

        if re.search(
            r"\b(lahir|umur|usia|tinggi|panjangnya|bahan|warna|luas|lantai|cup|hormon|bodyku|tubuhku|dadaku|cocok)\b",
            low,
        ):
            roles.add("fact")

        if any(x in low for x in (
            "sekarang ", "sedang ", "tinggal sendiri", "libur semester",
        )):
            roles.add("state")

        if any(x in low for x in (
            "mencoba memakai", "pakai wig", "tempelin", "melebur", "mengubah",
            "menyatu", "nyatu", "berjalan", "berlari", "duduk", "meraih",
            "mengambil", "naik tangga", "turun tangga",
        )):
            roles.add("event")

        if any(x in low for x in (
            "sebelum ", "setelah ", "sesudah ", "kemudian ", "lalu ",
        )):
            roles.add("temporal_constraint")

        if any(x in low for x in ("kalau ", "jika ", "seandainya ", "andaikan ")):
            roles.add("hypothetical")

        if any(x in low for x in ("tidak ", "nggak ", "gak ", "bukan ")):
            roles.add("negation_present")

        if any(x in low for x in ("bisa ", "mungkin ", "ingin ", "mau ")):
            roles.add("modality_present")

        if any(x in low for x in ("bodyku", "tubuhku", "dadaku", "pakaiannya cocok")):
            roles.add("description")

        return sorted(roles or {"context"})

    def segment(self, structure):
        out = []
        sid = 1
        nodes = structure["nodes"]
        node_map = {n["id"]: n for n in nodes}
        node_index = {n["id"]: i for i, n in enumerate(nodes)}

        for node in nodes:
            base = node.get("own_text", node["text"])
            if not base.strip():
                continue

            pieces = [base] if node["type"] != "prose" else re.split(
                r"(?<=[.!?])\s+|\n{2,}", base
            )

            for piece in pieces:
                if not piece or not piece.strip():
                    continue
                text = piece.strip()

                context = []
                parent = node.get("parent_id")
                while parent and parent in node_map:
                    p = node_map[parent]
                    context.append(p.get("own_text", p["text"]))
                    parent = p.get("parent_id")

                # Top-level annotations often refine the noun immediately to
                # their left: gamis[warna hitam], temanku[cowok-Fano], etc.
                if not context and node["type"] in {"bracket_note", "parenthetical"}:
                    idx = node_index[node["id"]]
                    if idx > 0:
                        prev = nodes[idx - 1]
                        if prev.get("end") == node.get("start"):
                            left = prev.get("own_text", prev.get("text", ""))
                            context.append(left[-220:])

                out.append({
                    "id": f"seg_{sid:04d}",
                    "source_node": node["id"],
                    "structure_type": node["type"],
                    "text": text,
                    "context_text": " | ".join(reversed(context)),
                    "start": node["start"],
                    "end": node["end"],
                    "roles": self.roles(text),
                    "recovered_structure": bool(node.get("recovered_unclosed")),
                })
                sid += 1

        return {
            "version": self.VERSION,
            "segments": out,
            "diagnostics": [],
        }
