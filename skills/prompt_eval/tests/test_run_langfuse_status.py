"""Tests for the langfuse-status subcommand."""
import pytest
from prompt_eval.run import main


def _clear_env(monkeypatch):
    for k in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL", "LANGFUSE_HOST"):
        monkeypatch.delenv(k, raising=False)


class TestLangfuseStatus:
    def test_exits_0_when_fully_configured(self, monkeypatch, capsys):
        _clear_env(monkeypatch)
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
        monkeypatch.setenv("LANGFUSE_HOST", "http://localhost")
        rc = main(["langfuse-status"])
        assert rc == 0
        assert "configured" in capsys.readouterr().out

    def test_exits_1_when_all_missing(self, monkeypatch):
        _clear_env(monkeypatch)
        rc = main(["langfuse-status"])
        assert rc == 1

    def test_exits_1_when_host_missing(self, monkeypatch):
        _clear_env(monkeypatch)
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
        rc = main(["langfuse-status"])
        assert rc == 1

    def test_prints_missing_vars_to_stderr_when_not_configured(self, monkeypatch, capsys):
        _clear_env(monkeypatch)
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
        rc = main(["langfuse-status"])
        assert rc == 1
        assert "LANGFUSE_SECRET_KEY" in capsys.readouterr().err

    def test_works_with_base_url_instead_of_host(self, monkeypatch, capsys):
        _clear_env(monkeypatch)
        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
        monkeypatch.setenv("LANGFUSE_BASE_URL", "http://localhost")
        rc = main(["langfuse-status"])
        assert rc == 0
