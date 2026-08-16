from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from src.runtime_config import RuntimeConfig
from src.service import ArlineService


@dataclass(slots=True)
class AblationOutcome:
    mode: str
    reasoning: str
    story: str
    post_validation: dict[str, Any]
    stats: dict[str, Any]
    diagnostic_score: float
    error: str | None = None

    @property
    def key(self) -> str:
        return f"{self.mode}__thinking_{self.reasoning}"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["key"] = self.key
        return data


class AblationRunner:
    """Run the same prompt through multiple context/reasoning conditions."""

    DEFAULT_CONDITIONS = (
        ("raw", "off"),
        ("raw", "on"),
        ("wcf", "off"),
        ("wcf", "on"),
        ("smart_hybrid", "off"),
        ("smart_hybrid", "on"),
    )

    def __init__(self, config: RuntimeConfig):
        self.config = config

    def run(
        self,
        prompt: str,
        *,
        conditions: Iterable[tuple[str, str]] | None = None,
        output_dir: str | Path | None = None,
    ) -> list[AblationOutcome]:
        results: list[AblationOutcome] = []
        base_out = Path(output_dir) if output_dir is not None else None

        for mode, reasoning in conditions or self.DEFAULT_CONDITIONS:
            cfg = deepcopy(self.config)
            cfg.writer.input_mode = mode
            cfg.generation.reasoning = reasoning
            try:
                service = ArlineService(cfg)
                generated = service.generate(prompt, mode=mode)
                report = (
                    generated.post_validation.to_dict()
                    if generated.post_validation is not None
                    else {"valid": True, "violations": [], "warnings": [], "metrics": {}}
                )
                outcome = AblationOutcome(
                    mode=mode,
                    reasoning=reasoning,
                    story=generated.story,
                    post_validation=report,
                    stats=generated.stats,
                    diagnostic_score=self._diagnostic_score(report),
                )

                if base_out is not None:
                    condition_dir = base_out / outcome.key
                    service.save_generation(generated, condition_dir)
            except Exception as exc:
                outcome = AblationOutcome(
                    mode=mode,
                    reasoning=reasoning,
                    story="",
                    post_validation={},
                    stats={},
                    diagnostic_score=0.0,
                    error=str(exc),
                )
            results.append(outcome)
        return results

    @staticmethod
    def _diagnostic_score(report: dict[str, Any]) -> float:
        """
        Development-only diagnostic score, not a literary quality score.

        It summarizes validator failures so ablations are easier to scan. The
        underlying metrics remain the source of truth.
        """
        violations = len(report.get("violations", []) or [])
        warnings = len(report.get("warnings", []) or [])
        metrics = report.get("metrics", {}) or {}
        repetition = int(metrics.get("repetition_pairs", 0) or 0)
        recitation = int(metrics.get("spec_recitations", 0) or 0)
        unsupported = int(metrics.get("unsupported_specificities", 0) or 0)
        score = 100.0
        score -= 18.0 * violations
        score -= 5.0 * warnings
        score -= 3.0 * repetition
        score -= 3.0 * recitation
        score -= 5.0 * unsupported
        return round(max(0.0, min(100.0, score)), 1)

    @staticmethod
    def markdown_table(results: list[AblationOutcome]) -> str:
        rows = [
            "| Context | Thinking | Diagnostic | Hard violations | Warnings | Tok/s |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for result in results:
            report = result.post_validation or {}
            stats = result.stats or {}
            if result.error:
                rows.append(
                    f"| `{result.mode}` | `{result.reasoning}` | error | — | — | — |"
                )
                continue
            tps = stats.get("tokens_per_second")
            tps_text = f"{float(tps):.1f}" if isinstance(tps, (int, float)) else "—"
            rows.append(
                "| `{}` | `{}` | {:.1f} | {} | {} | {} |".format(
                    result.mode,
                    result.reasoning,
                    result.diagnostic_score,
                    len(report.get("violations", []) or []),
                    len(report.get("warnings", []) or []),
                    tps_text,
                )
            )
        return "\n".join(rows)
