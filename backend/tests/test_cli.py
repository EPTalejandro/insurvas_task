from typer.testing import CliRunner

from app.cli import cli


def test_reset_db_without_yes_does_nothing():
    # The guard runs before any database work, so this never touches data/app.db.
    result = CliRunner().invoke(cli, ["reset-db"])
    assert result.exit_code == 1
    assert "--yes" in result.output
