"""Tests for the push subcommand."""
import json
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest
from prompt_eval.run import main


def _make_run(tmp_path, versions=("v1",), with_scores=True):
    run_dir = tmp_path / "prompt_eval_runs" / "prompts" / "summarizer" / "runs" / "run_001"
    (run_dir / "v1").mkdir(parents=True)
    dataset = [{"scenario": "s1", "prompt_inputs": {"text": "hi"}, "solution_criteria": "X"}]
    (run_dir / "dataset.json").write_text(json.dumps(dataset))
    meta = {"run_id": "run_001", "versions": list(versions), "test_model": "claude-haiku-4-5"}
    (run_dir / "metadata.json").write_text(json.dumps(meta))
    outputs = [{"case_index": 0, "output": "Hello", "tool_calls": []}]
    (run_dir / "v1" / "output.json").write_text(json.dumps(outputs))
    if with_scores:
        scores = {
            "version": "v1",
            "cases": [{"case_index": 0, "score": 8, "reasoning": "Good", "criteria_breakdown": {}}],
            "summary": {"average_score": 8.0, "pass_rate": 1.0, "total_cases": 1},
        }
        (run_dir / "v1" / "scores.json").write_text(json.dumps(scores))
    return run_dir


def _langfuse_patches():
    return [
        patch("prompt_eval.langfuse_push.get_client", return_value=MagicMock()),
        patch("prompt_eval.langfuse_push.push_dataset", return_value="summarizer-run_001"),
        patch("prompt_eval.langfuse_push.push_run_case"),
        patch("prompt_eval.langfuse_push.flush_or_warn", return_value=True),
    ]


def _set_langfuse_env(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    monkeypatch.setenv("LANGFUSE_HOST", "http://localhost")


class TestPushCommand:
    def test_exits_2_when_not_configured(self, tmp_path, monkeypatch):
        for k in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL", "LANGFUSE_HOST"):
            monkeypatch.delenv(k, raising=False)
        monkeypatch.setenv("PROMPT_EVAL_PROJECT_DIR", str(tmp_path))
        rc = main(["push", "--prompt", "summarizer", "--run-id", "run_001"])
        assert rc == 2

    def test_exits_2_when_run_not_found(self, tmp_path, monkeypatch):
        _set_langfuse_env(monkeypatch)
        monkeypatch.setenv("PROMPT_EVAL_PROJECT_DIR", str(tmp_path))
        rc = main(["push", "--prompt", "summarizer", "--run-id", "run_001"])
        assert rc == 2

    def test_exits_2_when_no_scored_versions(self, tmp_path, monkeypatch):
        _make_run(tmp_path, with_scores=False)
        _set_langfuse_env(monkeypatch)
        monkeypatch.setenv("PROMPT_EVAL_PROJECT_DIR", str(tmp_path))
        rc = main(["push", "--prompt", "summarizer", "--run-id", "run_001"])
        assert rc == 2

    def test_pushes_all_scored_versions_by_default(self, tmp_path, monkeypatch):
        _make_run(tmp_path)
        _set_langfuse_env(monkeypatch)
        monkeypatch.setenv("PROMPT_EVAL_PROJECT_DIR", str(tmp_path))
        with ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in _langfuse_patches()]
            mock_gc, mock_pd, mock_prc, mock_fw = mocks
            rc = main(["push", "--prompt", "summarizer", "--run-id", "run_001"])
        assert rc == 0
        mock_pd.assert_called_once()
        mock_prc.assert_called_once()
        mock_fw.assert_called_once()

    def test_pushes_specific_version_when_provided(self, tmp_path, monkeypatch):
        _make_run(tmp_path)
        _set_langfuse_env(monkeypatch)
        monkeypatch.setenv("PROMPT_EVAL_PROJECT_DIR", str(tmp_path))
        with ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in _langfuse_patches()]
            _, _, mock_prc, _ = mocks
            rc = main(["push", "--prompt", "summarizer", "--run-id", "run_001", "--version", "v1"])
        assert rc == 0
        call_kwargs = mock_prc.call_args[1]
        assert call_kwargs["version"] == "v1"
        assert call_kwargs["score"] == 8
        assert call_kwargs["output"] == "Hello"
        assert call_kwargs["model"] == "claude-haiku-4-5"

    def test_push_run_case_uses_prompt_inputs_as_rendered_prompt(self, tmp_path, monkeypatch):
        _make_run(tmp_path)
        _set_langfuse_env(monkeypatch)
        monkeypatch.setenv("PROMPT_EVAL_PROJECT_DIR", str(tmp_path))
        with ExitStack() as stack:
            mocks = [stack.enter_context(p) for p in _langfuse_patches()]
            _, _, mock_prc, _ = mocks
            main(["push", "--prompt", "summarizer", "--run-id", "run_001"])
        call_kwargs = mock_prc.call_args[1]
        assert call_kwargs["rendered_prompt"] == str({"text": "hi"})

    def test_exits_0_and_prints_success_message(self, tmp_path, monkeypatch, capsys):
        _make_run(tmp_path)
        _set_langfuse_env(monkeypatch)
        monkeypatch.setenv("PROMPT_EVAL_PROJECT_DIR", str(tmp_path))
        with ExitStack() as stack:
            for p in _langfuse_patches():
                stack.enter_context(p)
            rc = main(["push", "--prompt", "summarizer", "--run-id", "run_001"])
        assert rc == 0
        assert "Langfuse" in capsys.readouterr().out
