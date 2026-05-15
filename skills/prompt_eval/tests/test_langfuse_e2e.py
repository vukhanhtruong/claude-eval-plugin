"""End-to-end Langfuse round-trip test.

Requires real Langfuse credentials in environment:
  LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_HOST (or LANGFUSE_BASE_URL)

Run with: uv run pytest -m e2e
Excluded from default pytest run.
"""
import json
import pytest
from prompt_eval.run import main


@pytest.mark.e2e
def test_push_round_trip(tmp_path, monkeypatch):
    """Push a minimal run to Langfuse and verify no errors."""
    from prompt_eval import langfuse_push
    if not langfuse_push.is_configured():
        pytest.skip("Langfuse credentials not set")

    run_dir = tmp_path / "prompt_eval_runs" / "prompts" / "e2e_test" / "runs" / "run_001"
    (run_dir / "v1").mkdir(parents=True)

    dataset = [{"scenario": "basic", "prompt_inputs": {"text": "hello"}, "solution_criteria": "Says hi"}]
    (run_dir / "dataset.json").write_text(json.dumps(dataset))

    meta = {"run_id": "run_001", "versions": ["v1"], "test_model": "claude-haiku-4-5"}
    (run_dir / "metadata.json").write_text(json.dumps(meta))

    outputs = [{"case_index": 0, "output": "Hello there!", "tool_calls": []}]
    (run_dir / "v1" / "output.json").write_text(json.dumps(outputs))

    scores = {
        "version": "v1",
        "cases": [{"case_index": 0, "score": 9, "reasoning": "Good greeting", "criteria_breakdown": {}}],
        "summary": {"average_score": 9.0, "pass_rate": 1.0, "total_cases": 1},
    }
    (run_dir / "v1" / "scores.json").write_text(json.dumps(scores))

    monkeypatch.setenv("PROMPT_EVAL_PROJECT_DIR", str(tmp_path))

    rc = main(["push", "--prompt", "e2e_test", "--run-id", "run_001"])
    assert rc == 0
