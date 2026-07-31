from __future__ import annotations

from personalai.core.config import Config
from personalai.services.benchmark_service import benchmark_models, format_benchmark_report


class FakeClient:
    def chat(self, messages, model, on_token=None, images=None):
        if model == "bad":
            raise RuntimeError("missing model")
        return "hello " * 10


def test_benchmark_models_reports_success_and_failure():
    results = benchmark_models(Config(), FakeClient(), ["fast", "bad"])

    assert [result.model for result in results] == ["fast", "bad"]
    assert results[0].ok is True
    assert results[1].ok is False
    assert "missing model" in results[1].error


def test_format_benchmark_report_names_fastest_model():
    report = format_benchmark_report(benchmark_models(Config(), FakeClient(), ["a", "b"]))

    assert "Recommendation:" in report
