import typer

from app.db import init_db

cli = typer.Typer(help="Competitor Content Intelligence commands.", no_args_is_help=True)


@cli.command("init-db")
def init_db_command() -> None:
    """Create the database tables."""
    init_db()
    typer.echo("Database ready.")


@cli.callback()
def main() -> None:
    # Keeps Typer in multi-command mode while init-db is the only command.
    pass


if __name__ == "__main__":
    cli()
