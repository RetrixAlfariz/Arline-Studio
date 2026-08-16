from __future__ import annotations

import re


class AspectResolver:
    """Assign temporal/aspect status before event materialization."""

    VERSION = "0.3.3"

    @classmethod
    def default(cls):
        return cls()

    def resolve(self, scoped: dict) -> dict:
        out = []
        for seg in scoped.get("segments", []):
            text = seg.get("normalized_text") or seg["text"]
            low = text.lower()
            aspect = {
                "event_status": "current_or_unspecified",
                "frequency": None,
                "novelty": None,
                "historical": False,
            }

            if re.search(r"\b(?:sering|biasanya|kerap)\b", low):
                aspect["event_status"] = "habitual"
                aspect["frequency"] = "frequent"
            elif re.search(r"\b(?:kadang|sesekali)\b", low):
                aspect["event_status"] = "habitual"
                aspect["frequency"] = "occasional"

            if re.search(r"\bbukan\s+(?:yang\s+)?pertama\b", low):
                aspect["novelty"] = "repeated"
                if aspect["event_status"] == "current_or_unspecified":
                    aspect["event_status"] = "current_with_prior_experience"

            if re.search(r"\b(?:kali\s+pertama|pertama\s+kali)\b", low):
                aspect["novelty"] = "first_time"

            if re.search(r"^(?:awalnya|dulu|sebelumnya)\b|\bdulu\s+aku\b", low):
                aspect["historical"] = True
                if "lama-lama" not in low and "sekarang" not in low:
                    aspect["event_status"] = "historical"

            if seg.get("scope", {}).get("modality") == "hypothetical":
                aspect["event_status"] = "hypothetical"
            elif seg.get("scope", {}).get("modality") == "intent":
                aspect["event_status"] = "intended"
            elif "scenario_request" in seg.get("roles", []):
                aspect["event_status"] = "requested_scenario"

            item = dict(seg)
            item["aspect"] = aspect
            out.append(item)

        return {"version": self.VERSION, "segments": out, "diagnostics": []}
