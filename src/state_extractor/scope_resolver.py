from __future__ import annotations


class ScopeResolver:
    VERSION = "0.3.3"

    @classmethod
    def default(cls):
        return cls()

    def resolve(self, normalized_segments):
        out = []
        for s in normalized_segments.get("segments", []):
            text = s.get("normalized_text") or s["text"]
            low = text.lower().strip()
            modality = "asserted"
            if any(low.startswith(x) for x in ("kalau ", "jika ", "seandainya ", "andaikan ")):
                modality = "hypothetical"
            elif any(x in low for x in ("bisa bantu", "tolong", "jelaskan", "jelasin")):
                modality = "request"
            elif any(low.startswith(x) for x in ("ingin ", "mau ", "aku ingin ", "aku mau ")):
                modality = "intent"
            elif low.startswith("mungkin "):
                modality = "possible"

            temporal = "current_or_unspecified"
            if "sebelum " in low:
                temporal = "before_constraint"
            elif "setelah " in low or "sesudah " in low:
                temporal = "after_constraint"

            polarity = "positive"
            if any(low.startswith(x) for x in ("tidak ", "nggak ", "gak ", "bukan ")):
                polarity = "negative"

            q = dict(s)
            q["scope"] = {
                "polarity": polarity,
                "modality": modality,
                "temporal_scope": temporal,
            }
            out.append(q)
        return {"version": self.VERSION, "segments": out, "diagnostics": []}
