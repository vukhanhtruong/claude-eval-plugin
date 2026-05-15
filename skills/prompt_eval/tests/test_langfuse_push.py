"""Unit tests for langfuse_push module."""
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest


def _clear_langfuse_env(monkeypatch):
    for k in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL", "LANGFUSE_HOST"):
        monkeypatch.delenv(k, raising=False)


class TestIsConfigured:
    def test_returns_false_when_all_missing(self, monkeypatch):
        _clear_langfuse_env(monkeypatch)
        from prompt_eval import langfuse_push
        assert langfuse_push.is_configured() is False

    def test_returns_false_missing_secret_key(self, monkeypatch):
        _clear_langfuse_env(monkeypatch)
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
        monkeypatch.setenv("LANGFUSE_HOST", "http://localhost")
        from prompt_eval import langfuse_push
        assert langfuse_push.is_configured() is False

    def test_returns_false_missing_host_and_base_url(self, monkeypatch):
        _clear_langfuse_env(monkeypatch)
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
        from prompt_eval import langfuse_push
        assert langfuse_push.is_configured() is False

    def test_returns_true_with_host(self, monkeypatch):
        _clear_langfuse_env(monkeypatch)
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
        monkeypatch.setenv("LANGFUSE_HOST", "http://localhost")
        from prompt_eval import langfuse_push
        assert langfuse_push.is_configured() is True

    def test_returns_true_with_base_url(self, monkeypatch):
        _clear_langfuse_env(monkeypatch)
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
        monkeypatch.setenv("LANGFUSE_BASE_URL", "http://localhost")
        from prompt_eval import langfuse_push
        assert langfuse_push.is_configured() is True


class TestMissingEnvVars:
    def test_returns_all_when_none_set(self, monkeypatch):
        _clear_langfuse_env(monkeypatch)
        from prompt_eval import langfuse_push
        missing = langfuse_push.missing_env_vars()
        assert "LANGFUSE_PUBLIC_KEY" in missing
        assert "LANGFUSE_SECRET_KEY" in missing
        assert "LANGFUSE_HOST or LANGFUSE_BASE_URL" in missing

    def test_returns_empty_when_all_set(self, monkeypatch):
        _clear_langfuse_env(monkeypatch)
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
        monkeypatch.setenv("LANGFUSE_HOST", "http://localhost")
        from prompt_eval import langfuse_push
        assert langfuse_push.missing_env_vars() == []

    def test_returns_only_missing_vars(self, monkeypatch):
        _clear_langfuse_env(monkeypatch)
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
        monkeypatch.setenv("LANGFUSE_HOST", "http://localhost")
        from prompt_eval import langfuse_push
        missing = langfuse_push.missing_env_vars()
        assert "LANGFUSE_SECRET_KEY" in missing
        assert "LANGFUSE_PUBLIC_KEY" not in missing


class TestGetClient:
    def test_returns_none_when_not_configured(self, monkeypatch):
        _clear_langfuse_env(monkeypatch)
        from prompt_eval import langfuse_push
        assert langfuse_push.get_client() is None

    def test_returns_langfuse_when_configured(self, monkeypatch):
        _clear_langfuse_env(monkeypatch)
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
        monkeypatch.setenv("LANGFUSE_HOST", "http://localhost")
        from prompt_eval import langfuse_push
        mock_instance = MagicMock()
        with patch("prompt_eval.langfuse_push.Langfuse", return_value=mock_instance):
            client = langfuse_push.get_client()
        assert client is mock_instance


class TestPushDataset:
    def _dataset(self):
        return [{"scenario": "s1", "prompt_inputs": {"text": "hi"}, "solution_criteria": "X"}]

    def test_creates_dataset_when_not_exists(self):
        from prompt_eval import langfuse_push
        client = MagicMock()
        client.get_dataset.side_effect = Exception("not found")
        name = langfuse_push.push_dataset(
            client=client, prompt_name="summarizer", run_id="run_001",
            dataset=self._dataset(), task_description="task", inputs_spec={},
        )
        assert name == "summarizer-run_001"
        client.create_dataset.assert_called_once()
        client.create_dataset_item.assert_called_once()

    def test_upserts_when_dataset_exists(self):
        from prompt_eval import langfuse_push
        client = MagicMock()
        client.get_dataset.return_value = MagicMock()
        langfuse_push.push_dataset(
            client=client, prompt_name="summarizer", run_id="run_001",
            dataset=self._dataset(), task_description="", inputs_spec={},
        )
        client.create_dataset.assert_not_called()
        client.create_dataset_item.assert_called_once()

    def test_uses_deterministic_item_ids(self):
        from prompt_eval import langfuse_push
        client = MagicMock()
        client.get_dataset.side_effect = Exception("not found")
        langfuse_push.push_dataset(
            client=client, prompt_name="p", run_id="r", dataset=self._dataset(),
            task_description="", inputs_spec={},
        )
        call_kwargs = client.create_dataset_item.call_args[1]
        assert call_kwargs["id"] == "p-r-item-0"


class TestPushRunCase:
    def _make_client(self):
        client = MagicMock()
        span = MagicMock()
        span.trace_id = "trace-123"
        span.id = "obs-456"
        client.start_as_current_observation.return_value.__enter__ = lambda s, *a: span
        client.start_as_current_observation.return_value.__exit__ = MagicMock(return_value=False)
        mock_item = MagicMock()
        mock_item.id = "summarizer-run_001-item-0"
        mock_dataset = MagicMock()
        mock_dataset.items = [mock_item]
        client.get_dataset.return_value = mock_dataset
        return client

    def test_creates_span_and_score(self):
        from prompt_eval import langfuse_push
        client = self._make_client()
        langfuse_push.push_run_case(
            client=client, dataset_name="summarizer-run_001", item_index=0,
            run_id="run_001", version="v1", prompt_name="summarizer",
            rendered_prompt='{"text": "hi"}', output="Hello", score=8,
            reasoning="Good", model="claude-haiku-4-5", latency_ms=100,
        )
        client.start_as_current_observation.assert_called_once()
        client.api.dataset_run_items.create.assert_called_once()
        client.create_score.assert_called_once_with(
            name="Task Quality", value=0.8, trace_id="trace-123",
            comment="Good", data_type="NUMERIC",
        )

    def test_normalizes_score_to_0_1(self):
        from prompt_eval import langfuse_push
        client = self._make_client()
        langfuse_push.push_run_case(
            client=client, dataset_name="summarizer-run_001", item_index=0,
            run_id="run_001", version="v1", prompt_name="summarizer",
            rendered_prompt="x", output="y", score=10, reasoning="r",
            model="m", latency_ms=0,
        )
        call_kwargs = client.create_score.call_args[1]
        assert call_kwargs["value"] == 1.0


class TestFlushOrWarn:
    def test_returns_true_on_success(self):
        from prompt_eval import langfuse_push
        client = MagicMock()
        assert langfuse_push.flush_or_warn(client) is True
        client.flush.assert_called_once()

    def test_returns_false_on_exception(self, capsys):
        from prompt_eval import langfuse_push
        client = MagicMock()
        client.flush.side_effect = Exception("network error")
        assert langfuse_push.flush_or_warn(client) is False
        assert "flush failed" in capsys.readouterr().out.lower()
