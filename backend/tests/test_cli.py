from typer.testing import CliRunner

from app.cli import cli
from app.config import Settings


def test_reset_db_without_yes_does_nothing():
    # The guard runs before any database work, so this never touches data/app.db.
    result = CliRunner().invoke(cli, ["reset-db"])
    assert result.exit_code == 1
    assert "--yes" in result.output


def test_unknown_platform_is_rejected_before_any_work():
    result = CliRunner().invoke(cli, ["discover", "--platform", "instagram"])
    assert result.exit_code == 1
    assert "not available yet" in result.output


def test_collect_without_any_keys_collects_nothing(monkeypatch):
    monkeypatch.setattr("app.cli.get_settings", lambda: Settings(_env_file=None))
    result = CliRunner().invoke(cli, ["collect"])
    assert result.exit_code == 0
    assert "No platform has keys" in result.output


def test_collecting_a_platform_without_keys_is_an_error(monkeypatch):
    monkeypatch.setattr("app.cli.get_settings", lambda: Settings(_env_file=None))
    for name in ("youtube", "instagram"):
        result = CliRunner().invoke(cli, ["collect", "--platform", name])
        assert result.exit_code == 1
        assert f"{name} has no keys" in result.output


def test_collecting_an_unknown_platform_is_an_error():
    result = CliRunner().invoke(cli, ["collect", "--platform", "tiktok"])
    assert result.exit_code == 1
    assert "not available" in result.output
