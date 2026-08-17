from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import re
import shlex
from typing import Any


class RailKind(StrEnum):
    MONOLOGUE = "monologue"
    DIALOGUE = "dialogue"
    AMBIENCE = "ambience"
    INTIMACY = "intimacy"


class ExpressionChannel(StrEnum):
    INTERNAL = "internal"
    SPEECH = "speech"
    VOCALIZATION = "vocalization"
    ACTION = "action"
    SILENCE = "silence"
    AMBIENCE = "ambience"


class RailPacing(StrEnum):
    AUTO = "auto"
    IMMEDIATE = "immediate"
    FAST = "fast"
    NATURAL = "natural"
    SLOW = "slow"
    LINGERING = "lingering"


class RailIntensity(StrEnum):
    AUTO = "auto"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(slots=True)
class CharacterRail:
    index: int
    kind: RailKind
    participants: list[str]
    seed: str
    channel: ExpressionChannel | None = None
    delivery: str | None = None
    pacing: RailPacing = RailPacing.AUTO
    intensity: RailIntensity = RailIntensity.AUTO
    intensity_curve: str = "auto"
    length: str = "auto"
    termination: str = "natural_resolution"
    target: str | None = None
    literal: bool = False
    mode: str | None = None
    modifiers: dict[str, Any] = field(default_factory=dict)
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "kind": self.kind.value,
            "participants": self.participants,
            "seed": self.seed,
            "channel": self.channel.value if self.channel else None,
            "delivery": self.delivery,
            "pacing": self.pacing.value,
            "intensity": self.intensity.value,
            "intensity_curve": self.intensity_curve,
            "length": self.length,
            "termination": self.termination,
            "target": self.target,
            "literal": self.literal,
            "mode": self.mode,
            "modifiers": self.modifiers,
            "source": self.source,
        }


@dataclass(slots=True)
class RailCompilation:
    cleaned_prompt: str
    evidence_prompt: str
    rails: list[CharacterRail]
    warnings: list[str] = field(default_factory=list)
    rendered_text: str = ""

    @property
    def active(self) -> bool:
        return bool(self.rails)

    def to_dict(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "cleaned_prompt": self.cleaned_prompt,
            "evidence_prompt": self.evidence_prompt,
            "rails": [rail.to_dict() for rail in self.rails],
            "warnings": self.warnings,
            "rendered_text": self.rendered_text,
        }


class CharacterRailParser:
    """Compile generation-only slash rails without promoting them to story truth."""

    COMMAND = re.compile(r"^\s*/(mono|dia|ambience|intimacy)\b(.*)$", re.I)
    MENTION = re.compile(r"@([\w.\-]+)", re.UNICODE)
    PACING_ORDER = tuple(item.value for item in RailPacing)
    INTENSITY_ORDER = tuple(item.value for item in RailIntensity)
    DELIVERIES = (
        "normal", "whisper", "murmur", "mutter", "shout", "breathy",
        "broken", "involuntary", "soft", "quiet", "restrained",
    )
    LENGTHS = ("short", "medium", "long", "auto")
    CURVES = {"auto", "flat", "rising", "falling", "wave", "spike"}

    @classmethod
    def parse(cls, prompt: str) -> RailCompilation:
        rails: list[CharacterRail] = []
        kept: list[str] = []
        warnings: list[str] = []
        for line in prompt.splitlines():
            match = cls.COMMAND.match(line)
            if not match:
                kept.append(line)
                continue
            rail, warning = cls._parse_line(
                match.group(1).lower(), match.group(2).strip(), len(rails) + 1, line.strip()
            )
            if rail is not None:
                rails.append(rail)
            if warning:
                warnings.append(warning)

        evidence_prompt = "\n".join(kept).strip()
        cleaned = evidence_prompt
        if rails and not cleaned:
            cleaned = "Write the requested scene according to the active Character Rails."
        compiled = RailCompilation(
            cleaned_prompt=cleaned or prompt.strip(), evidence_prompt=evidence_prompt or (prompt.strip() if not rails else ""),
            rails=rails, warnings=warnings,
        )
        compiled.rendered_text = cls.render(compiled)
        return compiled

    @classmethod
    def _parse_line(
        cls, command: str, rest: str, index: int, source: str
    ) -> tuple[CharacterRail | None, str | None]:
        try:
            tokens = shlex.split(rest, posix=True)
        except ValueError as exc:
            return None, f"Rail {index} could not be parsed: {exc}"

        kind = {
            "mono": RailKind.MONOLOGUE,
            "dia": RailKind.DIALOGUE,
            "ambience": RailKind.AMBIENCE,
            "intimacy": RailKind.INTIMACY,
        }[command]
        participants: list[str] = []
        seed_parts: list[str] = []
        options: dict[str, str] = {}
        flags: list[str] = []

        for token in tokens:
            if token.startswith("@"):
                for mention in cls.MENTION.findall(token):
                    if mention not in participants:
                        participants.append(mention)
                continue
            if "=" in token:
                key, value = token.split("=", 1)
                key = key.strip().lower()
                if key in {"until", "to", "curve", "pacing", "intensity", "length", "mode", "delivery", "channel"}:
                    options[key] = value.strip()
                    continue
            low = token.lower()
            if low in set(cls.PACING_ORDER) | set(cls.INTENSITY_ORDER) | set(cls.DELIVERIES) | set(cls.LENGTHS) | {
                "internal", "spoken", "speech", "solo", "literal"
            }:
                flags.append(low)
                continue
            seed_parts.append(token)

        def first_flag(choices: tuple[str, ...], default: str) -> str:
            return next((flag for flag in flags if flag in choices), default)

        seed = " ".join(seed_parts).strip()
        pacing_value = (options.get("pacing") or first_flag(cls.PACING_ORDER, "auto")).lower()
        intensity_value = (options.get("intensity") or first_flag(cls.INTENSITY_ORDER, "auto")).lower()
        length = (options.get("length") or first_flag(cls.LENGTHS, "auto")).lower()
        curve = (options.get("curve") or "auto").lower()
        if curve not in cls.CURVES:
            curve = "auto"

        channel: ExpressionChannel | None = None
        delivery = options.get("delivery")
        explicit_channel = (options.get("channel") or "").lower()
        if kind == RailKind.MONOLOGUE:
            channel = ExpressionChannel.INTERNAL
            if explicit_channel in {"speech", "spoken"} or "spoken" in flags or "speech" in flags:
                channel = ExpressionChannel.SPEECH
            if explicit_channel == "internal" or "internal" in flags:
                channel = ExpressionChannel.INTERNAL
            if delivery is None:
                delivery = first_flag(cls.DELIVERIES, "") or None
            if delivery and channel != ExpressionChannel.INTERNAL:
                channel = ExpressionChannel.SPEECH
            elif delivery and "internal" not in flags and explicit_channel != "internal":
                channel = ExpressionChannel.SPEECH
        elif kind == RailKind.AMBIENCE:
            channel = ExpressionChannel.AMBIENCE

        target = options.get("to")
        if target:
            target_match = cls.MENTION.search(target)
            target = target_match.group(1) if target_match else target.lstrip("@")

        mode = options.get("mode")
        if kind == RailKind.INTIMACY and ("solo" in flags or len(participants) == 1):
            mode = "solo"
        elif kind == RailKind.INTIMACY and mode is None:
            mode = "interaction"

        warning: str | None = None
        if kind == RailKind.MONOLOGUE and not participants:
            warning = f"Rail {index} has no @character; active POV will be used."
        if kind == RailKind.DIALOGUE and len(participants) < 2:
            warning = f"Rail {index} dialogue has fewer than two explicit participants; active scene participants may fill the gap."

        try:
            pacing = RailPacing(pacing_value)
        except ValueError:
            pacing = RailPacing.AUTO
        try:
            intensity = RailIntensity(intensity_value)
        except ValueError:
            intensity = RailIntensity.AUTO

        return CharacterRail(
            index=index,
            kind=kind,
            participants=participants,
            seed=seed,
            channel=channel,
            delivery=delivery,
            pacing=pacing,
            intensity=intensity,
            intensity_curve=curve,
            length=length if length in cls.LENGTHS else "auto",
            termination=options.get("until") or "natural_resolution",
            target=target,
            literal="literal" in flags,
            mode=mode,
            modifiers={k: v for k, v in options.items() if k not in {"until", "to"}},
            source=source,
        ), warning

    @classmethod
    def render(cls, compilation: RailCompilation) -> str:
        if not compilation.rails:
            return ""
        lines = [
            "@ARLINE-CHARACTER-RAILS 1.0",
            "scope: generation_only",
            "canon_commit: forbidden",
            "Interpret every seed as intent/topic, not literal dialogue, unless literal=true.",
            "Adapt expression to canonical character personality, voice, current state, relationships, knowledge, POV, and scene context.",
            "Pacing controls meaningful intermediate state transitions and pauses, not filler word count.",
            "Dialogue is beat-driven: speaker order is adaptive; consecutive utterances, interruption, action, silence, vocalization, and POV-bound internal thought are allowed when natural.",
            "Never let a private/internal beat become knowledge for another character merely because the writer can see it.",
        ]
        for rail in compilation.rails:
            lines.extend(["", f"[RAIL {rail.index}: {rail.kind.value.upper()}]"])
            lines.append("participants: " + (", ".join("@" + x for x in rail.participants) if rail.participants else "active_scene"))
            if rail.channel:
                lines.append(f"channel: {rail.channel.value}")
            if rail.delivery:
                lines.append(f"delivery: {rail.delivery}")
            if rail.target:
                lines.append(f"target: @{rail.target}")
            if rail.mode:
                lines.append(f"mode: {rail.mode}")
            lines.append(f"pacing: {rail.pacing.value}")
            lines.append(f"intensity: {rail.intensity.value}")
            lines.append(f"intensity_curve: {rail.intensity_curve}")
            lines.append(f"length: {rail.length}")
            lines.append(f"termination: {rail.termination}")
            lines.append(f"literal: {'true' if rail.literal else 'false'}")
            if rail.seed:
                lines.append(f"seed: {rail.seed}")
            if rail.kind == RailKind.MONOLOGUE and rail.channel == ExpressionChannel.INTERNAL:
                lines.append("privacy: internal; only active POV/authorized internal lens may surface it")
            if rail.kind == RailKind.DIALOGUE:
                lines.append("interaction: resolve by character dynamics, not alternating-turn quotas")
            if rail.kind == RailKind.INTIMACY:
                lines.append("interaction: use the shared character-aware beat/pacing system and preserve narrative aftermath")
        if compilation.warnings:
            lines += ["", "[RAIL WARNINGS]"] + ["- " + item for item in compilation.warnings]
        return "\n".join(lines).rstrip() + "\n"
