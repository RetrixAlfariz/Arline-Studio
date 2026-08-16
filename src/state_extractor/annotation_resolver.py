from __future__ import annotations

import re


class AnnotationResolver:
    """Resolve HEAD[annotation] / HEAD(annotation) patterns into typed hints."""

    VERSION = "0.3.3"

    @classmethod
    def default(cls):
        return cls()

    def resolve(self, normalized_segments: dict) -> dict:
        segments = normalized_segments.get("segments", [])
        annotations = []
        seg_by_id = {s["id"]: s for s in segments}

        for seg in segments:
            if seg.get("structure_type") not in {"bracket_note", "parenthetical"}:
                continue

            text = seg.get("normalized_text") or seg["text"]
            context = seg.get("context_text", "")
            head = self._infer_head(context, text)
            hints = self._classify(text, head)
            annotations.append({
                "id": f"ann_{len(annotations)+1:04d}",
                "segment_id": seg["id"],
                "head": head,
                "text": text,
                "hints": hints,
                "confidence": 0.9 if hints else 0.55,
            })

        return {
            "version": self.VERSION,
            "annotations": annotations,
            "diagnostics": [],
        }

    def _infer_head(self, context: str, annotation: str) -> dict:
        low = context.lower()[-220:]
        own = annotation.lower()
        checks = [
            ("teman", "person.friend"),
            ("dada", "body.chest"),
            ("payudara", "body.chest"),
            ("rambut", "body.hair"),
            ("gamis", "garment.gamis"),
            ("khimar", "garment.khimar"),
            ("dress", "garment.dress"),
            ("apartemen", "location.apartment"),
            ("orang tua", "social.family_self"),
            ("keluarga", "social.family"),
        ]
        # A named noun inside an annotation can refine a generic parent,
        # e.g. pakaian perempuan(hitam, dressnya panjang 138cm, rayon).
        own_checks = [
            ("gamis", "garment.gamis"), ("khimar", "garment.khimar"),
            ("dress", "garment.dress"), ("bra", "garment.bra"),
            ("celana dalam", "garment.underwear"),
            ("wig", "item.wig"),
        ]
        for token, kind in own_checks:
            if re.search(rf"\b{re.escape(token)}(?:nya|ku|mu)?\b", own):
                return {"kind": kind, "text": annotation.strip()}

        # Nearest lexical head wins.
        best = None
        for token, kind in checks:
            pos = low.rfind(token)
            if pos >= 0 and (best is None or pos > best[0]):
                best = (pos, kind)
        if best:
            return {"kind": best[1], "text": context[-120:].strip()}
        return {"kind": "unknown", "text": context[-120:].strip()}

    def _classify(self, text: str, head: dict) -> list[dict]:
        low = text.lower()
        hints = []

        # Named person annotation: [cowok-fano]
        m = re.search(r"\b(?:cowok|laki-laki|pria)\s*[-:]\s*([a-z][\w'-]+)\b", low)
        if m:
            hints.append({"type": "person_identity", "name": m.group(1), "gender": "male"})

        # Physical chest annotation.
        cup = re.search(r"\b([a-h])\s*cup\b", low, re.I)
        if cup:
            hints.append({"type": "chest_cup", "value": cup.group(1).upper()})
        if "empuk" in low or "lembut" in low:
            hints.append({
                "type": "tissue_property",
                "target": "chest" if head.get("kind") == "body.chest" else head.get("kind"),
                "softness": "very_high" if ("sangat" in low or ("empuk" in low and "lembut" in low)) else "high",
                "compliance": "high",
            })

        # Garment annotation attributes.
        for color in ("hitam", "putih", "lavender", "merah", "biru", "navy", "pink", "ungu", "hijau", "kuning", "coklat", "magenta", "burgundy"):
            if re.search(rf"\b{color}\b", low):
                hints.append({"type": "color", "value": color})
                break
        for material in ("jersey", "rayon", "katun", "cotton", "satin", "silk", "sutra", "linen", "polyester"):
            if re.search(rf"\b{material}\b", low):
                hints.append({"type": "material", "value": material})
                break

        # Body-relative measurement.
        anchor_match = re.search(r"\b(?:sampai|sebatas)\s+(pinggang|bahu|lutut|mata\s+kaki|punggung)\b", low)
        if anchor_match:
            anchor = anchor_match.group(1).replace(" ", "_")
            hints.append({"type": "body_relative_length", "anchor": anchor})

        return hints
