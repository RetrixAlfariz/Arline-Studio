from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class NarrativeBrief:
    version: str
    language: str
    text: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "language": self.language,
            "text": self.text,
            "metadata": self.metadata,
        }


class NarrativeBriefBuilder:
    VERSION = "0.1"

    @classmethod
    def default(cls):
        return cls()

    def build(self, writer_context, narrative_runtime, *, workspace_context=None) -> NarrativeBrief:
        profile = narrative_runtime.language
        if profile.language == "id-ID":
            text = self._indonesian(writer_context, narrative_runtime, workspace_context)
        else:
            text = self._english(writer_context, narrative_runtime, workspace_context)
        return NarrativeBrief(
            version=self.VERSION,
            language=profile.language,
            text=text,
            metadata={
                "register": profile.register,
                "narrator_pronoun": profile.narrator_pronoun,
                "description_lens": narrative_runtime.description_lens.to_dict(),
                "scene_energy": narrative_runtime.scene_energy.to_dict(),
                "paragraph_functions": list(narrative_runtime.paragraph_functions),
            },
        )

    def _indonesian(self, ctx, narrative, workspace_context) -> str:
        lang = narrative.language
        goal = narrative.scene_goal
        beat = narrative.beat_state
        lens = narrative.description_lens.to_dict()
        dominant = sorted(lens, key=lens.get, reverse=True)[:3]
        lines = [
            "@ARLINE-NARRATIVE-BRIEF 0.1",
            "",
            "[BAHASA DAN SUARA]",
            f"bahasa: Bahasa Indonesia",
            f"ragam narasi: {lang.register.replace('_', ' ')}",
            f"kata ganti narator: {lang.narrator_pronoun}",
            "pertahankan kedekatan dengan cara pengguna bertutur, tetapi rapikan secukupnya agar nyaman dibaca",
            "hindari bahasa akademik, administratif, dan gaya terjemahan bahasa Inggris",
            "jangan berganti ke 'saya' bila suara narator memakai 'aku'",
            "",
            "[ARAH ADEGAN]",
            f"fase: {goal.phase}",
            f"tujuan: {goal.objective}",
            f"beat saat ini: {beat.current_beat}",
            f"ritme: {narrative.scene_energy.pacing}; energi: {narrative.scene_energy.level}",
            f"lensa deskripsi utama: {', '.join(dominant)}",
            "fungsi paragraf yang disarankan: " + " → ".join(narrative.paragraph_functions),
            "",
            "[ATURAN REALISASI]",
            "gunakan fakta sebagai latar pengetahuan, bukan daftar yang harus diulang",
            "gunakan projection sebagai gambaran relatif; jangan naikkan menjadi ukuran pasti",
            "tunjukkan akibat fisik/sosial secara natural daripada menjelaskan label analitisnya",
            "setiap paragraf harus memberi tindakan, pengamatan, interaksi, perubahan state, atau atmosfer baru",
        ]
        if workspace_context and workspace_context.scope:
            scope = workspace_context.scope
            lines.extend([
                "",
                "[LINGKUP KARYA]",
                f"project: {scope.get('project') or '-'}",
                f"world: {scope.get('world') or '-'}",
                f"branch: {scope.get('branch') or '-'}",
            ])
        return "\n".join(lines).rstrip() + "\n"

    def _english(self, ctx, narrative, workspace_context) -> str:
        goal = narrative.scene_goal
        beat = narrative.beat_state
        return (
            "@ARLINE-NARRATIVE-BRIEF 0.1\n\n"
            "[LANGUAGE AND VOICE]\n"
            f"language: English\nregister: {narrative.language.register}\n"
            f"narrator pronoun: {narrative.language.narrator_pronoun}\n"
            "preserve the user's contemporary voice; avoid translation-like phrasing\n\n"
            "[SCENE DIRECTION]\n"
            f"phase: {goal.phase}\nobjective: {goal.objective}\n"
            f"current beat: {beat.current_beat}\n"
            f"pacing: {narrative.scene_energy.pacing}\n"
        )
