from __future__ import annotations

import re

from src.narrative.rails import CharacterRailParser

from .arline_service import ArlineService


V121_RAIL_BLOCK_OPEN = "<CHARACTER_RAILS>"
V121_RAIL_BLOCK_CLOSE = "</CHARACTER_RAILS>"
_INSTALLED = False

_ORIGINAL_ANALYZE = ArlineService.analyze
_ORIGINAL_COMPOSE = ArlineService.compose_model_input


def _strip_persisted_rail_lines(text: str | None) -> str | None:
    if not text:
        return text
    rail_line = re.compile(r"^\s*(?:(?:USER|User|user)\s*:\s*)?/(?:mono|dia|ambience|intimacy)\b", re.I)
    kept = [line for line in str(text).splitlines() if not rail_line.match(line)]
    return "\n".join(kept).strip()


def _analyze_v121(self: ArlineService, prompt: str, *, surface_history=None, workspace_context=None):
    compilation = CharacterRailParser.parse(prompt)
    if compilation.active and workspace_context is not None:
        workspace_context.scope["character_rails"] = {
            "active": True,
            "count": len(compilation.rails),
            "kinds": [rail.kind.value for rail in compilation.rails],
            "generation_only": True,
            "canon_commit": False,
        }
    return _ORIGINAL_ANALYZE(
        self,
        compilation.cleaned_prompt if compilation.active else prompt,
        surface_history=surface_history,
        workspace_context=workspace_context,
    )


def _compose_v121(
    self: ArlineService,
    prompt: str,
    bundle,
    mode: str | None = None,
    *,
    session_context: str | None = None,
    beat_context: str | None = None,
) -> str:
    compilation = CharacterRailParser.parse(prompt)
    clean_prompt = compilation.cleaned_prompt if compilation.active else prompt
    clean_session = _strip_persisted_rail_lines(session_context)
    model_input = _ORIGINAL_COMPOSE(
        self,
        clean_prompt,
        bundle,
        mode,
        session_context=clean_session,
        beat_context=beat_context,
    )
    if not compilation.active or not compilation.rendered_text:
        return model_input

    block = (
        f"{V121_RAIL_BLOCK_OPEN}\n"
        f"{compilation.rendered_text.rstrip()}\n"
        f"{V121_RAIL_BLOCK_CLOSE}\n\n"
    )
    marker = "<REQUEST>"
    position = model_input.find(marker)
    if position >= 0:
        return model_input[:position] + block + model_input[position:]
    return block + model_input


def install_v121_service() -> None:
    """Keep Character Rails writer-only without mutating the v1.2.0 service API."""
    global _INSTALLED
    if _INSTALLED:
        return
    ArlineService.analyze = _analyze_v121
    ArlineService.compose_model_input = _compose_v121
    _INSTALLED = True
