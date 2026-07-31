"""Tiny local model benchmark used by the Nexus System tab."""

from __future__ import annotations

import time
from dataclasses import dataclass

from personalai.core.config import Config

BENCHMARK_PROMPT = (
    "Reply in one short paragraph. Explain why a local assistant should use "
    "memory, knowledge search, and a small model for simple questions."
)


@dataclass(frozen=True)
class ModelBenchmark:
    model: str
    ok: bool
    seconds: float
    chars_per_second: float
    reply_preview: str = ""
    error: str = ""


def benchmark_models(config: Config, client, models: list[str] | None = None) -> list[ModelBenchmark]:
    selected = models or _default_models(config)
    results: list[ModelBenchmark] = []
    for model in selected:
        started = time.perf_counter()
        try:
            reply = client.chat(
                [
                    {"role": "system", "content": "You are benchmarking local inference."},
                    {"role": "user", "content": BENCHMARK_PROMPT},
                ],
                model,
            )
        except Exception as exc:  # noqa: BLE001 - benchmark reports failures instead of aborting
            elapsed = time.perf_counter() - started
            results.append(ModelBenchmark(model, False, elapsed, 0.0, error=str(exc)))
            continue
        elapsed = max(0.001, time.perf_counter() - started)
        preview = " ".join(reply.split())[:160]
        results.append(ModelBenchmark(model, True, elapsed, len(reply) / elapsed, preview))
    return results


def format_benchmark_report(results: list[ModelBenchmark]) -> str:
    if not results:
        return "No models selected."
    lines = []
    best = max((r for r in results if r.ok), key=lambda r: r.chars_per_second, default=None)
    for result in results:
        if result.ok:
            marker = " <- fastest" if best is result else ""
            lines.append(
                f"{result.model}: {result.seconds:.1f}s, "
                f"{result.chars_per_second:.1f} chars/s{marker}"
            )
        else:
            lines.append(f"{result.model}: failed after {result.seconds:.1f}s - {result.error}")
    if best is not None:
        lines.append("")
        lines.append(f"Recommendation: keep {best.model} for everyday replies if it feels coherent.")
    return "\n".join(lines)


def _default_models(config: Config) -> list[str]:
    models = [
        config.fast_model,
        config.model_for("general"),
        config.deep_model,
        config.embedding_model,
    ]
    return [model for model in dict.fromkeys(models) if model]
