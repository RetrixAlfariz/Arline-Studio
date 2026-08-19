from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from src.context_compiler import AIFCompiler, VALID_PROFILES
from src.eval import AblationRunner
from src.runtime_config import (
    DEFAULT_CONFIG_PATH,
    RuntimeConfig,
    VALID_INPUT_MODES,
    VALID_REASONING,
    VALID_PROJECTION_MODES,
)
from src.service import ArlineService
from src.version import __version__


def dump(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            f"Arline Studio v{__version__} — local-first narrative workspace, memory, "
            "continuity, and LM Studio writer"
        )
    )
    parser.add_argument("input", nargs="?", type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)

    parser.add_argument("--ui", action="store_true")
    parser.add_argument("--list-models", action="store_true")
    parser.add_argument("--check-server", action="store_true")
    parser.add_argument("--reload-model", action="store_true")

    parser.add_argument("--model")
    parser.add_argument("--gpu-ratio", type=float)
    parser.add_argument("--context-length", type=int)
    parser.add_argument(
        "--reasoning",
        choices=sorted(VALID_REASONING),
        help="Native LM Studio reasoning mode; actual allowed values depend on the selected model",
    )
    parser.add_argument("--visible-output-tokens", type=int)
    parser.add_argument("--reasoning-reserve-tokens", type=int)
    parser.add_argument("--input-mode", choices=sorted(VALID_INPUT_MODES))
    parser.add_argument(
        "--projection-mode",
        choices=sorted(VALID_PROJECTION_MODES),
        help="Bounded writer visualization: off/conservative/balanced/vivid",
    )

    parser.add_argument("-o", "--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--write", action="store_true")
    parser.add_argument(
        "--ablation",
        action="store_true",
        help="Run the default Raw/WCF/Smart Hybrid × Thinking ON/OFF ablation",
    )
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--all-aif", action="store_true")
    parser.add_argument("--history", type=Path)
    return parser


def load_surface_history(path: Path | None):
    if path is None:
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.ui:
        from src.interface.web import launch_ui

        launch_ui(args.config)
        return 0

    try:
        cfg = RuntimeConfig.load(args.config)
    except Exception as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    if args.model:
        cfg.lmstudio.model = args.model
    if args.gpu_ratio is not None:
        if not 0.0 <= args.gpu_ratio <= 1.0:
            print("--gpu-ratio must be between 0.0 and 1.0", file=sys.stderr)
            return 2
        cfg.model_load.gpu_ratio = args.gpu_ratio
    if args.context_length is not None:
        if args.context_length <= 0:
            print("--context-length must be > 0", file=sys.stderr)
            return 2
        cfg.model_load.context_length = args.context_length
    if args.reasoning:
        cfg.generation.reasoning = args.reasoning
    if args.input_mode:
        cfg.writer.input_mode = args.input_mode
    if args.projection_mode:
        cfg.projection.mode = args.projection_mode
    if args.visible_output_tokens is not None:
        if args.visible_output_tokens <= 0:
            print("--visible-output-tokens must be > 0", file=sys.stderr)
            return 2
        cfg.generation.visible_output_tokens = args.visible_output_tokens
    if args.reasoning_reserve_tokens is not None:
        if args.reasoning_reserve_tokens < 0:
            print("--reasoning-reserve-tokens must be >= 0", file=sys.stderr)
            return 2
        cfg.generation.reasoning_reserve_tokens = args.reasoning_reserve_tokens

    service = ArlineService(cfg)

    if args.list_models:
        try:
            models = service.list_models()
        except Exception as exc:
            print(f"LM Studio error: {exc}", file=sys.stderr)
            return 3
        if not models:
            print("LM Studio is reachable, but no LLM models were returned.")
            return 0
        for model in models:
            marker = " [loaded]" if model.get("loaded_instances") else ""
            max_ctx = model.get("max_context_length")
            ctx = f" max_ctx={max_ctx}" if max_ctx else ""
            reasoning_cfg = (model.get("capabilities") or {}).get("reasoning") or model.get("reasoning") or {}
            allowed = reasoning_cfg.get("allowed_options") or []
            reasoning = f" reasoning={','.join(allowed)}" if allowed else " reasoning=none"
            print(f"- {model.get('key')}{marker}{ctx}{reasoning}")
        return 0

    if args.check_server:
        try:
            print(
                json.dumps(
                    service.client().check_server(),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        except Exception as exc:
            print(f"LM Studio error: {exc}", file=sys.stderr)
            return 3

    if args.reload_model:
        try:
            print(
                json.dumps(
                    service.reload_model(),
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        except Exception as exc:
            print(f"Model reload error: {exc}", file=sys.stderr)
            return 4

    if args.input is None:
        parser.error(
            "input is required unless using --ui, --list-models, "
            "--check-server, or --reload-model"
        )

    try:
        text = args.input.read_text(encoding="utf-8")
        history = load_surface_history(args.history)
    except Exception as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 2

    try:
        if args.ablation:
            results = AblationRunner(cfg).run(
                text,
                output_dir=args.output_dir / "ablation",
            )
            print(AblationRunner.markdown_table(results))
            dump(
                args.output_dir / "ablation_summary.json",
                [x.to_dict() for x in results],
            )
            return 0

        if args.write:
            generation = service.generate(
                text,
                mode=cfg.writer.input_mode,
                surface_history=history,
            )
            out = service.save_generation(generation, args.output_dir)
            bundle = generation.analysis
            print(f"Story saved to {out / 'story.txt'}")
        else:
            bundle = service.analyze(text, surface_history=history)
            out = args.output_dir
            out.mkdir(parents=True, exist_ok=True)
            result = bundle.pipeline_result

            dump(out / "extracted_state.json", result.extracted_state)
            dump(out / "events.json", result.events)
            dump(out / "analysis.json", result.analysis)
            dump(out / "semantic_core.json", bundle.semantic_core.to_dict())
            dump(out / "world_runtime.json", bundle.world_runtime)
            dump(out / "narrative_runtime.json", bundle.narrative_runtime.to_dict())
            dump(out / "writer_context.json", bundle.writer_context.to_dict())
            dump(out / "projections.json", [x.to_dict() for x in bundle.writer_context.projections])
            dump(out / "context.wcf", bundle.rendered_context.text)
            dump(out / "aif_core.txt", bundle.aif_core)
            dump(out / "wcf_validation.json", bundle.wcf_validation.to_dict())

            if args.debug:
                for name, payload in result.debug.items():
                    dump(out / "debug" / f"{name}.json", payload)

            if args.all_aif:
                compiler = AIFCompiler()
                for profile in sorted(VALID_PROFILES):
                    packet = compiler.compile(
                        result.extracted_state,
                        result.events,
                        result.analysis,
                        profile=profile,
                    )
                    dump(out / "aif" / f"{profile}.aif", packet.text)

        if args.summary:
            print(
                json.dumps(
                    {
                        "system_version": bundle.pipeline_result.extracted_state.get(
                            "system_version"
                        ),
                        "semantic_core_version": bundle.semantic_core.version,
                        "world_runtime_version": bundle.world_runtime.get("version"),
                        "wcf_version": bundle.rendered_context.version,
                        "wcf_valid": bundle.wcf_validation.valid,
                        "wcf_tokens_est": bundle.rendered_context.metadata.get(
                            "estimated_tokens"
                        ),
                        "wcf_budget": bundle.rendered_context.metadata.get(
                            "budget_tokens"
                        ),
                        "facts": len(bundle.semantic_core.facts),
                        "transitions": len(bundle.semantic_core.transitions),
                        "unknowns": len(bundle.writer_context.unknown),
                        "projections": len(bundle.writer_context.projections),
                        "projection_mode": cfg.projection.mode,
                        "input_mode": cfg.writer.input_mode,
                        "reasoning": cfg.generation.reasoning,
                        "visible_output_tokens": cfg.generation.visible_output_tokens,
                        "reasoning_reserve_tokens": cfg.generation.reasoning_reserve_tokens,
                        "api_max_output_tokens": cfg.generation.api_max_output_tokens,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        return 0
    except Exception as exc:
        print(f"Arline error: {exc}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
