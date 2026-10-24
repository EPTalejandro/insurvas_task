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


def test_empty_youtube_key_skips_the_platform(monkeypatch):
    monkeypatch.setattr("app.cli.get_settings", lambda: Settings(_env_file=None))
    result = CliRunner().invoke(cli, ["collect"])
    assert result.exit_code == 0
    assert "YOUTUBE_API_KEY is empty" in result.output
